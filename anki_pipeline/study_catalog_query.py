"""Read-only facts for all books; physical counts never use display row counts."""
from __future__ import annotations

from . import study_catalog as c
from .study_catalog_export import require_ready


def word_report(value, word):
    with c.connect(value, readonly=True) as db, db.transaction():
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        require_ready(db)
        row = db.execute("select id from words where language='en' and surface=%s", (word,)).fetchone()
        if row is None:
            raise ValueError('exact word is absent from the catalog')
        wid = row[0]; variants = []
        for book, nid, guid, card, title in db.execute('select n.book_id,n.note_id,n.guid,n.source_card_id,b.title '
                'from notes n join books b on b.id=n.book_id where n.word_id=%s order by n.book_id,n.ordinal', (wid,)):
            fields = [{'name': name, 'component_id': key, 'current_sha256': current}
                      for name, key, current in db.execute('select f.name,c.id,c.current_id from note_fields f '
                          'join components c on c.id=f.component_id where f.book_id=%s and f.note_id=%s order by f.ordinal', (book, nid))]
            units = [r[0] for r in db.execute('select u.name from native_cards n join units u on '
                     'u.book_id=n.book_id and u.id=n.unit_id where n.book_id=%s and n.note_id=%s order by n.ordinal', (book, nid))]
            variants.append({'book_id': book, 'title': title, 'note_id': nid, 'guid': guid,
                             'source_card_id': card, 'units': units, 'fields': fields})
        senses = [{'id': sid, 'dictionary': source, 'pos': pos, 'text': text, 'provenance': c.get_json(db, proof)}
                  for sid, source, pos, text, proof in db.execute('select id,dictionary,pos,text,provenance_id from '
                        'dictionary_senses where word_id=%s order by dictionary,pos,text,id', (wid,))]
    return {'schema': 'study-word-report.v1', 'word': word, 'word_id': wid, 'book_variants': variants, 'dictionary_senses': senses}


def frequency_report(value, *, word=None, book_id=None):
    """Return source-specific sense counts plus a physical union across books.

    A paragraph containing three targets counts three times. Another book's
    mapping of those same physical positions does not add three more globally.
    Different dictionary sense IDs stay separate instead of guessing equivalence.
    """
    with c.connect(value, readonly=True) as db, db.transaction():
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ'); require_ready(db)
        mapped = []
        for bid, manifest in db.execute("select b.book_id,s.manifest_id from book_sources b join sources s on s.id=b.source_id where s.kind='book-map'"):
            for ref in c.get_json(db, manifest).get('analysis_references', {}).values():
                mapped.append({'book_id': bid, 'source_book': ref['book_id'], 'source_card_id': ref['source_card_id']})
        prefix = ('WITH selection AS (select book_id,book_id as source_book,source_card_id from analyses UNION '
                  'select r.book_id,r.source_book,r.source_card_id from jsonb_to_recordset(%s::jsonb) '
                  'as r(book_id text,source_book text,source_card_id text)) ')
        filters = []; values = []
        if word is not None:
            if not db.execute("select 1 from words where surface=%s and language='en'", (word,)).fetchone():
                raise ValueError('exact word is absent from the catalog')
            filters.append('w.surface=%s'); values.append(word)
        if book_id is not None:
            if not db.execute('select 1 from books where id=%s', (book_id,)).fetchone():
                raise ValueError('unknown book')
            filters.append('m.book_id=%s'); values.append(book_id)
        where = ' where ' + ' and '.join(filters) if filters else ''
        values = [c.canonical(mapped), *values]
        base = (' from selection m join analyses a on a.book_id=m.source_book and a.source_card_id=m.source_card_id '
                'join words w on w.id=a.word_id ')
        known = db.execute(prefix+'select count(*)'+base+where, values).fetchone()[0]
        relations = (' from selection m join analyses a on a.book_id=m.source_book and a.source_card_id=m.source_card_id '
                     'join analysis_occurrences x on x.book_id=a.book_id and x.source_card_id=a.source_card_id '
                     'join words w on w.id=a.word_id join tokens t on t.id=x.token_id '
                     'join sentences s on s.id=t.sentence_id join decisions d on d.id=x.decision_id')
        totals = db.execute(prefix+'select count(distinct t.physical_id),count(distinct s.paper_id)' + relations + where, values).fetchone()
        per_book = [{'book_id': bid, 'word': spelling, 'physical_occurrences': count, 'papers': papers}
                    for bid, spelling, count, papers in db.execute(prefix+'select m.book_id,w.surface,count(distinct t.physical_id),'
                        'count(distinct s.paper_id)' + relations + where + ' group by m.book_id,w.surface order by m.book_id,w.surface', values)]
        by_sense = [{'book_id': bid, 'word': spelling, 'sense_id': sense, 'status': status, 'physical_occurrences': count}
                    for bid, spelling, sense, status, count in db.execute(prefix+'select m.book_id,w.surface,d.sense_id,d.status,'
                        'count(distinct t.physical_id)' + relations + where +
                        ' group by m.book_id,w.surface,d.sense_id,d.status order by m.book_id,w.surface,d.sense_id,d.status', values)]
    return {'schema': 'study-frequency-report.v1', 'word': word, 'book_id': book_id,
            'data_status': 'normalized' if known else 'not_normalized', 'analysis_records': known,
            'physical_occurrences': totals[0] if known else None, 'papers': totals[1] if known else None,
            'books': per_book, 'senses_by_book': by_sense,
            'rule': 'count distinct original physical positions; do not count grouped display rows or sum duplicate book mappings'}
