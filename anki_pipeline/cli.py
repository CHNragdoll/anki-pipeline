"""A single explicit command line interface for the local pipeline."""
from __future__ import annotations
import argparse
import json
import os
import tempfile
from pathlib import Path
import sqlite3
import sys
from . import __version__
from .config import load_config
from .store import backup_database, connect, logical_digest, restore_database, upsert_cards


def _json(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _write_json(path: Path, value):
    _write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _write_text(path: Path, value: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".report-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(value)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def _guard_output(path: Path, config, config_path: Path):
    target = path.resolve()
    root = config.project_root
    if not target.is_relative_to(root) or path.is_symlink():
        raise ValueError("输出必须位于新版项目目录内，不能通过符号链接覆盖外部文件")
    files = (config.database, config.legacy_database, config.wordbook, config_path.resolve())
    directories = (config.legacy_database.parent, config.legacy_audio, config.audio, config.backups)
    if target in files or any(target == d or target.is_relative_to(d) for d in directories):
        raise ValueError("输出路径指向受保护的数据库、原始资料或媒体/备份目录")


def parser():
    p = argparse.ArgumentParser(description="可恢复的英语词汇 Anki 制卡流水线")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--config", type=Path, default=Path("config.toml"), help="所有相对路径以此文件为基准")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="只读检查配置、依赖及输入路径")
    sub.add_parser("migrate", help="只读迁移 V2.0 到独立新库，并复制本地音频")
    sub.add_parser("reclassify", help="规则更新后重新核验例句匹配，不修改原文或译文")
    wordbook = sub.add_parser("import-wordbook", help="导入词表，保留已有补全资料")
    wordbook.add_argument("--file", type=Path)
    extract = sub.add_parser("extract", help="从 PDF 精确提取例句，已有译文保持不变")
    extract.add_argument("--pdf", type=Path)
    export = sub.add_parser("export-translations", help="导出按句子 ID 对齐的翻译 CSV")
    export.add_argument("--file", type=Path, required=True)
    export.add_argument("--all", action="store_true")
    imp = sub.add_parser("import-translations", help="验证完整 CSV 后事务导入译文")
    imp.add_argument("--file", type=Path, required=True)
    check = sub.add_parser("check", help="只读内容、音频与数据库校验")
    check.add_argument("--report", type=Path)
    check.add_argument("--strict-translations", action="store_true")
    build = sub.add_parser("build", help="校验后生成新版卡包和预览")
    build.add_argument("--file", type=Path)
    sub.add_parser("backup", help="创建带完整性校验的 SQLite 备份")
    restore = sub.add_parser("restore", help="恢复到新路径，不覆盖当前库")
    restore.add_argument("--file", type=Path, required=True)
    restore.add_argument("--to", type=Path, required=True)
    enrich = sub.add_parser("enrich", help="显式联网补全词典/音频，默认最多 10 个词")
    enrich.add_argument("--limit", type=int, default=10)
    enrich.add_argument("--provider", choices=["oxford", "youdao"], required=True)
    return p


def run(args):
    config = load_config(args.config)
    command = args.command
    for name in ("migration-report.json", "quality-report.json", "build-report.json", "preview.html"):
        _guard_output(config.output / name, config, args.config)
    if command == "check" and args.report:
        _guard_output(args.report, config, args.config)
    if command in {"build", "export-translations"} and args.file:
        _guard_output(args.file, config, args.config)
    if command == "build":
        _guard_output(config.output / f"anki-rebuilt-{__version__}.apkg", config, args.config)
    if command == "restore":
        _guard_output(args.to, config, args.config)
    if command == "doctor":
        paths = {k: {"path": str(getattr(config, k)), "exists": getattr(config, k).exists()}
                 for k in ("database", "legacy_database", "wordbook", "audio", "legacy_audio")}
        _json({"version": __version__, "python": sys.version.split()[0], "paths": paths,
               "network": "Only enrich contacts external services; other commands are offline."})
    elif command == "migrate":
        from .migration import migrate_legacy
        from .pipeline import copy_legacy_audio
        result = migrate_legacy(config.legacy_database, config.database, config.backups)
        result["media"] = copy_legacy_audio(config.database, config.legacy_audio, config.audio, package=config.legacy_package)
        _write_json(config.output / "migration-report.json", result)
        _json(result)
    elif command == "import-wordbook":
        from .inputs import read_wordbook
        _json({"imported": upsert_cards(config.database, read_wordbook(args.file or config.wordbook), config.backups)})
    elif command == "reclassify":
        from .pipeline import reclassify_examples
        _json(reclassify_examples(config.database, config.backups))
    elif command == "extract":
        from .pdf import extract_examples
        from .pipeline import add_examples
        from .forms import explicit_forms
        pdf = args.pdf or config.pdf
        if pdf is None:
            raise ValueError("请提供 --pdf 或配置 paths.pdf")
        with connect(config.database, readonly=True) as conn:
            forms = {}
            for row in conn.execute("SELECT word,word_forms FROM cards ORDER BY word"):
                forms.setdefault(row[0], set()).update(explicit_forms(row[1]))
        _json(add_examples(config.database, extract_examples(pdf, list(forms), extra_forms=forms), config.backups))
    elif command == "export-translations":
        from .translations import export_translations
        _json({"exported": export_translations(config.database, args.file, pending_only=not args.all), "file": str(args.file)})
    elif command == "import-translations":
        from .translations import import_translations
        _json(import_translations(config.database, args.file, config.backups))
    elif command in {"check", "build"}:
        from .quality import quality_report, cards_for_export
        report = quality_report(config.database, config.audio)
        if command == "check":
            if args.report:
                _write_json(args.report, report)
            _json({k: v for k, v in report.items() if k != "issues"})
            return 0 if report["ok"] and (not args.strict_translations or not report["counts"]["pending_accepted_translations"]) else 2
        if not report["ok"]:
            _json({k: v for k, v in report.items() if k != "issues"})
            raise ValueError("基础数据校验失败，未打包；运行 check --report 查看问题")
        from .packaging import build_package, render_preview
        output = args.file or config.output / f"anki-rebuilt-{__version__}.apkg"
        cards = cards_for_export(config.database)
        result = build_package(cards, config.audio, output, deck_name=config.deck_name, max_examples=config.max_examples)
        config.output.mkdir(parents=True, exist_ok=True)
        preview = config.output / "preview.html"
        _write_text(preview, render_preview(next((c for c in cards if c["examples"]), cards[0]), config.audio))
        _write_json(config.output / "quality-report.json", report)
        result.update({"preview": str(preview), "content_digest": logical_digest(config.database), "quality": report["counts"]})
        _write_json(config.output / "build-report.json", result)
        _json(result)
    elif command == "backup":
        _json({"backup": str(backup_database(config.database, config.backups))})
    elif command == "restore":
        restore_database(args.file, args.to)
        _json({"restored": str(args.to), "digest": logical_digest(args.to)})
    elif command == "enrich":
        from .inputs import lookup_oxford, lookup_youdao, download_audio, _valid_mp3
        if not 1 <= args.limit <= 100:
            raise ValueError("--limit 必须为 1–100")
        with connect(config.database, readonly=True) as conn:
            candidates = [dict(r) for r in conn.execute("SELECT * FROM cards ORDER BY id")]
        cards = []
        for card in candidates:
            if args.provider == "youdao":
                missing = not card["simple_definition"]
            else:
                audio_path = config.audio / card["audio_filename"]
                valid = (bool(card["audio_filename"]) and audio_path.is_file()
                         and audio_path.resolve().is_relative_to(config.audio.resolve())
                         and audio_path.stat().st_size <= 5 * 1024 * 1024)
                valid = valid and _valid_mp3(audio_path.read_bytes())
                missing = not card["phonetic"] or not valid
            if missing:
                cards.append(card)
            if len(cards) == args.limit:
                break
        completed, failures = [], []
        for card in cards:
            try:
                result = lookup_oxford(card["word"]) if args.provider == "oxford" else lookup_youdao(card["word"])
                if result.get("audio_url"):
                    card["audio_filename"] = download_audio(result["audio_url"], card["word"], config.audio)
                for key in ("phonetic", "simple_definition", "level", "word_forms"):
                    if result.get(key) and not card[key]:
                        card[key] = result[key]
                completed.append(card)
            except (ValueError, OSError, RuntimeError) as exc:
                failures.append({"word": card["word"], "error": str(exc)})
        if completed:
            upsert_cards(config.database, completed, config.backups)
        _json({"updated": len(completed), "failures": failures})
        return 2 if failures else 0
    return 0


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        return run(args)
    except (OSError, ValueError, sqlite3.Error, RuntimeError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2
