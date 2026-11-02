"""Append one independent usage guide to a legacy exam APKG.

Content still comes from the common catalog exporter. This finalizer only adds
one guide model/deck/note/card; it never opens a user collection or changes the
existing question rows, templates, scheduling or media.
"""
from __future__ import annotations

import copy
from contextlib import closing
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import zipfile

GUIDE_CSS = '''.card{font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;font-size:18px;line-height:1.8;text-align:left;color:#243247;background:#f5f7fc;margin:0;padding:24px}.guide{max-width:760px;margin:0 auto;background:white;border:1px solid #e1e7f0;border-radius:18px;padding:28px}h1{font-size:27px;margin:0 0 8px}h2{font-size:19px;color:#285da8;margin:24px 0 6px}p{margin:0 0 12px}.intro,.footer{color:#697b93}.footer{border-top:1px solid #e1e7f0;padding-top:16px;margin-top:24px;font-size:15px}@media(max-width:500px){.card{padding:12px;font-size:17px}.guide{padding:20px}}.nightMode .guide{background:#202733;color:#e1e7f0}.nightMode.card{background:#151a22;color:#e1e7f0}'''


GUIDE_SUPPORT_HTML = """<section class="guide guide-support">
<h2>如果这套牌组对你有帮助，欢迎支持：</h2>
<ul>
<li>在本 AnkiWeb 页面为牌组<strong>点赞或留下好评</strong>，帮助更多考研同学发现它。</li>
<li>到 <a href="https://github.com/CHNragdoll/anki-pipeline">GitHub 项目仓库 anki-pipeline</a> 点击右上角 <strong>Star ⭐</strong>，支持项目持续维护。</li>
<li>发现问题或有改进建议，欢迎通过 <a href="https://github.com/CHNragdoll/anki-pipeline/issues">GitHub Issues</a> 反馈。请尽量提供单词、卡片位置、使用客户端及截图，便于核对和修复。</li>
</ul>
<p>作者 GitHub：<a href="https://github.com/CHNragdoll">CHNragdoll</a><br>
联系邮箱：<a href="mailto:Ragdoll@dad.ac.cn">Ragdoll@dad.ac.cn</a></p>
</section>"""

class GuideCollisionError(ValueError):
    """A guide identity or destination deck already exists in the input."""


@dataclass(frozen=True)
class GuideIdentity:
    guid: str
    model_id: int
    deck_id: int
    note_id: int
    card_id: int


def guide_identity(book_id: str) -> GuideIdentity:
    """Derive stable guide identities from the immutable book ID, not its title."""
    if not isinstance(book_id, str) or not book_id.strip() or book_id != book_id.strip() or any(c in book_id for c in ('\x00', '\x1f', '\n', '\r')):
        raise ValueError('A nonempty stable book identity is required')
    def digest(kind):
        return hashlib.sha256(('anki-pipeline/exam-guide/v1\0' + book_id + '\0' + kind).encode()).digest()
    def number(kind):
        return int.from_bytes(digest(kind)[:6], 'big') or 1
    return GuideIdentity('Eg' + digest('guid').hex()[:14], number('model'),
                         number('deck'), number('note'), number('card'))


def _sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _validate_identity(identity):
    if not isinstance(identity, GuideIdentity) or not isinstance(identity.guid, str) or not identity.guid or not identity.guid.isascii() or any(not 33 <= ord(c) <= 126 for c in identity.guid):
        raise ValueError('Invalid guide identity')
    if any(type(value) is not int or not 0 < value < 2**53
           for value in (identity.model_id, identity.deck_id, identity.note_id, identity.card_id)):
        raise ValueError('Guide numeric identities must be positive safe integers')


