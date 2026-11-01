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

from .study_exam_assets import IMAGE_SUFFIXES, resolve_redraws, sealed_bytes

_TYPES = {'single_choice': '单选题', 'multiple_choice': '多选题', 'free_response': '材料分析题'}
_FORBIDDEN = {'script', 'style', 'iframe', 'object', 'embed', 'base', 'meta', 'link', 'form', 'input', 'button'}


def question_type_labels(overrides=None):
    """Resolve display labels without changing question types or deck identities."""
    labels = dict(_TYPES)
    if overrides is None:
        return labels
    if not isinstance(overrides, dict) or set(overrides) - set(labels):
        raise ValueError('unsupported question type label mapping')
    for kind, label in overrides.items():
        if (not isinstance(label, str) or not label.strip() or label != label.strip()
                or '::' in label or any(ord(char) < 32 for char in label)):
            raise ValueError('question type label must be one nonempty deck segment')
        labels[kind] = label
    return labels


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
            source, data = sealed_bytes(path, seal)
            suffix = seal.get('presentation_suffix', path.suffix.lower()) if seal else path.suffix.lower()
            if suffix not in IMAGE_SUFFIXES:
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


class _AnswerBoundary(HTMLParser):
    """Locate an explicit answer paragraph without reserializing source HTML."""
    _VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
             'link', 'meta', 'param', 'source', 'track', 'wbr'}
    _MARKER = re.compile(r'^(?:【(?:参考)?答案】|(?:解答|参考答案|答案|解析)\s*[：:])')

    def __init__(self, source):
        super().__init__(convert_charrefs=False)
        self.starts = [0] + [match.end() for match in re.finditer('\n', source)]
        self.stack = []
        self.boundaries = []
        self.malformed = False

    def handle_starttag(self, tag, attrs):
        if tag in self._VOID:
            return
        line, column = self.getpos()
        node = {'tag': tag, 'start': self.starts[line - 1] + column,
                'opening': self.get_starttag_text(), 'texts': [],
                'ancestors': [(n['tag'], n['opening']) for n in self.stack]}
        self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        if tag not in self._VOID:
            self.handle_starttag(tag, attrs)
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in self._VOID:
            return
        if not self.stack or self.stack[-1]['tag'] != tag:
            self.malformed = True
            return
        node = self.stack.pop()
        if tag == 'p' or re.fullmatch(r'h[1-6]', tag):
            text = ''.join(node['texts']).lstrip()
            marker = self._MARKER.match(text)
            if marker:
                self.boundaries.append({**node, 'marker': marker[0]})

    def handle_data(self, text):
        for node in self.stack:
            node['texts'].append(text)

    def handle_entityref(self, name):
        self.handle_data(html.unescape('&' + name + ';'))

    def handle_charref(self, name):
        self.handle_data(html.unescape('&#' + name + ';'))


def _owned_answer_parts(block):
    """Partition mixed ownership only at a proved paragraph/heading boundary.

    Source-role ``answer`` also authorizes continuation blocks lacking their
    own repeated heading. Unknown mixed ownership must never delete a stem or
    expose a solution through a guessed textual split.
    """
    source = block['content_html']
    parser = _AnswerBoundary(source)
    parser.feed(source); parser.close()
    if parser.malformed or parser.stack:
        raise ValueError('overlapping answer block has malformed HTML: ' + block['id'])
    if not parser.boundaries:
        if block.get('role') == 'answer':
            return '', source, None
        raise ValueError('overlapping answer block has no explicit answer boundary: ' + block['id'])
    boundary = min(parser.boundaries, key=lambda node: node['start'])
    ancestors = boundary['ancestors']
    if any(tag not in {'div', 'section', 'article'} for tag, _ in ancestors):
        raise ValueError('answer boundary is not inside a separable container: ' + block['id'])
    prefix = source[:boundary['start']]
    text = html.unescape(re.sub(r'<[^>]*>', '', prefix)).strip()
    if not text and not re.search(r'<(?:img|svg|math|table|pre|code)\b', prefix, re.I):
        return '', source, None
    front = prefix + ''.join('</' + tag + '>' for tag, _ in reversed(ancestors))
    answer = ''.join(opening for _, opening in ancestors) + source[boundary['start']:]
    receipt = {'block_id': block['id'], 'source_html_sha256': hashlib.sha256(source.encode()).hexdigest(),
               'answer_start': boundary['start'], 'marker': boundary['marker'],
               'front_html': front, 'answer_html': answer}
    return front, answer, receipt


