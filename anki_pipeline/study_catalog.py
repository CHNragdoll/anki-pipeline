"""Shared learning content, book mappings and lossless source archives.

The catalog is separate from user Anki collections. Content addresses identify
exact bytes; a word's identity preserves case and never infers lemmatization.
Book-specific Anki identities and source audit seals remain separate identities.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import gzip
import base64
import unicodedata
import uuid
import zlib
import psycopg
from psycopg import sql

VERSION = 1
DEFAULT_DSN = 'host=/tmp dbname=anki_study_catalog user=anki_study_catalog_owner'
SCHEMA = '''
CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE objects(id TEXT PRIMARY KEY CHECK(length(id)=64),codec TEXT NOT NULL CHECK(codec IN('raw','zlib')),
 byte_length INTEGER NOT NULL CHECK(byte_length>=0),data BLOB NOT NULL);
CREATE TABLE words(id TEXT PRIMARY KEY,language TEXT NOT NULL,surface TEXT NOT NULL,
 UNIQUE(language,surface));
CREATE TABLE books(id TEXT PRIMARY KEY,title TEXT NOT NULL,edition INTEGER NOT NULL);
CREATE TABLE sources(id TEXT PRIMARY KEY,kind TEXT NOT NULL,label TEXT NOT NULL,
 manifest_id TEXT NOT NULL REFERENCES objects(id),status TEXT NOT NULL CHECK(status IN('building','complete')));
CREATE TABLE book_sources(book_id TEXT PRIMARY KEY REFERENCES books(id),source_id TEXT NOT NULL REFERENCES sources(id),
 collection_id TEXT NOT NULL REFERENCES objects(id),col_payload_id TEXT NOT NULL REFERENCES objects(id));
CREATE TABLE units(book_id TEXT NOT NULL REFERENCES books(id),id INTEGER NOT NULL,name TEXT NOT NULL,
 parent_id INTEGER,payload_id TEXT NOT NULL REFERENCES objects(id),PRIMARY KEY(book_id,id));
CREATE TABLE notes(book_id TEXT NOT NULL REFERENCES books(id),note_id INTEGER NOT NULL,guid TEXT NOT NULL,
 word_id TEXT REFERENCES words(id),kind TEXT NOT NULL CHECK(kind IN('word','guide','supplemental')),
 ordinal INTEGER NOT NULL,model_id INTEGER NOT NULL,payload_id TEXT NOT NULL REFERENCES objects(id),
 source_card_id TEXT,PRIMARY KEY(book_id,note_id),UNIQUE(book_id,guid),UNIQUE(book_id,ordinal));
CREATE INDEX note_words ON notes(word_id,book_id);
CREATE TABLE components(id TEXT PRIMARY KEY,word_id TEXT REFERENCES words(id),name TEXT NOT NULL,
 original_id TEXT NOT NULL REFERENCES objects(id),current_id TEXT NOT NULL REFERENCES objects(id),
 UNIQUE(word_id,name,original_id));
CREATE TABLE note_fields(book_id TEXT NOT NULL,note_id INTEGER NOT NULL,ordinal INTEGER NOT NULL,
 name TEXT NOT NULL,component_id TEXT NOT NULL REFERENCES components(id),PRIMARY KEY(book_id,note_id,ordinal),
 FOREIGN KEY(book_id,note_id) REFERENCES notes(book_id,note_id));
CREATE INDEX fields_component ON note_fields(component_id);
CREATE TABLE component_revisions(id INTEGER PRIMARY KEY,component_id TEXT NOT NULL REFERENCES components(id),
 before_id TEXT NOT NULL REFERENCES objects(id),after_id TEXT NOT NULL REFERENCES objects(id),
 reason TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE native_cards(book_id TEXT NOT NULL,native_id INTEGER NOT NULL,note_id INTEGER NOT NULL,
 unit_id INTEGER NOT NULL,ordinal INTEGER NOT NULL,payload_id TEXT NOT NULL REFERENCES objects(id),
 PRIMARY KEY(book_id,native_id),FOREIGN KEY(book_id,note_id) REFERENCES notes(book_id,note_id),
 FOREIGN KEY(book_id,unit_id) REFERENCES units(book_id,id));
CREATE TABLE resource_aliases(book_id TEXT NOT NULL REFERENCES books(id),name TEXT NOT NULL,
 object_id TEXT NOT NULL REFERENCES objects(id),zip_info_id TEXT NOT NULL REFERENCES objects(id),
 PRIMARY KEY(book_id,name));
CREATE INDEX resource_content ON resource_aliases(object_id);
CREATE TABLE archive_tables(source_id TEXT NOT NULL REFERENCES sources(id),name TEXT NOT NULL,
 definition_id TEXT NOT NULL REFERENCES objects(id),columns_id TEXT NOT NULL REFERENCES objects(id),
 row_count INTEGER NOT NULL DEFAULT 0,row_digest TEXT,PRIMARY KEY(source_id,name));
CREATE TABLE archive_rows(source_id TEXT NOT NULL,table_name TEXT NOT NULL,ordinal INTEGER NOT NULL,
 payload_id TEXT NOT NULL REFERENCES objects(id),PRIMARY KEY(source_id,table_name,ordinal),
 FOREIGN KEY(source_id,table_name) REFERENCES archive_tables(source_id,name));
CREATE TABLE analyses(book_id TEXT NOT NULL REFERENCES books(id),source_card_id TEXT NOT NULL,
 word_id TEXT NOT NULL REFERENCES words(id),snapshot_id TEXT NOT NULL,record_id TEXT NOT NULL REFERENCES objects(id),
 expected_occurrences INTEGER NOT NULL CHECK(expected_occurrences>=0),PRIMARY KEY(book_id,source_card_id));
CREATE INDEX analysis_words ON analyses(word_id);
CREATE TABLE dictionary_senses(id TEXT PRIMARY KEY,word_id TEXT NOT NULL REFERENCES words(id),
 dictionary TEXT NOT NULL,pos TEXT NOT NULL,text TEXT NOT NULL,provenance_id TEXT NOT NULL REFERENCES objects(id));
CREATE TABLE analysis_senses(book_id TEXT NOT NULL,source_card_id TEXT NOT NULL,ordinal INTEGER NOT NULL,
 original_sense_id TEXT NOT NULL,sense_id TEXT NOT NULL REFERENCES dictionary_senses(id),
 PRIMARY KEY(book_id,source_card_id,ordinal),FOREIGN KEY(book_id,source_card_id) REFERENCES analyses(book_id,source_card_id));
CREATE TABLE sentences(id TEXT PRIMARY KEY,paper_id TEXT NOT NULL,source_sentence_id TEXT NOT NULL,
 english_id TEXT NOT NULL REFERENCES objects(id),translation_id TEXT NOT NULL REFERENCES objects(id),
 alignment_id TEXT REFERENCES objects(id));
CREATE INDEX sentence_sources ON sentences(paper_id,source_sentence_id);
CREATE TABLE tokens(id TEXT PRIMARY KEY,physical_id TEXT NOT NULL,word_id TEXT NOT NULL REFERENCES words(id),
 sentence_id TEXT NOT NULL REFERENCES sentences(id),target_start INTEGER NOT NULL,target_end INTEGER NOT NULL,
 physical_source_id TEXT NOT NULL REFERENCES objects(id),CHECK(target_start>=0 AND target_end>target_start));
CREATE INDEX token_words ON tokens(word_id,physical_id);
CREATE TABLE decisions(id TEXT PRIMARY KEY,word_id TEXT NOT NULL REFERENCES words(id),token_id TEXT NOT NULL REFERENCES tokens(id),
 sense_id TEXT REFERENCES dictionary_senses(id),status TEXT NOT NULL,reason TEXT NOT NULL,method TEXT NOT NULL);
CREATE TABLE analysis_occurrences(book_id TEXT NOT NULL,source_card_id TEXT NOT NULL,ordinal INTEGER NOT NULL,
 original_occurrence_id TEXT NOT NULL,token_id TEXT NOT NULL REFERENCES tokens(id),decision_id TEXT NOT NULL REFERENCES decisions(id),
 payload_id TEXT NOT NULL REFERENCES objects(id),PRIMARY KEY(book_id,source_card_id,original_occurrence_id),
 UNIQUE(book_id,source_card_id,ordinal),FOREIGN KEY(book_id,source_card_id) REFERENCES analyses(book_id,source_card_id));
CREATE INDEX occurrence_decisions ON analysis_occurrences(decision_id);
CREATE TABLE chunks(sentence_id TEXT NOT NULL REFERENCES sentences(id),ordinal INTEGER NOT NULL,
 payload_id TEXT NOT NULL REFERENCES objects(id),PRIMARY KEY(sentence_id,ordinal));
CREATE TABLE events(id INTEGER PRIMARY KEY,happened_at TEXT NOT NULL,action TEXT NOT NULL,
 payload_id TEXT NOT NULL REFERENCES objects(id));
'''
SCHEMA = (SCHEMA.replace('INTEGER', 'BIGINT').replace(' BLOB', ' BYTEA')
          .replace('id BIGINT PRIMARY KEY,component_id', 'id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,component_id')
          .replace('events(id BIGINT PRIMARY KEY,', 'events(id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,'))
TABLES = tuple(line.split('CREATE TABLE ',1)[1].split('(',1)[0] for line in SCHEMA.splitlines() if line.startswith('CREATE TABLE '))


@dataclass(frozen=True)
class Target:
    dsn: str = field(default_factory=lambda: os.environ.get('ANKI_STUDY_DSN', DEFAULT_DSN), repr=False)
    schema: str = 'study_catalog'

    def __post_init__(self):
        import re
        if not re.fullmatch('[a-z][a-z0-9_]{0,62}',self.schema):raise ValueError('invalid catalog schema identifier')


def target(value=None):
    return value if isinstance(value,Target) else Target(value) if isinstance(value,str) else Target()


def now():
    return datetime.now(timezone.utc).isoformat()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), sort_keys=True, allow_nan=False)


def identity(*parts):
    return hashlib.sha256(canonical(parts).encode()).hexdigest()


def validate(db):
    row=db.execute("select value from metadata where key='schema'").fetchone()
    if row is None or row[0]!='unified-study-catalog.pg.v1':raise ValueError('not a supported PostgreSQL study database')


@contextmanager
def connect(value=None, *, readonly=False):
    selected=target(value)
    db=psycopg.connect(selected.dsn,autocommit=True,connect_timeout=10)
    try:
        db.execute(sql.SQL('SET search_path TO {},pg_catalog').format(sql.Identifier(selected.schema)))
        if readonly:db.execute('SET default_transaction_read_only=on')
        validate(db)
        yield db
    finally:db.close()


def _initialize_connection(db,selected,*,must_new=False):
    db.execute('select pg_advisory_xact_lock(%s)',(int(identity('schema',selected.schema)[:15],16),))
    exists=db.execute('select 1 from pg_namespace where nspname=%s',(selected.schema,)).fetchone()
    if exists:
        if must_new:raise FileExistsError('restore target schema must be new')
        db.execute(sql.SQL('SET LOCAL search_path TO {},pg_catalog').format(sql.Identifier(selected.schema)))
        validate(db);return
    db.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(selected.schema)))
    db.execute(sql.SQL('SET LOCAL search_path TO {},pg_catalog').format(sql.Identifier(selected.schema)))
    db.execute(SCHEMA,prepare=False)
    db.execute('insert into metadata values(%s,%s)',('schema','unified-study-catalog.pg.v1'))


def initialize(value=None):
    selected=target(value)
    with psycopg.connect(selected.dsn,autocommit=True,connect_timeout=10) as db,db.transaction():
        _initialize_connection(db,selected)


@contextmanager
def transaction(db):
    with db.transaction():yield db


def put_object(db, raw):
    if not isinstance(raw,bytes):raise ValueError('content must be exact bytes')
    key=hashlib.sha256(raw).hexdigest()
    if db.execute('select 1 from objects where id=%s',(key,)).fetchone():return key
    compressed=zlib.compress(raw,6) if len(raw)>=1024 else raw
    codec,data=('zlib',compressed) if len(compressed)+64<len(raw) else ('raw',raw)
    db.execute('insert into objects values(%s,%s,%s,%s) on conflict do nothing',(key,codec,len(raw),data))
    return key


def put_json(db, value):return put_object(db,canonical(value).encode())


def _object_parts(db,key):
    row=db.execute('select codec,byte_length,data from objects where id=%s',(key,)).fetchone()
    if row is None:raise ValueError('missing catalog content: '+key)
    codec,size,data=row
    if codec=='raw':
        for i in range(0,len(data),1024*1024):yield data[i:i+1024*1024]
    else:
        try:
            decoder=zlib.decompressobj();total=0
            for i in range(0,len(data),65536):
                pending=data[i:i+65536]
                while pending:
                    part=decoder.decompress(pending,min(1024*1024,size-total+1))
                    total+=len(part)
                    if total>size:raise ValueError('decompressed object exceeds declared size')
                    if part:yield part
                    pending=decoder.unconsumed_tail
            tail=decoder.flush()
            if tail:yield tail
            if not decoder.eof or decoder.unused_data:raise ValueError('incomplete or trailing compressed content')
        except zlib.error as exc:raise ValueError('corrupt compressed catalog content') from exc


def write_object(db,key,stream):
    row=db.execute('select byte_length from objects where id=%s',(key,)).fetchone()
    if row is None:raise ValueError('missing catalog object')
    digest=hashlib.sha256();total=0
    for part in _object_parts(db,key):digest.update(part);total+=len(part);stream.write(part)
    if total!=row[0] or digest.hexdigest()!=key:raise ValueError('catalog object digest/length mismatch')
    return total


def get_object(db,key):
    import io
    stream=io.BytesIO();write_object(db,key,stream);return stream.getvalue()


def get_json(db,key):return json.loads(get_object(db,key))


def put_file(db,path):
    """Hash and compress a large source file without reading it all into RAM."""
    path=Path(path);before=path.stat();h=hashlib.sha256();compressor=zlib.compressobj(6);pieces=[]
    with path.open('rb') as f:
        for part in iter(lambda:f.read(1024*1024),b''):
            h.update(part);encoded=compressor.compress(part)
            if encoded:pieces.append(encoded)
    pieces.append(compressor.flush());after=path.stat()
    if (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns):
        raise ValueError('source file changed while importing')
    key=h.hexdigest()
    db.execute('insert into objects values(%s,%s,%s,%s) on conflict do nothing',(key,'zlib',before.st_size,b''.join(pieces)))
    return key


def ensure_word(db,surface,language='en'):
    if not isinstance(surface,str) or not surface.strip() or '\x00' in surface:raise ValueError('word must be nonempty text')
    surface=unicodedata.normalize('NFC',surface.strip());key=identity('word',language,surface)
    db.execute('insert into words values(%s,%s,%s) on conflict do nothing',(key,language,surface));return key


def ensure_book(db,key,title,edition):
    if not isinstance(key,str) or not key.strip() or not isinstance(title,str) or not title.strip() or type(edition)!=int:
        raise ValueError('book needs explicit identity, title and edition')
    previous=db.execute('select title,edition from books where id=%s',(key,)).fetchone()
    if previous and tuple(previous)!=(title,edition):raise ValueError('book identity already belongs to another edition/title')
    db.execute('insert into books values(%s,%s,%s) on conflict do nothing',(key,title,edition));return key


def ensure_component(db,word,name,text,*,scope=''):
    if not isinstance(text,str):raise ValueError('component must be exact text')
    original=put_object(db,text.encode());key=identity('component',word or scope,name,original)
    db.execute('insert into components values(%s,%s,%s,%s,%s) on conflict do nothing',(key,word,name,original,original));return key


def note_fields(db,book,note):
    rows=db.execute('select o.id from note_fields f join components c on c.id=f.component_id join objects o on o.id=c.current_id '
                    'where f.book_id=%s and f.note_id=%s order by f.ordinal',(book,note))
    return [get_object(db,row[0]).decode() for row in rows]


def event(db,action,payload):
    db.execute('insert into events(happened_at,action,payload_id) values(%s,%s,%s)',(now(),action,put_json(db,payload)))


def guard_new_output(path,sources=()):
    path=Path(path).expanduser().absolute()
    if path.is_symlink() or path.exists():raise ValueError('output must be a new path; never overwrite originals')
    dest=path.resolve()
    for source in sources:
        source=Path(source).resolve()
        if dest==source or dest.is_relative_to(source):raise ValueError('output overlaps protected source')
    return path



def _pack_cell(value):
    return {'$bytes':base64.b64encode(value).decode('ascii')} if isinstance(value,bytes) else value


def _unpack_cell(value):
    if isinstance(value,dict):
        if set(value)!={'$bytes'}:raise ValueError('unsupported backup cell')
        return base64.b64decode(value['$bytes'],validate=True)
    if value is not None and type(value) not in (int,str,bool):raise ValueError('unsupported backup cell type')
    return value


def _columns(db,name):
    return [row[0] for row in db.execute('select column_name from information_schema.columns where table_schema=current_schema() and table_name=%s order by ordinal_position',(name,))]


def _rows(db,name):
    # Named cursors stream BYTEA and history without retaining a whole table.
    width=3 if name in {'note_fields','archive_rows','analysis_senses','analysis_occurrences'} else 2 if name in {
        'units','notes','native_cards','resource_aliases','archive_tables','analyses','chunks'} else 1
    with db.cursor(name='archive_'+uuid.uuid4().hex) as cursor:
        cursor.execute(sql.SQL('select * from {} order by {}').format(sql.Identifier(name),
                       sql.SQL(',').join(sql.Literal(i) for i in range(1,width+1))))
        yield from cursor


def backup(value,directory):
    selected=target(value);directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=True)
    dest=directory/f'catalog-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:8]}.pg.jsonl.gz'
    digest=hashlib.sha256();counts={}
    try:
        with connect(selected,readonly=True) as db,db.transaction():
            db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            columns={name:_columns(db,name) for name in TABLES}
            with dest.open('xb') as output,gzip.GzipFile(fileobj=output,mode='wb') as stream:
                stream.write((canonical({'schema':'study-catalog-postgresql-backup.v1','tables':columns,'engine':'postgresql'})+'\n').encode())
                for name in TABLES:
                    count=0
                    for row in _rows(db,name):
                        line=(canonical([name,[_pack_cell(v) for v in row]])+'\n').encode()
                        stream.write(line);digest.update(line);count+=1
                    counts[name]=count
                stream.write((canonical({'counts':counts,'rows_sha256':digest.hexdigest()})+'\n').encode())
    except BaseException:dest.unlink(missing_ok=True);raise
    return dest


def restore(source,destination):
    selected=target(destination)
    with psycopg.connect(selected.dsn,autocommit=True) as db,db.transaction():
        _initialize_connection(db,selected,must_new=True)
        with gzip.open(source,'rb') as stream:
            header=json.loads(stream.readline())
            expected={name:_columns(db,name) for name in TABLES}
            if header!={'schema':'study-catalog-postgresql-backup.v1','engine':'postgresql','tables':expected}:
                raise ValueError('unsupported PostgreSQL backup schema')
            db.execute('delete from metadata');digest=hashlib.sha256();counts={name:0 for name in TABLES};footer=None
            for line in stream:
                record=json.loads(line)
                if isinstance(record,dict):footer=record;break
                name,values=record
                if name not in expected or len(values)!=len(expected[name]):raise ValueError('invalid backup row')
                query=sql.SQL('insert into {} values({})').format(sql.Identifier(name),sql.SQL(',').join(sql.Placeholder() for _ in values))
                db.execute(query,[_unpack_cell(v) for v in values]);digest.update(line);counts[name]+=1
            if not footer or footer!={'counts':counts,'rows_sha256':digest.hexdigest()} or stream.read():
                raise ValueError('backup count or digest mismatch')
            validate(db)
            for name in ('events','component_revisions'):
                sequence=db.execute("select pg_get_serial_sequence(%s,'id')",(name,)).fetchone()[0]
                maximum=db.execute(sql.SQL('select max(id) from {}').format(sql.Identifier(name))).fetchone()[0]
                if maximum is not None:db.execute('select setval(%s,%s,true)',(sequence,maximum))
    return selected


def logical_digest(value):
    h=hashlib.sha256()
    with connect(value,readonly=True) as db,db.transaction():
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        for name in TABLES:
            h.update(name.encode()+b'\0')
            for row in _rows(db,name):h.update(canonical([_pack_cell(v) for v in row]).encode()+b'\n')
    return h.hexdigest()


def edit_component(path,key,text,*,expected,reason,backups):
    if not isinstance(text,str) or not isinstance(expected,str) or not isinstance(reason,str) or not reason.strip():
        raise ValueError('edit requires exact previous text and a nonempty reason')
    with connect(path,readonly=True) as db:
        row=db.execute('select current_id from components where id=%s',(key,)).fetchone()
        if row is None or get_object(db,row[0]).decode()!=expected:raise ValueError('stale or missing shared component')
        before=row[0]
    saved=backup(path,backups)
    with connect(path) as db,transaction(db):
        row=db.execute('select current_id from components where id=%s FOR UPDATE',(key,)).fetchone()
        if row is None or row[0]!=before:raise ValueError('component changed after edit preparation')
        after=put_object(db,text.encode());db.execute('update components set current_id=%s where id=%s',(after,key))
        db.execute('insert into component_revisions(component_id,before_id,after_id,reason,created_at) values(%s,%s,%s,%s,%s)',
                   (key,before,after,reason,now()))
        affected=db.execute('select count(*) from note_fields where component_id=%s',(key,)).fetchone()[0]
        event(db,'edit-shared-component',{'component_id':key,'before':before,'after':after,'reason':reason,'affected_notes':affected})
    return {'component_id':key,'affected_notes':affected,'backup':str(saved),'before':before,'after':after}


def summary(value=None):
    with connect(value,readonly=True) as db:
        counts={name:db.execute('select count(*) from '+name).fetchone()[0] for name in
                ('books','words','units','notes','components','objects','resource_aliases','analyses','dictionary_senses','sentences','tokens','decisions','chunks','archive_rows')}
        cur=db.execute('select b.*,count(n.note_id) as notes from books b left join notes n on n.book_id=b.id group by b.id order by b.id')
        books=[dict(zip([c.name for c in cur.description],row)) for row in cur]
        cur=db.execute('select id,kind,label,status from sources order by id')
        sources=[dict(zip([c.name for c in cur.description],row)) for row in cur]
        counts['resource_unique_contents']=db.execute('select count(distinct object_id) from resource_aliases').fetchone()[0]
    return {'schema':'unified-study-catalog.pg.v1','engine':'postgresql','counts':counts,'books':books,'sources':sources}
