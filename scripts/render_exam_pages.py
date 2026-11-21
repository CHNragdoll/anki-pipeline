#!/usr/bin/env python3
"""Add the public exam download pages to the project-metrics Pages artifact."""
from html import escape
from pathlib import Path
import json
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
SITE = "https://chnragdoll.github.io/anki-pipeline"
REPO = "https://github.com/CHNragdoll/anki-pipeline"
RELEASES = f"{REPO}/releases"
DOWNLOAD_BADGES = "https://raw.githubusercontent.com/CHNragdoll/anki-pipeline/project-metrics"
WORKBOOK_FORMATS = (
    ("a4-adaptive", "A4 动态留白"),
    ("a4-2", "A4 每页最多两题"),
    ("a4-3", "A4 每页最多三题"),
    ("a5-1", "A5 横向一页一题"),
)
WORKBOOK_SUBJECTS = {
    301: ("math1", "math"), 302: ("math2", "math"), 303: ("math3", "math"),
    101: ("politics", "politics"), 408: ("cs408", "cs408"),
    199: ("management199", "management199"), 396: ("economics396", "economics396"),
}
WORKBOOK_NAMES = {
    301: "考研数学一历年真题做题本",
    302: "考研数学二历年真题做题本",
    303: "考研数学三历年真题做题本",
    101: "考研政治历年真题做题本",
    408: "考研408历年真题做题本（计算机）",
    199: "考研199管综历年真题做题本（管理类综合能力）",
    396: "考研396经综历年真题做题本（经济类综合能力）",
}
WORKBOOK_NOTE = (
    "初次下载可选 A4 动态留白版，紧凑版依据整本《真题与详解》分配作答空间。"
    "也可选择 A4 每页最多两题、最多三题，或 A5 横向一页一题。"
    "长题会减少同页题数或接续页。"
)
WORKBOOK_HELP = "199 和 396 写作沿用原尺寸作文格。打印时可选择对应纸型和 100% 实际大小。"

RELATED_EXAMS = {
    "math": f'数学 · <a href="{REPO}#math-downloads">历年真题 PDF 与 Anki</a>',
    "politics": f'政治 · <a href="{REPO}#考研历年真题-pdf-与-anki-下载">历年真题 PDF</a> · <a href="{REPO}#下载-anki-卡包">Anki 完整包</a>',
    "english": f'英语 · <a href="{REPO}#考研英语历年真题带答题卡pdf">英语一、英语二历年真题 PDF（带答题卡）</a>',
    "cs408": f'计算机 408 · <a href="{REPO}#考研历年真题-pdf-与-anki-下载">历年真题 PDF 与 Anki</a>',
    "management199": f'管综 · <a href="{REPO}#考研管综历年真题pdf-与-anki">历年真题 PDF 与 Anki</a>',
    "economics396": f'经综 · <a href="{REPO}#考研经综历年真题pdf-与-anki">历年真题 PDF 与 Anki</a>',
}


