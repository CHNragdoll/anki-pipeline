"""Read-only question-bank adapter for the common, subject-neutral catalog.

Use explicit question/answer block ownership. A normalized explanation is not
an exhaustive answer: original answer blocks remain authoritative and retained.
No answer inference, source edits or output-host rendering happens here.
"""
from __future__ import annotations

import hashlib
from contextlib import closing
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import unquote, urlsplit

_TYPES = {'single_choice': '单选题', 'multiple_choice': '多选题', 'free_response': '材料分析题'}
_FORBIDDEN = {'script', 'style', 'iframe', 'object', 'embed', 'base', 'meta', 'link', 'form', 'input', 'button'}


class _Portable(HTMLParser):
    def __init__(self, base, root, resources, overrides):
        super().__init__(convert_charrefs=False)
        self.base, self.root, self.resources, self.overrides = base, root, resources, overrides
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in _FORBIDDEN or any(name.lower().startswith('on') for name, _ in attrs):
            raise ValueError('active markup is not an exam source block')
        raw = self.get_starttag_text()
        for name, value in attrs:
            if value and (name == 'style' and re.search(r'url\s*\(|expression\s*\(', value, re.I) or value.lstrip().lower().startswith('javascript:')):
                raise ValueError('active resource in exam source block')
        if tag == 'img':
            value = dict(attrs).get('src')
            if not value:
                raise ValueError('image source is missing')
            url = urlsplit(value)
            if url.scheme or url.netloc or url.query or url.fragment or '\\' in value or '\x00' in unquote(value):
                raise ValueError('only confined local exam images may be packaged')
            path = (self.base / unquote(url.path)).resolve(strict=False)
            if not path.is_relative_to(self.root) or not path.is_file():
                raise ValueError('exam image escapes its source root')
            seal = self.overrides.get(str(path))
            source = path
            if seal:
                state = path.stat()
                if (state.st_size, state.st_mtime_ns) != (seal['source_bytes'], seal['source_mtime_ns']):
                    raise ValueError('sealed source image metadata changed')
                source = Path(seal['path']).resolve(strict=True)
            data = source.read_bytes()
            if seal and hashlib.sha256(data).hexdigest() != seal['sha256']:
                raise ValueError('sealed image bytes differ')
            suffix = path.suffix.lower()
            if suffix not in {'.svg', '.png', '.jpg', '.jpeg', '.gif', '.webp'}:
                raise ValueError('unsupported exam image type')
            if suffix == '.svg' and re.search(rb'<script\b|\bon\w+\s*=|(?:href|xlink:href)\s*=\s*[\"\']\s*(?:https?:|file:|javascript:)', data, re.I):
                raise ValueError('active SVG source')
            sha = hashlib.sha256(data).hexdigest()
            alias = '_exam_' + sha + suffix
            self.resources[alias] = {'path': str(source), 'source_path': str(path), 'bytes': len(data), 'sha256': sha, 'recovery': seal}
            raw, count = re.subn(r'(\bsrc\s*=\s*)([\"\'])(.*?)\2',
                                lambda m: m[1] + m[2] + alias + m[2], raw, count=1, flags=re.I | re.S)
            if count != 1:
                raise ValueError('image source must be explicitly quoted')
        self.parts.append(raw)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag in _FORBIDDEN:
            raise ValueError('active markup is not an exam source block')
        self.parts.append('</' + tag + '>')

    def handle_data(self, data): self.parts.append(data)
    def handle_entityref(self, name): self.parts.append('&' + name + ';')
    def handle_charref(self, name): self.parts.append('&#' + name + ';')
    def handle_comment(self, data): self.parts.append('<!--' + data + '-->')


def _portable(raw, base, root, resources, overrides):
    parser = _Portable(base, root, resources, overrides)
    parser.feed(raw); parser.close()
    return ''.join(parser.parts)


def _paragraphs(text):
    return ''.join('<p>' + html.escape(part).replace('\n', '<br>') + '</p>'
                   for part in (text or '').split('\n\n') if part)


