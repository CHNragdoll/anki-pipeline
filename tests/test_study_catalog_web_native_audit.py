"""Exact native-source audit regressions; real snapshots are opt-in, read-only."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from anki_pipeline import study_catalog_web as web
from anki_pipeline import study_catalog_web_materialize as materialize


NATIVE_PINS = frozenset({
    'b15c0a87ba4cc698c9fa27e1ee3af7cfd6f631f4cc05b350d627a989fe745f26',
    '286040a79570249e4e76fa5240f8cbdc09f7303d0f2d6120d2ea70d5a869de67',
})


def policy(sides, media):
    audit = web.SharedMountAudit()
    audit.observe(sides)
    external = web.script_deferral_policy(
        ['<script src="' + name + '"></script>' for name in sorted(audit.external)],
        media,
        audited_sha256=web.AUDITED_MOUNT_EXTERNAL_SHA256 | web.AUDITED_MOUNT_INLINE_SHA256,
    )
    return {'external': external, 'inline': [{'source': value} for value in audit.inline.values()]}


class NativeAuditTests(unittest.TestCase):
    def test_approved_whole_native_cohorts_are_audited_for_shared_mount(self):
        self.assertTrue(NATIVE_PINS <= materialize.AUDITED_NATIVE_MODULES)
        self.assertTrue(NATIVE_PINS <= web.AUDITED_MOUNT_EXTERNAL_SHA256)

    def test_unknown_native_bytes_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            media = Path(folder)
            (media / 'native.js').write_bytes(b'window.unknownNativeVersion=true;')
            side = '<!doctype html><body><script src="native.js"></script></body>'
            actual = policy([side], media)
            self.assertNotIn('native.js', actual['external'])
            with self.assertRaisesRegex(ValueError, 'script source lacks an exact audit'):
                materialize._eligible_side(side, actual)


@unittest.skipUnless(os.environ.get('ANKI_STUDY_WEB_NATIVE_AUDIT_SAMPLES'),
                     'requires externally pinned, read-only small export samples')
class ActualNativeAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(Path(os.environ['ANKI_STUDY_WEB_NATIVE_AUDIT_SAMPLES']).read_bytes())

    def read_pinned(self, row, limit):
        path = Path(row['path'])
        self.assertLessEqual(path.stat().st_size, limit)
        raw = path.read_bytes()
        self.assertEqual(len(raw), row['bytes'])
        self.assertEqual(hashlib.sha256(raw).hexdigest(), row['sha256'])
        return raw

    def test_actual_approved_sources_and_one_byte_mutations(self):
        rows = self.fixture['modules']
        self.assertEqual({row['sha256'] for row in rows}, NATIVE_PINS)
        for row in rows:
            with self.subTest(pin=row['sha256']), tempfile.TemporaryDirectory() as folder:
                raw = self.read_pinned(row, 2 * 1024 * 1024)
                media = Path(folder)
                target = media / 'native.js'
                target.write_bytes(raw)
                side = '<!doctype html><body><script src="native.js"></script></body>'
                actual = policy([side], media)
                self.assertEqual(actual['external'].get('native.js'), row['sha256'])
                materialize._eligible_side(side, actual)
                target.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
                altered = policy([side], media)
                self.assertNotIn('native.js', altered['external'])
                with self.assertRaisesRegex(ValueError, 'script source lacks an exact audit'):
                    materialize._eligible_side(side, altered)

    def test_actual_small_protected_wrappers_keep_both_sides_eligible(self):
        self.assertEqual(len(self.fixture['wrappers']), 2)
        media = Path(self.fixture['media'])
        for row in self.fixture['wrappers']:
            with self.subTest(pin=row['sha256']):
                raw = self.read_pinned(row, 128 * 1024)
                payload = web.card_payload(raw)
                self.assertEqual(raw, web.card_shell(payload.decode(), '../media/').encode())
                sides = json.loads(payload)
                self.assertEqual(len(sides), 2)
                actual = policy(sides, media)
                for side in sides:
                    materialize._eligible_side(side, actual)


if __name__ == '__main__':
    unittest.main()
