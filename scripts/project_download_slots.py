"""Associate Release attachments with stable download cells and rebuild daily history."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from html import unescape
import re
from urllib.parse import unquote

BEIJING = timezone(timedelta(hours=8))
DOWNLOAD_RELEASES = {
    "math-exams": "考研数学历年真题",
    "politics-exams": "考研政治历年真题",
    "english-exams": "考研英语",
    "cs408-exams": "考研408历年真题",
    "management199-exams": "管理类综合能力（199）",
    "economics396-exams": "经济类综合能力（396）",
    "answer-sheets": "考研初试答题卡",
    "redbook-2027.10.06": "2027 红宝书",
    "redbook-2026.10.06": "2026 红宝书",
    "v3.0.1": "2027 刘晓艳",
}
EXAM_SUBJECTS = {
    "301": ("math1", "数学一", "math-exams"),
    "302": ("math2", "数学二", "math-exams"),
    "303": ("math3", "数学三", "math-exams"),
    "101": ("politics", "思想政治理论", "politics-exams"),
    "201": ("english1", "英语一", "english-exams"),
    "204": ("english2", "英语二", "english-exams"),
    "408": ("cs408", "计算机 408", "cs408-exams"),
    "199": ("management199", "管综 199", "management199-exams"),
    "396": ("economics396", "经综 396", "economics396-exams"),
}
EXAM_TYPES = {
    "questions": "真题试卷 PDF",
    "answers": "答案速查 PDF",
    "answer-details": "答案详解 PDF",
    "solutions": "真题与详解 PDF",
    "a4-adaptive": "做题本 PDF（A4 动态留白）",
    "a4-2": "做题本 PDF（A4 每页最多两题）",
    "a4-3": "做题本 PDF（A4 每页最多三题）",
    "a5-1": "做题本 PDF（A5 横向一页一题）",
    "anki": "Anki 完整包",
    "syllabus": "考试大纲 PDF",
}
EXAM_HEADERS = {
    **{label: kind for kind, label in EXAM_TYPES.items()},
    "做题本 PDF（动态留白）": "a4-adaptive",
    "A4 动态留白": "a4-adaptive",
    "A4 每页最多两题": "a4-2",
    "A4 每页最多三题": "a4-3",
    "A5 横向一页一题": "a5-1",
}
SHEET_SUBJECTS = {
    "politics": "政治",
    "english-1": "英语一",
    "english-2": "英语二",
    "english-writing": "英语作文纸",
    "math": "数学",
    "management-199": DOWNLOAD_RELEASES["management199-exams"],
    "economics-396": DOWNLOAD_RELEASES["economics396-exams"],
    "education-311": "教育学（311）",
    "psychology-312": "心理学（312）",
    "medicine-306": "西医综合（306）",
    "law-nonlaw-basic": "法硕（非法学）基础课",
    "law-nonlaw-comprehensive": "法硕（非法学）综合课",
    "law-law-basic": "法硕（法学）基础课",
    "law-law-comprehensive": "法硕（法学）综合课",
    "education-333": "教育综合（333）",
    "school-specific": "自命题专业课",
    "school-specific-a3": "自命题专业课 · A3 打印",
    "school-specific-b4": "自命题专业课 · B4 打印",
}
SHEET_TYPES = {"old": "旧版矢量 PDF", "new": "新版矢量 PDF"}
BOOKS = {
    "redbook2027.anki": ("2027 红宝书", "redbook-2027.10.06", r"2027-redbook-full-.+\.apkg"),
    "redbook2026.anki": ("2026 红宝书", "redbook-2026.10.06", r"2026-redbook-full-.+\.apkg"),
    "liuxiaoyan2027.anki": ("2027 刘晓艳", "v3.0.1", r"2027-liuxiaoyan-english-vocabulary-.+\.apkg"),
}
ASSET_LINK = re.compile(
    r'https://github\.com/CHNragdoll/anki-pipeline/releases/download/([^/]+)/([^\s)"<>]+\.(?:apkg|pdf))',
    re.IGNORECASE,
)

EXAM_FILE_RULES = {
    "questions": r"all-{subject}-questions(?:-\d{{8}}(?:-r\d+)?)?\.pdf",
    "answers": r"all-{subject}-answers(?:-\d{{8}}(?:-r\d+)?)?\.pdf",
    "answer-details": r"all-{subject}-answer-details(?:-\d{{8}}(?:-r\d+)?)?\.pdf",
    "solutions": r"all-{subject}-solutions(?:-\d{{8}}(?:-r\d+)?)?\.pdf",
    "syllabus": r"\d{{4}}-{subject}-syllabus(?:-\d{{8}}(?:-r\d+)?)?\.pdf",
    "anki": r"{subject}-past-exams-.+\.apkg",
    **{
        layout: r"{subject}-practice-workbook-{kind}-\d{{8}}(?:-r\d+)?\.pdf"
        for layout in ("a4-adaptive", "a4-2", "a4-3", "a5-1")
    },
}
SHEET_BY_LABEL = {value: key for key, value in SHEET_SUBJECTS.items()}
SYLLABUS_SUBJECTS = {
    "数学一": "math1", "数学二": "math2", "数学三": "math3", "政治": "politics",
    "英语一": "english1", "英语二": "english2", "408": "cs408", "管综": "management199", "经综": "economics396",
}


def asset_slot(tag, name):
    """Recognize published naming conventions for backfill; scoped to each fixed Release."""
    name = name.lower()
    for slot, (_, release, pattern) in BOOKS.items():
        if tag == release and re.fullmatch(pattern, name):
            return slot
    if tag == "answer-sheets":
        match = re.fullmatch(r"(.+)-answer-sheet-(2023|collection)(?:-\d{8}(?:-r\d+)?)?\.pdf", name)
        if match and match[1] in SHEET_SUBJECTS:
            return f"sheet.{match[1]}.{'old' if match[2] == '2023' else 'new'}"
    for subject, _, release in EXAM_SUBJECTS.values():
        if tag == release:
            for kind, pattern in EXAM_FILE_RULES.items():
                if re.fullmatch(pattern.format(subject=subject, kind=kind), name):
                    return f"{subject}.{kind}"
    return None


def asset_links(text):
    return {(unquote(tag), unquote(name)) for tag, name in ASSET_LINK.findall(text)}


def readme_slots(readme):
    """Map live links via table position, even when a replacement was named differently."""
    pinned = readme.split("## 下载 Anki 卡包", 1)[-1].split("<!-- pinned-entrypoints:end -->", 1)[0]
    mapped = {}

    def assign(link, slot):
        if slot:
            previous = mapped.setdefault(link, slot)
            if previous != slot:
                raise ValueError(f"Release link is assigned to multiple download cells: {link}")

    headers = []
    for line in pinned.splitlines():
        if not line.startswith("|"):
            headers = []
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if cells[0] in {"科目", "卡包"}:
            headers = [unescape(cell).replace("\u2060", "").replace("\xa0", " ").replace("<br/>", "")
                       for cell in cells]
            continue
        if not headers or len(headers) != len(cells):
            continue
        subject_match = re.search(r"·\s*(\d{3})$", cells[0])
        subject = EXAM_SUBJECTS.get(subject_match[1]) if subject_match else None
        for header, cell in zip(headers[1:], cells[1:]):
            links = asset_links(cell)
            for link in links:
                if subject and header in EXAM_HEADERS:
                    assign(link, f"{subject[0]}.{EXAM_HEADERS[header]}")
                elif cells[0] in SHEET_BY_LABEL and header in SHEET_TYPES.values():
                    kind = "old" if header == SHEET_TYPES["old"] else "new"
                    assign(link, f"sheet.{SHEET_BY_LABEL[cells[0]]}.{kind}")
                elif headers[0] == "卡包" and header == "APKG 下载":
                    vocabulary = next((slot for slot, (label, _, _) in BOOKS.items()
                                       if all(word in cells[0] for word in label.split())), None)
                    if vocabulary is None and "刘晓艳" in cells[0]:
                        vocabulary = "liuxiaoyan2027.anki"
                    assign(link, vocabulary or asset_slot(*link))
    for anchor, url in re.findall(r"\[([^\]\n]*考试大纲[^\]\n]*)\]\(([^)]+)\)", pinned):
        subject = next((subject for label, subject in SYLLABUS_SUBJECTS.items() if label in anchor), None)
        if subject:
            for link in asset_links(url):
                assign(link, f"{subject}.syllabus")
    for link in asset_links(pinned):
        # Includes individual syllabi in prose and the redundant Anki/download links.
        if link not in mapped:
            assign(link, asset_slot(*link))
    return mapped


def record_slot_assets(archive, readme, releases):
    """Persist ID associations so a later README link replacement can keep the old ID."""
    linked_slots = readme_slots(readme)
    archived_slots = archive.setdefault("slot_assets", {})
    for release in releases:
        if release.get("draft"):
            continue
        for asset in release.get("assets", []):
            slot = linked_slots.get((release["tag_name"], asset["name"]))
            if slot and "id" in asset:
                # An attachment keeps its original cell even if someone later reuses that ID in another cell.
                archived_slots.setdefault(str(asset["id"]), slot)


def slot_details(slot):
    if slot in BOOKS:
        label, release, _ = BOOKS[slot]
        return f"{label} · Anki 完整包", release
    parts = slot.split(".")
    if len(parts) == 3 and parts[0] == "sheet":
        _, subject, kind = parts
        return f"{SHEET_SUBJECTS[subject]} · 答题卡{SHEET_TYPES[kind]}", "answer-sheets"
    subject, kind = parts
    _, label, release = next(row for row in EXAM_SUBJECTS.values() if row[0] == subject)
    return f"{label} · {EXAM_TYPES[kind]}", release


def time_at(timestamp):
    return datetime.fromisoformat(timestamp).astimezone(timezone.utc)


def offline_slot_assets(archive, linked_slots, current_assets, collected_at):
    """Match README links against the selected snapshot's own public inventory."""
    cutoff = time_at(collected_at)
    eligible = [stamp for stamp in archive.get("samples", {}) if time_at(stamp) <= cutoff]
    if not eligible:
        return {}
    sample = archive["samples"][max(eligible, key=time_at)]["counts"]
    currents = {(row["tag"], row["name"]) for row in current_assets if row.get("published", True)}
    aliases = {}
    for identity in sample:
        metadata = archive.get("assets", {}).get(identity)
        if not metadata:
            continue
        link = tuple(metadata[:2])
        if link in currents and link in linked_slots:
            aliases[identity] = linked_slots[link]
    return aliases


