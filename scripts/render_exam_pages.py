#!/usr/bin/env python3
"""Add the public exam download pages to the project-metrics Pages artifact."""
from html import escape
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
SITE = "https://chnragdoll.github.io/anki-pipeline"
RELEASES = "https://github.com/CHNragdoll/anki-pipeline/releases"
PAGES = {
    "math": {
        "heading": "考研数学历年真题 PDF 下载（1987—2026）",
        "subtitle": "数学一、二、三",
        "eyebrow": "数学一 · 数学二 · 数学三",
        "intro": "收录数学一（301）、数学二（302）和数学三（303）历年真题。各科 PDF 合订本附 <strong>2027 考研数学考试大纲</strong>。",
        "subjects": (("数学一", 301), ("数学二", 302), ("数学三", 303)),
        "previews": {
            "math-covers-12.jpg": "数学一、数学二、数学三的 12 款 PDF 封面",
            "math-directory-syllabus.jpg": "可点击目录与 2027 考试大纲",
            "math-questions-figures.jpg": "真题试卷双页，含图形选项与矩阵",
            "math-answers-details.jpg": "答案速查与答案详解双页",
            "math-questions-solutions.jpg": "真题与详解双页，含解题步骤",
        },
    },
    "politics": {
        "heading": "考研政治历年真题 PDF 下载（2003—2026）",
        "subtitle": "思想政治理论 101",
        "eyebrow": "思想政治理论 · 101",
        "intro": "收录 2003—2026 年思想政治理论历年真题，提供四版 PDF、Anki 完整包及独立的 <strong>2027 考研政治考试大纲</strong>。",
        "subjects": (("思想政治理论", 101),),
        "previews": {
            "covers.png": "考研政治四款 PDF 封面",
            "politics-directory-syllabus.jpg": "合并版目录与 2027 考研政治考试大纲",
            "politics-questions.jpg": "2026 年真题试卷双页，展示单项选择题",
            "politics-answers-details.jpg": "2026 年答案速查与答案详解双页",
            "politics-questions-solutions.jpg": "2026 年真题与详解双页，展示材料分析题",
        },
    },
    "english": {
        "heading": "考研英语历年真题（带答题卡）PDF 下载（2000—2026）",
        "subtitle": "英语一、英语二",
        "eyebrow": "英语一 · 英语二",
        "intro": "收录 2010—2026 年英语一（201）、英语二（204）历年真题，附 2000—2009 年统考英语，提供真题试卷（带答题卡）、答案速查及两份独立的 <strong>2027 考试大纲</strong>。",
        "subjects": (("英语一", 201), ("英语二", 204)),
        "previews": {
            "english-covers-4.jpg": "英语一、英语二的四款 PDF 封面",
            "english-directory-syllabus.jpg": "英语一目录与 2027 考试大纲双页预览",
            "english-questions-spread.jpg": "2026 年英语二完形填空正文与选项双页预览",
            "english-answers-spread.jpg": "2026 年英语一与英语二答案速查双页预览",
            "english1-translation-answer-sheet.jpg": "2026 年英语一翻译题双页预览（带答题卡）",
            "english2-writing-answer-sheet.jpg": "2026 年英语二写作题双页预览（带答题卡）",
        },
        "note": "真题试卷适合整卷练习，答案速查按题号以表格列出客观题选项。斜线表示该版本暂无发行文件。",
        "preview_note": "点击图片查看四款封面，以及目录、大纲、完形填空、答案表格和翻译、写作（带答题卡）的双页截图。",
    },
}


def download_rows(readme, subject):
    section = readme.split("### 考研历年真题 PDF 与 Anki 下载\n", 1)[1]
    section = section.split("## 反馈问题", 1)[0]
    download = f"{RELEASES}/download/{subject}-exams/"
    for name, number in PAGES[subject]["subjects"]:
        prefix = f"| {name} · {number} |"
        row, = (line for line in section.splitlines() if line.startswith(prefix))
        cells = row.strip("|").split("|")[1:]
        if len(cells) != 5:
            raise ValueError(f"{name} must have five download columns")
        links = []
        for index, cell in enumerate(cells):
            if cell.strip() == "/":
                links.append("<td>/</td>")
                continue
            match = re.match(r"\s*\[([^\]]+)\]\((" + re.escape(download) + r"[\w.-]+)\)", cell)
            if not match or not match[2].endswith(".pdf" if index < 4 else ".apkg"):
                raise ValueError(f"Invalid {name} download in column {index+1}")
            links.append(f'<td><a href="{escape(match[2])}">{escape(match[1])}</a></td>')
        yield f'<tr><th scope="row">{name}<small>{number}</small></th>{"".join(links)}</tr>'


def render(output):
    readme = (ROOT / "README.md").read_text()
    template = (ROOT / "scripts/exam_download_page.html").read_text()
    for subject, config in PAGES.items():
        page = output / subject
        page.mkdir(parents=True, exist_ok=True)
        figures = []
        for filename, caption in config["previews"].items():
            shutil.copyfile(ROOT / f"assets/{subject}-pdf" / filename, page / filename)
            figures.append(
                f'<figure><a href="{filename}"><img src="{filename}" alt="{caption}" loading="lazy"></a>'
                f'<figcaption>{caption}</figcaption></figure>'
            )
        syllabus_links = re.findall(
            r"\[(\d{4} 考研[^\]（）]+考试大纲 PDF)（(\d+ 页)）\]\(("
            + re.escape(f"{RELEASES}/download/{subject}-exams/") + r"[\w.-]+\.pdf)\)",
            readme,
        )
        if len(syllabus_links) != len(config["subjects"]):
            raise ValueError(f"Missing or duplicate standalone syllabus links for {subject}")
        syllabus_items = "".join(
            f'<li><a href="{escape(url)}">{escape(label)} · {escape(pages)}</a></li>'
            for label, pages, url in syllabus_links
        )
        replacements = {
            "TITLE": config["heading"] + "｜" + config["subtitle"],
            "DESCRIPTION": re.sub(r"<[^>]+>", "", config["intro"]),
            "CANONICAL": f"{SITE}/{subject}/",
            "HEADING": config["heading"],
            "EYEBROW": config["eyebrow"],
            "INTRO": config["intro"],
            "RELEASE": f"{RELEASES}/tag/{subject}-exams",
            "DOWNLOAD_ROWS": "\n".join(download_rows(readme, subject)),
            "PREVIEWS": "\n".join(figures),
            "DOWNLOAD_NOTE": config.get("note", "真题试卷适合整卷练习，答案速查用于对答案。答案详解提供解题步骤，真题与详解把试题和解析收在同一册。Anki 卡包按年份与题型组织。"),
            "PREVIEW_NOTE": config.get("preview_note", "点击图片查看大图。双页图展示目录、试卷、答案和解析的实际排版。"),
            "EXTRA": f'<h3>独立考试大纲</h3><ul class="syllabus">{syllabus_items}</ul>',
        }
        (page / "index.html").write_text(
            re.sub(r"__([A-Z_]+)__", lambda match: replacements[match[1]], template)
        )
    urls = "".join(f"  <url><loc>{SITE}/{subject}/</loc></url>\n" for subject in PAGES)
    (output / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + urls + '</urlset>\n'
    )
    for verification in (ROOT / "assets/pages-verification").glob("google*.html"):
        shutil.copyfile(verification, output / verification.name)


if __name__ == "__main__":
    render(Path(sys.argv[1]))
