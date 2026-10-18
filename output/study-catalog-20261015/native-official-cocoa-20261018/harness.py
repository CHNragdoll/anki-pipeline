import os, sys, json, time, hashlib, pathlib, subprocess, signal, sqlite3, ctypes, threading, traceback
STAGE = pathlib.Path(__file__).resolve().parent;APP = pathlib.Path('/Applications/Anki.app/Contents/Resources/app_packages')
SOURCE = pathlib.Path('/Users/apple/Library/Application Support/AnkiStudyCatalog/service-runtime/native-authored-filter-v4-9o9w56zb/native-full-QA-index-control-ov8yctem/collection.anki2')
TARGET = 1791119704960;START = float(os.environ.get('STUDY_COCOA_START', time.monotonic()))
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
    import aqt;from aqt import gui_hooks
    from aqt.qt import QTimer, QApplication, qInstallMessageHandler, QFile, QIODevice
    from aqt.webview import AnkiWebPage;from aqt.editor_legacy import Editor
    from aqt.browser.previewer import Previewer
    from anki.notes import Note;from anki.collection import Collection
    assert QApplication.platformName()=='cocoa', 'refuse non-Cocoa platform'
    cf=ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
    cf.CFBundleGetMainBundle.restype=ctypes.c_void_p;cf.CFBundleGetIdentifier.argtypes=[ctypes.c_void_p];cf.CFBundleGetIdentifier.restype=ctypes.c_void_p
    cf.CFStringGetCString.argtypes=[ctypes.c_void_p,ctypes.c_char_p,ctypes.c_long,ctypes.c_uint32];cf.CFStringGetCString.restype=ctypes.c_bool
    ident=cf.CFBundleGetIdentifier(cf.CFBundleGetMainBundle());buf=ctypes.create_string_buffer(512)
    bundle_id=buf.value.decode() if ident and cf.CFStringGetCString(ident,buf,len(buf),0x08000100) else None
    emit('addon_loaded',platform=QApplication.platformName(),bundle_id=bundle_id,ppid=os.getppid(),pgid=os.getpgrp(),argv=sys.argv,executable=sys.executable,aqt_file=aqt.__file__)
    if bundle_id!='net.ankiweb.anki':raise RuntimeError('official Anki bundle identity not established')
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
        emit('terminal',completion=value);temp=STAGE/'TERMINAL.partial.json';temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
        os.link(temp,STAGE/'TERMINAL.json');temp.unlink()
        def close_owned():
            emit('graceful_close_requested');b=holders['browser']
            if b and b._previewer:b._previewer.close()
            aqt.mw.close()
        QTimer.singleShot(100,close_owned)
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
                if not holders.get('first_back_ready_ms'):
                    holders['first_back_ready_ms']=round((time.monotonic()-START)*1000);QTimer.singleShot(250,poll);return
                image=pv.grab()
                if image.isNull() or image.width()<10 or image.height()<10:return finish('ERROR',error='Previewer grab returned empty image')
                image_path=STAGE/'preview-a-back.png';file=QFile(str(image_path))
                if not file.open(QIODevice.OpenModeFlag.WriteOnly|QIODevice.OpenModeFlag.NewOnly):return finish('ERROR',error='screenshot destination unavailable')
                try:saved=image.save(file,'PNG')
                finally:file.close()
                if not saved:return finish('ERROR',error='Qt failed to save Previewer image')
                emit('screenshot_saved',image=digest(image_path),width=image.width(),height=image.height());return finish('READY',snapshot=value,first_back_ready_ms=holders['first_back_ready_ms'],back_wait_ms=holders['first_back_ready_ms']-holders['flip_ms'],image=digest(image_path))
            QTimer.singleShot(200,poll)
        pv._web.evalWithCallback(snapshot_js,got)
    def preview():
        b=holders['browser'];b.onTogglePreview();holders['phase']='front';emit('preview_open');QTimer.singleShot(200,poll)
    def loaded(e):
        nid=getattr(getattr(e,'note',None),'id',None);emit('editor_load_callback',nid=nid,editor=type(e).__name__)
        if holders['phase']=='editor' and nid==TARGET:
            if type(e).__name__!='Editor':return finish('ERROR',error='actual editor differs from approved legacy route')
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
        emit('profile_open',base=aqt.mw.pm.base,collection=aqt.mw.col.path,notes=aqt.mw.col.db.scalar('select count(*) from notes'),experimental_features=aqt.mw.col.get_config('experimentalFeatures'))
        if pathlib.Path(aqt.mw.pm.base).resolve()!=STAGE/'base':raise RuntimeError('private base mismatch')
        def browse():
            emit('browse_a_requested',nid=TARGET)
            holders['browser']=aqt.dialogs.open('Browser',aqt.mw,search=('nid:'+str(TARGET),))
            emit('browse_open_returned',editor=type(holders['browser'].editor).__name__)
        QTimer.singleShot(500,browse)
    gui_hooks.profile_did_open.append(opened)
    globals()['_diagnostic_holders']=holders
