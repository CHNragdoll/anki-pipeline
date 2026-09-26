"""Configuration is explicit and independent of the shell's working directory."""
from dataclasses import dataclass
from pathlib import Path
import tomllib


@dataclass(frozen=True)
class Config:
    project_root: Path
    database: Path
    legacy_database: Path
    wordbook: Path
    audio: Path
    legacy_audio: Path
    output: Path
    backups: Path
    pdf: Path | None = None
    legacy_package: Path | None = None
    deck_name: str = "考研英语 · 精选真题"
    max_examples: int = 5


def load_config(path: Path) -> Config:
    path = path.expanduser().resolve(strict=True)
    with path.open("rb") as stream:
        data = tomllib.load(stream)
    values = data.get("paths", {})
    project_root = (path.parent / data.get("project", {}).get("root", ".")).resolve()
    def resolve(key: str) -> Path:
        value = Path(values[key]).expanduser()
        return (path.parent / value).resolve()
    paths = {key: resolve(key) for key in ("database", "legacy_database", "wordbook", "audio", "legacy_audio", "output", "backups")}
    if paths["database"] == paths["legacy_database"]:
        raise ValueError("新版数据库不能指向原始 V2.0 数据库")
    if paths["audio"] == paths["legacy_audio"]:
        raise ValueError("新版音频目录不能指向原始目录")
    if paths["legacy_database"] in paths["database"].parents:
        raise ValueError("数据库路径无效")
    for name in ("database", "audio", "output", "backups"):
        value = paths[name]
        if not value.is_relative_to(project_root):
            raise ValueError(f"paths.{name} 必须位于 project.root 所指定的新版项目目录内")
        for protected in (paths["legacy_database"].parent, paths["legacy_audio"]):
            if value == protected or value.is_relative_to(protected):
                raise ValueError(f"paths.{name} 不能写入原始资料目录")
    if len({paths[k] for k in ("database", "audio", "output", "backups")}) != 4:
        raise ValueError("数据库、音频、输出和备份路径必须彼此不同")
    deck = data.get("deck", {})
    maximum = deck.get("max_examples", 5)
    if isinstance(maximum, bool) or not isinstance(maximum, int) or not 1 <= maximum <= 30:
        raise ValueError("deck.max_examples 必须是 1–30 的整数")
    return Config(**paths, project_root=project_root, pdf=resolve("pdf") if values.get("pdf") else None,
                  legacy_package=resolve("legacy_package") if values.get("legacy_package") else None,
                  deck_name=str(deck.get("name", "考研英语 · 精选真题")), max_examples=maximum)
