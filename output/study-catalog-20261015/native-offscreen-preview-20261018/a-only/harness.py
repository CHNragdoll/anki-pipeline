import os, sys, json, time, hashlib, pathlib, subprocess, signal, sqlite3, ctypes, threading, traceback
STAGE = pathlib.Path(__file__).resolve().parent
APP = pathlib.Path('/Applications/Anki.app/Contents/Resources/app_packages')
SOURCE = pathlib.Path('/Users/apple/Library/Application Support/AnkiStudyCatalog/service-runtime/native-authored-filter-v4-9o9w56zb/native-full-QA-index-control-ov8yctem/collection.anki2')
TARGET = 1791119704960
START = float(os.environ.get('STUDY_OFFSCREEN_START', time.monotonic()))
def emit(event, **values):
    row = dict(event=event, elapsed_ms=round((time.monotonic()-START)*1000), pid=os.getpid(), thread=threading.current_thread().name, **values)
    fd = os.open(STAGE/'events.jsonl', os.O_WRONLY|os.O_APPEND|os.O_CREAT, 0o600)
    try: os.write(fd, (json.dumps(row, ensure_ascii=False, default=str)+'\n').encode())
    finally: os.close(fd)
def digest(path):
    h=hashlib.sha256()
    with open(path, 'rb') as f:
        while part:=f.read(1024*1024): h.update(part)
    st=path.stat()
    return dict(path=str(path), sha256=h.hexdigest(), bytes=st.st_size, inode=st.st_ino, device=st.st_dev, mtime_ns=st.st_mtime_ns)
def fields(path, immutable=False):
    con=sqlite3.connect(path.as_uri()+'?mode=ro'+('&immutable=1' if immutable else ''), uri=True, timeout=2)
    try:
        out={'notes':con.execute('select count(*) from notes').fetchone()[0], 'rows':[]}
        for nid,mid,mod,flds in con.execute('select id,mid,mod,flds from notes where id in (?,?) order by id',(1791119704960,TARGET)):
            parts=flds.split('\x1f')
            out['rows'].append(dict(nid=nid, mid=mid, mod=mod, word=parts[0], fields=[dict(bytes=len(v.encode()),sha256=hashlib.sha256(v.encode()).hexdigest()) for v in parts]))
        return out
    finally: con.close()
