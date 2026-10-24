#!/usr/bin/env python3
"""Owned, one-time v2 -> text-v3/dictionary transport migration.

Default invocation only checks sealed inputs. Explicit ``YEAR --build`` creates
one new year directory and package. No PG connection, semantic generation,
Anki process, overwrite, unlink, hard link or source-file mutation is used.
Failed/partial outputs are retained and are never accepted without PACKED.json.
The final package still requires independent archive parity and client gates.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack, closing
import copy
import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import subprocess
import sys
import time
import zipfile

ROOT = Path('/Users/apple/Documents/PyCharm/Anki/anki_rebuild')
BASE = Path('/Users/apple/Library/Application Support/AnkiStudyCatalog/service-runtime/native-editor-compatible-v3-txoev54z')
V2 = Path('/Users/apple/Library/Application Support/AnkiStudyCatalog/service-runtime/native-schema-compatible-v2-c4g3mir5')
SOURCES = ROOT / 'output/inline-disclosures-20261015'
SOURCE_COMMIT = '56cab064b1e4f74e47c69b4e8bb9fb4e22c616e3'
HOST_SHA256 = 'cb64b6fd8d64408319f9a556fce632919a223fc0ac1bc8e78a1e57ed6b75241d'
CONFIG = {
    2026: {'book_id': 'redbook', 'compiled_notes': 6681,
           'parity_sha256': '74cd2ea6bc2a3ecb3695501182b1962adc3b7a17b5ff7e461b36804618d4ba5c',
           'archive_sha256': '4a1e04e27415e0d7c4f11e370299552acf6fa2e29c605570c5a5f9eec1e28179'},
    2027: {'book_id': 'redbook2027', 'compiled_notes': 6531,
           'parity_sha256': 'a21b5f04f4ba253bb61bf98de70e1e92f8a52ec200a94d9ecf2e1f535792bc4e',
           'archive_sha256': 'bf6b27516cd5ac48f021d6435b377a0c98c556918b1050f3d316408d55bd5470'},
}
CHUNK = 1024 * 1024
HASH = re.compile(r'[a-f0-9]{64}')
CARRIER = re.compile(r'_study_native_([a-f0-9]{64})\.js')
BOOTSTRAP = re.compile(r'_study_native_bootstrap_([a-f0-9]{64})\.js')
V2_FOOTER = '<script type="application/json" data-study-native-delivery="v2">'
LITERAL_PREFIX = b'window.StudyCompiledNative.register('

sys.path.insert(0, str(ROOT))
from anki_pipeline import study_compiled_native as native
from anki_pipeline import study_catalog_native_delivery as delivery
from anki_pipeline.study_native_carrier import build_native_carrier
from anki_pipeline.study_apkg_repack import repack_apkg


def need(condition, message):
    if not condition:
        raise ValueError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def compact(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        need(key not in result, 'duplicate JSON key: ' + key)
        result[key] = value
    return result


def json_value(raw):
    return json.loads(raw, object_pairs_hook=no_duplicates,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite JSON: ' + value)))


def stamp(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


class PinnedFile:
    """Keep a regular read-only fd and its path identity for the entire build."""
    def __init__(self, path, expected_sha256=None, expected_bytes=None):
        self.path = Path(path)
        self.expected_sha256 = expected_sha256
        self.expected_bytes = expected_bytes
        self.stream = None

    def __enter__(self):
        named = self.path.stat(follow_symlinks=False)
        need(stat.S_ISREG(named.st_mode), 'regular nonsymlink input required: ' + str(self.path))
        flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
        self.stream = os.fdopen(os.open(self.path, flags), 'rb')
        try:
            self.before = stamp(os.fstat(self.stream.fileno()))
            need(self.before == stamp(named), 'input changed while opening: ' + str(self.path))
            self.pin = self.verify(rehash=True)
            return self
        except BaseException:
            self.stream.close()
            raise

    def verify(self, *, rehash=False):
        need(stamp(os.fstat(self.stream.fileno())) == self.before == stamp(self.path.stat(follow_symlinks=False)),
             'input identity/content stamp changed: ' + str(self.path))
        if self.expected_bytes is not None:
            need(self.before[3] == self.expected_bytes, 'input byte count differs: ' + str(self.path))
        if rehash:
            self.stream.seek(0)
            pin = hashlib.file_digest(self.stream, 'sha256').hexdigest()
            need(self.expected_sha256 is None or pin == self.expected_sha256,
                 'input SHA differs: ' + str(self.path))
            if hasattr(self, 'pin'):
                need(pin == self.pin, 'input SHA changed: ' + str(self.path))
            self.verify()
            return pin

    def read(self):
        self.verify()
        self.stream.seek(0)
        raw = self.stream.read()
        need(digest(raw) == self.pin, 'input changed while reading: ' + str(self.path))
        self.verify()
        return raw

    def descriptor(self):
        return {'path': str(self.path), 'sha256': self.pin, 'bytes': self.before[3]}

    def __exit__(self, *args):
        self.stream.close()


def open_pin(stack, descriptor):
    need(set(descriptor) == {'path', 'sha256', 'bytes'}, 'exact external file pin required')
    need(isinstance(descriptor['sha256'], str) and HASH.fullmatch(descriptor['sha256']) is not None,
         'invalid external SHA')
    return stack.enter_context(PinnedFile(descriptor['path'], descriptor['sha256'], descriptor['bytes']))


def host_check():
    observed = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    need(observed == SOURCE_COMMIT, 'source commit differs from the reviewed operation')
    unchanged = subprocess.run(['git', 'diff', '--quiet', 'HEAD', '--',
        'anki_pipeline/study_compiled_native.py', 'anki_pipeline/compiled/native-bootstrap.js',
        'anki_pipeline/study_native_carrier.py', 'anki_pipeline/study_apkg_repack.py',
        'anki_pipeline/study_catalog_native_delivery.py'], cwd=ROOT, check=False)
    need(unchanged.returncode == 0, 'reviewed transport source files have uncommitted changes')
    need(delivery.native_host_sha256() == HOST_SHA256, 'native host differs from the reviewed operation')


def fsync_directory(path):
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_new(path, raw):
    with Path(path).open('xb') as stream:
        before = os.fstat(stream.fileno())
        need(stream.write(raw) == len(raw), 'short output write: ' + str(path))
        stream.flush()
        os.fsync(stream.fileno())
        named = Path(path).stat(follow_symlinks=False)
        need((named.st_dev, named.st_ino) == (before.st_dev, before.st_ino), 'output path was replaced')
    return {'path': str(path), 'sha256': digest(raw), 'bytes': len(raw)}


def save_new(path, value):
    return write_new(path, (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode())


def read_only(path):
    db = sqlite3.connect(Path(path).as_uri() + '?mode=ro&immutable=1', uri=True)
    db.execute('pragma query_only=on')
    db.execute('pragma cache_size=-16384')
    return db


def registration(stack):
    host_check()
    need(Path(__file__).absolute() == BASE / 'rebind-complete-v3.py', 'runner belongs to another stage')
    need(stat.S_ISDIR(BASE.stat(follow_symlinks=False).st_mode), 'stage directory required')
    files = [stack.enter_context(PinnedFile(__file__))]
    def load(path):
        item = stack.enter_context(PinnedFile(path)); files.append(item)
        return json_value(item.read())
    plan_raw = load(BASE / 'PLAN.json')
    plan, plan_pin = delivery._plan(plan_raw)  # Pure validation; never connects to PG.
    need(plan['schema'] == 'study-native-delivery-plan.v2' and plan['native_host_sha256'] == HOST_SHA256,
         'a current native-host-bound plan is required')
    need(set(plan['books']) == {item['book_id'] for item in CONFIG.values()}, 'complete two-book plan required')
    reg = load(BASE / 'REGISTERED.json')
    journal = BASE / 'REGISTRATION_JOURNAL'
    committed = load(journal / 'COMMITTED.json')
    need(reg == committed and reg['schema'] == 'study-native-delivery-registration-result.v1',
         'REGISTERED and COMMITTED do not agree')
    need(reg['plan_sha256'] == plan_pin and Path(reg['journal']) == journal, 'registration belongs to another plan/stage')
    seal = load(journal / 'SEAL.json')
    need(files[-1].pin == reg['journal_sha256'], 'registration seal SHA differs')
    need(seal['schema'] == 'study-native-delivery-journal.v1' and
         seal['write_keys'] == list(delivery.WRITE_KEYS) and
         set(seal['files']) == {'plan.json', 'before.json', 'after.json'}, 'registration seal scope differs')
    values = {}
    for name, pin in seal['files'].items():
        item = stack.enter_context(PinnedFile(journal / name, pin)); files.append(item)
        values[name] = json_value(item.read())
    need(values['plan.json'] == plan_raw, 'journal plan differs from stage plan')
    before, after = values['before.json'], values['after.json']
    need(before['plan_sha256'] == after['plan_sha256'] == plan_pin and
         before['target'] == after['target'] == plan['target'], 'journal target/plan differs')
    need(before['snapshot'] == plan['expected'] and before['metadata'] == plan['metadata'], 'journal before differs from plan')
    need(delivery._sha(before['metadata']) == seal['metadata_before_sha256'] and
         delivery._sha(after['metadata']) == seal['metadata_after_sha256'] == reg['metadata_after_sha256'],
         'journal metadata seal differs')
    expected_versions = delivery._native_versions(after['snapshot'])
    need(json_value(compact(expected_versions)) == reg['native_versions'], 'registration versions differ from sealed after snapshot')
    return plan, plan_pin, reg, files


def prior_proof(stack, year):
    config = CONFIG[year]
    item = stack.enter_context(PinnedFile(V2 / str(year) / 'ARCHIVE_PARITY.json', config['parity_sha256']))
    report = json_value(item.read())
    need(report['schema'] == 'study-native-apkg-complete-parity.v1' and report['status'] == 'PASS' and
         len(report['books']) == 1, 'prior archive parity is not a complete PASS')
    book = report['books'][0]
    need(book['book_id'] == config['book_id'] and book['delivery_transport'] == 'meta-footer-v2', 'prior book/transport differs')
    need(book['candidate']['sha256'] == config['archive_sha256'] and
         Path(book['candidate']['path']) == V2 / str(year) / f'{year}-RedBook-Complete-Compiled-Schema-Compatible.apkg',
         'prior candidate pin/path differs')
    need(Path(book['source']['path']) == SOURCES / f'{year}红宝书完整版-统一内嵌展开正文-20261015.apkg', 'original archive path differs')
    need(Path(book['source_collection_bound_to_final_archive']['path']) == SOURCES / str(year) / 'collection.anki2' and
         Path(book['candidate_collection_bound_to_final_archive']['path']) == V2 / str(year) / 'collection.anki2',
         'source/cache binding paths differ')
    return book, item


def inputs(stack, year):
    plan, plan_pin, reg, held = registration(stack)
    proof, proof_file = prior_proof(stack, year); held.append(proof_file)
    pinned = {key: open_pin(stack, proof[key]) for key in
              ('source', 'candidate', 'source_collection_bound_to_final_archive', 'candidate_collection_bound_to_final_archive')}
    held.extend(pinned.values())
    bid = CONFIG[year]['book_id']
    versions = {kind: {int(key): value for key, value in rows.items()} for kind, rows in reg['native_versions'][bid].items()}
    need(set(versions) == {'notes', 'models'} and all(type(value) is int and value > 0
         for rows in versions.values() for value in rows.values()), 'invalid registered versions')
    identities = {row['note_id']: row['id'] for row in plan['books'][bid]}
    need(len(identities) == CONFIG[year]['compiled_notes'] and set(identities) == set(versions['notes']),
         'registration/plan compiled coverage differs')
    return plan, plan_pin, reg, proof, pinned, held, versions, identities


def literal_carrier(raw, alias):
    match = CARRIER.fullmatch(alias)
    need(match is not None and digest(raw) == match[1], 'carrier filename/raw SHA differs: ' + alias)
    need(raw.startswith(LITERAL_PREFIX) and raw.endswith(b');'), 'prior carrier is not the fixed literal program')
    values = json_value(b'[' + raw[len(LITERAL_PREFIX):-2] + b']')
    need(type(values) is list and len(values) == 2, 'prior literal shape differs')
    pin, text = values
    need(type(pin) is str and HASH.fullmatch(pin) is not None and type(text) is str and
         digest(text.encode()) == pin, 'prior carrier logical SHA differs')
    expected = (LITERAL_PREFIX.decode() + compact(pin) + ',' + compact(text).replace('<', '\\u003c') + ');').encode()
    need(raw == expected, 'prior carrier is not canonical old literal bytes')
    return pin, text


def v2_descriptor(fields, prior_fields):
    need(len(fields) == len(prior_fields) == 10, 'original ten-field schema changed')
    meta = prior_fields[8]
    need(meta.count(V2_FOOTER) == 1 and meta.endswith('</script>'), 'one canonical terminal v2 footer required')
    prefix, payload = meta.split(V2_FOOTER)
    need(prefix == fields[8] and '<' not in prefix and '&' not in prefix, 'original Meta prefix differs')
    descriptor = json_value(payload[:-9])
    need(payload[:-9] == compact(descriptor).replace('<', '\\u003c'), 'v2 descriptor is not canonical')
    need(all(a == b for index, (a, b) in enumerate(zip(fields, prior_fields)) if index != 8), 'original non-Meta field differs')
    need(type(descriptor) is dict and set(descriptor) ==
         {'id', 'entry', 'runtime', 'packet', 'policy', 'transport', 'styles', 'local_media', 'bootstrap_version'},
         'v2 descriptor shape differs')
    return descriptor


def media_transform(archive, original_archive, proof, out, bootstrap):
    need(len(archive.infolist()) == len(archive.NameToInfo), 'duplicate ZIP members')
    media = json_value(archive.read('media'))
    original_media = json_value(original_archive.read('media'))
    need(len(set(media.values())) == len(media), 'duplicate media aliases')
    need(all(media.get(member) == alias for member, alias in original_media.items()), 'original media member/alias changed')
    added = proof['media']['new_media']
    need(len({row['member'] for row in added}) == len(added) and
         {row['member'] for row in added} == set(media) - set(original_media), 'prior added-media census differs')
    replacements, aliases, logical, records = {}, {}, {}, []
    carrier_dir = out / 'carriers'; carrier_dir.mkdir(mode=0o700)
    boot_member = None
    for row in added:
        member, alias = row['member'], row['alias']
        need(re.fullmatch(r'[0-9]+', member) is not None and media[member] == alias, 'numeric media member differs')
        info = archive.getinfo(member)
        need(info.file_size == row['bytes'] and info.file_size <= 192 * 1024 * 1024, 'sealed carrier size differs/exceeds bound')
        raw = archive.read(member)
        need(digest(raw) == row['sha256'], 'sealed added media raw SHA differs')
        if row['kind'] == 'native-bootstrap':
            need(boot_member is None and BOOTSTRAP.fullmatch(alias) is not None and
                 digest(raw) == BOOTSTRAP.fullmatch(alias)[1], 'prior bootstrap differs')
            boot_member = member
            new_alias = '_study_native_bootstrap_' + digest(bootstrap) + '.js'
            need(alias != new_alias, 'bootstrap must advance from unpublished v2')
            replacements[member] = bootstrap
        else:
            need(row['kind'] == 'register-carrier', 'unsupported prior added media kind')
            pin, text = literal_carrier(raw, alias)
            logical[alias] = pin
            transformed = build_native_carrier(pin, text)
            new_alias = '_study_native_' + digest(transformed) + '.js'
            aliases[alias] = new_alias
            if transformed != raw:
                replacement = carrier_dir / new_alias
                written = write_new(replacement, transformed)
                replacements[member] = replacement
                records.append({'member': member, 'old_alias': alias, 'new_alias': new_alias,
                                'old_bytes': len(raw), 'new_bytes': len(transformed),
                                'old_zip_bytes': info.compress_size, 'logical_sha256': pin,
                                'replacement': written})
            del transformed, text
        media[member] = new_alias
        del raw
    need(boot_member is not None and len(set(media.values())) == len(media), 'bootstrap missing or transformed aliases collide')
    fsync_directory(carrier_dir)
    return media, replacements, aliases, logical, records, boot_member


def columns(db, table):
    return [row[1] for row in db.execute('pragma table_info("' + table.replace('"', '""') + '")')]


def ordered_rows(db, table):
    quote = lambda value: '"' + value.replace('"', '""') + '"'
    names = columns(db, table)
    return db.execute('select * from ' + quote(table) + ' order by ' + ','.join(map(quote, names)))


def exact_rows(first, second, label):
    missing, count = object(), 0
    for before, after in itertools.zip_longest(first, second, fillvalue=missing):
        need(before is not missing and after is not missing and before == after, 'row parity differs: ' + label)
        count += 1
    return count


def bind_collection(original_path, prior_path, candidate, versions, identities, aliases, logical, bootstrap_name, bootstrap_version):
    count = field_count = 0
    source_descriptor_hash = hashlib.sha256()
    seen_aliases, models_after = set(), {}
    with closing(read_only(original_path)) as old, closing(read_only(prior_path)) as prior, closing(sqlite3.connect(candidate)) as new:
        old_models = json_value(old.execute('select models from col').fetchone()[0])
        prior_models = json_value(prior.execute('select models from col').fetchone()[0])
        models = copy.deepcopy(prior_models)
        names = columns(old, 'notes'); need(names == columns(prior, 'notes'), 'notes schema differs')
        ix = {name: index for index, name in enumerate(names)}
        new.execute('pragma synchronous=FULL')
        new.execute('begin immediate')
        missing = object()
        for before, was in itertools.zip_longest(old.execute('select * from notes order by id'), prior.execute('select * from notes order by id'), fillvalue=missing):
            need(before is not missing and was is not missing and before[ix['id']] == was[ix['id']], 'original/v2 note identities differ')
            nid, mid = before[ix['id']], before[ix['mid']]
            if nid not in versions['notes']:
                need(before == was and mid not in versions['models'], 'authored note/model differs')
                continue
            need(mid == was[ix['mid']] and mid in versions['models'], 'compiled model identity differs')
            need(versions['notes'][nid] > was[ix['mod']] and versions['models'][mid] > prior_models[str(mid)]['mod'],
                 'registered versions must advance beyond v2')
            model = copy.deepcopy(old_models[str(mid)])
            need(model['flds'] == prior_models[str(mid)]['flds'] and model['flds'][8]['name'] == 'Meta', 'original model fields differ')
            fields, prior_fields = before[ix['flds']].split('\x1f'), was[ix['flds']].split('\x1f')
            descriptor = v2_descriptor(fields, prior_fields)
            need(descriptor['id'] == identities[nid], 'plan/descriptor identity differs')
            source_descriptor_hash.update(nid.to_bytes(8, 'big')); source_descriptor_hash.update(compact(descriptor).encode())
            transformed = copy.deepcopy(descriptor)
            transformed['bootstrap_version'] = bootstrap_version
            for item in transformed['transport'].values():
                need(type(item) is dict and set(item) == {'src', 'sha256'} and
                     item['src'] in aliases and logical[item['src']] == item['sha256'], 'descriptor transport pin differs')
                seen_aliases.add(item['src'])
                item['src'] = aliases[item['src']]
            note = {'id': descriptor['id'], 'field_names': [field['name'] for field in model['flds']],
                    'fields': fields, 'model': model, 'payload': dict(zip(names, before)), 'content_mod': was[ix['mod']]}
            bound = native.bind_native_delivery(note, transformed, bootstrap_name=bootstrap_name,
                                               model_mod=versions['models'][mid], note_mod=versions['notes'][nid])
            need(native.restore_native_source_fields(bound) == fields, 'source fields failed exact v3 inverse')
            need(native.split_native_delivery_meta(bound['fields'][8])[1] == transformed, 'v3 descriptor inverse differs')
            # No semantic descriptor branch is regenerated or replaced.
            need(all(transformed[key] == descriptor[key] for key in descriptor if key not in ('bootstrap_version', 'transport')),
                 'semantic descriptor branch changed')
            if mid in models_after:
                need(models_after[mid] == bound['model'], 'one model produced multiple shells')
            models_after[mid] = bound['model']
            new.execute('update notes set flds=?,mod=?,usn=-1 where id=?',
                        ('\x1f'.join(bound['fields']), versions['notes'][nid], nid))
            count += 1; field_count += len(fields)
        need(count == len(versions['notes']) == len(identities) and set(models_after) == set(versions['models']), 'compiled coverage differs')
        need(seen_aliases == set(aliases), 'unreferenced or missing source carrier')
        models.update({str(mid): model for mid, model in models_after.items()})
        new.execute('update col set models=?', (compact(models),))
        new.commit()
        need(new.execute('pragma integrity_check').fetchall() == [('ok',)], 'candidate integrity_check failed')
        schema = lambda db: list(db.execute('select type,name,tbl_name,sql from sqlite_master order by type,name'))
        need(schema(prior) == schema(new), 'candidate SQLite schema changed')
        for key in ('user_version', 'application_id', 'page_size', 'encoding'):
            need(prior.execute('pragma ' + key).fetchone() == new.execute('pragma ' + key).fetchone(), 'candidate SQLite pragma differs: ' + key)
        tables = [row[0] for row in prior.execute("select name from sqlite_master where type='table' order by name")]
        table_counts = {}
        for table in tables:
            if table not in ('col', 'notes'):
                table_counts[table] = exact_rows(ordered_rows(prior, table), ordered_rows(new, table), table)
        col_names = columns(prior, 'col')
        before_col, after_col = list(ordered_rows(prior, 'col')), list(ordered_rows(new, 'col'))
        need(len(before_col) == len(after_col) == 1, 'collection row count differs')
        need(all(a == b for key, a, b in zip(col_names, before_col[0], after_col[0]) if key != 'models'), 'non-model collection value changed')
        verified = 0
        for before, after in itertools.zip_longest(prior.execute('select * from notes order by id'), new.execute('select * from notes order by id'), fillvalue=missing):
            need(before is not missing and after is not missing, 'candidate note census changed')
            nid = before[ix['id']]
            need(nid == after[ix['id']], 'candidate note identity changed')
            if nid not in versions['notes']:
                need(before == after, 'candidate authored note changed')
            else:
                need(all(a == b for key, a, b in zip(names, before, after) if key not in ('mod', 'usn', 'flds')),
                     'candidate source identity/cache/tag value changed')
                need(after[ix['mod']] == versions['notes'][nid] and after[ix['usn']] == -1, 'candidate registered note version differs')
                # Compare the bytes actually stored by SQLite with the original fields.
                source = old.execute('select flds from notes where id=?', (nid,)).fetchone()[0].split('\x1f')
                model = models[str(after[ix['mid']])]
                restored = native.restore_native_source_fields({'fields': after[ix['flds']].split('\x1f'),
                    'field_names': [field['name'] for field in model['flds']], 'model': model})
                need(restored == source, 'stored candidate fields failed exact original inverse')
                verified += 1
        need(verified == count, 'stored candidate compiled census differs')
    return {'compiled_notes': count, 'original_field_values_roundtrip_exact': field_count,
            'unchanged_identity_and_learning_tables': table_counts,
            'source_descriptor_stream_sha256': source_descriptor_hash.hexdigest()}


def build(year):
    started = time.monotonic()
    with ExitStack() as stack:
        plan, plan_pin, reg, proof, pinned, held, versions, identities = inputs(stack, year)
        for item in held:
            item.verify()
        host_check()
        out = BASE / str(year)
        out.mkdir(mode=0o700)  # Exclusive; never resume over a previous partial.
        out_identity = out.stat()
        candidate = out / 'collection.anki2'
        with candidate.open('xb') as target:
            source = pinned['candidate_collection_bound_to_final_archive'].stream
            source.seek(0)
            while block := source.read(CHUNK):
                need(target.write(block) == len(block), 'short SQLite copy')
            target.flush(); os.fsync(target.fileno())
        bootstrap = native.native_bootstrap_source().encode()
        bootstrap_name = '_study_native_bootstrap_' + digest(bootstrap) + '.js'
        bootstrap_version = native._bootstrap_parts()[1]
        with zipfile.ZipFile(pinned['candidate'].stream) as archive, zipfile.ZipFile(pinned['source'].stream) as original_archive:
            media, replacements, aliases, logical, records, boot_member = media_transform(archive, original_archive, proof, out, bootstrap)
        sql = bind_collection(pinned['source_collection_bound_to_final_archive'].path,
            pinned['candidate_collection_bound_to_final_archive'].path, candidate, versions, identities,
            aliases, logical, bootstrap_name, bootstrap_version)
        with candidate.open('rb') as stream:
            os.fsync(stream.fileno())
        with PinnedFile(candidate) as compiled:
            candidate_pin = compiled.descriptor()
        media_raw = compact(media).encode()
        replacements.update({'collection.anki2': candidate, 'media': media_raw})
        need(set(replacements) <= {row['member'] for row in proof['media']['new_media']} | {'collection.anki2', 'media'},
             'replacement would modify an original media/extra member')
        host_check()
        for item in held:
            item.verify()
        package = out / f'{year}-RedBook-Complete-Compiled-Editor-Compatible.apkg'
        receipt = repack_apkg(pinned['candidate'].path, package, replacements,
                             expected_source_sha256=proof['candidate']['sha256'])
        # Bind the final archive's SQLite member to the exact newly checked cache.
        with zipfile.ZipFile(package) as final:
            with final.open('collection.anki2') as stream:
                need(hashlib.file_digest(stream, 'sha256').hexdigest() == candidate_pin['sha256'], 'archive/cache SQLite binding differs')
            need(final.read('media') == media_raw and final.read(boot_member) == bootstrap, 'final media/bootstrap bytes differ')
            for row in records:
                info = final.getinfo(row['member'])
                need(info.file_size == row['new_bytes'], 'final carrier byte count differs')
                row['new_zip_bytes'] = info.compress_size
                row['zip_saved_bytes'] = row['old_zip_bytes'] - row['new_zip_bytes']
                need(row['zip_saved_bytes'] >= 128, 'repacked carrier did not retain the required net ZIP gain')
        # All input contents and host bytes are re-read after packing, not merely
        # trusted because their names or earlier fstat snapshots still exist.
        for item in held:
            item.verify(rehash=True)
        host_check()
        current = out.stat(follow_symlinks=False)
        need((current.st_dev, current.st_ino) == (out_identity.st_dev, out_identity.st_ino), 'output directory identity changed')
        with PinnedFile(package) as packed:
            package_pin = packed.descriptor()
        for item in held:
            item.verify()
        host_check()
        changed = save_new(out / 'CARRIER_CHANGES.json', {'schema': 'study-native-carrier-rebind-changes.v1', 'assets': records})
        result = {'schema': 'study-native-editor-and-dictionary-rebind.v1', 'book_id': CONFIG[year]['book_id'], 'year': year,
            'status': 'PACKED_AWAITING_INDEPENDENT_PARITY_AND_NATIVE_IMPORT', 'source_commit': SOURCE_COMMIT,
            'host_sha256': HOST_SHA256, 'plan_sha256': plan_pin, 'registered_versions_used': True,
            'registration_journal_sha256': reg['journal_sha256'], 'delivery_transport': 'meta-text-v3',
            'semantic_descriptor_changes': False, 'descriptor_changes': ['bootstrap_version', 'transport.*.src'],
            'field_schema_unchanged': True, 'same_numeric_media_members': True,
            'bootstrap': {'alias': bootstrap_name, 'sha256': digest(bootstrap), 'bytes': len(bootstrap), 'version': bootstrap_version},
            'carriers_checked': len(aliases), 'carriers_changed': len(records), 'carrier_changes': changed,
            'carrier_zip_saved_bytes': sum(row['zip_saved_bytes'] for row in records),
            'carrier_raw_saved_bytes': sum(row['old_bytes'] - row['new_bytes'] for row in records),
            'prior_archive_parity_report_sha256': CONFIG[year]['parity_sha256'],
            'source_inputs_pre_post_SHA_and_identity_exact': [item.descriptor() for item in pinned.values()],
            'collection': candidate_pin, 'package': package_pin, 'repack': receipt, **sql,
            'elapsed_seconds': round(time.monotonic() - started, 3), 'PG_writes': False,
            'Anki_user_profile_access': False, 'full_content_recompiled': False, 'client_performance_acceptance': False}
        fsync_directory(out)
        save_new(out / 'PACKED.json', result)
        fsync_directory(out); fsync_directory(BASE)
        print(json.dumps(result, ensure_ascii=False), flush=True)


def check(years):
    results = []
    for year in years:
        with ExitStack() as stack:
            plan, pin, reg, proof, pinned, held, versions, identities = inputs(stack, year)
            need(not (BASE / str(year)).exists(), 'output year directory already exists; partials are never overwritten')
            for item in held:
                item.verify()
            results.append({'year': year, 'status': 'READ_ONLY_INPUTS_CHECKED', 'plan_sha256': pin,
                            'host_sha256': HOST_SHA256, 'compiled_notes': len(identities),
                            'inputs': [item.descriptor() for item in pinned.values()]})
    host_check()
    print(json.dumps({'build_executed': False, 'PG_writes': False, 'books': results}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('year', type=int, choices=sorted(CONFIG), nargs='?')
    parser.add_argument('--build', action='store_true', help='Explicitly build one year after every registration/source gate passes')
    args = parser.parse_args()
    if args.build:
        need(args.year is not None, '--build requires one explicit year')
        build(args.year)
    else:
        check([args.year] if args.year else sorted(CONFIG))


if __name__ == '__main__':
    main()