def related_resources(subject):
    exam_items = "\n".join(
        f"<li>{item}</li>" for key, item in RELATED_EXAMS.items() if key != subject
    )
    return f"""<section aria-labelledby="related-resources">
<h2 id="related-resources">更多考研资料</h2>
<ul>
{exam_items}
<li><a href="{REPO}#下载-anki-卡包">2026／2027 红宝书 Anki</a></li>
<li><a href="{REPO}#下载-anki-卡包">刘晓艳考研英语词汇 Anki</a></li>
</ul>
</section>"""


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
        "intro": "收录 2003—2026 年思想政治理论历年真题，提供四版 PDF、Anki 完整包及独立的 <strong>2027 考研政治考试大纲</strong>。2026-11-15 校订。政治 PDF 恢复作答说明、漏印字形和材料设问，修正误混入题面的解析。<a href='https://github.com/CHNragdoll/anki-pipeline/releases/download/politics-exams/SHA256SUMS-PDF-101-20261115.txt'>PDF 校验清单</a>。",
        "subjects": (("思想政治理论", 101),),
        "previews": {
            "covers.png": "考研政治四款 PDF 封面",
            "politics-directory-syllabus.jpg": "合并版目录与 2027 考研政治考试大纲",
            "politics-questions.jpg": "2026 年真题试卷双页，展示单项选择题",
            "politics-answers-details.jpg": "2026 年答案速查与答案详解双页",
            "politics-questions-solutions.jpg": "2026 年真题与详解双页，展示材料分析题",
        },
    },
    "cs408": {
        "heading": "考研 408 历年真题 PDF 下载（2009—2026）",
        "subtitle": "计算机学科专业基础综合",
        "eyebrow": "计算机学科专业基础综合 · 408",
        "intro": "收录 2009—2026 年考研 408 真题，提供四版 PDF、Anki 完整包及独立的 <strong>2027 考试大纲</strong>。2026 年试题为公开回忆整理版。",
        "subjects": (("计算机学科专业基础", 408),),
        "previews": {
            "cs408-covers.jpg": "考研 408 四款 PDF 封面",
            "cs408-questions-spread.jpg": "2026 年真题试卷双页，含数据通路配图",
            "cs408-solutions-spread.jpg": "2026 年真题与详解双页",
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
    "management199": {
        "heading": "考研管综历年真题 PDF 下载（2010—2026）",
        "subtitle": "管理类综合能力",
        "eyebrow": "管理类综合能力 · 199",
        "intro": "收录 2010—2026 年管理类综合能力历年真题，提供四版 PDF、独立的 <strong>2027 考试大纲</strong>和 Anki 卡包。2026-11-15 校订。管综 PDF 恢复多年份错位题目的原卷顺序，同步对应答案和解析，并校正公式与选项。<a href='https://github.com/CHNragdoll/anki-pipeline/releases/download/management199-exams/SHA256SUMS-PDF-199-20261115.txt'>PDF 校验清单</a>。",
        "subjects": (("管理类综合能力", 199),),
        "previews": {
            "covers.jpg": "管综四版 PDF 封面",
            "questions-spread.jpg": "2026 年真题试卷双页",
            "solutions-spread.jpg": "2026 年真题与详解双页",
        },
    },
    "economics396": {
        "heading": "考研经综历年真题 PDF 下载（2011—2026）",
        "subtitle": "经济类综合能力",
        "eyebrow": "经济类综合能力 · 396",
        "intro": "收录 2011—2026 年经济类综合能力历年真题，提供四版 PDF、独立的 <strong>2027 考试大纲</strong>和 Anki 卡包。<strong>四版 PDF 和 Anki 卡包已补齐 2026 年卷第 42–44 题，详解版和卡包提供解题步骤。</strong>2026-11-15 修复 396 旧版答题卡及真题试卷内嵌答题卡的纸边黑线。2026-11-15 校订。经综 PDF 恢复经核对的题干、选项和写作材料，保留 2026 年第 42–44 题及详解。<a href='https://github.com/CHNragdoll/anki-pipeline/releases/download/economics396-exams/SHA256SUMS-PDF-396-20261115.txt'>上一版 PDF 校验清单</a>。2024 年第 52 题 C 项已更正为东线，真题试卷、真题与详解和 Anki 卡包已同步。<a href='https://github.com/CHNragdoll/anki-pipeline/issues/57'>勘误记录</a> · <a href='https://github.com/CHNragdoll/anki-pipeline/releases/download/economics396-exams/economics396-verification-20261115-issue57.json'>核验记录</a>。2025 年第 39、40、44 题在三份含答案 PDF 和 Anki 卡包中采用启航参考答案 E、B、C。<a href='https://github.com/CHNragdoll/anki-pipeline/issues/59'>勘误记录</a> · <a href='https://github.com/CHNragdoll/anki-pipeline/releases/download/economics396-exams/SHA256SUMS-PDF-396-20261116.txt'>最新 PDF 校验清单</a>。",
        "subjects": (("经济类综合能力", 396),),
        "previews": {
            "covers.jpg": "经综四版 PDF 封面",
            "questions-spread.jpg": "2026 年真题试卷双页",
            "solutions-spread.jpg": "2026 年真题与详解双页",
            "answer-card-spread.jpg": "2026 年答题卡双页",
        },
    },
}


def download_cell(label, url, *, workbook_badge=False):
    title = escape(label)
    if workbook_badge:
        badge = f"{DOWNLOAD_BADGES}/{Path(url).stem}-downloads.svg"
        title += f'<img class="download-badge" src="{escape(badge)}" alt="下载量">'
    return f'<td><a href="{escape(url)}">{title}</a></td>'


def download_rows(readme, subject):
    section = readme.split("### 考研历年真题 PDF 与 Anki 下载\n", 1)[1]
    section = section.split('<a id="workbook-downloads"></a>', 1)[0]
    download = f"{RELEASES}/download/{subject}-exams/"
    for name, number in PAGES[subject]["subjects"]:
        prefix = f"| {name} · {number} |"
        row, = (line for line in section.splitlines() if line.startswith(prefix))
        cells = row.strip("|").split("|")[1:]
        if len(cells) != 6:
            raise ValueError(f"{name} must have six download columns")
        links = []
        for index, cell in enumerate(cells):
            if cell.strip() == "/":
                links.append("<td>/</td>")
                continue
            match = re.match(r"\s*\[([^\]]+)\]\((" + re.escape(download) + r"[\w.-]+)\)", cell)
            if not match or not match[2].endswith(".pdf" if index < 5 else ".apkg"):
                raise ValueError(f"Invalid {name} download in column {index+1}")
            links.append(download_cell(*match.groups(), workbook_badge=index == 4))
        yield f'<tr><th scope="row">{name}<small>{number}</small></th>{"".join(links)}</tr>'


def read_workbooks(readme):
    """Read the public workbook table from the same source as the main downloads."""
    section = readme.split("#### 做题本专项 PDF 下载\n", 1)[1]
    section = section.split("#### 考研初试答题卡 PDF 下载", 1)[0]
    books = {}
    captions = json.loads((ROOT / "assets/workbook-pdf/captions.json").read_text())
    for line in section.splitlines():
        if not line.startswith("| ") or line.startswith("| 科目 ") or line.startswith("| ---"):
            continue
        name, *cells = (cell.strip() for cell in line.strip("|").split("|"))
        number = int(name.rsplit(" · ", 1)[1])
        key, subject = WORKBOOK_SUBJECTS[number]
        if len(cells) != len(WORKBOOK_FORMATS) or number in books:
            raise ValueError(f"Invalid workbook row for {name}")
        formats = []
        for cell, (variant, title) in zip(cells, WORKBOOK_FORMATS, strict=True):
            url_prefix = f"{RELEASES}/download/{subject}-exams/{key}-practice-workbook-{variant}-"
            match = re.fullmatch(r"\[([^\]]+)\]\((" + re.escape(url_prefix) + r"\d{8}(?:-r\d+)?\.pdf)\)", cell.split("<br/>", 1)[0])
            if not match:
                raise ValueError(f"Invalid {variant} workbook download for {name}")
            label, url = match.groups()
            filename = f"{key}-{variant}-spread.webp"
            formats.append((title, label, url, filename, captions[filename]))
        books[number] = (name, formats)
    if set(books) != set(WORKBOOK_SUBJECTS):
        raise ValueError("Missing workbook rows")
    return books


def workbook_section(books, numbers, preview_root):
    tables = []
    previews = []
    for number in numbers:
        name, formats = books[number]
        cols = []
        figures = []
        for title, label, url, filename, description in formats:
            href = f"{preview_root}{filename}"
            caption = f"{name} · {title} · {description}"
            cols.append(download_cell(label, url, workbook_badge=True))
            figures.append(
                f'<figure><a href="{escape(href)}"><img src="{escape(href)}" '
                f'alt="{escape(caption)}" loading="lazy"></a>'
                f'<figcaption>{escape(title)} · {escape(description)}</figcaption></figure>'
            )
        subject_key, _ = WORKBOOK_SUBJECTS[number]
        tables.append(f'<tr id="workbook-{subject_key}"><th scope="row">{escape(name)}</th>{"".join(cols)}</tr>')
        previews.append(
            f'<details{"" if len(numbers)>1 else " open"}><summary>{escape(name)}双页实图</summary>'
            f'<div class="gallery workbook-gallery">{"".join(figures)}</div></details>'
        )
    cols = "".join(f'<th scope="col">{escape(title)}</th>' for _, title in WORKBOOK_FORMATS)
    subject_links = "、".join(
        f'<a href="#workbook-{WORKBOOK_SUBJECTS[number][0]}">{escape(WORKBOOK_NAMES[number])}</a>'
        for number in numbers
    )
    return f"""<section aria-labelledby="workbook-downloads">
<h2 id="workbook-downloads">做题本专项 PDF 下载</h2>
<p>在下表下载{subject_links}。</p>
<p>{WORKBOOK_NOTE}</p>
<div class="table-scroll" role="region" aria-label="做题本版式下载表，可横向滚动" tabindex="0"><table>
<thead><tr><th scope="col">科目</th>{cols}</tr></thead>
<tbody>{''.join(tables)}</tbody></table></div>
<p class="note">{WORKBOOK_HELP}</p>
{''.join(previews)}
</section>"""


def render_workbook_hub(output, books, template):
    page = output / "workbooks"
    image_dir = page / "previews"
    image_dir.mkdir(parents=True, exist_ok=True)
    for _, formats in books.values():
        for _, _, _, filename, _ in formats:
            shutil.copyfile(ROOT / "assets/workbook-pdf" / filename, image_dir / filename)
    template = re.sub(r'<section aria-labelledby="downloads">.*?</section>', "", template, count=1, flags=re.S)
    template = re.sub(r'<section aria-labelledby="previews">.*?</section>', "", template, count=1, flags=re.S)
    replacements = {
        "TITLE": "考研历年真题做题本 PDF 下载｜七科四种版式",
        "DESCRIPTION": "下载考研数学一、数学二、数学三、政治、计算机408、199管综和396经综历年真题做题本 PDF。每科提供四种版式与双页实图。",
        "CANONICAL": f"{SITE}/workbooks/",
        "HEADING": "考研历年真题做题本",
        "EYEBROW": "数学一、二、三 · 政治 · 408 · 199 · 396",
        "INTRO": "按科目和纸型选择做题本，下载后可直接打印或在 PDF 阅读器中练习。",
        "RELEASE": f"{REPO}#workbook-downloads",
        "WORKBOOKS": workbook_section(books, tuple(books), "previews/"),
        "RELATED_RESOURCES": related_resources("workbooks"),
        "WORKBOOK_LINK": "",
    }
    (page / "index.html").write_text(
        re.sub(r"__([A-Z_]+)__", lambda match: replacements[match[1]], template)
    )


def render_answer_sheets(output, readme, template):
    heading = "考研初试答题卡 PDF 下载"
    section = readme.split(f"#### {heading}\n", 1)[1]
    rows = []
    download = re.escape(f"{RELEASES}/download/answer-sheets/")
    for line in section.splitlines():
        if not line.startswith("|"):
            if rows:
                break
            continue
        if not line.startswith("| ") or line.startswith("| 科目 "):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != 3:
            raise ValueError("Each answer-sheet row must contain two versions")
        links = []
        for cell in cells[1:]:
            if cell == "/":
                links.append("<td>/</td>")
                continue
            match = re.match(r"\[([^\]]+)\]\((" + download + r"[\w.-]+\.pdf)\)", cell)
            if not match:
                raise ValueError(f"Invalid answer-sheet download for {cells[0]}")
            links.append(f'<td><a href="{escape(match[2])}">{escape(match[1])}</a></td>')
        rows.append(f'<tr><th scope="row">{escape(cells[0])}</th>{"".join(links)}</tr>')
    if not rows:
        raise ValueError("Missing answer-sheet downloads")
    intro = "按科目提供旧版和新版矢量答题卡，支持打印，已加密并嵌入隐水印。"
    replacements = {
        "TITLE": heading,
        "DESCRIPTION": intro,
        "CANONICAL": f"{SITE}/answer-sheets/",
        "HEADING": heading,
        "EYEBROW": "旧版 · 新版",
        "INTRO": intro,
        "RELEASE": f"{RELEASES}/tag/answer-sheets",
        "DOWNLOAD_ROWS": "\n".join(rows),
        "RELATED_RESOURCES": related_resources("answer-sheets"),
        "WORKBOOKS": "",
        "WORKBOOK_LINK": "",
        "DOWNLOAD_NOTE": "396、311、333 和 306 的新版文字均为纯矢量路径。斜线表示该版本暂无对应文件。2026-11-15 修复 396 旧版答题卡及真题试卷内嵌答题卡的纸边黑线。",
        "EXTRA": "",
    }
    template = template.replace("PDF 与 Anki 下载</h2>", "答题卡 PDF 下载</h2>")
    template = re.sub(
        r"<thead>.*?</thead>",
        '<thead><tr><th scope="col">科目</th><th scope="col">旧版矢量 PDF</th>'
        '<th scope="col">新版矢量 PDF</th></tr></thead>',
        template,
        count=1,
    )
    template = re.sub(r'<section aria-labelledby="previews">.*?</section>', "", template, count=1, flags=re.S)
    page = output / "answer-sheets"
    page.mkdir(parents=True, exist_ok=True)
    (page / "index.html").write_text(
        re.sub(r"__([A-Z_]+)__", lambda match: replacements[match[1]], template)
    )


def render(output):
    readme = (ROOT / "README.md").read_text()
    template = (ROOT / "scripts/exam_download_page.html").read_text()
    books = read_workbooks(readme)
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
        workbook_numbers = tuple(number for _, number in config["subjects"] if number in books)
        replacements = {
            "TITLE": config["heading"] + "｜" + config["subtitle"],
            "DESCRIPTION": re.sub(r"<[^>]+>", "", config["intro"]),
            "CANONICAL": f"{SITE}/{subject}/",
            "HEADING": config["heading"],
            "EYEBROW": config["eyebrow"],
            "INTRO": config["intro"],
            "RELEASE": f"{RELEASES}/tag/{subject}-exams",
            "DOWNLOAD_ROWS": "\n".join(download_rows(readme, subject)),
            "RELATED_RESOURCES": related_resources(subject),
            "WORKBOOKS": workbook_section(books, workbook_numbers, "../workbooks/previews/") if workbook_numbers else "",
            "WORKBOOK_LINK": '<p><a href="#workbook-downloads">下载本学科做题本</a></p>' if workbook_numbers else "",

            "PREVIEWS": "\n".join(figures),
            "DOWNLOAD_NOTE": config.get("note", "真题试卷适合整卷练习，答案速查用于对答案。答案详解提供解题步骤，真题与详解把试题和解析收在同一册。Anki 卡包按年份与题型组织。"),
            "PREVIEW_NOTE": config.get("preview_note", "点击图片查看大图。双页图展示目录、试卷、答案和解析的实际排版。"),
            "EXTRA": f'<h3>独立考试大纲</h3><ul class="syllabus">{syllabus_items}</ul>',
        }
        (page / "index.html").write_text(
            re.sub(r"__([A-Z_]+)__", lambda match: replacements[match[1]], template)
        )
    render_answer_sheets(output, readme, template)
    render_workbook_hub(output, books, template)
    urls = "".join(f"  <url><loc>{SITE}/{subject}/</loc></url>\n" for subject in (*PAGES, "answer-sheets", "workbooks"))
    (output / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + urls + '</urlset>\n'
    )
    for verification in (ROOT / "assets/pages-verification").glob("google*.html"):
        shutil.copyfile(verification, output / verification.name)


if __name__ == "__main__":
    render(Path(sys.argv[1]))
