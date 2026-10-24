import hashlib
import json
import unittest

from anki_pipeline.ordinary_examples_inline import PinnedMedia, complete_examples
from anki_pipeline.slim_apkg_content import Store, placeholder, transform
from pathlib import Path
import tempfile


class OrdinaryExamplesInline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name))

    def test_exact_legacy_expansion_keeps_all_rows_and_other_disclosures(self):
        history = '<details><div class="as-lazy" data-as-kind="detail">unchanged</div></details>'
        rows = ['<li class="example-card"><b>'+str(n)+'</b> 原句 &amp; translation</li>\n' for n in range(43)]
        parts = []
        for begin in range(10, 43, 10):
            group = rows[begin:begin + 10]
            parts.append({**self.store.add(''.join(group)), 'count': len(group)})
        raw = '<ol class="examples">'+''.join(rows[:10])+placeholder(parts, 'examples', 33)+'</ol>'+history
        expected = '<ol class="examples">'+''.join(rows)+'</ol>'+history
        self.assertEqual(complete_examples(raw, self.store), expected)
        self.assertEqual(complete_examples(expected, self.store), expected)

    def test_new_examples_never_reintroduce_ten_row_cap(self):
        raw = '<ol class="examples">'+''.join('<li class="example-card">'+str(n)+'</li>' for n in range(43))+'</ol>'
        self.assertEqual(transform(raw, self.store, 'examples'), raw)

    def test_manifest_count_mismatch_rejects(self):
        part = {**self.store.add('<li>x</li>'), 'count': 2}
        with self.assertRaisesRegex(ValueError, 'counts differ'):
            complete_examples(placeholder([part], 'examples', 1), self.store)

    def test_packed_reader_checks_original_sha_and_missing_media(self):
        resources = {}
        def register(value):
            pin = hashlib.sha256(value.encode()).hexdigest()
            name = '_as_'+pin[:24]+'.js'
            resources[name] = 'window.AnkiSlimAssets=window.AnkiSlimAssets||{};window.AnkiSlimAssets['+json.dumps(pin)+']='+json.dumps(value)+';'
            return {'src': name, 'sha256': pin}
        ref = register('完整原句')
        reader = PinnedMedia(resources.get)
        self.assertEqual(reader.read(ref), '完整原句')
        resources[ref['src']] = resources[ref['src']].replace('\\u5b8c', 'X')
        with self.assertRaisesRegex(ValueError, 'SHA differs'):
            reader.read(ref)
        resources.clear()
        with self.assertRaisesRegex(ValueError, 'missing'):
            reader.read(ref)