def add_guide(source, target, *, book_id: str, root: str, question_count: int,
              guide_html: str, title: str | None = None, css: str = GUIDE_CSS,
              identity: GuideIdentity | None = None):
    """Build a new package, refusing overwrite, duplicate guides and ID collisions.

    The source must have one card/note per question. ``identity`` is only needed
    for a previously published guide whose established IDs must be retained.
    """
    source, target = Path(source), Path(target)
    if source.resolve() == target.resolve() or target.exists() or target.is_symlink():
        raise ValueError('Destination already exists or aliases the source')
    if not isinstance(root, str) or not root.strip() or root != root.strip() or any(c in root for c in ('::', '\x00', '\x1f', '\n', '\r')):
        raise ValueError('A single nonempty root deck name is required')
    if type(question_count) is not int or question_count < 1:
        raise ValueError('A positive question count is required')
    title = root + ' · 使用说明' if title is None else title
    if any(not isinstance(value, str) or not value or '\x1f' in value or '\x00' in value
           for value in (title, guide_html, css)):
        raise ValueError('Guide title, HTML and CSS must be nonempty single-field strings')
    derived = guide_identity(book_id)
    identity = derived if identity is None else identity
    _validate_identity(identity)
    now = int(time.time())
    source_sha = _sha256(source)
    guide_deck = root + '::00 使用说明'
    with zipfile.ZipFile(source) as original, tempfile.TemporaryDirectory(prefix='exam-guide-') as temp:
        names = original.namelist()
        if (len(names) != len(set(names)) or 'collection.anki2' not in names
                or any(name in names for name in ('collection.anki21', 'collection.anki21b', 'meta'))):
            raise ValueError('A legacy APKG with unique members is required')
        path = Path(temp) / 'collection.anki2'
        path.write_bytes(original.read('collection.anki2'))
        with closing(sqlite3.connect(path)) as db:
            tables = ('notes', 'cards', 'revlog', 'graves')
            before = {table: db.execute(f'SELECT * FROM {table} ORDER BY 1').fetchall()
                      for table in tables}
            models_raw, decks_raw = db.execute('SELECT models,decks FROM col').fetchone()
            models, decks = json.loads(models_raw), json.loads(decks_raw)
            if (str(identity.model_id) in models or str(identity.deck_id) in decks
                    or any(deck['name'] == guide_deck for deck in decks.values())
                    or db.execute('SELECT 1 FROM notes WHERE guid=? OR id=?', (identity.guid, identity.note_id)).fetchone()
                    or db.execute('SELECT 1 FROM cards WHERE id=?', (identity.card_id,)).fetchone()):
                raise GuideCollisionError('Guide identity or 00 使用说明 deck already exists')
            if len(before['notes']) != question_count or len(before['cards']) != question_count:
                raise ValueError('Source question/card count does not match the declared count')
            parent = next((deck for deck in decks.values() if deck['name'].startswith(root + '::')), None)
            if parent is None or not models:
                raise ValueError('Source does not contain the requested exam root and model')
            model = copy.deepcopy(next(iter(models.values())))
            if not model.get('flds') or not model.get('tmpls'):
                raise ValueError('Source model has no field/template prototype')
            model.update(id=identity.model_id, name=root + ' · 使用说明', did=identity.deck_id,
                         mod=now, type=0, sortf=0, usn=-1, css=css, tags=[], req=[[0, 'all', [0]]])
            field = copy.deepcopy(model['flds'][0])
            model['flds'] = [dict(field, name=name, ord=i) for i, name in enumerate(('Title', 'Instructions'))]
            template = copy.deepcopy(model['tmpls'][0])
            template.update(name='使用说明', ord=0,
                            qfmt='<section class="guide"><h1>{{Title}}</h1><p>翻面查看使用方法、题型结构与更新说明。</p></section>',
                            afmt='{{Instructions}}', bqfmt='', bafmt='', did=None)
            model['tmpls'] = [template]
            deck = copy.deepcopy(parent)
            deck.update(id=identity.deck_id, name=guide_deck, desc='独立使用说明，不计入真题数量。', mod=now, usn=-1)
            models[str(identity.model_id)], decks[str(identity.deck_id)] = model, deck
            db.execute('UPDATE col SET models=?,decks=?',
                       (json.dumps(models, ensure_ascii=False), json.dumps(decks, ensure_ascii=False)))
            checksum = int(hashlib.sha1(title.encode()).hexdigest()[:8], 16)
            db.execute('INSERT INTO notes VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                       (identity.note_id, identity.guid, identity.model_id, now, -1, ' 使用说明 ',
                        title + '\x1f' + guide_html + GUIDE_SUPPORT_HTML, title, checksum, 0, ''))
            db.execute('INSERT INTO cards VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (identity.card_id, identity.note_id, identity.deck_id, 0, now, -1, 0, 0,
                        1, 0, 0, 0, 0, 0, 0, 0, 0, ''))
            db.commit()
            for table in tables:
                actual = db.execute(f'SELECT * FROM {table} ORDER BY 1').fetchall()
                if table in ('notes', 'cards'):
                    new_id = identity.note_id if table == 'notes' else identity.card_id
                    actual = [row for row in actual if row[0] != new_id]
                if actual != before[table]:
                    raise ValueError('Existing study rows changed in ' + table)
            if any(models[key] != value for key, value in json.loads(models_raw).items()):
                raise ValueError('Existing model changed')
            if any(decks[key] != value for key, value in json.loads(decks_raw).items()):
                raise ValueError('Existing deck changed')
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('Final guide database failed integrity check')
        target.parent.mkdir(parents=True, exist_ok=True)
        # Validate a complete staged archive before an atomic, no-overwrite
        # publication. A failed write never leaves a final-looking APKG behind.
        fd, staged_name = tempfile.mkstemp(prefix='.exam-guide-', suffix='.apkg', dir=target.parent)
        os.close(fd)
        staged = Path(staged_name)
        try:
            with zipfile.ZipFile(staged, 'w') as result:
                collection = path.read_bytes()
                for member in original.infolist():
                    result.writestr(copy.copy(member), collection if member.filename == 'collection.anki2' else original.read(member))
            with zipfile.ZipFile(staged) as result:
                if result.testzip() is not None:
                    raise ValueError('Final guide archive failed CRC verification')
                for name in names:
                    if name != 'collection.anki2' and original.read(name) != result.read(name):
                        raise ValueError('Existing media/archive member changed')
            if _sha256(source) != source_sha:
                raise ValueError('Source package changed during finalization')
            os.link(staged, target)
        finally:
            staged.unlink(missing_ok=True)
    return dict(cards=question_count + 1, questions=question_count, guide_cards=1,
                guide_deck=guide_deck, existing_rows_templates_and_media_unchanged=True,
                bytes=target.stat().st_size, sha256=_sha256(target),
                guide_identity=asdict(identity))