def build_download_slots(archive, collected_at, active=(), aliases=None):
    """Use each attachment's latest observation, retaining the last count after withdrawal."""
    assets = archive.get("assets", {})
    assigned = {identity: slot
                for identity, (tag, name, *_) in assets.items()
                if (slot := asset_slot(tag, name))}
    assigned.update(aliases or {})
    assigned.update(archive.get("slot_assets", {}))
    by_legacy_link = defaultdict(list)
    for identity, metadata in assets.items():
        by_legacy_link[tuple(metadata[:2])].append(identity)
    cutoff = time_at(collected_at)
    versions = defaultdict(list)
    for identity, slot in assigned.items():
        created_at = assets[identity][2]
        uploaded = time_at(created_at) if created_at else None
        if uploaded is None or uploaded <= cutoff:
            versions[slot].append((identity, uploaded))

    observations = defaultdict(dict)
    complete = set()
    uncertain_legacy = set()
    for stamp, row in archive.get("legacy", {}).items():
        sampled = time_at(stamp)
        if sampled > cutoff:
            continue
        for tag, name, count in row.get("files", []):
            candidates = [identity for identity in by_legacy_link[tag, name]
                          if not assets[identity][2] or time_at(assets[identity][2]) <= sampled]
            if len(candidates) == 1 and candidates[0] in assigned:
                observations[sampled][candidates[0]] = count
            else:
                uncertain_legacy.update(assigned[identity] for identity in candidates if identity in assigned)
                if slot := asset_slot(tag, name):
                    uncertain_legacy.add(slot)
    for stamp, row in archive.get("samples", {}).items():
        sampled = time_at(stamp)
        if sampled > cutoff:
            continue
        observations[sampled].update({identity: count for identity, count in row.get("counts", {}).items()
                                      if identity in assigned})
        if row.get("total") is not None:
            complete.add(sampled)
    totals = {}
    latest = {}
    discoveries = defaultdict(list)
    zones = {"points": BEIJING, "utc_points": timezone.utc}
    daily = {key: defaultdict(dict) for key in zones}
    daily_full_sample = {key: {} for key in zones}
    for sampled, counts in sorted(observations.items()):
        touched = set()
        for identity, count in counts.items():
            slot = assigned[identity]
            if identity not in latest and count > 0:
                created_at = assets[identity][2]
                discoveries[slot].append((sampled, time_at(created_at) if created_at else None))
            totals[slot] = totals.get(slot, 0) + count - latest.get(identity, 0)
            latest[identity] = count
            touched.add(slot)
        # Seeded samples collect only a few files. Full snapshots also confirm the rest
        # of the public inventory so last known totals can persist after attachments disappear.
        for key, zone in zones.items():
            day = sampled.astimezone(zone).date()
            if sampled in complete:
                daily_full_sample[key][day] = sampled
            for slot in totals.keys() if sampled in complete else touched:
                daily[key][slot][day] = (sampled, totals[slot])

    def series(slot, key, zone):
        current_day = cutoff.astimezone(zone).date()
        days = daily[key][slot]
        first_day = min(days, default=None)
        for day, (sampled, total) in sorted(days.items()):
            previous_day = day - timedelta(days=1)
            prior = days.get(previous_day)
            prior_full = daily_full_sample[key].get(previous_day)
            change = None
            if prior and (prior[0] in complete) == (sampled in complete):
                # First observations of an older attachment may contain preexisting downloads.
                # A file-only sample and a complete inventory also have different coverage.
                widened = any(prior[0] < first <= sampled and (created is None or created <= prior[0])
                              for first, created in discoveries[slot])
                if not widened:
                    change = total - prior[1]
            elif (day == first_day and sampled in complete and prior_full and slot not in uncertain_legacy
                  and all(created and created > prior_full for _, created in versions[slot])):
                # A complete inventory before all of this cell's uploads establishes a zero baseline.
                change = total
            yield {
                "day": day.isoformat(),
                "total": total,
                "change": change,
                "sampled_at": sampled.isoformat(),
                "partial": day == current_day or sampled not in complete,
            }

    slots = []
    missing_upload = datetime.min.replace(tzinfo=timezone.utc)
    for slot in sorted(set(assigned.values()) | set(active)):
        label, release = slot_details(slot)
        # Numeric IDs break timestamp ties, including the legacy case without upload times.
        ordered_versions = sorted(versions[slot],
                                  key=lambda row: (row[1] or missing_upload, len(row[0]), row[0]), reverse=True)
        slots.append({"id": slot, "label": label, "release": release,
                      "asset_ids": [identity for identity, _ in ordered_versions],
                      **{key: list(series(slot, key, zone)) for key, zone in zones.items()}})
    order = {tag: index for index, tag in enumerate(DOWNLOAD_RELEASES)}
    subject_order = {key: index for index, (key, _, _) in enumerate(EXAM_SUBJECTS.values())}
    role_order = {kind: index for index, kind in enumerate(EXAM_TYPES)}
    return sorted(slots, key=lambda row: (
        order[row["release"]],
        subject_order.get(row["id"].split(".")[0], -1),
        role_order.get(row["id"].split(".")[-1], -1),
        row["id"],
    ))
