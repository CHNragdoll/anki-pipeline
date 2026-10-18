import base64
from contextlib import closing
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from anki_pipeline import study_compiled_native as native
from anki_pipeline.study_catalog_export import _CompiledNativeExport
from anki_pipeline.study_native_carrier import build_native_carrier, NativeCarrierBundle
from anki_pipeline.study_catalog_native_delivery import native_host_sha256
from anki_pipeline import study_catalog_export as exporter
from tests.test_study_compiled_native import sample_note


def meta(prefix, descriptor):
    token = base64.urlsafe_b64encode(native.native_delivery_json(descriptor).encode()).decode().rstrip('=')
    return prefix + native.NATIVE_DELIVERY_FOOTER + token + native.NATIVE_DELIVERY_END


class BundleExportTests(unittest.TestCase):
    def test_export_bundle_wiring_is_bound_to_native_revision(self):
        source = Path(exporter.__file__)
        raw = source.read_bytes()
        marker = b'if compiled is not None:compiled.bundle_media(native)'
        self.assertEqual(raw.count(marker), 1)
        altered = raw.replace(marker, b'pass  # bundling removed after planning')
        before = native_host_sha256()
        original_read = Path.read_bytes
        def read(path):
            return altered if path == source else original_read(path)
        with patch.object(Path, 'read_bytes', read):
            self.assertNotEqual(native_host_sha256(), before)

    def test_rebind_only_transport_addresses_and_preserve_source_prefix(self):
        old = '_study_native_' + '1' * 64 + '.js'
        new = '_study_native_' + '2' * 64 + '.js'
        descriptor = {'id': '书:a', 'bootstrap_version': 'b' * 64,
                      'transport': {'a.json': {'src': old, 'sha256': 'a' * 64},
                                    'b.json': {'src': old, 'sha256': 'c' * 64}},
                      'packet': {'src': 'a.json', 'sha256': 'a' * 64},
                      'source': {'original': '完整原文、chunk、审核与音频'}}
        frozen = copy.deepcopy(descriptor)
        before = meta('原Meta：甲\n乙', descriptor)
        after = native.rebind_native_media_transport(before, {old: new})
        prefix, got = native.split_native_delivery_meta(after)
        self.assertEqual(prefix, '原Meta：甲\n乙')
        expected = copy.deepcopy(descriptor)
        for item in expected['transport'].values():
            item['src'] = new
        self.assertEqual(got, expected)
        self.assertEqual(descriptor, frozen)
        self.assertEqual(native.rebind_native_media_transport(before, {}), before)

    def test_rebind_rejects_unaddressed_or_malformed_carriers(self):
        old = '_study_native_' + '1' * 64 + '.js'
        value = meta('source', {'transport': {'a': {'src': old, 'sha256': 'a' * 64}}})
        for replacement in ('../x.js', 'x.js', '_study_native_' + 'X' * 64 + '.js'):
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                native.rebind_native_media_transport(value, {old: replacement})
        bad = meta('source', {'transport': {'a': {'src': old, 'sha256': 'broken'}}})
        with self.assertRaises(ValueError):
            native.rebind_native_media_transport(bad, {})

    def test_complete_staged_sqlite_rebinds_only_compiled_meta(self):
        with tempfile.TemporaryDirectory() as folder, closing(sqlite3.connect(':memory:')) as db:
            root = Path(folder)
            export = _CompiledNativeExport.__new__(_CompiledNativeExport)
            export.media, export.media_pins = {}, {}
            aliases = []
            for text in ('完整A', '完整B'):
                pin = hashlib.sha256(text.encode()).hexdigest()
                raw = build_native_carrier(pin, text)
                digest = hashlib.sha256(raw).hexdigest()
                alias = '_study_native_' + digest + '.js'
                path = root / alias
                path.write_bytes(raw)
                export.media[alias] = path
                export.media_pins[alias] = digest
                aliases.append((alias, pin, raw))
            export.compiled_notes = {1, 2}
            export.media_consumers = {alias: {('opaque-1', 'a' * 64), ('opaque-2', 'a' * 64)}
                                      for alias, _, _ in aliases}
            export.models = {10: {'flds': [{'name': 'Word'}, {'name': 'Meta'}]}}
            export.bundle_report = None
            db.execute('create table notes(id integer primary key, mid integer, flds text, mod integer)')
            for number in (1, 2):
                fields = [f'word-{number}', meta(f'原始Meta{number}', {
                    'transport': {str(index): {'src': alias, 'sha256': pin}
                                  for index, (alias, pin, _) in enumerate(aliases)},
                    'id': str(number), 'unchanged': ['双语', '审核', 'chunk']})]
                db.execute('insert into notes values (?,?,?,?)', (number, 10, '\x1f'.join(fields), 99))
            db.execute('insert into notes values(3,20,?,100)', ('guide\x1foriginal-meta',))
            before = list(db.execute('select * from notes order by id'))
            export.bundle_media(db)
            after = list(db.execute('select * from notes order by id'))
            self.assertEqual(len(export.media), 1)
            alias, stream = next(iter(export.media.items()))
            expected_raw = b''.join(row[2] for row in sorted(aliases))
            self.assertEqual(b''.join(stream.iter_chunks()), expected_raw)
            self.assertEqual(export.media_pins[alias], hashlib.sha256(expected_raw).hexdigest())
            self.assertEqual(before[2], after[2])
            for old, new in zip(before[:2], after[:2]):
                self.assertEqual(old[:2] + old[3:], new[:2] + new[3:])
                a, b = old[2].split('\x1f'), new[2].split('\x1f')
                self.assertEqual(a[0], b[0])
                old_prefix, original = native.split_native_delivery_meta(a[1])
                new_prefix, rebound = native.split_native_delivery_meta(b[1])
                self.assertEqual(old_prefix, new_prefix)
                for item in original['transport'].values():
                    item['src'] = alias
                self.assertEqual(original, rebound)
            self.assertTrue(all(path.is_file() for path in root.iterdir()))

    def test_unrelated_profiles_never_load_foreign_bundle_members(self):
        with tempfile.TemporaryDirectory() as folder, closing(sqlite3.connect(':memory:')) as db:
            root = Path(folder)
            export = _CompiledNativeExport.__new__(_CompiledNativeExport)
            export.media, export.media_pins, export.media_consumers = {}, {}, {}
            aliases = []
            for number in range(7):
                raw = build_native_carrier(hashlib.sha256(str(number).encode()).hexdigest(), str(number))
                digest = hashlib.sha256(raw).hexdigest()
                alias = '_study_native_' + digest + '.js'
                path = root / alias
                path.write_bytes(raw)
                export.media[alias], export.media_pins[alias] = path, digest
                aliases.append(alias)
            uses = {1: set(aliases[:2] + aliases[4:6]), 2: set(aliases[2:6])}
            for number, names in uses.items():
                for name in names:
                    export.media_consumers.setdefault(name, set()).add(('opaque-' + str(number), str(number) * 64))
            export.compiled_notes = set(uses)
            export.models = {10: {'flds': [{'name': 'Word'}, {'name': 'Meta'}]}}
            export.bundle_report = None
            db.execute('create table notes(id integer primary key, mid integer, flds text, mod integer)')
            original = {}
            for number, names in uses.items():
                descriptor = {'id': 'opaque-' + str(number), 'entry': {'profile': {'sha256': str(number) * 64}},
                    'transport': {str(index): {'src': name, 'sha256': 'a' * 64}
                                  for index, name in enumerate(sorted(names))}}
                original[number] = copy.deepcopy(descriptor)
                db.execute('insert into notes values (?,?,?,?)',
                           (number, 10, f'word-{number}\x1f' + meta('source', descriptor), 99))
            before_files = {path.name: path.read_bytes() for path in root.iterdir()}
            export.bundle_media(db)
            for number, flds in db.execute('select id,flds from notes'):
                prefix, descriptor = native.split_native_delivery_meta(flds.split('\x1f')[1])
                self.assertEqual(prefix, 'source')
                for logical, item in descriptor['transport'].items():
                    self.assertEqual(item['sha256'], original[number]['transport'][logical]['sha256'])
                    value = export.media[item['src']]
                    members = {member.alias for member in value.members} if isinstance(value, NativeCarrierBundle) else {item['src']}
                    self.assertLessEqual(members, uses[number], f'profile {number} loads foreign carriers')
            self.assertEqual(len(export.media), 4)  # Two private cohorts, one shared cohort, one unknown.
            self.assertEqual(export.media[aliases[6]], root / aliases[6])
            self.assertEqual({path.name: path.read_bytes() for path in root.iterdir()}, before_files)

    def test_project_records_shared_media_consumers_before_deduplication(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            notes, delivery, projected = [], {}, []
            raw = b'/* same independently executable carrier */'
            digest = hashlib.sha256(raw).hexdigest()
            alias = '_study_native_' + digest + '.js'
            for index in (1, 2):
                note = sample_note()
                note.update(id='opaque-' + str(index), note_id=index, content_mod=21)
                note['payload']['id'] = index
                notes.append(note)
                delivery[index] = {'result': {'identity': 'book:' + note['id'], 'mode': 'compiled',
                    'entry': {'html': {}, 'profile': {}}, 'runtime': {}, 'record': {}},
                    'prepared': {}, 'policy': {},
                    'source_sha256': exporter.compiled_source_sha256(note)}
                # Distinct profile pins are part of the opaque consumer identity.
                descriptor = {'id': note['id'], 'entry': {'profile': {'sha256': str(index) * 64}},
                    'transport': {'first.json': {'src': alias, 'sha256': 'a' * 64},
                                  'same-alias.json': {'src': alias, 'sha256': 'b' * 64}}}
                output = copy.deepcopy(note)
                output['fields'][output['field_names'].index('Meta')] = meta('source', descriptor)
                projected.append({'note': output, 'media': {alias: raw}})
            book = {'id': 'book', 'col': {'models': json.dumps({'17': notes[0]['model']})}}
            export = _CompiledNativeExport(book, root, delivery,
                {'models': {17: 20}, 'notes': {1: 21, 2: 21}})
            with patch.object(export, '_resources', return_value={}), patch.object(
                    native, 'project_native_note', side_effect=projected):
                for note in notes:
                    export.project(note)
            self.assertEqual(export.media_consumers,
                {alias: {('opaque-1', '1' * 64), ('opaque-2', '2' * 64)}})
            self.assertEqual(set(export.media), {alias})
            self.assertEqual(export.media[alias].read_bytes(), raw)


if __name__ == '__main__':
    unittest.main()
