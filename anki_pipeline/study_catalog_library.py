"""Subject-neutral library facets; exams are metadata, not code branches.

Stored as a versioned registry in the catalog metadata table so adding a subject
never requires another database or a DDL migration. Source fields stay intact.
"""
from __future__ import annotations

from . import study_catalog as c

KEY='library.scopes.v1'


def validate_scope(scope):
    if not isinstance(scope,dict) or set(scope)-{'subject','exam','language','topics','kind'}:
        raise ValueError('scope accepts subject, exam, language, topics and kind')
    if not isinstance(scope.get('subject'),str) or not scope['subject'].strip():
        raise ValueError('scope needs an explicit subject')
    for field in ('exam','language','kind'):
        if field in scope and (not isinstance(scope[field],str) or not scope[field].strip()):
            raise ValueError('scope fields must be nonempty text')
    if 'topics' in scope and (not isinstance(scope['topics'],list) or any(not isinstance(x,str) or not x.strip() for x in scope['topics'])):
        raise ValueError('scope topics must be explicit text labels')
    return scope


def scopes(db):
    row=db.execute('select value from metadata where key=%s',(KEY,)).fetchone()
    return __import__('json').loads(row[0]) if row else {}


def set_scope(db,book_id,scope):
    validate_scope(scope)
    if not db.execute('select 1 from books where id=%s',(book_id,)).fetchone():raise ValueError('unknown book')
    db.execute('select pg_advisory_xact_lock(%s)',(int(c.identity(KEY)[:15],16),))
    registry=scopes(db);old=registry.get(book_id)
    if old==scope:return
    registry[book_id]=scope
    db.execute('insert into metadata values(%s,%s) on conflict(key) do update set value=excluded.value',
               (KEY,c.canonical(registry)))
    c.event(db,'classify-library-book',{'book_id':book_id,'before':old,'after':scope})


def classify(value,book_id,scope,*,backups):
    validate_scope(scope);saved=c.backup(value,backups)
    with c.connect(value) as db,c.transaction(db):set_scope(db,book_id,scope)
    return {'book_id':book_id,'scope':scope,'backup':str(saved)}


def classify_many(value, changes, *, expected, backups):
    """Apply explicit book classifications atomically after one full backup.

    ``expected`` is the exact current scope for every selected book; ``None``
    means no classification yet. Unrelated books remain in the same registry.
    The snapshot is a recovery input, never an automatic overwrite of later
    catalog changes.
    """
    if (not isinstance(changes, dict) or not changes or
            any(not isinstance(book, str) or not book for book in changes) or
            not isinstance(expected, dict) or set(expected) != set(changes)):
        raise ValueError('classification needs nonempty books and exact expected scopes')
    for scope in changes.values():
        validate_scope(scope)
    for scope in expected.values():
        if scope is not None:
            validate_scope(scope)
    # Freeze caller-owned mappings before the backup/transaction boundary.
    import json
    changes = json.loads(c.canonical(changes))
    expected = json.loads(c.canonical(expected))
    saved = c.backup(value, backups)
    with c.connect(value) as db, c.transaction(db):
        db.execute('select pg_advisory_xact_lock(%s)', (int(c.identity(KEY)[:15], 16),))
        registry = scopes(db)
        if not isinstance(registry, dict):
            raise ValueError('invalid library scope registry')
        # Validate all books and CAS values before the first mutation/event.
        for book in changes:
            if not db.execute('select 1 from books where id=%s', (book,)).fetchone():
                raise ValueError('unknown book: ' + book)
            if registry.get(book) != expected[book]:
                raise ValueError('library classification changed: ' + book)
        for book, scope in changes.items():
            set_scope(db, book, scope)
    return {'books': changes, 'before': expected, 'backup': str(saved)}


def library(value,*,subject=None,exam=None):
    with c.connect(value,readonly=True) as db:
        registry=scopes(db);books=[]
        for bid,title,edition,count in db.execute('select b.id,b.title,b.edition,count(n.note_id) from books b left join notes n on n.book_id=b.id group by b.id order by b.id'):
            scope=registry.get(bid,{})
            if subject is not None and scope.get('subject')!=subject:continue
            if exam is not None and scope.get('exam')!=exam:continue
            books.append({'id':bid,'title':title,'edition':edition,'notes':count,'scope':scope})
    return {'schema':'study-library.v1','books':books}
