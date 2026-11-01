#!/usr/bin/env python3
"""Collect public repository metrics and authorized Traffic; render portable SVGs.

No third-party dependencies. Credentials stay in gh/environment, never in outputs.
README's current release rows are the single source for book/card scope.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone, timedelta, date
from html import escape
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
REPO = "CHNragdoll/anki-pipeline"
BLUE, TEAL, INK, MUTED, LINE = "#215fbb", "#087e80", "#202b3c", "#596779", "#dce4ef"


def api(endpoint: str, *, paginate: bool = False, star: bool = False, token: str | None = None):
    command = ["gh", "api", endpoint]
    if paginate:
        command += ["--paginate", "--slurp"]
    if star:
        command += ["-H", "Accept: application/vnd.github.star+json"]
    env = dict(os.environ, GH_TOKEN=token) if token else None
    result = subprocess.run(command, capture_output=True, text=True, timeout=90, env=env)
    if result.returncode:
        # Do not persist stderr: authentication diagnostics can include private context.
        raise RuntimeError(f"GitHub request failed: {endpoint.split('?')[0]}")
    data = json.loads(result.stdout)
    return [item for page in data for item in page] if paginate else data


def book_rows(readme: str) -> list[dict]:
    """Use only the current APKG table, not historical examples elsewhere in README."""
    section = readme.split("## 下载 Anki 卡包", 1)[1].split("<!-- pinned-entrypoints:end -->", 1)[0]
    books = []
    for row in section.splitlines():
        if not row.startswith("| ") or "/releases/download/" not in row:
            continue
        cells = [cell.strip() for cell in row.strip("|").split("|")]
        match = re.search(r"https://github\.com/([^/]+/[^/]+)/releases/download/([^/]+)/([^\s)]+\.apkg)", cells[1])
        if not match or match[1] != REPO:
            raise ValueError("Invalid current package URL")
        cards, groups = [int(value.replace(",", "")) for value in cells[2].split("/")]
        subject = "408" if match[2] == "cs408-exams" else "政治" if match[2] == "politics-exams" else "英语"
        questions = re.search(r"([\d,]+) 道", cells[3])
        books.append({"name": cells[0], "tag": match[2], "asset": match[3], "cards": cards,
                      "groups": groups, "subject": subject,
                      "questions": int(questions[1].replace(",", "")) if questions else 0,
                      "size_label": cells[4], "download_url": match[0]})
    if not books or len({book["tag"] for book in books}) != len(books):
        raise ValueError("Current release rows missing or duplicated")
    return books


def apkg_assets(releases: list[dict]) -> list[dict]:
    return [dict(asset, tag=release["tag_name"]) for release in releases
            if not release.get("draft") for asset in release.get("assets", [])
            if asset["name"].lower().endswith(".apkg")]


def merge_traffic(old: dict, snapshot: dict, fetched_at: str) -> dict:
    """Replace reported dates (including downward corrections); never invent zeros."""
    history = json.loads(json.dumps(old))
    for kind, key in (("views", "views"), ("clones", "clones")):
        incoming = snapshot.get(kind)
        if incoming is None:
            continue
        days = history.setdefault(kind, {})
        for row in incoming[key]:
            day = date.fromisoformat(row["timestamp"][:10]).isoformat()
            count, uniques = row["count"], row["uniques"]
            if not isinstance(count, int) or not isinstance(uniques, int) or not 0 <= uniques <= count:
                raise ValueError("Invalid Traffic count")
            days[day] = {"count": count, "uniques": uniques}
        # A window UV is authoritative; it is not a sum of daily uniques.
        history[kind + "_window"] = {"count": incoming["count"], "uniques": incoming["uniques"],
                                     "fetched_at": fetched_at,
                                     "start": None if not incoming[key] else incoming[key][0]["timestamp"][:10],
                                     "end": None if not incoming[key] else incoming[key][-1]["timestamp"][:10]}
    return history


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(path)


def collect(readme: str, previous: dict) -> tuple[dict, dict]:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    repository = api(f"repos/{REPO}")
    releases = api(f"repos/{REPO}/releases?per_page=100", paginate=True)
    assets = apkg_assets(releases)
    books = book_rows(readme)
    for book in books:
        current = [asset for asset in assets if asset["tag"] == book["tag"] and asset["name"] == book["asset"]]
        if len(current) != 1:
            raise ValueError(f"Current published APKG not found: {book['tag']}")
        book.update(downloads=current[0]["download_count"], bytes=current[0]["size"],
                    release_apkg_downloads=sum(a["download_count"] for a in assets if a["tag"] == book["tag"]))
    traffic, unavailable = {}, []
    for kind in ("views", "clones"):
        try:
            traffic[kind] = api(f"repos/{REPO}/traffic/{kind}?per=day", token=os.environ.get("PROJECT_METRICS_TOKEN"))
        except (RuntimeError, subprocess.TimeoutExpired):
            traffic[kind] = None
            unavailable.append(kind)
    history = merge_traffic(previous, traffic, now)
    history.setdefault("stars", {})[now[:10]] = repository["stargazers_count"]
    stargazers = api(f"repos/{REPO}/stargazers?per_page=100", paginate=True, star=True)
    languages = api(f"repos/{REPO}/languages")
    since = (datetime.now(timezone.utc) - timedelta(days=366)).isoformat()
    commits = api(f"repos/{REPO}/commits?since={since}&per_page=100", paginate=True)
    commit_days = {}
    for commit in commits:
        day = commit['commit']['committer']['date'][:10]
        commit_days[day] = commit_days.get(day, 0)+1
    cutoff = (datetime.now(timezone.utc)-timedelta(days=30)).isoformat()
    data = {"schema": "project-metrics.v1", "repository": REPO, "collected_at": now,
            "stars": repository["stargazers_count"], "forks": repository["forks_count"],
            "open_issues_and_prs": repository["open_issues_count"],
            "license": (repository.get("license") or {}).get("spdx_id", "NOASSERTION"),
            "apkg_downloads_all_releases": sum(asset["download_count"] for asset in assets),
            "books": books, "languages": languages,
            "commits_30_days": sum(c['commit']['committer']['date'] >= cutoff for c in commits),
            "commit_days": commit_days, "default_branch": repository.get('default_branch', 'main'),
            "commit_coverage_start": (datetime.fromisoformat(now)-timedelta(days=365)).date().isoformat(),
            "commit_coverage_end": now[:10],
            "current_stargazer_dates": [row["starred_at"][:10] for row in stargazers],
            "traffic_unavailable": unavailable, "history": history}
    return data, history


def text(x, y, value, size=14, fill=INK, weight=400, anchor="start"):
    return f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" font-weight="{weight}" text-anchor="{anchor}">{escape(str(value))}</text>'


def svg(title, width, height, parts):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title, quote=True)}">'
            f'<title>{escape(title)}</title><style>text{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;font-variant-numeric:tabular-nums}}</style>'
            f'<rect width="{width}" height="{height}" rx="12" fill="white" stroke="{LINE}"/>' + "".join(parts) + '</svg>\n')


def timestamp_label(data):
    return data["collected_at"].replace("T", " ").replace("+00:00", " UTC")


def overview(data):
    books = data["books"]
    parts = [text(28, 35, "项目内容概览", 21, weight=650), text(28, 59, "按当前正式卡包统计 · 含说明与查阅卡，不等于去重知识点数", 13, MUTED)]
    totals = [("学科", len({b["subject"] for b in books})), ("完整卡包", len(books)),
              ("卡片合计", sum(b["cards"] for b in books)), ("政治＋408试题", sum(b["questions"] for b in books))]
    for i, (label, value) in enumerate(totals):
        x = 28 + i * 225
        parts += [text(x, 102, label, 14, MUTED), text(x, 140, f"{value:,}", 29, BLUE, 650)]
    labels = {"cs408-exams": "考研408历年真题", "politics-exams": "考研政治历年真题",
              "redbook-2027.10.06": "2027 红宝书", "redbook-2026.10.06": "2026 红宝书", "v3.0.1": "2027 刘晓艳"}
    parts += [text(28, 181, '卡包与年份', 12, MUTED), text(430, 181, '卡片', 12, MUTED, anchor='end'),
              text(600, 181, '有卡分组', 12, MUTED, anchor='end'), text(760, 181, '当前包下载', 12, MUTED, anchor='end'),
              text(912, 181, '全部版本下载', 12, MUTED, anchor='end'), f'<path d="M28 194H912" stroke="{LINE}"/>']
    for i, book in enumerate(books):
        y = 221 + i * 30
        parts += ['<a href="https://github.com/CHNragdoll/anki-pipeline/releases/tag/'+escape(book['tag'], quote=True)+'">'+text(28, y, labels.get(book["tag"], book["tag"]), 15, BLUE)+'</a>' ,
                  text(430, y, f'{book["cards"]:,} 张卡', 15, anchor="end"),
                  text(600, y, book['groups'], 14, MUTED, anchor="end"),
                  text(760, y, f'{book["downloads"]:,} 次', 14, BLUE, anchor="end"),
                  text(912, y, f'{book["release_apkg_downloads"]:,} 次', 14, TEAL, anchor="end")]
    parts += [text(28, 391, "英语真题 2000—2026；政治／408 年份分别列示。各年份、各书之间可能存在重复内容。", 12, MUTED),
              text(28, 416, "更新：" + timestamp_label(data), 12, MUTED)]
    return svg("项目内容概览", 940, 440, parts)


def chart(title, subtitle, days, series, note, collected_at, mobile=False):
    width, height = (400, 360) if mobile else (600, 330)
    left, right, top, bottom = 44, width-24, 112, 240
    values = [mapping[day] for _, mapping, _ in series for day in days if day in mapping]
    maximum = max(values + [1])
    parts = [text(24, 33, title, 20, weight=650), text(24, 57, subtitle, 12, MUTED)]
    for i, (name, _, color) in enumerate(series):
        x = 24 + i * (180 if mobile else 225)
        parts += [f'<path d="M{x} 80h20" stroke="{color}" stroke-width="3"/>', text(x+28, 84, name, 13, color)]
    for n in range(3):
        y = bottom - n * (bottom-top)/2
        parts += [f'<path d="M{left} {y}H{right}" stroke="{LINE}"/>', text(left-10, y+4, f"{maximum*n/2:g}", 11, MUTED, anchor="end")]
    if days:
        positions = {day: left+i*(right-left)/max(1, len(days)-1) for i, day in enumerate(days)}
        for series_index, (_, mapping, color) in enumerate(series):
            segment = []
            for day in days + [None]:
                if day not in mapping:
                    if segment:
                        parts.append(f'<polyline points="{" ".join(segment)}" fill="none" stroke="{color}" stroke-width="2.5"/>')
                    segment = []
                    continue
                x, y = positions[day], bottom-mapping[day]*(bottom-top)/maximum
                segment.append(f"{x:.2f},{y:.2f}")
                parts.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3" fill="{color}"><title>{escape(day)}: {mapping[day]}</title></circle>')
                if not mobile or len(days) <= 16:
                    # Every point is readable as a static README image; interactive page adds tooltips.
                    offset = -9 if series_index == 0 else 16
                    parts.append(text(round(x, 2), round(y+offset, 2), mapping[day], 10, color, anchor='middle'))
        for index in sorted({0, len(days)//2, len(days)-1}):
            parts.append(text(positions[days[index]], 282, days[index][5:], 11, MUTED, anchor="middle"))
    else:
        parts.append(text(300, 190, "暂无已采集数据", 16, MUTED, anchor="middle"))
    if mobile:
        # Source SVG stays readable at phone width; no tiny desktop graphic scaled down.
        parts += [text(24, 299, note[:29], 12, MUTED), text(24, 318, note[29:], 12, MUTED),
                  text(24, 343, "采集：" + collected_at[:19].replace("T", " ") + " UTC", 11, MUTED)]
    else:
        parts += [text(24, 299, note, 11, MUTED), text(24, 318, "采集：" + collected_at, 10, MUTED)]
    return svg(title, width, height, parts)


def traffic_chart(data, kind, mobile=False):
    mapping = data["history"].get(kind, {})
    # Daily records use GitHub's UTC date; do not reinterpret them as Beijing days.
    if mapping:
        end = date.fromisoformat(max(mapping))
        start = max(date.fromisoformat(min(mapping)), end-timedelta(days=29))
        days = [(start+timedelta(days=i)).isoformat() for i in range((end-start).days+1)]
    else:
        days = []
    window = data["history"].get(kind+"_window", {})
    names = ("每日浏览量 PV", "每日独立访客 UV") if kind == "views" else ("每日克隆次数", "每日独立克隆者")
    series = [(names[0], {d: row["count"] for d, row in mapping.items()}, BLUE),
              (names[1], {d: row["uniques"] for d, row in mapping.items()}, TEAL)]
    end_label = max(mapping) if mapping else "暂无数据"
    stale = " · 本次无权限，保留历史" if kind in data["traffic_unavailable"] else ""
    return chart("每日访客趋势" if kind == "views" else "每日克隆趋势",
                 f"UTC 日界 · 截至 {end_label}{stale}", days, series,
                 "缺失日期不补零；每日独立人数不可直接相加。", window.get("fetched_at", data["collected_at"]).replace("T", " "), mobile)


def stars_chart(data, mobile=False):
    dates = sorted(data["current_stargazer_dates"])
    if dates:
        start, end = date.fromisoformat(dates[0]), date.fromisoformat(max(dates[-1], data["collected_at"][:10]))
        days = [(start+timedelta(days=i)).isoformat() for i in range((end-start).days+1)]
        mapping = {day: sum(d <= day for d in dates) for day in days}
    else:
        days, mapping = [], {}
    return chart("Star 时间分布", f'当前 {data["stars"]} 个 Star · GitHub stargazers API', days,
                 [("当前仍保留的 Star 累计", mapping, BLUE)],
                 "由现存 Star 的时间重建，不含已取消 Star；不是完整净增长历史。", timestamp_label(data), mobile)


def overview_mobile(data):
    books = data['books']
    parts = [text(22, 34, '项目内容概览', 21, weight=650), text(22, 58, '当前正式包 · 含说明卡及查阅卡', 13, MUTED)]
    totals = [('学科', len({b['subject'] for b in books})), ('完整卡包', len(books)),
              ('卡片合计', sum(b['cards'] for b in books)), ('政治＋408试题', sum(b['questions'] for b in books))]
    for i, (label, value) in enumerate(totals):
        x, y = 22+(i%2)*184, 95+(i//2)*82
        parts += [text(x, y, label, 14, MUTED), text(x, y+34, f'{value:,}', 28, BLUE, 650)]
    labels = ['考研408历年真题', '考研政治历年真题', '2027 红宝书', '2026 红宝书', '2027 刘晓艳']
    for i, book in enumerate(books):
        y = 272+i*62
        parts += ['<a href="https://github.com/CHNragdoll/anki-pipeline/releases/tag/'+escape(book['tag'], quote=True)+'">'+text(22, y, labels[i], 15, BLUE)+'</a>' , text(378, y, f'{book["cards"]:,} 张', 15, BLUE, anchor='end'),
                  text(22, y+19, f'{book["groups"]} 个有卡分组 · 当前包 {book["downloads"]:,} 次下载', 12, MUTED),
                  text(22, y+37, f'全部版本 APKG 下载 {book["release_apkg_downloads"]:,} 次', 12, TEAL)]
    parts += [text(22, 599, '跨书、跨年份可能重复，不等于去重知识点数。', 12, MUTED),
              text(22, 621, '英语真题2000—2026；其他年份如上。', 12, MUTED),
              text(22, 646, '更新：'+timestamp_label(data), 11, MUTED)]
    return svg('项目内容概览（手机）', 400, 666, parts)


def combined_traffic(data, mobile=False):
    a, b = traffic_chart(data, 'views', mobile), traffic_chart(data, 'clones', mobile)
    width, height, bx, by = (400, 732, 0, 372) if mobile else (1216, 330, 616, 0)
    b = b.replace('<svg ', f'<svg x="{bx}" y="{by}" ', 1)
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="每日访客及克隆趋势"><title>每日访客及克隆趋势</title>{a}{b}</svg>\n'


def activity(data):
    languages = data["languages"]
    total = sum(languages.values()) or 1
    parts = [text(28, 35, "仓库活动与技术组成", 21, weight=650),
             text(28, 61, "项目级统计 · 不混入作者其他仓库的个人贡献", 13, MUTED)]
    items = [("Star", data["stars"]), ("Fork", data["forks"]),
             ("开放 Issue＋PR", data["open_issues_and_prs"]), ("近30天提交", data["commits_30_days"])]
    for i, (label, value) in enumerate(items):
        x = 28+i*225
        parts += [text(x, 100, label, 14, MUTED), text(x, 138, str(value), 28, BLUE, 650)]
    x = 28
    colors = [BLUE, TEAL, "#97651b", "#6634a3", "#75849b", "#bf5a40"]
    selected = sorted(languages.items(), key=lambda item: -item[1])[:5]
    rest = total-sum(value for _, value in selected)
    if rest:
        selected.append(("其他", rest))
    for i, (name, value) in enumerate(selected):
        w = value/total*884
        parts.append(f'<rect x="{x:.3f}" y="166" width="{w:.3f}" height="12" fill="{colors[i]}"/>')
        x += w
        parts.append(text(28+(i%3)*300, 210+(i//3)*27, f"{name}  {value/total:.1%}", 14, colors[i]))
    parts += [text(28, 280, "语言占比按 GitHub 识别的源代码字节，不是卡包内容占比。", 12, MUTED),
              text(28, 304, "更新："+timestamp_label(data), 12, MUTED)]
    return svg("仓库活动与技术组成", 940, 326, parts)


def activity_mobile(data):
    parts = [text(22, 34, '仓库活动与技术组成', 21, weight=650), text(22, 58, '仅当前仓库 · GitHub 官方数据', 13, MUTED)]
    items = [('Star', data['stars']), ('Fork', data['forks']),
             ('开放 Issue＋PR', data['open_issues_and_prs']), ('近30天提交', data['commits_30_days'])]
    for i, (label, value) in enumerate(items):
        x, y = 22+(i%2)*184, 94+(i//2)*75
        parts += [text(x, y, label, 14, MUTED), text(x, y+32, value, 26, BLUE, 650)]
    total = sum(data['languages'].values()) or 1
    selected = sorted(data['languages'].items(), key=lambda item: -item[1])[:5]
    for i, (name, value) in enumerate(selected):
        y = 252+i*28
        parts += [text(22, y, name, 15), text(378, y, f'{value/total:.1%}', 15, TEAL, anchor='end')]
    parts += [text(22, 408, '语言按源代码字节统计，不是卡包内容占比。', 12, MUTED),
              text(22, 432, '更新：'+timestamp_label(data), 11, MUTED)]
    return svg('仓库活动与技术组成（手机）', 400, 452, parts)


def maintenance_heatmap(data):
    if 'commit_days' not in data:
        return svg('仓库维护热力图', 940, 130, [text(24, 35, '仓库维护热力图', 21, weight=650), text(24, 77, '该快照尚无提交历史，请重新采集；不以零代替未知。', 14, MUTED)])
    end = date.fromisoformat(data['collected_at'][:10])
    first = end-timedelta(days=364)
    start = first-timedelta(days=(first.weekday()+1)%7)
    days = data.get('commit_days', {})
    parts = [text(24, 32, '仓库维护热力图', 21, weight=650),
             text(24, 56, '默认分支提交 · 提交者日期 / UTC · 不含其他仓库贡献', 13, MUTED)]
    previous_month = None
    colors = ['#edf2f8', '#c9dcf5', '#8db5e8', '#4c88d5', BLUE]
    for i in range((end-start).days+1):
        day = start+timedelta(days=i)
        x, y = 53+(i//7)*16, 92+(i%7)*17
        if day < first:
            continue
        value = days.get(day.isoformat(), 0)
        level = 0 if not value else min(4, 1+(value>2)+(value>5)+(value>12))
        if day.month != previous_month and day.day <= 7:
            parts.append(text(x, 81, f'{day.month}月', 11, MUTED))
            previous_month = day.month
        parts.append(f'<rect x="{x}" y="{y}" width="12" height="13" rx="2" fill="{colors[level]}"><title>{day}: {value} 次提交</title></rect>')
    parts += [text(22, 103, '日', 11, MUTED), text(22, 137, '二', 11, MUTED), text(22, 171, '四', 11, MUTED), text(22, 205, '六', 11, MUTED),
              text(24, 244, f'近一年 {sum(v for d,v in days.items() if first.isoformat() <= d <= end.isoformat()):,} 次提交 · {sum(v>0 for d,v in days.items() if first.isoformat() <= d <= end.isoformat())} 个活跃日', 14),
              text(24, 271, '点击首页的交互统计入口，可悬停或点按日期查看每日提交数。', 12, MUTED),
              text(24, 294, '更新：'+timestamp_label(data), 11, MUTED)]
    return svg('仓库维护热力图', 940, 316, parts)


def dashboard(data):
    template = Path(__file__).with_name('project_metrics_dashboard.html').read_text()
    # Prevent public metadata or future book titles from closing the inert JSON script.
    payload = json.dumps(data, ensure_ascii=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    return template.replace('__METRICS_JSON__', payload)


def activate_remote_links(readme_path: Path):
    """Run only during authorized publication, after data assets are publicly live."""
    content = readme_path.read_text()
    prefix = f'https://raw.githubusercontent.com/{REPO}/project-metrics/'
    paths = sorted(set(re.findall(r'assets/project-metrics/([\w.-]+\.(?:svg|json))', content)))
    for name in paths:
        with urlopen(prefix+name, timeout=20) as response:
            body = response.read()
        if name.endswith('.svg'):
            if not body.lstrip().startswith(b'<svg'):
                raise ValueError(f'Not a valid published SVG: {name}')
        elif json.loads(body).get('repository') != REPO:
            raise ValueError('Published snapshot repository mismatch')
    # No mutation until every asset passed. A 404 never creates broken README links.
    if paths:
        readme_path.write_text(content.replace('assets/project-metrics/', prefix))
    return len(paths)


def badge(label, value, color=BLUE):
    left = max(56, len(label)*7+18)
    right = max(42, len(str(value))*8+18)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{left+right}" height="22" role="img" aria-label="{escape(label)}: {escape(str(value))}">'
            f'<title>{escape(label)}: {escape(str(value))}</title><rect width="{left+right}" height="22" rx="4" fill="{color}"/>'
            f'<path fill="#47566c" d="M4 0h{left-4}v22H4q-4 0-4-4V4q0-4 4-4"/>'
            f'<g font-family="Verdana,sans-serif" font-size="11" fill="white" text-anchor="middle"><text x="{left/2}" y="15">{escape(label)}</text>'
            f'<text x="{left+right/2}" y="15">{escape(str(value))}</text></g></svg>\n')


def render(data, out: Path):
    out.mkdir(parents=True, exist_ok=True)
    for name, content in {"overview.svg": overview(data), "visitors.svg": traffic_chart(data, "views"),
                          "clones.svg": traffic_chart(data, "clones"), "stars.svg": stars_chart(data),
                          "overview-mobile.svg": overview_mobile(data), "stars-mobile.svg": stars_chart(data, True),
                          "traffic.svg": combined_traffic(data), "traffic-mobile.svg": combined_traffic(data, True),
                          "activity.svg": activity(data), "activity-mobile.svg": activity_mobile(data),
                          "maintenance.svg": maintenance_heatmap(data),
                          "apkg-downloads.svg": badge("APKG downloads", f'{data["apkg_downloads_all_releases"]:,}')}.items():
        (out/name).write_text(content)
    for book in data["books"]:
        (out/(book["tag"]+"-downloads.svg")).write_text(badge("APKG", f'{book["release_apkg_downloads"]:,}'))
    write_json(out/"snapshot.json", data)
    write_json(out/"history.json", data["history"])
    (out/'index.html').write_text(dashboard(data))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT/"assets/project-metrics")
    parser.add_argument("--history", type=Path)
    parser.add_argument("--snapshot", type=Path, help="Render an existing snapshot without network calls")
    parser.add_argument("--activate-remote-links", action='store_true', help='Verify public data-branch assets, then switch README links; only for authorized publication')
    args = parser.parse_args()
    if args.activate_remote_links:
        print(json.dumps({'verified_links': activate_remote_links(ROOT/'README.md')}))
        return
    if args.snapshot:
        data = json.loads(args.snapshot.read_text())
    else:
        history_path = args.history or args.output/"history.json"
        previous = json.loads(history_path.read_text()) if history_path.exists() else {}
        data, _ = collect((ROOT/"README.md").read_text(), previous)
    render(data, args.output)
    print(json.dumps({"output": str(args.output), "collected_at": data["collected_at"],
                      "books": len(data["books"]), "traffic_unavailable": data["traffic_unavailable"]}))


if __name__ == "__main__":
    main()
