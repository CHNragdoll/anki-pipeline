"""Produce an immutable question-bank input for the common package importer.

This is a source-format adapter. Final Web and Anki deliveries must both come
from study_catalog_export, never directly from this intermediate collection.
"""
from __future__ import annotations
import hashlib
from contextlib import closing
import html
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import zipfile

FIELDS = ('Title', 'Question', 'Answer', 'Source', 'Status', 'SourceRecord')
FRONT = '<article class="exam-notecard"><header class="exam-heading"><span>真题练习</span><h1>{{Title}}</h1></header><div class="exam-body">{{Question}}</div></article>'
BACK = '<article id="answer" class="exam-notecard exam-answer" data-answer-status="{{Status}}"><header class="exam-heading"><span>答案与解析</span><h1>{{Title}}</h1></header><div class="exam-body">{{Answer}}</div><details class="exam-question-reference"><summary>回看本题题目与材料</summary><div class="exam-body">{{Question}}</div></details><footer class="exam-source">{{Source}}</footer><details class="exam-audit"><summary>来源与原始记录</summary><pre>{{SourceRecord}}</pre></details></article>'

CSS = '''.card{font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;font-size:18px;line-height:1.85;color:#243248;background:#f5f7fb;text-align:left;margin:0;padding:12px;overflow-wrap:break-word}.exam-notecard{box-sizing:border-box;max-width:920px;margin:14px auto 24px;padding:26px 30px;background:white;border:1px solid #dce5f1;border-radius:16px}.exam-heading{padding-bottom:15px;margin-bottom:18px;border-bottom:1px solid #e5ebf3}.exam-heading>span{font-size:13px;font-weight:600;color:#5374a5;letter-spacing:.04em}.exam-heading h1{font-size:20px;line-height:1.5;margin:8px 0 0}.exam-body p{margin:.8em 0}.exam-body h2,.exam-body h3{font-size:18px;margin:1.4em 0 .6em}.choices{display:grid;gap:10px;margin:18px 0}.choice{display:flex;gap:12px;padding:10px 14px;background:#f7f9fc;border:1px solid #e5ebf3;border-radius:8px}.choice>b{flex:none;color:#355b91}.choice>span{min-width:0}.exam-body img{display:block;max-width:100%;height:auto;margin:16px auto}.table-scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;margin:18px 0}th,td{border:1px solid #dce5f1;padding:8px 12px;vertical-align:top}.exam-answer{border-top:3px solid #527bb5}.exam-missing,.exam-answer[data-answer-status=missing]{border-color:#d9b876}.exam-missing{padding:15px;background:#fff9e9;border:1px solid #e5cf9a;border-radius:8px;color:#805f24}.exam-source{font-size:13px;color:#718198;margin-top:24px;padding-top:14px;border-top:1px solid #e5ebf3}.exam-audit{font-size:12px;color:#718198;margin-top:16px}.exam-audit summary{cursor:pointer}.exam-audit pre{white-space:pre-wrap;word-break:break-word;max-height:440px;overflow:auto}.nightMode.card,.night_mode.card{background:#181d25;color:#e2e7ef}.nightMode .exam-notecard,.night_mode .exam-notecard{background:#232b36;border-color:#3d4a5c}.nightMode .choice,.night_mode .choice{background:#2b3544;border-color:#3d4a5c}@media(max-width:600px){.card{padding:8px;font-size:17px}.exam-notecard{padding:20px 18px;border-radius:12px}.exam-heading h1{font-size:18px}}'''


def _number(namespace, key):
    return int(hashlib.sha256((namespace + '\0' + key).encode()).hexdigest()[:8], 16) % 2_147_483_646 + 1


def source_package(snapshot, destination, *, book_id, title):
    import genanki
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError('source package already exists; preserve its native identities')
    destination.parent.mkdir(parents=True, exist_ok=True)
    model = genanki.Model(_number('exam-model', 'v1'), '整卷真题 · 通用题目 v1',
        fields=[{'name': name} for name in FIELDS], templates=[{'name': '题目 → 答案解析', 'qfmt': FRONT, 'afmt': BACK}], css=CSS)
    decks = {}; missing = []
    seen = set()
    for row in snapshot['questions']:
        if row['key'] in seen:
            raise ValueError('duplicate exam question identity')
        seen.add(row['key'])
        year = str(row['year'])
        if year not in decks:
            decks[year] = genanki.Deck(_number('exam-unit', book_id + ':' + year), title + '::' + year + ' 年')
        source = html.escape(row['source_label']) + '<br>题目 ID：' + html.escape(row['key'])
        fields = [html.escape(row['title']), row['question'], row['answer'], source, row['status'],
                  html.escape(json.dumps(row['source_record'], ensure_ascii=False, separators=(',', ':')))]
        guid = genanki.guid_for('anki-pipeline/exam-question/v1', book_id, row['key'])
        note = genanki.Note(model=model, fields=fields, guid=guid,
                           tags=['exam', 'year::' + year, row['type'], 'answer::' + row['status']])
        decks[year].add_note(note)
        if row['status'] != 'available':
            missing.append(guid)
    resources = snapshot['resources']
    for alias, resource in resources.items():
        raw = Path(resource['path']).read_bytes()
        if len(raw) != resource['bytes'] or hashlib.sha256(raw).hexdigest() != resource['sha256']:
            raise ValueError('source media changed')
    with tempfile.TemporaryDirectory(prefix='exam-source-') as temporary:
        root = Path(temporary); media = root / 'media'; media.mkdir()
        files = []
        for alias, resource in resources.items():
            path = media / alias; path.write_bytes(Path(resource['path']).read_bytes()); files.append(str(path))
        raw_package = root / 'source.apkg'
        package = genanki.Package(list(decks.values())); package.media_files = files
        package.write_to_file(str(raw_package), timestamp=int(time.time()))
        with zipfile.ZipFile(raw_package) as archive:
            collection = root / 'collection.anki2'; collection.write_bytes(archive.read('collection.anki2'))
            with closing(sqlite3.connect(collection)) as db, db:
                for guid in missing:
                    db.execute('UPDATE cards SET queue=-1 WHERE nid IN (SELECT id FROM notes WHERE guid=?)', (guid,))
                if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('source collection integrity failed')
                notes = db.execute('SELECT count(*) FROM notes').fetchone()[0]
                cards = db.execute('SELECT count(*) FROM cards').fetchone()[0]
                assert notes == cards == len(seen)
            with zipfile.ZipFile(destination, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as output:
                for entry in archive.infolist():
                    output.writestr(entry.filename, collection.read_bytes() if entry.filename == 'collection.anki2' else archive.read(entry.filename))
    with destination.open('rb') as stream:
        package_sha256 = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'book_id': book_id, 'notes': len(seen), 'cards': len(seen), 'years': len(decks), 'media': len(resources),
            'missing_answer_suspended': len(missing), 'source_sha256': snapshot['source_sha256'],
            'package_sha256': package_sha256, 'bytes': destination.stat().st_size}