def read_bank(database, category, *, structured_root, asset_root=None, asset_overrides=None):
    database = Path(database).resolve(strict=True)
    structured_root = Path(structured_root).resolve(strict=True)
    asset_root = Path(asset_root or structured_root.parent.parent).resolve(strict=True)
    before = database.stat()
    with database.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    resources = {}; questions = []; papers = []
    overrides = asset_overrides or {}
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON'); db.execute('BEGIN')
        selected = list(db.execute("SELECT * FROM papers WHERE category=? AND kind='questions' ORDER BY year,ordinal,id", (category,)))
        if not selected:
            raise ValueError('no question papers in requested category')
        for paper in selected:
            paper = dict(paper)
            base = (structured_root / paper['reader_path']).parent
            if not base.resolve().is_relative_to(asset_root):
                raise ValueError('paper reader escapes its source root')
            paper_rows = []
            for question in db.execute('SELECT * FROM questions WHERE paper_id=? ORDER BY ordinal,id', (paper['id'],)):
                raw = json.loads(question['raw_json'])
                blocks = list(db.execute('SELECT DISTINCT b.* FROM source_blocks b JOIN question_source_blocks x ON x.block_id=b.id WHERE x.question_id=? ORDER BY b.ordinal,b.id', (question['id'],)))
                context = list(db.execute('SELECT b.* FROM source_blocks b JOIN context_source_blocks x ON x.block_id=b.id WHERE x.question_id=? ORDER BY x.ordinal', (question['id'],)))
                owned = {row['id']: dict(row) for row in [*context, *blocks]}
                body = ''.join(_portable(row['content_html'], base, asset_root, resources, overrides)
                               for row in sorted(owned.values(), key=lambda r: (r['ordinal'], r['id'])))
                if not body:
                    body = _paragraphs(raw.get('stem'))
                    body += ''.join('<p class="choice"><b>' + html.escape(str(o.get('label', ''))) + '</b> ' + html.escape(o.get('text', '')) + '</p>' for o in raw.get('options', []))
                if not body.strip():
                    raise ValueError('question has no complete source body')
                answer = db.execute('SELECT * FROM answers WHERE question_id=?', (question['id'],)).fetchone()
                original_answer = dict(answer) if answer else None
                answer_blocks = []
                answer_context = []
                if answer and answer['source_document_id']:
                    answer_context = [dict(row) for row in db.execute(
                        'SELECT * FROM source_blocks WHERE paper_id=? ORDER BY ordinal',
                        (answer['source_document_id'],))
                        if '非官方' in row['content_html'] and '仅供参考' in row['content_html']]
                if answer:
                    for local_id in json.loads(answer['source_blocks_json'] or '[]'):
                        block = db.execute('SELECT * FROM source_blocks WHERE paper_id=? AND local_id=?', (answer['source_document_id'], local_id)).fetchone()
                        if block is None:
                            raise ValueError('referenced answer source block is missing')
                        answer_blocks.append(dict(block))
                original_status = answer['status'] if answer else 'missing'
                status = 'available' if original_status == 'explicit' else 'missing' if original_status == 'missing' else 'pending'
                answer_body = ''.join(_portable(row['content_html'], base, asset_root, resources, overrides) for row in answer_blocks)
                if not answer_body and status != 'missing':
                    values = json.loads(answer['raw_json'])
                    answer_body = ''.join('<section><h3>' + label + '</h3>' + _paragraphs(values.get(name)) + '</section>' for name, label in
                                          [('value', '答案'), ('solution', '答案要点'), ('explanation', '解析'), ('commentary', '考点点拨'), ('knowledge', '知识定位')] if values.get(name))
                # An answer table is authoritative evidence for the current key,
                # not a reason to expose every other question's answer. Keep
                # the exact table in SourceRecord, display only its mapped key.
                if (answer and original_status == 'explicit'
                        and raw.get('questionType') in {'single_choice', 'multiple_choice'}
                        and answer_blocks and all('<table' in row['content_html'] for row in answer_blocks)):
                    value = json.loads(answer['raw_json']).get('value')
                    labels = {re.sub(r'[^A-Za-z0-9]', '', str(option.get('label', ''))) for option in raw.get('options', [])}
                    if not isinstance(value, str) or not value or not set(value) <= labels:
                        raise ValueError('table answer has no verified option key')
                    answer_body = '<p class="exam-answer-key">【答案】' + html.escape(value) + '</p>'
                    answer_body += '<p>来源仅提供答案表，未附逐题解析。</p>'
                if answer_context:
                    answer_body = ''.join(_portable(row['content_html'], base, asset_root, resources, overrides)
                                          for row in answer_context) + answer_body
                if status == 'missing':
                    answer_body = '<p class="exam-missing">现有资料未提供可核对的答案解析；题目与来源完整保留。</p>' + answer_body
                elif not answer_body:
                    raise ValueError('explicit answer is empty')
                title = str(paper['year']) + ' · ' + _TYPES.get(question['question_type'], '试题') + ' · 第 ' + str(question['number']) + ' 题'
                record = {'key': question['id'], 'paper_id': paper['id'], 'year': paper['year'], 'ordinal': question['ordinal'],
                          'number': question['number'], 'type': question['question_type'], 'title': title,
                          'question': body, 'answer': answer_body, 'status': status,
                          'source_record': {'paper': json.loads(paper['raw_json']), 'question': raw, 'answer': original_answer,
                                            'question_blocks': list(owned.values()), 'answer_blocks': answer_blocks,
                                            **({'answer_context': answer_context} if answer_context else {})},
                          'source_label': paper['title'] + ' · 第 ' + str(question['number']) + ' 题', 'reader_path': paper['reader_path']}
                questions.append(record); paper_rows.append(record['key'])
            papers.append({'id': paper['id'], 'year': paper['year'], 'title': paper['title'], 'questions': paper_rows,
                           'reader_path': paper['reader_path']})
    after = database.stat()
    if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
        raise ValueError('source question bank changed during snapshot')
    return {'schema': 'exam-bank-projection.v1', 'source': str(database), 'source_sha256': digest, 'category': category,
            'papers': papers, 'questions': questions, 'resources': resources}
