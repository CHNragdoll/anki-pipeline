"""Batch the same immutable reviewed facts into normalized PostgreSQL tables."""
from __future__ import annotations

import hashlib
import zlib

from psycopg import sql

from . import study_catalog as c


class _Objects:
    def __init__(self):
        self.rows = {}

    def raw(self, value):
        key = hashlib.sha256(value).hexdigest()
        if key not in self.rows:
            encoded = zlib.compress(value, 6) if len(value) >= 1024 else value
            codec, data = ('zlib', encoded) if len(encoded) + 64 < len(value) else ('raw', value)
            self.rows[key] = key, codec, len(value), data
        return key

    def json(self, value):
        return self.raw(c.canonical(value).encode())


def _write(db, table, rows, *, ignore=False):
    if not rows:
        return
    stage = '_catalog_normalize_' + table
    db.execute(sql.SQL('CREATE TEMP TABLE IF NOT EXISTS {} (LIKE {}) ON COMMIT DELETE ROWS').format(
        sql.Identifier(stage), sql.Identifier(table)))
    db.execute(sql.SQL('TRUNCATE {}').format(sql.Identifier(stage)))
    with db.cursor().copy(sql.SQL('COPY {} FROM STDIN').format(sql.Identifier(stage))) as writer:
        for row in rows:
            writer.write_row(row)
    query = sql.SQL('INSERT INTO {} SELECT * FROM {}').format(sql.Identifier(table), sql.Identifier(stage))
    if ignore:
        query += sql.SQL(' ON CONFLICT DO NOTHING')
    db.execute(query)


def import_analysis(db, record):
    from .study_catalog_import import _dictionary_binding
    book, card = record['book_id'], record['card_id']; word = c.ensure_word(db, record['word'])
    rows = record['occurrences']
    if len(rows) != record['expected_occurrences']:
        raise ValueError('active physical count differs from its sealed record')
    objects = _Objects(); senses = {}; output = {name: [] for name in (
        'analyses', 'dictionary_senses', 'analysis_senses', 'sentences', 'chunks', 'tokens', 'decisions', 'analysis_occurrences')}
    output['analyses'].append((book, card, word, record['snapshot_id'], objects.json(record), len(rows)))
    for ordinal, sense in enumerate(record['senses']):
        proof = _dictionary_binding(record, sense)
        sid = c.identity('sense', word, proof, sense['pos'], sense['text'])
        output['dictionary_senses'].append((sid, word, proof['dictionary'], sense['pos'], sense['text'], objects.json(proof)))
        output['analysis_senses'].append((book, card, ordinal, sense['sense_id'], sid)); senses[sense['sense_id']] = sid
    for ordinal, row in enumerate(rows):
        english = row['english']; translation = row['translation']; start, end = row['target_range']
        if not 0 <= start < end <= len(english):
            raise ValueError('physical token range differs from exact text')
        if hashlib.sha256(english.encode()).hexdigest() != row['english_hash']:
            raise ValueError('stale source English hash')
        alignment = row.get('alignment'); aid = objects.json(alignment) if alignment else None
        enid = objects.raw(english.encode()); cnid = objects.raw(translation.encode())
        sentence = c.identity('sentence', row['paper_id'], row['physical_source'], enid, cnid, aid)
        output['sentences'].append((sentence, row['paper_id'], row['sentence_id'], enid, cnid, aid))
        for index, chunk in enumerate((alignment or {}).get('alignments', [])):
            output['chunks'].append((sentence, index, objects.json(chunk)))
        physical = objects.json(row['physical_source']); token = c.identity('token', row['occurrence_id'], word, sentence)
        output['tokens'].append((token, row['occurrence_id'], word, sentence, start, end, physical))
        sense = senses.get(row['sense_id'])
        if row['sense_id'] is not None and sense is None:
            raise ValueError('review points to missing dictionary sense')
        decision = c.identity('decision', word, token, sense, row['status'], row['reason'], row['method'])
        output['decisions'].append((decision, word, token, sense, row['status'], row['reason'], row['method']))
        output['analysis_occurrences'].append((book, card, ordinal, row['occurrence_id'], token, decision, objects.json(row)))
    _write(db, 'objects', objects.rows.values(), ignore=True)
    for table, rows in output.items():
        _write(db, table, rows, ignore=table in {'dictionary_senses', 'sentences', 'chunks', 'tokens', 'decisions'})
