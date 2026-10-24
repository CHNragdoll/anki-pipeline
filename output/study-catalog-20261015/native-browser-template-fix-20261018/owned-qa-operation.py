from pathlib import Path
import copy,hashlib,json,os,shutil,sqlite3,subprocess,sys,tempfile,time
BASE=Path('/Users/apple/Library/Application Support/AnkiStudyCatalog/service-runtime/native-authored-filter-v4-9o9w56zb')
PROFILE=BASE/'native-v4-2026-gui-eaygla6f/User 1'
FLAGS=BASE/'native-editor-flags-QA-only-1i5o5ccf'
MID=1552983369
def save(path,value):
    with path.open('x') as f:json.dump(value,f,ensure_ascii=False,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def rows():
    result={}
    with sqlite3.connect((PROFILE/'collection.anki2').as_uri()+'?mode=ro',uri=True) as db:
        for table in ('notes','cards','revlog'):
            h=hashlib.sha256();n=0
            for row in db.execute('select * from '+table+' order by id'):
                h.update((json.dumps(row,ensure_ascii=False,separators=(',',':'))+'\n').encode());n+=1
            result[table]={'rows':n,'sha256':h.hexdigest()}
    return result
assert not [s for s in subprocess.check_output(['ps','-axo','command='],text=True).splitlines() if s.strip().startswith('/Applications/Anki.app/Contents/MacOS/Anki ')]
opened=subprocess.run(['/usr/sbin/lsof','-nP','--',str(PROFILE/'collection.anki2')],capture_output=True,text=True)
assert opened.returncode==1 and not opened.stdout.strip()
backup=json.loads((FLAGS/'BACKUP.json').read_text())
assert sha(Path(backup['archive']))==backup['archive_sha256']
original=json.loads((FLAGS/'MODEL_BEFORE.json').read_text())
flags=json.loads((FLAGS/'MODEL_AFTER.json').read_text())
protected=rows();assert protected==json.loads((FLAGS/'PROTECTED_ROWS_BEFORE.json').read_text())
stage=Path(tempfile.mkdtemp(prefix='native-browser-format-QA-only-',dir=BASE));os.chmod(stage,0o700)
shutil.copyfile(__file__,stage/'operation.py')
save(stage/'SCOPE.json',{'profile':str(PROFILE),'model_id':MID,'operation_sha256':sha(Path(__file__)),'full_recovery_backup':backup,'only_changes':['restore original field display flags','set browser-specific question and answer only'],'normal_preview_changes':False,'production_or_PG_changes':False})
sys.path.insert(0,'/Applications/Anki.app/Contents/Resources/app_packages')
from anki.collection import Collection
col=Collection(str(PROFILE/'collection.anki2'))
try:
    current=col.models.get(MID);assert current==flags
    changed=copy.deepcopy(current);changed['flds']=copy.deepcopy(original['flds'])
    assert original['sortf']==0 and original['flds'][0]['name']=='Word'
    for old,new in zip(original['tmpls'],changed['tmpls']):
        assert old['bqfmt']==old['bafmt']==''
        new['bqfmt']='{{text:Word}}';new['bafmt']='条目：{{text:Word}}'
    save(stage/'MODEL_BEFORE.json',current)
    samples=list(col.find_notes('abide'))+list(col.find_notes('venture'))
    selected=[1791119707352]+[nid for nid in samples if col.get_note(nid).fields[0] in ('venture','abide')]
    selected=list(dict.fromkeys(selected));assert len(selected)>=2
    baseline={}
    for nid in selected:
        n=col.get_note(nid);c=n.cards()[0]
        baseline[nid]={'fields':list(n.fields),'normal':(c.question(reload=True),c.answer())}
    col.models.save(changed);col.models._clear_cache()
    actual=col.models.get(MID);assert actual['flds']==original['flds']
    for old,new in zip(original['tmpls'],actual['tmpls']):
        assert {k:v for k,v in old.items() if k not in ('bqfmt','bafmt')}=={k:v for k,v in new.items() if k not in ('bqfmt','bafmt')}
    col._backend.set_active_browser_columns(['question','answer'])
    results=[]
    for nid in selected:
        n=col.get_note(nid);c=n.cards()[0];start=time.monotonic()
        cells=[cell.text for cell in col._backend.browser_row_for_id(c.id).cells]
        elapsed=time.monotonic()-start
        assert cells==[n.fields[0],'条目：'+n.fields[0]],cells
        assert n.fields==baseline[nid]['fields']
        assert (c.question(reload=True),c.answer())==baseline[nid]['normal']
        results.append({'note_id':nid,'word':n.fields[0],'table_cells':cells,'backend_row_seconds':elapsed,'normal_question_answer_byte_exact':True,'fields_byte_exact':True})
    save(stage/'MODEL_AFTER.json',actual)
finally:col.close()
post=rows();assert protected==post
result={'schema':'owned-native-browser-format-result.v1','stage':str(stage),'QA_only':True,'original_field_flags_restored':True,'normal_templates_css_exact':True,'all_notes_cards_revlog_rows_exact':True,'protected_rows':post,'samples':results,'UI_acceptance':'PENDING','AX_crash_fix_proven':False,'backup':str(FLAGS/'BACKUP.json')}
save(stage/'RESULT.json',result);save(BASE/'2026/BROWSER_FORMAT_PROTOTYPE.json',result)
print(json.dumps(result,ensure_ascii=False),flush=True)
