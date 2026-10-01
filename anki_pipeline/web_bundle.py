"""Export a verified static preview with a standalone local-only web server."""
import json
import os
from pathlib import Path
import tempfile
import zipfile

from .web_preview import _validate_version, _reject_symlinks


_SERVER = '''#!/usr/bin/env python3
"""Serve only this bundled preview; no dictionary/database/API is required."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import webbrowser

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--no-open", action="store_true")
args = parser.parse_args()
root = Path(__file__).resolve().parent
handler = partial(SimpleHTTPRequestHandler, directory=str(root))
with ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
    url = f"http://127.0.0.1:{server.server_port}/preview-library.html"
    print(url, flush=True)
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
'''
_LAUNCH = '''#!/bin/sh
cd -- "$(dirname -- "$0")" || exit 1
exec python3 serve_preview.py
'''
_README = '''# 考研英语完整网页预览

解压整个文件夹，双击「启动网页预览.command」。需 Python 3，只启动附带的本机静态网页服务（随机空闲端口），不需要牛津/韦氏词典服务、源数据库或联网。

其他系统运行 `python3 serve_preview.py`。保留终端窗口，关闭或按 Ctrl+C 后服务停止。

网页包括所有卡组、卡片、译文、牛津释义、韦氏词形及两套本地发音。牛津缺失释义、韦氏缺失词形时使用 ECDICT 的明确记录；考试标签取自 ECDICT。相关数据与许可已包含在网页中，无需 ECDICT 目录或词典接口。左上角发音来源选择会跨卡保存。原包确实缺少的词条或录音在卡片上明确标出。

真题例句先加载韦氏词形，再匹配原词及其屈折变化；韦氏整栏缺失时使用经词性核查的 ECDICT 词形。派生词与词族单独展示，不并入原词例句。

真题例句只高亮英文目标词，中文译文以普通文字展示。完形填空与有明确答案的阅读题干先回填答案，回填部分加下划线；词频仍按原题印刷内容统计，不重复计入人工回填的词。

阅读题选项显示完整问题与 A/B/C/D 候选身份：有空位的填入当前选项并加下划线，没有空位的分行显示问题与选项。中文显示完整一段译文，所有新组合经过独立逐条审校。来源按原卷层级用 ➫ 连接。Part B 句子插入空位按明确答案回填，并保留插入范围的下划线。

有现成 chunk 索引的例句支持英文悬停或点击查看中文对应；再次点击或点击空白取消。初始中文保持普通文字，缺少有效对应的例句不猜测标注。

例句跳转保留你原来的真题库地址；阅读原卷需另行启动真题库服务。词典释义和发音独立于该服务。

Anki 使用单独的「Anki-本地双词典版.apkg」，两套词典音频均包含在卡包中。
'''


def build_web_bundle(report: dict, output: Path) -> dict:
    """Keep the previous ZIP until all versioned assets pass manifest checks."""
    entry = Path(report["output_path"])
    version = Path(report["version_directory"])
    output = Path(output).absolute()
    _reject_symlinks(output)
    if output.suffix.lower() != ".zip" or output == entry:
        raise ValueError("web bundle output must be a separate ZIP file")
    if output.is_relative_to(version):
        raise ValueError("cannot write a ZIP inside immutable preview assets")
    _reject_symlinks(entry)
    manifest = json.loads((version / "manifest.json").read_text(encoding="utf-8"))
    _validate_version(version, manifest)
    shell = entry.read_bytes()
    if report["input_digest"].encode() not in shell:
        raise ValueError("preview entry no longer refers to this asset version")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, suffix=".tmp.zip", delete=False) as stream:
            temporary = Path(stream.name)
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            base = "Anki-完整网页预览/"
            archive.writestr(base + "preview-library.html", shell)
            archive.writestr(base + "README.md", _README)
            archive.writestr(base + "serve_preview.py", _SERVER)
            launcher = zipfile.ZipInfo(base + "启动网页预览.command")
            launcher.create_system = 3
            launcher.external_attr = 0o100755 << 16
            archive.writestr(launcher, _LAUNCH)
            for name in sorted([*manifest["files"], "manifest.json"]):
                path = version / name
                _reject_symlinks(path)
                archive.write(path, base + f"web-preview/{report['input_digest']}/{name}")
        with zipfile.ZipFile(temporary) as archive:
            if archive.testzip() is not None:
                raise ValueError("web bundle ZIP integrity failed")
            count = len(archive.infolist())
        _validate_version(version, manifest)
        if entry.read_bytes() != shell:
            raise ValueError("preview entry changed during bundling")
        os.replace(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {"output_path": str(output), "input_digest": report["input_digest"],
            "files": count, "bytes": output.stat().st_size}
