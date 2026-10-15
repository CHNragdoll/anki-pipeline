"""Bounded COPY batches for immutable historical rows in PostgreSQL."""
from __future__ import annotations

import hashlib
import zlib

from . import study_catalog as c


def write_batch(db, source_id, table, start, rows, digest):
    """Keep the original object hashes and row stream, using two COPY streams.

    The caller owns one transaction per batch. Any object or foreign-key
    failure rolls the entire batch back, retaining the previous resume ordinal.
    """
    objects = {}; references = []
    for ordinal, row in enumerate(rows, start):
        raw = c.canonical([c._pack_cell(v) for v in row]).encode()
        digest.update(raw + b'\n'); key = hashlib.sha256(raw).hexdigest()
        if key not in objects:
            encoded = zlib.compress(raw, 6) if len(raw) >= 1024 else raw
            codec, data = ('zlib', encoded) if len(encoded) + 64 < len(raw) else ('raw', raw)
            objects[key] = (key, codec, len(raw), data)
        references.append((source_id, table, ordinal, key))
    db.execute('CREATE TEMP TABLE IF NOT EXISTS _catalog_archive_object_stage '
               '(id TEXT,codec TEXT,byte_length BIGINT,data BYTEA) ON COMMIT DELETE ROWS')
    with db.cursor().copy('COPY _catalog_archive_object_stage FROM STDIN') as writer:
        for row in objects.values():
            writer.write_row(row)
    db.execute('INSERT INTO objects SELECT * FROM _catalog_archive_object_stage ON CONFLICT(id) DO NOTHING')
    with db.cursor().copy('COPY archive_rows FROM STDIN') as writer:
        for row in references:
            writer.write_row(row)
    return start + len(rows)
