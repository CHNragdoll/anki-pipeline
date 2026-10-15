"""Import and update only disposable two-card collections; export native faces."""
from __future__ import annotations
import hashlib
import html
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, '/Applications/Anki.app/Contents/Resources/app_packages')
from anki.collection import Collection
from anki.import_export_pb2 import ImportAnkiPackageOptions, ImportAnkiPackageRequest
from scripts.build_inline_disclosure_delivery import OWN, sha, save, SAMPLE_WORDS
from scripts.verify_final_apkg_native import _native_identities, _native_states
from scripts.verify_slim_apkg_native import check_exact_identities, check_exact_states


def verify():
    started = time.monotonic(); folder = OWN / '2027-sample'
    report = json.loads((folder / 'build-report.json').read_text())
    source = folder / 'source-sample.apkg'; package = Path(report['output'])
    assert sha(package) == report['sha256'] and report['cards'] == 2
    assert not (folder / 'native-verification.json').exists()
    qa = folder / 'native-qa'; qa.mkdir(exist_ok=True)
    assert not any(qa.iterdir()), 'never overwrite native acceptance faces'
    with tempfile.TemporaryDirectory(prefix='inline-disclosures-sample-') as directory:
        collection = Collection(str(Path(directory) / 'collection.anki2'))
        try:
            def load(path):
                collection.import_anki_package(ImportAnkiPackageRequest(package_path=str(path),
                    options=ImportAnkiPackageOptions(with_scheduling=True)))
                collection.models._clear_cache()
            load(source); assert collection.note_count() == collection.card_count() == 2
            cid = collection.db.scalar('select id from cards where queue>=0 and type=0 order by id limit 1')
            assert cid is not None
            collection.decks.select(collection.get_card(cid).did)
            collection.sched.reset()
            queued = collection.sched.get_queued_cards(fetch_limit=1).cards[0]
            reviewed = collection.get_card(queued.card.id); reviewed.start_timer()
            collection.sched.answer_card(collection.sched.build_answer(card=reviewed, states=queued.states, rating=3))
            collection.sched.suspend_cards([reviewed.id]); collection.set_user_flag_for_cards(3, [reviewed.id])
            identities = _native_identities(collection); states = _native_states(collection)
            revlog = collection.db.all('select * from revlog order by id')
            assert revlog
            attempts = []
            for operation in ('update', 'repeat'):
                load(package); assert collection.note_count() == collection.card_count() == 2
                check_exact_identities(identities, _native_identities(collection))
                check_exact_states(states, _native_states(collection))
                assert collection.db.all('select * from revlog order by id') == revlog
                attempts.append({'operation': operation, 'notes_cards': 2, 'identities_schedule_flags_revlog_preserved': True})
            samples = []; words = set()
            expected = __import__('sqlite3').connect(folder / 'collection.anki2')
            for guid, fields in expected.execute('select guid,flds from notes'):
                got = collection.db.first('select id,mid,flds from notes where guid=?', guid)
                assert got and got[2] == fields
                word = fields.split('\x1f')[0]; assert word in SAMPLE_WORDS; words.add(word)
                card = collection.get_card(collection.db.scalar('select id from cards where nid=?', got[0]))
                model = collection.models.get(got[1])
                for face, body in (('question', card.question()), ('answer', card.answer())):
                    document = ('<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" '
                        'content="width=device-width,initial-scale=1"><title>' + html.escape(word + ' ' + face) +
                        '</title><style>' + model['css'] + '</style></head><body class="card">' + body + '</body></html>')
                    page = qa / (word + '-' + face + '.html'); page.write_text(document)
                    samples.append({'word': word, 'face': face, 'file': str(page), 'sha256': sha(page)})
            expected.close(); assert words == SAMPLE_WORDS
            with zipfile.ZipFile(package) as archive:
                media = json.loads(archive.read('media'))
                for key, name in media.items():
                    actual = Path(collection.media.dir()) / name
                    with archive.open(key) as stream:
                        assert hashlib.file_digest(stream, 'sha256').hexdigest() == sha(actual)
                    shutil.copyfile(actual, qa / name)
            missing = collection.media.check().missing
            assert not missing, missing
        finally:
            collection.close()
    assert sha(package) == report['sha256']
    result = {'schema': 'inline-disclosure-sample-native.v1', 'package': str(package),
              'package_sha256': report['sha256'], 'cards': 2, 'attempts': attempts,
              'all_fields_match_package': True, 'all_media_byte_hashes_match': True,
              'missing_media': 0, 'samples': samples, 'actual_user_profile_modified': False,
              'phone_verified': False, 'elapsed_seconds': round(time.monotonic()-started, 2)}
    save(folder / 'native-verification.json', result); print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    verify()
