"""Future storage generations keep the two phone disclosures native HTML."""
from contextlib import closing, redirect_stdout
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from anki_pipeline.slim_apkg_content import Store, Slices, digest, placeholder, restore, transform
from scripts import build_shared_apkg as shared


FIELDS = ['Word', 'Phonetic', 'Definition', 'SimpleDefinition', 'Level',
          'WordForms', 'Audio', 'Examples', 'Meta', 'Note']
PREFIX = '<p class="dictionary-source" title="a &gt; b">原释义 &amp; 来源</p>\n'
SUFFIX = '\n<aside data-proof="&quot;x&quot;">其他内容原样保留</aside>'


def body():
    audit = ('<details class="sf-ownership-history"><summary>完整审核</summary>'
             + '审校说明 &lt;original&gt;\n' * 180 + '</details>')
    return ('\n<p class="sf-hint">原说明 &amp; 年份</p>\n'
            '<article class="sf-example" data-sf-occurrence-id="a">'
            '<p class="sf-en"><span class="card-chunk">train</span> original.</p>'
            '<p class="sf-zh"><span class="card-chunk">火车</span>原译。</p>'
            + audit + '</article>\n')


def definition():
    return (PREFIX + '<div class="sf-report" data-sense-frequency="v1">'
            '<details class="sf-pending"><summary>待核对原文</summary>'
            + body() + '</details>\n'
            '<details class="sf-sense"><summary class="sf-row">原释义 · 3 次</summary>'
            '<div class="sf-panel">' + body() + '</div></details></div>' + SUFFIX)


def target_bodies(raw):
    tree = Slices(raw, interests={'sf-pending', 'sf-sense', 'sf-panel'})
    result = []
    for node in tree.nodes:
        if 'sf-pending' in node.classes:
            summaries = [child for child in node.children
                         if child.tag == 'summary' and child.direct_parent == node.start]
            result.append(raw[summaries[0].end:node.closed])
        elif 'sf-panel' in node.classes and node.parent and 'sf-sense' in node.parent.classes:
            result.append(raw[node.opened:node.closed])
    return result