def setup_preferences():
    sys.path.insert(0,str(APP))
    from anki.lang import set_lang;from aqt.profiles import ProfileManager
    from aqt.qt import QCoreApplication
    if QCoreApplication.instance() is not None:raise RuntimeError('preferences setup must remain GUI-free')
    set_lang('en_US');pm=ProfileManager(str(STAGE/'base'));pm.setupMeta();pm.create('NativeQA');pm.load('NativeQA')
    pm.profile.update(autoSync=False,syncKey=None,numBackups=0)
    pm.meta.update(defaultLang='en_US',updates=False,firstRun=False);pm.save();emit('preferences_created_without_qapp',driver=str(pm.video_driver()));pm.db.close()
def prepare():
    copy=json.loads((STAGE/'MEDIA-COPY.json').read_text())
    if copy['exit_code']!=0 or copy['timed_out']: raise RuntimeError('media clone failed')
    before=digest(SOURCE);snapshot=fields(SOURCE,True)
    if before['sha256']!='abb1a62f102fe28d7e072e9720c9c2909cfe89dbed1733c1035710803b2ded30':raise RuntimeError('source SHA changed')
    if snapshot['notes']!=6682: raise RuntimeError('source count changed')
    wal=pathlib.Path(str(SOURCE)+'-wal')
    if wal.exists() and wal.stat().st_size: raise RuntimeError('nonempty source WAL')
    profile=STAGE/'base/NativeQA';profile.mkdir(parents=True,exist_ok=True)
    dest=profile/'collection.anki2';lib=ctypes.CDLL('/usr/lib/libSystem.B.dylib',use_errno=True)
    lib.clonefile.argtypes=[ctypes.c_char_p,ctypes.c_char_p,ctypes.c_int];lib.clonefile.restype=ctypes.c_int
    if lib.clonefile(os.fsencode(SOURCE),os.fsencode(dest),0): raise OSError(ctypes.get_errno(),'clonefile failed')
    cloned=digest(dest)
    if before['sha256']!=cloned['sha256'] or before['inode']==cloned['inode']: raise RuntimeError('clone identity mismatch')
    raw=SOURCE.parent.parent/'2026/collection.anki2';rawstat=raw.stat()
    con=sqlite3.connect(raw.as_uri()+'?mode=ro&immutable=1',uri=True)
    try: original_a=con.execute('select mid,flds from notes where id=?',(1791119704960,)).fetchone()
    finally: con.close()
    if original_a is None or len(original_a[1].split('\x1f'))!=10: raise RuntimeError('original a unavailable')
    if hashlib.sha256(original_a[1].encode()).hexdigest()!='82b71eb1bafedb6629c122ca8b199492b0befe8317beaafa526dc3f6bef90030':raise RuntimeError('raw a source changed')
    own=sqlite3.connect(dest)
    try:
        changed=own.execute('update notes set flds=? where id=? and mid=?',(original_a[1],1791119704960,original_a[0])).rowcount
        if changed!=1: raise RuntimeError('clone a identity mismatch')
        own.commit()
    finally: own.close()
    setup=dict(path=str(raw),source_stat=dict(inode=rawstat.st_ino,bytes=rawstat.st_size,mtime_ns=rawstat.st_mtime_ns),nid=1791119704960,column='flds',sha256=hashlib.sha256(original_a[1].encode()).hexdigest(),bytes=len(original_a[1].encode()),fields=10,only_owned_clone_modified=True)
    clone_fields=fields(dest);(profile/'collection.media').mkdir(exist_ok=True)
    if not (STAGE/'MEDIA-COPY.json').exists(): raise RuntimeError('media clone not recorded')
    ad=STAGE/'base/addons21/987654321';ad.mkdir(parents=True)
    ad.joinpath('__init__.py').write_text('import runpy\nrunpy.run_path('+repr(str(STAGE/'harness.py'))+',run_name="__anki_offscreen_addon__")\n')
    ad.joinpath('meta.json').write_text('{"name":"Owned Cocoa Diagnostic","disabled":false}');apppins={str(p.relative_to(APP)):digest(p) for p in [APP/'aqt/__init__.pyc',APP/'aqt/browser/browser.pyc',APP/'aqt/editor.pyc',APP/'aqt/editor_legacy.pyc',APP/'aqt/browser/previewer.pyc',APP/'anki/notes.pyc',APP/'anki/collection.pyc',APP/'_aqt/hooks.pyc',APP/'aqt/mediasrv.pyc',APP/'_aqt/data/web/js/editor.js',APP/'_aqt/data/web/js/reviewer.js',APP/'anki/buildinfo.pyc',APP/'_aqt/data/web/sveltekit/_app/immutable/nodes/8.B4uzZOEE.mjs']}
    setup_preferences();selected={'QT_QPA_PLATFORM':'cocoa','ANKI_SINGLE_INSTANCE_KEY':'anki-cocoa-'+STAGE.name,'PYTHONDONTWRITEBYTECODE':'1','PYTHONUNBUFFERED':'1'}
    inputs=dict(media_copy=copy,source=before,source_fields=snapshot,clone_before=cloned,setup_mutation=setup,clone_fields_before_launch=clone_fields,app_pins=apppins,env=selected,timeout_seconds=45,script=digest(STAGE/'harness.py'),python_version=sys.version,app_version='26.09.3 (29bb700b)',platform_plugin=digest(APP/'PyQt6/Qt6/plugins/platforms/libqcocoa.dylib'),official_executable=digest(pathlib.Path('/Applications/Anki.app/Contents/MacOS/Anki')),official_info=digest(pathlib.Path('/Applications/Anki.app/Contents/Info.plist')),clone_prepared=digest(dest),unset_env=['QTWEBENGINE_CHROMIUM_FLAGS','ANKI_SOFTWAREOPENGL'])
    (STAGE/'INPUTS.json').write_text(json.dumps(inputs,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'status':'PREPARED_NOT_LAUNCHED','stage':str(STAGE),'source_sha256':before['sha256']}))
