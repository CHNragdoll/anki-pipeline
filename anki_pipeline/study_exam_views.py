"""Whole-paper access using the same projected notes and template renderer.

This is an additional Web navigation view, not an independent source parser or
answer renderer. Both halves are the exact authored Anki template projection.
"""
from __future__ import annotations
import hashlib
import html
import json
from pathlib import Path


def write_paper_views(db, book, root):
    from .study_catalog_export import _web_catalog_notes, _render_note
    from .study_catalog_presentation import rewrite_field_references
    from .study_catalog_math import required, header
    grouped = {}; resources = {}
    for name, in db.execute('SELECT name FROM resource_aliases WHERE book_id=%s', (book['id'],)):
        resources[name] = '../media/' + name
    for note, natives in _web_catalog_notes(db, book):
        if len(natives) != 1:
            raise ValueError('whole-paper view requires one authored card per question')
        unit = natives[0][2]; fields = dict(zip(note['field_names'], note['fields']))
        front, back = _render_note(note, natives[0][1])
        if back.startswith(front):
            back = back[len(front):]
        section = ''
        if fields.get('SourceRecord'):
            record = json.loads(html.unescape(fields['SourceRecord']))
            section = record.get('question', {}).get('sectionTitle', '')
        grouped.setdefault(unit, []).append({'front': rewrite_field_references(front, resources),
            'back': rewrite_field_references(back, resources), 'section': section,
            'css': note['model'].get('css', ''), 'math': required(note['fields'])})
    folder = Path(root) / 'papers'; folder.mkdir()
    links = []
    style = 'body{margin:0;background:#f5f7fb;color:#243248;font-family:-apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif}main{max-width:1040px;margin:auto;padding:24px 12px}.paper-top{padding:18px 22px;background:white;border:1px solid #dce5f1;border-radius:14px;margin-bottom:24px}.paper-top a{color:#355f9c}.paper-section{max-width:920px;margin:30px auto 12px;padding:0 12px;font-size:18px;line-height:1.8}.paper-answer{max-width:920px;margin:-10px auto 28px}.paper-answer>summary{cursor:pointer;color:#355f9c;padding:12px 20px;background:#edf3fb;border-radius:10px}.paper-answer .exam-notecard{margin-top:12px}.paper-links{display:grid;gap:12px}.paper-links a{padding:16px 20px;border:1px solid #dce5f1;border-radius:10px;background:white;color:#355f9c;text-decoration:none}'
    for unit, questions in grouped.items():
        filename = hashlib.sha256(unit.encode()).hexdigest()[:16] + '.html'
        label = unit.split('::', 1)[-1]
        links.append((filename, label, len(questions)))
        body = []; previous = None
        for row in questions:
            if row['section'] and row['section'] != previous:
                body.append('<h2 class="paper-section">' + html.escape(row['section']) + '</h2>')
                previous = row['section']
            body.append(row['front'] + '<details class="paper-answer"><summary>查看本题答案与解析</summary>' + row['back'] + '</details>')
        math = header('../media/_study_mathjax/tex-chtml-full.js') if any(row['math'] for row in questions) else ''
        (folder / filename).write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>' + html.escape(book['title'] + ' · ' + label) + '</title><style>' + questions[0]['css'] + style + '</style>' + math + '<main><header class="paper-top"><a href="index.html">← 全部年份</a> · <a href="../index.html">逐题卡片</a><h1>' + html.escape(label) + '</h1><p>' + str(len(questions)) + ' 道题 · 题目、材料与小问完整保留 · 点击展开本题答案</p></header>' + ''.join(body) + '</main></html>')
    (folder / 'index.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>' + html.escape(book['title']) + ' · 整卷阅读</title><style>' + style + '</style><main><header class="paper-top"><a href="../index.html">← 逐题卡片</a><h1>' + html.escape(book['title']) + '</h1><p>整卷阅读 · 答案默认收起 · 与 Anki 共用总库中的题目和答案投影</p></header><nav class="paper-links">' + ''.join('<a href="' + name + '">' + html.escape(label) + ' · ' + str(count) + ' 题</a>' for name, label, count in links) + '</nav></main></html>')
    return {'papers': len(links), 'questions': sum(count for _, _, count in links), 'index': 'papers/index.html'}