def addon():
    import aqt
    from aqt import gui_hooks
    from aqt.qt import QTimer, QApplication, qInstallMessageHandler
    from aqt.webview import AnkiWebPage
    from aqt.editor_legacy import Editor
    from aqt.browser.previewer import Previewer
    from anki.notes import Note
    from anki.collection import Collection
    assert QApplication.platformName()=='offscreen', 'refuse non-offscreen platform'
    emit('addon_loaded',platform=QApplication.platformName())
    qInstallMessageHandler(lambda typ,ctx,msg:emit('qt_message',level=str(typ),message=msg))
    previous=AnkiWebPage.javaScriptConsoleMessage
    def console(self,level,msg,line,src):
        emit('js_console',level=str(level),message=msg[:2000],line=line,source=src)
        return previous(self,level,msg,line,src)
    AnkiWebPage.javaScriptConsoleMessage=console
    def trace(cls,name,note_arg=False):
        original=getattr(cls,name)
        def wrapped(self,*args,**kwargs):
            note=args[0] if note_arg and args else (self if isinstance(self,Note) else getattr(self,'note',None))
            info=dict(method=cls.__name__+'.'+name,nid=getattr(note,'id',None));stamp=time.monotonic();emit('native_begin',**info)
            try:
                result=original(self,*args,**kwargs);emit('native_end',duration_ms=round((time.monotonic()-stamp)*1000),**info);return result
            except BaseException as e:emit('native_error',error=repr(e),**info);raise
        setattr(cls,name,wrapped)
    for cls,name,arg in [(Note,'fields_check',False),(Collection,'update_note',True),(Editor,'loadNote',False),(Editor,'_save_current_note',False),(Previewer,'_render_scheduled',False)]:trace(cls,name,arg)
    holders={'browser':None,'phase':'editor','front':None,'flip_ms':None}
    snapshot_js="""(()=>{const d=document;return {owner:window.StudyCompiledNative?.snapshot?.()||null,nativeVersion:window.StudyCompiledNative?.version||null,word:(d.querySelector('.vocab-word,.word-title,.word-text,.word,h1')?.textContent||'').trim().slice(0,80),native:[...d.querySelectorAll('[data-native-state]')].slice(0,5).map(n=>({tag:n.tagName,state:n.getAttribute('data-native-state')})),anchor:[...d.querySelectorAll('[data-study-native-owner]')].slice(0,2).map(n=>({state:n.dataset.studyNativeState,generation:n.dataset.studyNativeGeneration})),status:[...d.querySelectorAll('[data-study-native-status],[role=alert],[role=status],.sf-preview-count')].slice(0,6).map(n=>(n.textContent||'').slice(0,240)),selectors:Object.fromEntries(['[data-study-native-owner]','.sf-panel','.sf-example','.sf-sense','details','iframe'].map(q=>[q,d.querySelectorAll(q).length]))}})()"""
    def finish(status,**details):
        if holders['phase']=='terminal':return
        holders['phase']='terminal';value=dict(status=status,elapsed_ms=round((time.monotonic()-START)*1000),front=holders['front'],flip_ms=holders['flip_ms'],**details)
        emit('terminal',**value)
        temp=STAGE/'TERMINAL.partial.json';temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
        os.link(temp,STAGE/'TERMINAL.json');temp.unlink()
    def poll():
        phase=holders['phase'];b=holders['browser'];pv=b._previewer
        if phase not in ('front','back'):return
        if not pv or not pv._web or not b.card or b.card.nid!=TARGET:return finish('ERROR',error='native Preview/card identity changed')
        def got(value):
            if holders['phase']!=phase:return
            emit('preview_snapshot',phase=phase,state=pv.state(),nid=b.card.nid,data=value)
            if not isinstance(value,dict):return finish('ERROR',error='invalid preview snapshot')
            owner=value.get('owner') or {};native=value.get('native') or [];anchors=value.get('anchor') or []
            if owner.get('state')=='failed' or any(n.get('state')=='failed' for n in native+anchors):return finish('ERROR',error='actual native owner/payload failed',snapshot=value)
            expected_answer=phase=='back';expected_state='answer' if expected_answer else 'question'
            ready=owner.get('ready') is True and owner.get('state')=='ready' and owner.get('answer') is expected_answer and value.get('word')=='a' and pv.state()==expected_state
            if ready and phase=='front':
                if not isinstance(owner.get('id'),str) or not owner['id'] or not isinstance(owner.get('generation'),int):return finish('ERROR',error='invalid front owner identity')
                holders['front']={'owner':owner,'elapsed_ms':round((time.monotonic()-START)*1000),'snapshot':value};holders['phase']='back'
                holders['flip_ms']=round((time.monotonic()-START)*1000);emit('preview_flip_requested',front_owner=owner)
                pv._on_next();QTimer.singleShot(200,poll);return
            if ready and phase=='back':
                front=holders['front']['owner']
                if owner.get('id')!=front['id'] or not isinstance(owner.get('generation'),int) or owner['generation']<=front['generation']:return finish('ERROR',error='back owner identity/generation differs')
                return finish('READY',snapshot=value,back_wait_ms=round((time.monotonic()-START)*1000)-holders['flip_ms'])
            QTimer.singleShot(200,poll)
        pv._web.evalWithCallback(snapshot_js,got)
    def preview():
        b=holders['browser'];b.onTogglePreview();holders['phase']='front';emit('preview_open');QTimer.singleShot(200,poll)
    def loaded(e):
        nid=getattr(getattr(e,'note',None),'id',None);emit('editor_load_callback',nid=nid,editor=type(e).__name__)
        if holders['phase']=='editor' and nid==TARGET:
            holders['phase']='save'
            def save():
                emit('save_requested',nid=nid)
                e.call_after_note_saved(lambda:(emit('save_callback',nid=nid),QTimer.singleShot(500,preview)))
            QTimer.singleShot(500,save)
    gui_hooks.editor_did_load_note.append(loaded)
    gui_hooks.browser_did_change_row.append(lambda b:emit('browser_row',nid=b.card.nid if b.card else None,editor=type(b.editor).__name__))
    gui_hooks.browser_did_search.append(lambda ctx:emit('browser_search_done'))
    timer=QTimer();timer.setInterval(1000);timer.timeout.connect(lambda:emit('event_loop_tick'));timer.start();holders['timer']=timer
    def opened():
        emit('profile_open',base=aqt.mw.pm.base,notes=aqt.mw.col.db.scalar('select count(*) from notes'))
        def browse():
            emit('browse_a_requested',nid=TARGET)
            holders['browser']=aqt.dialogs.open('Browser',aqt.mw,search=('nid:'+str(TARGET),))
            emit('browse_open_returned',editor=type(holders['browser'].editor).__name__)
        QTimer.singleShot(500,browse)
    gui_hooks.profile_did_open.append(opened)
    globals()['_diagnostic_holders']=holders