def processes():
    result={}
    for line in subprocess.check_output(['/bin/ps','-axo','pid=,ppid=,pgid=,command='],text=True).splitlines():
        row=line.strip().split(None,3)
        if len(row)==4:result[int(row[0])]=dict(pid=int(row[0]),ppid=int(row[1]),pgid=int(row[2]),command=row[3])
    return result
def run():
    i=json.loads((STAGE/'INPUTS.json').read_text());dest=STAGE/'base/NativeQA/collection.anki2'
    if any((STAGE/n).exists() for n in ['PROCESS.json','RESULT.json','TERMINAL.json','preview-a-back.png']):raise RuntimeError('one shot stage already used')
    if digest(SOURCE)!=i['source'] or digest(dest)!=i['clone_prepared'] or digest(STAGE/'harness.py')!=i['script']:raise RuntimeError('source/clone/script pin changed')
    for asset in list(i['app_pins'].values())+[i['platform_plugin'],i['official_executable'],i['official_info']]:
        if digest(pathlib.Path(asset['path']))!=asset:raise RuntimeError('installed input pin changed')
    env=os.environ.copy()
    for name in i['unset_env']:env.pop(name,None)
    env.update(i['env']);started=time.monotonic();env['STUDY_COCOA_START']=str(started)
    command=[i['official_executable']['path'],'-b',str(STAGE/'base'),'-p','NativeQA','-l','en_US']
    (STAGE/'RUN-ENV.json').write_text(json.dumps(dict(command=command,env={n:env.get(n) for n in list(i['env'])+i['unset_env']}),indent=2)+'\n')
    known=set();groups=set();observed=[];timed_out=False
    with open(STAGE/'stdout.log','wb') as out,open(STAGE/'stderr.log','wb') as err:
        proc=subprocess.Popen(command,env=env,stdout=out,stderr=err,start_new_session=True,cwd=STAGE);known.add(proc.pid);groups.add(proc.pid)
        (STAGE/'PROCESS.json').write_text(json.dumps(dict(launcher_pid=proc.pid,launcher_pgid=proc.pid,command=command,hard_timeout=45))+'\n')
        try:
            while True:
                table=processes();changed=True
                while changed:
                    changed=False
                    for pid,row in table.items():
                        if pid not in known and (row['ppid'] in known or row['pgid'] in groups or ('-b '+str(STAGE/'base')) in row['command']):known.add(pid);changed=True
                active=[table[n] for n in known if n in table]
                for row in active:
                    if row['pgid'] in known and row['pgid']!=os.getpgrp():groups.add(row['pgid'])
                    if row not in observed:observed.append(row)
                if not active and proc.poll() is not None:break
                if time.monotonic()-started>=45:timed_out=True;break
                time.sleep(.1)
        finally:
            for group in groups:
                try:os.killpg(group,signal.SIGKILL)
                except ProcessLookupError:pass
            proc.wait(timeout=5)
    time.sleep(.1);remaining=[v for n,v in processes().items() if n in known or v['pgid'] in groups]
    result=dict(launcher_exit_code=proc.returncode,timed_out=timed_out,elapsed_seconds=round(time.monotonic()-started,3),owned_processes=observed,remaining_owned=remaining,source_after=digest(SOURCE),clone_after=digest(dest))
    result['source_unchanged']=i['source']==result['source_after']
    try:result['clone_fields_after']=fields(dest)
    except Exception as e:result['clone_fields_error']=repr(e)
    (STAGE/'RESULT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(dict(stage=str(STAGE),launcher_exit_code=proc.returncode,timed_out=timed_out,remaining_owned=len(remaining),source_unchanged=result['source_unchanged'])))
if __name__=='__anki_offscreen_addon__':addon()
elif __name__=='__main__':
    if sys.argv[1:]==['--prepare']:prepare()
    elif sys.argv[1:]==['--run','启动 Cocoa']:run()
    else:raise SystemExit('Usage: --prepare; authorized one shot: --run "启动 Cocoa"')
