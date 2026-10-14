"""Render both native review and browser faces in a disposable sample library."""
import sys,json,html,tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,'/Applications/Anki.app/Contents/Resources/app_packages')
from anki.collection import Collection
from anki.import_export_pb2 import ImportAnkiPackageOptions,ImportAnkiPackageRequest
from anki_pipeline.inline_disclosures import restore_definition_disclosures
from scripts.build_inline_disclosure_delivery import OWN,sha,save,SAMPLE_WORDS
folder=OWN/'2027-sample'; report=json.loads((folder/'build-report.json').read_text()); qa=folder/'native-browser-qa';qa.mkdir(exist_ok=False)
assert sha(report['output']) == report['sha256'] and report['cards'] == 2
with tempfile.TemporaryDirectory(prefix='anki-inline-browser-') as tmp:
    col=Collection(str(Path(tmp)/'collection.anki2'))
    try:
        col.import_anki_package(ImportAnkiPackageRequest(package_path=report['output'],options=ImportAnkiPackageOptions(with_scheduling=True)))
        assert col.note_count() == col.card_count() == 2
        proofs=[]
        for cid in col.db.list('select id from cards order by id'):
            card=col.get_card(cid); note=card.note(); word=note['Word']; model=note.note_type()
            bodies={}
            for mode in ('review','browser'):
                rendered=card.render_output(reload=True,browser=mode=='browser')
                for face,body in (('question',rendered.question_and_style()),('answer',rendered.answer_and_style())):
                    document='<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+html.escape(word+' '+mode+' '+face)+'</title><style>'+model['css']+'</style></head><body class="card">'+body+'</body></html>'
                    path=qa/(word+'-'+mode+'-'+face+'.html');path.write_text(document)
                    if face=='answer':
                        assert restore_definition_disclosures(body,note['Definition']).html==body
                        bodies[mode]=body
                    proofs.append({'word':word,'mode':mode,'face':face,'file':str(path),'sha256':sha(path)})
            assert bodies['review']==bodies['browser']
    finally:
        col.close()
assert {row['word'] for row in proofs} == SAMPLE_WORDS
assert sha(report['output']) == report['sha256']
for path in (folder/'native-qa').iterdir():
    if path.suffix not in ('.html',):
        import shutil
        shutil.copyfile(path,qa/path.name)
save(folder/'native-browser-verification.json',{'package_sha256':report['sha256'],'review_browser_answers_byte_identical':True,'both_disclosure_bodies_inline_without_javascript':True,'samples':proofs,'actual_user_profile_modified':False,'phone_verified':False})
print('PASS review/browser native renders and inline bodies; 8 faces exported')
