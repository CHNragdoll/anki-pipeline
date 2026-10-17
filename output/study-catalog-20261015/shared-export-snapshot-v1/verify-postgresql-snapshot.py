import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import zipfile
from unittest.mock import patch

from anki_pipeline import study_catalog as c
from anki_pipeline import study_catalog_export as ex
from anki_pipeline import study_catalog_presentation as presentation
from anki_pipeline.study_catalog_books import create_book
from tests.test_study_catalog_export import CatalogExportTests


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if not os.environ.get('ANKI_STUDY_TEST_DSN'):
        raise RuntimeError('explicit isolated test DSN required')
    result_dir=Path(tempfile.mkdtemp(prefix='study-export-batch-pg-20261017-'))
    case=CatalogExportTests(methodName='test_standalone_apkg_export_retains_all_original_member_bytes')
    case.setUp()
    try:
        assert case.target.schema.startswith('testcatalog_')
        presentation.install(case.target)
        create_book(case.target, {'schema':'study-book-map.v1','id':'three','title':'Mapped third book','edition':2028,
                                  'units':[{'name':'Unit 01','words':[{'word':'train','from_book':'one'}]}]})
        with c.connect(case.target,readonly=True) as db:
            component=db.execute("select c.id from components c join words w on w.id=c.word_id where w.surface='train' and c.name='SimpleDefinition'").fetchone()[0]
            before_revision=db.execute('select coalesce(max(id),0) from events').fetchone()[0]
        requests=[{'book_id':book,'format':fmt,'name':book+('.apkg' if fmt=='apkg' else '-web')}
                  for book in ('one','two','three') for fmt in ('apkg','web')]
        destination=case.root/'batch'
        calls=[]
        changed=False
        original=ex._export_projected
        def between_outputs(db, book, *args, **kwargs):
            nonlocal changed
            row=db.execute('show transaction_isolation').fetchone()[0]
            read_only=db.execute('show transaction_read_only').fetchone()[0]
            revision=db.execute('select coalesce(max(id),0) from events').fetchone()[0]
            calls.append({'connection':id(db),'book':book['id'],'revision':revision,'isolation':row,'read_only':read_only})
            value=original(db,book,*args,**kwargs)
            if not changed:
                changed=True
                c.edit_component(case.target,component,'并发修订后的释义',expected='训练',reason='isolated batch snapshot test',backups=case.root/'writer-backups')
            return value
        started=time.monotonic()
        with patch.object(ex,'_export_projected',side_effect=between_outputs):
            report=ex.export_batch(case.target,requests,destination)
        assert len(calls)==6, calls
        assert len({row['connection'] for row in calls})==1, calls
        assert all(row['revision']==before_revision and row['isolation']=='repeatable read' and row['read_only']=='on' for row in calls), calls
        evidence=[]
        for request in requests:
            path=destination/request['name']
            if request['format']=='apkg':
                with zipfile.ZipFile(path) as archive:
                    db=sqlite3.connect(':memory:')
                    try:
                        db.deserialize(archive.read('collection.anki2'))
                        fields=db.execute("select flds from notes where sfld='train'").fetchone()[0].split('\x1f')
                    finally:
                        db.close()
                assert fields[3]=='训练', fields[3]
                evidence.append({'name':request['name'],'sha256':sha(path),'definition':'original snapshot'})
            else:
                catalog=json.loads((path/'catalog.json').read_text())
                card=next(card for card in catalog['cards'] if card['word']=='train')
                raw=(path/card['url']).read_text()
                assert '训练' in raw and '并发修订后的释义' not in raw
                evidence.append({'name':request['name'],'catalog_sha256':sha(path/'catalog.json'),'definition':'original snapshot'})
        assert (destination/'manifest.json').is_file() and (destination/'COMPLETE.json').is_file()
        with c.connect(case.target,readonly=True) as db:
            after_revision=db.execute('select coalesce(max(id),0) from events').fetchone()[0]
        assert after_revision>before_revision
        fresh=case.root/'fresh.apkg'
        ex.export_book(case.target,'one',fresh)
        with zipfile.ZipFile(fresh) as archive:
            db=sqlite3.connect(':memory:')
            try:
                db.deserialize(archive.read('collection.anki2'))
                fields=db.execute("select flds from notes where sfld='train'").fetchone()[0].split('\x1f')
            finally:db.close()
        assert fields[3]=='并发修订后的释义'
        result={'schema':'study-export-batch-pg-review.v1','ok':True,'scope':'new random isolated schema only; no formal catalog, service or native collection writes',
                'calls':[{key:value for key,value in row.items() if key!='connection'} for row in calls],
                'one_connection':True,'before_revision':before_revision,'after_revision':after_revision,
                'six_outputs_keep_before_snapshot':evidence,'fresh_single_export_sees_committed_revision':True,
                'batch_manifest_sha256':sha(destination/'manifest.json'),'batch_complete_sha256':sha(destination/'COMPLETE.json'),
                'source_sha256':sha(Path(ex.__file__)),'seconds':round(time.monotonic()-started,3)}
        (result_dir/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps({'ok':True,'result':str(result_dir/'result.json'),'seconds':result['seconds']},ensure_ascii=False))
    finally:
        case.tearDown()

if __name__=='__main__':main()
