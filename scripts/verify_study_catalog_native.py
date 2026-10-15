"""Verify master-generated packages in a disposable native Anki collection.

Never accepts a user collection/profile path. Source and candidate packages are
read-only; reviewed/suspended/flagged study state exists only in TemporaryDirectory.
Native NFC normalization is reported separately from exact field and media bytes.
ZIP member parity and browser/phone display checks are outside this command.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import time
import unicodedata
import zipfile


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def compare_fields(guid, expected, actual):
    """Accept only exact text or Anki's NFC normalization, per field value."""
    if actual is None:
        raise ValueError('native note missing for GUID '+guid)
    expected_fields=expected.split('\x1f');actual_fields=actual.split('\x1f')
    if len(expected_fields)!=len(actual_fields):
        raise ValueError('native field count differs for GUID '+guid)
    counts={'values_checked':len(expected_fields),'values_raw_equal':0,'values_nfc_normalized':0}
    for index,(original,imported) in enumerate(zip(expected_fields,actual_fields)):
        if imported==original:
            counts['values_raw_equal']+=1
        elif imported==unicodedata.normalize('NFC',original):
            counts['values_nfc_normalized']+=1
        else:
            offset=next((i for i,(a,b) in enumerate(zip(imported,original)) if a!=b),min(len(imported),len(original)))
            raise ValueError('native field differs for GUID '+guid+', field '+str(index)+' at '+str(offset))
    return counts


def verify(source,candidate,report):
    report=Path(report)
    if report.exists():raise FileExistsError('native evidence must be a new output')
    # Native modules ship with the installed application, independently of the
    # Python generator. This is a local acceptance command, not a dependency.
    sys.path.insert(0,'/Applications/Anki.app/Contents/Resources/app_packages')
    from anki.collection import Collection
    from anki.import_export_pb2 import ImportAnkiPackageOptions,ImportAnkiPackageRequest
    before={str(p):sha(p) for p in (source,candidate)};started=time.monotonic()
    field_evidence={'notes_checked':0,'notes_raw_equal':0,'notes_nfc_normalized':0,
                    'values_checked':0,'values_raw_equal':0,'values_nfc_normalized':0}
    with tempfile.TemporaryDirectory(prefix='study-native-qa-') as folder:
        col=Collection(str(Path(folder)/'collection.anki2'))
        try:
            def load(path):
                col.import_anki_package(ImportAnkiPackageRequest(package_path=str(Path(path).resolve()),
                    options=ImportAnkiPackageOptions(with_scheduling=True)))
                col.models._clear_cache()
            def identities():return col.db.all('select id,guid,mid from notes order by id')
            def states():
                fields=[r[1] for r in col.db.all('pragma table_info(cards)')]
                keep=[i for i,name in enumerate(fields) if name not in {'mod','usn'}]
                return [[r[i] for i in keep] for r in col.db.all('select * from cards order by id')]
            load(source);notes=col.note_count();cards=col.card_count()
            cid=col.db.scalar('select id from cards where type=0 and queue>=0 order by id limit 1')
            if cid is None:raise ValueError('acceptance source needs one fresh test card')
            col.decks.select(col.get_card(cid).did);col.sched.reset()
            queued=col.sched.get_queued_cards(fetch_limit=1).cards[0]
            reviewed=col.get_card(queued.card.id);reviewed.start_timer()
            col.sched.answer_card(col.sched.build_answer(card=reviewed,states=queued.states,rating=3))
            col.sched.suspend_cards([reviewed.id]);col.set_user_flag_for_cards(3,[reviewed.id])
            old_ids=identities();old_states=states();old_log=col.db.all('select * from revlog order by id')
            assert old_log
            for _ in range(2):
                load(candidate)
                assert (col.note_count(),col.card_count())==(notes,cards)
                assert identities()==old_ids and states()==old_states
                assert col.db.all('select * from revlog order by id')==old_log
            with zipfile.ZipFile(candidate) as archive:
                entry='collection.anki21' if 'collection.anki21' in archive.namelist() else 'collection.anki2'
                # Bound Python memory instead of deserializing a hundreds-of-MB
                # collection into a second in-memory database.
                expected_path=Path(folder)/'candidate-readonly.anki2'
                with archive.open(entry) as incoming,expected_path.open('wb') as target:
                    shutil.copyfileobj(incoming,target,length=1024*1024)
                raw=sqlite3.connect(expected_path.as_uri()+'?mode=ro',uri=True)
                try:
                    for guid,fields in raw.execute('select guid,flds from notes'):
                        got=col.db.scalar('select flds from notes where guid=?',guid)
                        counts=compare_fields(guid,fields,got)
                        field_evidence['notes_checked']+=1
                        field_evidence['notes_raw_equal' if got==fields else 'notes_nfc_normalized']+=1
                        for key,value in counts.items():field_evidence[key]+=value
                finally:raw.close()
                assert field_evidence['notes_checked']==notes
                media=json.loads(archive.read('media'))
                for member,name in media.items():
                    actual=Path(col.media.dir())/name
                    with archive.open(member) as stream:assert hashlib.file_digest(stream,'sha256').hexdigest()==sha(actual)
            rendered=0
            for cid in col.db.list('select id from cards order by id limit 12'):
                card=col.get_card(cid);question=card.question();answer=card.answer()
                assert isinstance(question,str) and question.strip()
                assert isinstance(answer,str) and answer.strip()
                rendered+=1
            assert not col.media.check().missing
        finally:col.close()
    assert all(sha(p)==digest for p,digest in before.items())
    result={'schema':'study-native-acceptance.v2','source':str(source),'candidate':str(candidate),
        'sha256':before,'notes':notes,'cards':cards,'duplicate_update_imports':2,
        'identity_schedule_flags_revlog_preserved':True,
        'field_verification':{**field_evidence,'all_values_exact_or_nfc':True},
        'media_verification':{'files_checked':len(media),'sha256_exact':True,'missing_count':0},
        'source_candidate_package_bytes_unchanged':True,
        'source_candidate_zip_member_parity_verified_by_this_command':False,
        'native_rendered_samples':rendered,
        'native_render_scope':'nonempty question/answer strings from Anki template renderer',
        'actual_user_profile_modified':False,'browser_visual_verified':False,'phone_verified':False,
        'elapsed_seconds':round(time.monotonic()-started,2)}
    report.parent.mkdir(parents=True,exist_ok=True)
    with report.open('x') as output:output.write(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--candidate',type=Path,required=True);parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(verify(args.source,args.candidate,args.report),ensure_ascii=False))
