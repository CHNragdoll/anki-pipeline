"""Shared guide finalization retains published identities and source data."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import zipfile

from anki_pipeline.study_exam_guide import add_guide, guide_identity, GuideIdentity, GuideCollisionError
from scripts import add_politics_guide as politics


class SharedExamGuideTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.fixture('考研408历年真题', 3)
        self.original = self.source.read_bytes()

    def fixture(self, root, count):
        path = self.root / 'source.sqlite'
        with closing(sqlite3.connect(path)) as db:
            db.execute('CREATE TABLE col(models text, decks text, extra text)')
            db.execute('CREATE TABLE notes(id integer primary key,guid text,mid integer,mod integer,usn integer,tags text,flds text,sfld text,csum integer,flags integer,data text)')
            db.execute('CREATE TABLE cards(id integer primary key,nid integer,did integer,ord integer,mod integer,usn integer,type integer,queue integer,due integer,ivl integer,factor integer,reps integer,lapses integer,left integer,odue integer,odid integer,flags integer,data text)')
            db.execute('CREATE TABLE revlog(id integer primary key,cid integer)')
            db.execute('CREATE TABLE graves(usn integer,oid integer,type integer)')
            model = {'id': 1, 'name': 'exam', 'css': '.old{}', 'flds': [{'name': 'Question', 'ord': 0}],
                     'tmpls': [{'name': 'Question', 'qfmt': '{{Question}}', 'afmt': '{{Question}}', 'ord': 0}]}
            decks = {'1': {'id': 1, 'name': root + '::2025 年::综合应用题', 'conf': 1, 'daily': [5, 2]}}
            db.execute('INSERT INTO col VALUES (?,?,?)', (json.dumps({'1': model}), json.dumps(decks), 'retain'))
            for i in range(1, count + 1):
                db.execute('INSERT INTO notes VALUES (?,?,?,?,?,?,?,?,?,?,?)', (i, 'source' + str(i), 1, 5, -1, 'keep', 'Q' + str(i), 'Q', 0, 3, 'original'))
                db.execute('INSERT INTO cards VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (i, i, 1, 0, 5, -1, 2, -1, i, 32, 2500, 5, 1, 0, 0, 0, 3, 'original'))
            db.execute('INSERT INTO revlog VALUES (1,1)')
            db.execute('INSERT INTO graves VALUES (-1,999,0)')
            db.commit()
        package = self.root / 'source.apkg'
        with zipfile.ZipFile(package, 'w', compression=zipfile.ZIP_DEFLATED) as z:
            z.write(path, 'collection.anki2')
            z.writestr('media', '{"0":"figure.svg"}')
            z.writestr('0', '<svg>unchanged</svg>')
        return package

    def read(self, package):
        with zipfile.ZipFile(package) as z:
            path = self.root / ('inspect-' + package.stem + '.sqlite')
            path.write_bytes(z.read('collection.anki2'))
        return sqlite3.connect(path)

    def kwargs(self):
        return dict(book_id='cs408-exams', root='考研408历年真题', question_count=3,
                    guide_html='<section class="guide"><h1>使用说明</h1><p>综合应用题</p></section>')

    def test_book_identity_is_stable_and_independent_of_display_name(self):
        self.assertEqual(guide_identity('cs408-exams'), guide_identity('cs408-exams'))
        self.assertNotEqual(guide_identity('cs408-exams'), guide_identity('another-book'))
        output = self.root / 'final.apkg'
        report = add_guide(self.source, output, **self.kwargs())
        identity = guide_identity('cs408-exams')
        self.assertEqual(report['cards'], 4)
        self.assertEqual(report['guide_deck'], '考研408历年真题::00 使用说明')
        with closing(self.read(output)) as db:
            self.assertEqual(db.execute('SELECT guid,mid FROM notes WHERE id=?', (identity.note_id,)).fetchone(), (identity.guid, identity.model_id))
            self.assertEqual(db.execute('SELECT extra FROM col').fetchone()[0], 'retain')
            self.assertEqual(db.execute('SELECT queue,ivl,reps,flags,data FROM cards WHERE id=1').fetchone(), (-1, 32, 5, 3, 'original'))
        self.assertEqual(self.source.read_bytes(), self.original)
        with zipfile.ZipFile(self.source) as old, zipfile.ZipFile(output) as new:
            for name in ('0', 'media'):
                self.assertEqual(old.read(name), new.read(name))

    def test_wrong_count_overwrite_duplicate_and_collision_refused(self):
        output = self.root / 'bad.apkg'
        bad = self.kwargs();bad['question_count'] = 2
        with self.assertRaisesRegex(ValueError, 'count'):
            add_guide(self.source, output, **bad)
        self.assertFalse(output.exists())
        add_guide(self.source, output, **self.kwargs())
        with self.assertRaises(ValueError):
            add_guide(self.source, output, **self.kwargs())
        with self.assertRaises(GuideCollisionError):
            add_guide(output, self.root / 'duplicate.apkg', **self.kwargs())
        self.assertFalse((self.root / 'duplicate.apkg').exists())
        with self.assertRaises(GuideCollisionError):
            add_guide(self.source, self.root / 'collision.apkg', **self.kwargs(), identity=GuideIdentity('new', 20, 21, 22, 1))
        self.assertFalse((self.root / 'collision.apkg').exists())
        self.assertFalse(list(self.root.glob('.exam-guide-*')))

    def test_politics_wrapper_retains_all_original_constants_body_and_css(self):
        self.assertEqual((politics.GUID, politics.MODEL_ID, politics.DECK_ID, politics.NOTE_ID, politics.CARD_ID),
                         ('PolGuide01', 1911002001, 1911002002, 1793548800001, 1793548800002))
        self.assertIn('2003—2024 年 · 832 道真题', politics.BODY)
        self.assertIn('完整包共 833 张卡', politics.BODY)
        self.assertIn('.nightMode.card{background:#151a22;color:#e1e7f0}', politics.CSS)

    def test_modern_decoy_and_broken_destination_symlink_are_rejected(self):
        modern = self.root / 'modern.apkg'
        with zipfile.ZipFile(self.source) as original, zipfile.ZipFile(modern, 'w') as output:
            for member in original.infolist():
                output.writestr(member.filename, original.read(member))
            output.writestr('collection.anki21b', 'modern collection')
        with self.assertRaisesRegex(ValueError, 'legacy APKG'):
            add_guide(modern, self.root / 'modern-final.apkg', **self.kwargs())
        self.assertFalse((self.root / 'modern-final.apkg').exists())
        broken = self.root / 'broken.apkg'
        broken.symlink_to(self.root / 'absent')
        with self.assertRaises(ValueError):
            add_guide(self.source, broken, **self.kwargs())
        self.assertTrue(broken.is_symlink())

    def test_single_field_and_safe_identity_constraints(self):
        for book in ('', ' x', 'x\x00', 'x\n'):
            with self.assertRaises(ValueError):guide_identity(book)
        for field, value in [('root', 'x::y'), ('guide_html', 'bad\x1ffield'), ('question_count', True)]:
            values = self.kwargs();values[field] = value
            with self.assertRaises(ValueError):add_guide(self.source, self.root / 'invalid.apkg', **values)
        self.assertEqual(self.source.read_bytes(), self.original)


if __name__ == '__main__':
    unittest.main()