def child():
    sys.path.insert(0,str(APP))
    import aqt
    from anki.lang import set_lang
    from aqt.profiles import ProfileManager, VideoDriver
    set_lang('en_US')
    pm=ProfileManager(str(STAGE/'base'));pm.setupMeta();pm.create('OffscreenQA');pm.load('OffscreenQA')
    pm.profile.update(autoSync=False,syncKey=None,numBackups=0)
    pm.meta.update(defaultLang='en_US',updates=False,firstRun=False)
    pm.set_video_driver(VideoDriver.Software);pm.save();pm.db.close()
    emit('profile_preferences_created')
    aqt._run(['/Applications/Anki.app/Contents/MacOS/Anki','-b',str(STAGE/'base'),'-p','OffscreenQA','-l','en_US'])
    emit('aqt_run_returned')

def parent():
    copy=json.loads((STAGE/'MEDIA-COPY.json').read_text())
    if copy['exit_code']!=0 or copy['timed_out']: raise RuntimeError('media clone failed')
    before=digest(SOURCE);snapshot=fields(SOURCE,True)
    if snapshot['notes']!=6682: raise RuntimeError('source count changed')
    wal=pathlib.Path(str(SOURCE)+'-wal')
    if wal.exists() and wal.stat().st_size: raise RuntimeError('nonempty source WAL')
    profile=STAGE/'base/OffscreenQA';profile.mkdir(parents=True,exist_ok=True)
    dest=profile/'collection.anki2'
    lib=ctypes.CDLL('/usr/lib/libSystem.B.dylib',use_errno=True)
    lib.clonefile.argtypes=[ctypes.c_char_p,ctypes.c_char_p,ctypes.c_int];lib.clonefile.restype=ctypes.c_int
    if lib.clonefile(os.fsencode(SOURCE),os.fsencode(dest),0): raise OSError(ctypes.get_errno(),'clonefile failed')
    cloned=digest(dest)
    if before['sha256']!=cloned['sha256'] or before['inode']==cloned['inode']: raise RuntimeError('clone identity mismatch')
    raw=SOURCE.parent.parent/'2026/collection.anki2'
    rawstat=raw.stat()
    con=sqlite3.connect(raw.as_uri()+'?mode=ro&immutable=1',uri=True)
    try: original_a=con.execute('select mid,flds from notes where id=?',(1791119704960,)).fetchone()
    finally: con.close()
    if original_a is None or len(original_a[1].split('\x1f'))!=10: raise RuntimeError('original a unavailable')
    own=sqlite3.connect(dest)
    try:
        changed=own.execute('update notes set flds=? where id=? and mid=?',(original_a[1],1791119704960,original_a[0])).rowcount
        if changed!=1: raise RuntimeError('clone a identity mismatch')
        own.commit()
    finally: own.close()
    setup=dict(path=str(raw),source_stat=dict(inode=rawstat.st_ino,bytes=rawstat.st_size,mtime_ns=rawstat.st_mtime_ns),nid=1791119704960,column='flds',sha256=hashlib.sha256(original_a[1].encode()).hexdigest(),bytes=len(original_a[1].encode()),fields=10,only_owned_clone_modified=True)
    clone_fields=fields(dest)
    (profile/'collection.media').mkdir(exist_ok=True)
    if not (STAGE/'MEDIA-COPY.json').exists(): raise RuntimeError('media clone not recorded')
    ad=STAGE/'base/addons21/987654321';ad.mkdir(parents=True)
    ad.joinpath('__init__.py').write_text('import runpy\nrunpy.run_path('+repr(str(STAGE/'harness.py'))+',run_name="__anki_offscreen_addon__")\n')
    ad.joinpath('meta.json').write_text('{"name":"Owned Offscreen Diagnostic","disabled":false}')
    apppins={str(p.relative_to(APP)):digest(p) for p in [APP/'aqt/__init__.pyc',APP/'aqt/browser/browser.pyc',APP/'aqt/editor.pyc',APP/'aqt/editor_legacy.pyc',APP/'aqt/browser/previewer.pyc',APP/'anki/notes.pyc',APP/'anki/collection.pyc',APP/'_aqt/hooks.pyc',APP/'aqt/mediasrv.pyc',APP/'_aqt/data/web/js/editor.js',APP/'_aqt/data/web/js/reviewer.js',APP/'anki/buildinfo.pyc',APP/'_aqt/data/web/sveltekit/_app/immutable/nodes/8.B4uzZOEE.mjs']}
    env=os.environ.copy();selected={'QT_QPA_PLATFORM':'offscreen','QTWEBENGINE_CHROMIUM_FLAGS':'--disable-gpu','ANKI_SINGLE_INSTANCE_KEY':'anki-offscreen-'+STAGE.name,'PYTHONDONTWRITEBYTECODE':'1','PYTHONUNBUFFERED':'1','STUDY_OFFSCREEN_START':str(time.monotonic())}
    env.update(selected)
    inputs=dict(media_copy=copy,source=before,source_fields=snapshot,clone_before=cloned,setup_mutation=setup,clone_fields_before_launch=clone_fields,app_pins=apppins,env=selected,timeout_seconds=45,script=digest(STAGE/'harness.py'),python_version=sys.version,app_version='26.09.3 (29bb700b)',offscreen_plugin=digest(APP/'PyQt6/Qt6/plugins/platforms/libqoffscreen.dylib'))
    (STAGE/'INPUTS.json').write_text(json.dumps(inputs,ensure_ascii=False,indent=2)+'\n')
    started=time.monotonic();timed_out=False;termination_reason='process_exit'
    with open(STAGE/'stdout.log','wb') as out,open(STAGE/'stderr.log','wb') as err:
        proc=subprocess.Popen([sys.executable,'-B',str(STAGE/'harness.py'),'--child'],env=env,stdout=out,stderr=err,start_new_session=True,cwd=STAGE)
        (STAGE/'PROCESS.json').write_text(json.dumps({'pid':proc.pid,'pgid':proc.pid,'hard_timeout':45})+'\n')
        try:
            while proc.poll() is None:
                if (STAGE/'TERMINAL.json').exists():termination_reason='terminal';break
                remaining=45-(time.monotonic()-started)
                if remaining<=0:timed_out=True;termination_reason='hard_timeout';break
                try:proc.wait(timeout=min(.1,remaining))
                except subprocess.TimeoutExpired:pass
        finally:
            try: os.killpg(proc.pid,signal.SIGKILL)
            except ProcessLookupError: pass
            proc.wait(timeout=5)
    result=dict(exit_code=proc.returncode,timed_out=timed_out,termination_reason=termination_reason,elapsed_seconds=round(time.monotonic()-started,3),source_after=digest(SOURCE),clone_after=digest(dest))
    result['source_unchanged']=before==result['source_after']
    try: result['clone_fields_after']=fields(dest)
    except Exception as e: result['clone_fields_error']=repr(e)
    (STAGE/'RESULT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'stage':str(STAGE),'exit_code':proc.returncode,'timed_out':timed_out,'source_unchanged':result['source_unchanged']}))
if __name__=='__anki_offscreen_addon__': addon()
elif __name__=='__main__':
    if sys.argv[1:] == ['--child']: child()
    elif not sys.argv[1:]: parent()
    else: raise SystemExit('no unknown arguments')
