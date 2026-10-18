import base64
from contextlib import closing
import copy
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from anki_pipeline import study_compiled_native as native
from anki_pipeline.study_catalog_export import _CompiledNativeExport
from anki_pipeline.study_native_carrier import build_native_carrier
from anki_pipeline.study_catalog_native_delivery import native_host_sha256
from anki_pipeline import study_catalog_export as exporter


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
            export.models = {10: {'flds': [{'name': 'Word'}, {'name': 'Meta'}]}}
            export.bundle_report = None
            db.execute('create table notes(id integer primary key, mid integer, flds text, mod integer)')
            for number, (alias, pin, _) in enumerate(aliases, 1):
                fields = [f'word-{number}', meta(f'原始Meta{number}', {
                    'transport': {'asset.json': {'src': alias, 'sha256': pin}},
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
                original['transport']['asset.json']['src'] = alias
                self.assertEqual(original, rebound)
            self.assertTrue(all(path.is_file() for path in root.iterdir()))


if __name__ == '__main__':
    unittest.main()