class InlineGeneration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = Store(self.root / 'media')

    def test_v1_disclosure_bodies_exist_without_javascript(self):
        raw = definition()
        revised = transform(raw, self.store, 'definition')
        self.assertEqual(target_bodies(revised), target_bodies(raw))
        self.assertTrue(revised.startswith(PREFIX))
        self.assertTrue(revised.endswith(SUFFIX))
        self.assertEqual(restore(revised, self.store), raw)

    def test_v1_still_externalizes_unrelated_history_but_keeps_all_examples(self):
        outside = ('<details class="sf-ownership-history"><summary>其他历史</summary>'
                   + '另一处审核 ' * 800 + '</details>')
        raw = definition() + outside
        revised = transform(raw, self.store, 'definition')
        self.assertEqual(target_bodies(revised), target_bodies(raw))
        self.assertIn('data-as-kind="detail"', revised[len(definition()):])
        self.assertEqual(restore(revised, self.store), raw)
        examples = ''.join('<li class="example-card"><p>' + str(n) + '</p></li>'
                           for n in range(13))
        new_examples = transform(examples, self.store, 'examples')
        self.assertEqual(new_examples.count('<li class="example-card">'), 13)
        self.assertEqual(new_examples, examples)
        self.assertNotIn('data-as-kind="examples"', new_examples)
        self.assertEqual(restore(new_examples, self.store), examples)

    def run_prepare(self, raw):
        year = 'fixture'
        source_root = self.root / 'source'
        folder = source_root / year
        folder.mkdir(parents=True)
        (folder / 'build-report.json').write_text('{}\n')
        source = folder / 'collection.anki2'
        db = sqlite3.connect(source)
        db.execute('create table col(models text)')
        db.execute('insert into col values (?)',
                   (json.dumps({'1': {'flds': [{'name': name} for name in FIELDS]}}),))
        db.execute('create table notes(id integer primary key,guid text,mid integer,'
                   'flds text,mod integer,usn integer)')
        values = ['train', '', raw, '', '', '', '[sound:original.mp3]',
                  '<li class="example-card">原例句</li>', '原注', '学习笔记']
        db.execute('insert into notes values (1,\'stable-guid\',1,?,1,0)',
                   ('\x1f'.join(values),))
        for table in ('cards', 'revlog', 'graves'):
            db.execute('create table ' + table + '(id integer primary key,value text)')
            db.execute('insert into ' + table + ' values (1,\'preserved\')')
        db.commit()
        db.close()
        package = self.root / 'fixture.apkg'
        with zipfile.ZipFile(package, 'w') as archive:
            archive.write(source, 'collection.anki2')
        output = self.root / 'derived'
        connections = []
        connect = sqlite3.connect

        def tracked_connect(*args, **kwargs):
            connection = connect(*args, **kwargs)
            connections.append(connection)
            return connection

        with patch.object(shared, 'INPUT', source_root), \
                patch.object(shared, 'OWN', output), \
                patch.object(shared, 'SOURCE_SHA', {year: shared.sha(package)}), \
                patch.object(shared.sqlite3, 'connect', side_effect=tracked_connect), \
                patch.object(shared, 'input_package', return_value=(package, {})):
            try:
                with redirect_stdout(io.StringIO()):
                    shared.prepare(year)
            finally:
                for connection in connections:
                    connection.close()
        with closing(sqlite3.connect(output / year / 'collection.anki2')) as derived:
            new = derived.execute('select flds from notes where id=1').fetchone()[0].split('\x1f')
            for table in ('cards', 'revlog', 'graves'):
                self.assertEqual(derived.execute('select * from ' + table).fetchall(),
                                 [(1, 'preserved')])
        self.assertEqual([new[n] for n in (0, 1, 3, 4, 5, 6, 7, 8, 9)],
                         [values[n] for n in (0, 1, 3, 4, 5, 6, 7, 8, 9)])
        return new[2]

    def test_v2_prepare_does_not_externalize_the_disclosures_again(self):
        raw = definition()
        revised = self.run_prepare(raw)
        self.assertEqual(target_bodies(revised), target_bodies(raw))
        self.assertEqual(revised, raw)

    def test_two_storage_generations_keep_the_same_native_disclosure_bodies(self):
        raw = definition() + ('<script class="anki-final-reviewed-data" '
                              'type="application/json">{ "records": [] }</script>')
        first = transform(raw, self.store, 'definition')
        self.assertEqual(target_bodies(first), target_bodies(raw))
        second = self.run_prepare(first)
        self.assertEqual(target_bodies(second), target_bodies(raw))
        self.assertEqual(second, first)
        self.assertEqual(restore(second, self.store), raw)

    def test_v1_rejects_a_legacy_lazy_target_instead_of_propagating_it(self):
        raw = '<div class="sf-report"><details class="sf-sense"><summary>释义</summary><div class="sf-panel">'
        raw += '<div class="as-lazy"><script class="as-manifest" type="application/json">{}</script></div>'
        raw += '</div></details></div>'
        with self.assertRaisesRegex(ValueError, 'lazy|inline|延迟|懒'):
            transform(raw, self.store, 'definition')

    def test_v2_prepare_rejects_a_legacy_lazy_target(self):
        raw = '<div class="sf-report"><details class="sf-pending"><summary>记录</summary>'
        raw += '<div class="as-lazy"><script class="as-manifest" type="application/json">{}</script></div></details></div>'
        with self.assertRaisesRegex(ValueError, 'lazy|inline|延迟|懒'):
            self.run_prepare(raw)

    def test_seal_rejects_an_old_prepared_lazy_body_before_expanding_media(self):
        raw = definition()
        self.run_prepare(raw)
        source_root, output, year = self.root / 'source', self.root / 'derived', 'fixture'
        folder = output / year
        bank_raw = shared.dictionary_json(())
        pin = digest(bank_raw)
        bank = {'src': '_as_' + pin[:24] + '.js', 'sha256': pin, 'literal': True}
        (output / 'shared-dictionary.json').write_text(bank_raw)
        (folder / 'new-media' / bank['src']).write_text(shared.registration(pin, bank_raw))
        proof_file = folder / 'media-proofs.jsonl'
        proof_file.write_text('')
        (folder / 'encode-report.json').write_text(json.dumps({
            'bank': bank, 'dictionary_sha256': pin, 'proof_file_sha256': shared.sha(proof_file)}))
        part = {'src': '_as_' + 'a' * 24 + '.js', 'sha256': 'a' * 64, 'count': 1}
        lazy = placeholder([part], 'detail', 1)
        stale = raw.replace(body(), lazy, 1)
        with closing(sqlite3.connect(folder / 'collection.anki2')) as db:
            fields = db.execute('select flds from notes where id=1').fetchone()[0].split('\x1f')
            fields[2] = stale
            db.execute('update notes set flds=? where id=1', ('\x1f'.join(fields),))
            db.commit()
        package = self.root / 'fixture.apkg'
        connections = []
        connect = sqlite3.connect

        def tracked_connect(*args, **kwargs):
            connection = connect(*args, **kwargs)
            connections.append(connection)
            return connection

        with patch.object(shared, 'INPUT', source_root), \
                patch.object(shared, 'OWN', output), \
                patch.object(shared, 'SOURCE_SHA', {year: shared.sha(package)}), \
                patch.object(shared.sqlite3, 'connect', side_effect=tracked_connect), \
                patch.object(shared, 'input_package', return_value=(package, {})):
            try:
                with self.assertRaisesRegex(ValueError, 'inline disclosures must be prepared again'):
                    shared.seal(year)
            finally:
                for connection in connections:
                    connection.close()


if __name__ == '__main__':
    unittest.main()