def read_bank(database, category, *, structured_root, asset_root=None, asset_overrides=None,
              paper_kinds=('questions', 'complete'), type_labels=None, redraw_manifest=None):
    if (not isinstance(paper_kinds, (list, tuple)) or not paper_kinds
            or any(not isinstance(kind, str) or kind not in {'questions', 'complete'} for kind in paper_kinds)
            or len(set(paper_kinds)) != len(paper_kinds)):
        raise ValueError('explicit question or complete paper kinds required')
    labels = question_type_labels(type_labels)
    database = Path(database).resolve(strict=True)
    structured_root = Path(structured_root).resolve(strict=True)
    asset_root = Path(asset_root or structured_root.parent.parent).resolve(strict=True)
    before = database.stat()
    with database.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    resources = {}; questions = []; papers = []
    overrides = asset_overrides or {}
    if redraw_manifest is not None:
        overrides = resolve_redraws(asset_root, overrides, redraw_manifest)
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON'); db.execute('BEGIN')
        placeholders = ','.join('?' for _ in paper_kinds)
        selected = list(db.execute('SELECT * FROM papers WHERE category=? AND kind IN (' + placeholders + ') ORDER BY year,ordinal,id', (category, *paper_kinds)))
        if not selected:
            raise ValueError('no question papers in requested category')
        for paper in selected:
            paper = dict(paper)
            base = (structured_root / paper['reader_path']).parent
            if not base.resolve().is_relative_to(asset_root):
                raise ValueError('paper reader escapes its source root')
            paper_rows = []
            for question in db.execute('SELECT * FROM questions WHERE paper_id=? AND in_bank=1 ORDER BY ordinal,id', (paper['id'],)):
                raw = json.loads(question['raw_json'])
                blocks = list(db.execute('SELECT DISTINCT b.* FROM source_blocks b JOIN question_source_blocks x ON x.block_id=b.id WHERE x.question_id=? ORDER BY b.ordinal,b.id', (question['id'],)))
                context = list(db.execute('SELECT b.* FROM source_blocks b JOIN context_source_blocks x ON x.block_id=b.id WHERE x.question_id=? ORDER BY x.ordinal', (question['id'],)))
                owned = {row['id']: dict(row) for row in [*context, *blocks]}
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
                # Combined papers may give a question ownership of its inline
                # solution too. Only explicit mapped answer IDs are excluded;
                # original ownership stays intact in SourceRecord for audit.
                answer_ids = {block['id'] for block in answer_blocks}
                overlap = sorted(answer_ids.intersection(owned))
                excluded = []; partitions = []; projected_answers = {}
                front_html = {key: row['content_html'] for key, row in owned.items()}
                for key in overlap:
                    front, answer_html, receipt = _owned_answer_parts(owned[key])
                    front_html[key] = front
                    projected_answers[key] = answer_html
                    if receipt:
                        partitions.append(receipt)
                    else:
                        excluded.append(key)
                body = ''.join(_portable(front_html[row['id']], base, asset_root, resources, overrides)
                               for row in sorted(owned.values(), key=lambda r: (r['ordinal'], r['id']))
                               if front_html[row['id']])
                if not body:
                    if overlap:
                        raise ValueError('question has no question-only source body')
                    body = _paragraphs(raw.get('stem'))
                    body += ''.join('<p class="choice"><b>' + html.escape(str(o.get('label', ''))) + '</b> ' + html.escape(o.get('text', '')) + '</p>' for o in raw.get('options', []))
                if not body.strip():
                    raise ValueError('question has no complete source body')
                original_status = answer['status'] if answer else 'missing'
                status = 'available' if original_status == 'explicit' else 'missing' if original_status == 'missing' else 'pending'
                answer_body = ''.join(_portable(projected_answers.get(row['id'], row['content_html']), base, asset_root, resources, overrides) for row in answer_blocks)
                if not answer_body and status != 'missing':
                    values = json.loads(answer['raw_json'])
                    answer_body = ''.join('<section><h3>' + label + '</h3>' + _paragraphs(values.get(name)) + '</section>' for name, label in
                                          [('value', '答案'), ('solution', '答案要点'), ('explanation', '解析'), ('commentary', '考点点拨'), ('knowledge', '知识定位')] if values.get(name))
                # An answer table is authoritative evidence for the current key,
                # not a reason to expose every other question's answer. Keep
                # the exact table in SourceRecord, display only its mapped key.
                if (answer and original_status == 'explicit'
                        and raw.get('questionType') in {'single_choice', 'multiple_choice'}
                        and answer_blocks and not partitions and all('<table' in row['content_html'] for row in answer_blocks)):
                    value = json.loads(answer['raw_json']).get('value')
                    option_labels = {re.sub(r'[^A-Za-z0-9]', '', str(option.get('label', ''))) for option in raw.get('options', [])}
                    if not isinstance(value, str) or not value or not set(value) <= option_labels:
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
                kind_label = labels.get(question['question_type'], '试题')
                title = str(paper['year']) + ' · ' + kind_label + ' · 第 ' + str(question['number']) + ' 题'
                record = {'key': question['id'], 'paper_id': paper['id'], 'year': paper['year'], 'ordinal': question['ordinal'],
                          'number': question['number'], 'type': question['question_type'], 'type_label': kind_label, 'title': title,
                          'question': body, 'answer': answer_body, 'status': status,
                          'source_record': {'paper': json.loads(paper['raw_json']), 'question': raw, 'answer': original_answer,
                                            'question_blocks': list(owned.values()), 'answer_blocks': answer_blocks,
                                            **({'front_answer_block_ids_excluded': excluded} if excluded else {}),
                                            **({'front_answer_block_partitions': partitions} if partitions else {}),
                                            **({'question_type_label': kind_label} if kind_label != _TYPES.get(question['question_type']) else {}),
                                            **({'answer_context': answer_context} if answer_context else {})},
                          'source_label': paper['title'] + ' · 第 ' + str(question['number']) + ' 题', 'reader_path': paper['reader_path']}
                questions.append(record); paper_rows.append(record['key'])
            papers.append({'id': paper['id'], 'year': paper['year'], 'title': paper['title'], 'questions': paper_rows,
                           'reader_path': paper['reader_path']})
    after = database.stat()
    if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
        raise ValueError('source question bank changed during snapshot')
    return {'schema': 'exam-bank-projection.v1', 'source': str(database), 'source_sha256': digest, 'category': category,
            'papers': papers, 'questions': questions, 'resources': resources, 'question_type_labels': labels}
