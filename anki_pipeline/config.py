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
    deck_identity_name: str | None = None
    max_examples: int = 5
    exam_library: Path | None = None
    exam_base_url: str = "http://localhost:8765"
    exam_reader: str = "latex"
    exam_max_examples: int = 0
    exam_sentence_source: str = "legacy"
    codex_index_root: Path | None = None
    reading_completion_path: Path | None = None
    dictionary_root: Path | None = None
    ecdict_root: Path | None = None
    cigen_root: Path | None = None


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
    deck_identity_name = deck.get("identity_name")
    if "identity_name" in deck and (not isinstance(deck_identity_name, str)
                                   or not deck_identity_name.strip()):
        raise ValueError("deck.identity_name 必须是非空字符串")
    library = data.get("exam_library", {})
    reader = library.get("reader", "latex")
    if reader not in {"latex", "full-paper"}:
        raise ValueError("exam_library.reader 必须是 latex 或 full-paper")
    maximum = deck.get("max_examples", 5)
    if isinstance(maximum, bool) or not isinstance(maximum, int) or not 1 <= maximum <= 30:
        raise ValueError("deck.max_examples 必须是 1–30 的整数")
    exam_maximum = library.get("max_examples", 0)
    if isinstance(exam_maximum, bool) or not isinstance(exam_maximum, int) or exam_maximum < 0:
        raise ValueError("exam_library.max_examples 必须是非负整数，0 表示全部例句")
    sentence_source = library.get("sentence_source", "legacy")
    if sentence_source not in {"legacy", "codex"}:
        raise ValueError("exam_library.sentence_source 必须是 legacy 或 codex")
    if library.get("codex_index_root") and sentence_source != "codex":
        raise ValueError("codex_index_root 必须配合 sentence_source=codex")
    if library.get("reading_completion_path") and sentence_source != "codex":
        raise ValueError("reading_completion_path 必须配合 sentence_source=codex")
    completion_path = None
    if sentence_source == "codex":
        completion_path = ((path.parent / Path(library["reading_completion_path"]).expanduser()).resolve()
                           if library.get("reading_completion_path") else
                           project_root / "data/reading-completions-v1.json")
    return Config(**paths, project_root=project_root, pdf=resolve("pdf") if values.get("pdf") else None,
                  legacy_package=resolve("legacy_package") if values.get("legacy_package") else None,
                  deck_name=str(deck.get("name", "考研英语 · 精选真题")),
                  deck_identity_name=deck_identity_name,
                  max_examples=maximum,
                  exam_library=(path.parent / Path(library["root"]).expanduser()).resolve() if library.get("root") else None,
                  exam_base_url=str(library.get("base_url", "http://localhost:8765")),
                  exam_reader=reader, exam_max_examples=exam_maximum,
                  exam_sentence_source=sentence_source,
                  codex_index_root=(path.parent / Path(library["codex_index_root"]).expanduser()).resolve()
                  if library.get("codex_index_root") else None,
                  reading_completion_path=completion_path,
                  dictionary_root=(path.parent / Path(data["local_dictionary"]["root"]).expanduser()).resolve()
                  if data.get("local_dictionary", {}).get("root") else None,
                  ecdict_root=(path.parent / Path(data["ecdict"]["root"]).expanduser()).resolve()
                  if data.get("ecdict", {}).get("root") else None,
                  cigen_root=(path.parent / Path(data["etymology"]["root"]).expanduser()).resolve()
                  if data.get("etymology", {}).get("root") else None)
