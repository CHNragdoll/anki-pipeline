"""One PostgreSQL projection shared by APKG and static browser generation."""
from __future__ import annotations

import base64
from contextlib import closing
import copy
import errno
import hashlib
import html
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import tempfile
import unicodedata
import zipfile
from urllib.parse import quote, urlsplit

from . import study_catalog as c
from .packaging import _render_template
from . import study_catalog_presentation as presentation
from .study_catalog_anki import field_cache,content_mods,model_mods,runtime_revisions,effective_content_mod
from . import study_catalog_math
from . import study_catalog_web

APKG_FORMATS=frozenset({'apkg','apkg-modern'})
OUTPUT_FORMATS=APKG_FORMATS|{'web'}


def _require_modern_codec():
    # Fail before any PG projection or potentially large staging writes.
    try:import zstandard
    except ImportError as error:
        raise ValueError('apkg-modern requires the optional apkg dependencies; use --extra apkg') from error


def require_ready(db):
    pending=db.execute("select count(*) from sources where status<>'complete'").fetchone()[0]
    if pending:raise ValueError('catalog migration is incomplete; no artifact may be published')


def project_book(db,book_id):
    """This is the only book/field read path used by both output formats."""
    require_ready(db)
    row=db.execute('select b.title,b.edition,s.collection_id,s.col_payload_id,x.manifest_id from books b '
                   'join book_sources s on s.book_id=b.id join sources x on x.id=s.source_id where b.id=%s',(book_id,)).fetchone()
    if row is None:raise ValueError('unknown book or missing exact import source')
    title,edition,collection,col_id,manifest_id=row
    col=c.get_json(db,col_id);models,runtime=presentation.project(db,book_id,col);units=json.loads(col['decks'])
    versions=model_mods(db);originals=json.loads(col['models'])
    for mid,model in models.items():
        version=versions.get(c.identity(book_id,mid))
        if version is not None:model['mod']=max(model['mod'],version)
        original=originals[mid]
        if model!=original and model['mod']<=original['mod']:
            raise ValueError('shared presentation revision has no committed native model version')
    from .study_catalog_library import scopes
    from .study_catalog_revision import registry
    return {'id':book_id,'title':title,'edition':edition,'collection_id':collection,'col':col,
            'models':models,'runtime':runtime,'units':units,'scope':scopes(db).get(book_id,{}),'manifest':c.get_json(db,manifest_id),
            'content_mods':content_mods(db),
            'runtime_revision':runtime_revisions(db).get(book_id),
            'semantic_projections':registry(db),
            'revision':db.execute('select coalesce(max(id),0) from events').fetchone()[0]}


def project_note(db,book,note_id,*,apply_runtime=True):
    """Project shared fields, optionally followed by host resource references.

    Semantic revision writers must use ``apply_runtime=False`` so a generated
    resource alias never becomes authored content. Both delivery hosts use the
    default final projection; their resource rewrite remains identical.
    """
    row=db.execute('select guid,word_id,kind,ordinal,model_id,payload_id,source_card_id from notes where book_id=%s and note_id=%s',
                   (book['id'],note_id)).fetchone()
    if row is None:raise ValueError('unknown book note')
    guid,word,kind,ordinal,mid,payload,source_id=row
    fields=c.note_fields(db,book['id'],note_id);model=book['models'][str(mid)]
    names=[f['name'] for f in model['flds']]
    if len(names)!=len(fields):raise ValueError('master note field/model mismatch')
    from .study_catalog_revision import project_fields,project_display_fields
    fields=project_fields(db,book,source_id,names,fields)
    if apply_runtime:fields=project_display_fields(db,book,source_id,names,fields)
    if apply_runtime and book['runtime']['aliases']:
        if any(presentation._dynamic_reference(text) for text in fields):
            raise ValueError('dynamic note runtime reference requires an explicit dependency declaration')
        fields=[presentation.rewrite_references(text,book['runtime']['aliases']) for text in fields]
    if apply_runtime and book.get('field_script_transport'):
        from .study_field_scripts import protect_fields
        fields=protect_fields(model,names,fields)
    payload=c.get_json(db,payload);mod=book['content_mods'].get(c.identity(book['id'],note_id))
    mod=effective_content_mod(payload['mod'],mod,book['runtime_revision'])
    return {'id':source_id or guid,'note_id':note_id,'guid':guid,'word_id':word,'kind':kind,'ordinal':ordinal,
            'model_id':mid,'model':model,'field_names':names,'fields':fields,'payload':payload,'content_mod':mod}


def _zip_info(name,metadata):
    info=zipfile.ZipInfo(name,tuple(metadata['date_time']))
    for field in ('compress_type','create_system','create_version','extract_version','internal_attr','external_attr'):
        setattr(info,field,metadata[field])
    info.comment=base64.b64decode(metadata['comment']);info.extra=base64.b64decode(metadata['extra'])
    return info


def _write_member(archive,db,key,info):
    with archive.open(info,'w',force_zip64=True) as stream:c.write_object(db,key,stream)


def _render_note(note,template_ordinal=0):
    """Shared source template registry; no book-name or year-specific branch."""
    fields=dict(zip(note['field_names'],note['fields']));template=note['model']['tmpls'][template_ordinal]
    front=_render_template(template['qfmt'],fields)
    back=_render_template(template['afmt'],{**fields,'FrontSide':front})
    return front,back


def compiled_source_sha256(note):
    """Pin the original projection before appending host transport fields.

    Committed native revision numbers do not affect authored rendering, so the
    model's mod is deliberately excluded. Identities, field order, every source
    field, CSS and templates are included. The caller captures this at the same
    source projection used for its common CompiledBuild result.
    """
    model={key:value for key,value in note['model'].items() if key!='mod'}
    value={key:note[key] for key in ('id','note_id','guid','model_id','field_names','fields')}
    return hashlib.sha256(c.canonical({**value,'model':model}).encode()).hexdigest()


class _CompiledNativeExport:
    """Explicit common deliveries and committed versions; no source writes."""
    def __init__(self,book,folder,delivery,versions):
        if type(delivery) is not dict or any(type(key) is not int for key in delivery):
            raise ValueError('compiled delivery keys must be integer native note IDs')
        if (type(versions) is not dict or set(versions)!={'models','notes'} or
                any(type(parts) is not dict or any(type(k) is not int or type(v) is not int for k,v in parts.items())
                    for parts in versions.values())):
            raise ValueError('explicit integer registered model/note version maps are required')
        self.book,self.folder,self.delivery,self.versions=book,folder,dict(delivery),copy.deepcopy(versions)
        self.original_models=json.loads(book['col']['models'])
        self.models,self.modes,self.seen,self.compiled_notes={}, {}, set(), set()
        self.media,self.media_pins,self.evidence={}, {}, []
        self.media_consumers={}
        self.bundle_report=None

    @staticmethod
    def _resources(result):
        from .study_compiled_build import _read
        values=result.get('resources')
        if type(values) is not dict or not values:raise ValueError('explicit common build resources are required')
        resources={};html_paths=[]
        for url,item in values.items():
            if (type(url) is not str or type(item) is not dict or set(item)!={'path','sha256','bytes'} or
                    type(item['path']) is not str or not Path(item['path']).is_absolute() or
                    type(item['bytes']) is not int or item['bytes']<0):
                raise ValueError('invalid common build resource descriptor')
            parsed=urlsplit(url);name=parsed.path.rsplit('/',1)[-1]
            if (parsed.scheme not in {'http','https'} or not parsed.netloc or parsed.query or parsed.fragment or
                    parsed.username is not None or parsed.password is not None or not name or
                    any(char in name for char in '\\\0') or any(ord(char)<32 for char in url)):
                raise ValueError('invalid common build logical resource URL')
            raw=_read(item['path'],item['sha256'],item['bytes'])
            if name in resources and resources[name]!=raw:raise ValueError('conflicting common media basenames')
            resources[name]=raw
            if name==result['entry']['html']['src'] and item['sha256']==result['entry']['html']['sha256']:
                html_paths.append(Path(item['path']))
        if len(html_paths)!=1:raise ValueError('common delivery requires one explicit HTML resource')
        record=result.get('record',{})
        if (type(record) is not dict or set(record)!={'src','sha256'} or
                type(record['src']) is not str or Path(record['src']).name!=record['src'] or
                record['src'] in {'.','..'} or '\\' in record['src']):
            raise ValueError('explicit immutable common build record is required')
        original=json.loads(_read(html_paths[0].parent/record['src'],record['sha256']))
        if (original.get('schema')!='study-complete-card-build.v1' or
                any(original.get(key)!=result.get(key) for key in ('identity','build_key','entry'))):
            raise ValueError('common build record differs from selected delivery')
        projection=result.get('runtime_projection')
        if projection is None:
            if original.get('runtime')!=result.get('runtime'):raise ValueError('binder changed without explicit projection')
        else:
            from .study_compiled_runtime import ADMITTED_RUNTIME_SHA256,CURRENT_RUNTIME_SHA256
            origin=original.get('runtime',{}).get('sha256')
            expected={'schema':'study-compatible-binder-projection.v1','source_build_record':record,
                'from_sha256':origin,'to_sha256':CURRENT_RUNTIME_SHA256,
                'html':result['entry']['html'],'profile':result['entry']['profile'],'body_profile_bytes_unchanged':True}
            if (projection!=expected or origin not in ADMITTED_RUNTIME_SHA256 or origin==CURRENT_RUNTIME_SHA256 or
                    result.get('runtime',{}).get('sha256')!=CURRENT_RUNTIME_SHA256):
                raise ValueError('invalid explicit compatible binder projection')
        for url,item in original.get('resources',{}).items():
            actual=values.get(url,{})
            if actual.get('sha256')!=item.get('sha256') or actual.get('bytes')!=item.get('bytes'):
                raise ValueError('common build original resource binding differs')
        return resources

    def project(self,note):
        nid,mid=note['note_id'],note['model_id'];self.seen.add(nid)
        item=copy.deepcopy(self.delivery.get(nid))
        compiled=False
        if item is not None:
            if type(item) is not dict or set(item)!={'result','prepared','policy','source_sha256'}:
                raise ValueError('delivery requires result, prepared, policy and source_sha256')
            result=item['result']
            if (type(result) is not dict or result.get('identity')!=self.book['id']+':'+str(note['id']) or
                    item['source_sha256']!=compiled_source_sha256(note)):
                raise ValueError('common delivery does not bind this source note')
            if result.get('mode') not in {'compiled','authored'}:raise ValueError('unknown common delivery capability')
            compiled=result['mode']=='compiled'
        if mid in self.modes and self.modes[mid]!=compiled:
            raise ValueError('mixed compiled/authored notes in one native model are unsupported')
        self.modes[mid]=compiled
        if not compiled:return note
        model_mod=self.versions['models'].get(mid);note_mod=self.versions['notes'].get(nid)
        if model_mod!=note['model']['mod'] or note_mod is None or note_mod!=note['content_mod']:
            raise ValueError('native delivery versions must equal the registered projection')
        from .study_compiled_native import project_native_note,split_native_delivery_meta
        projected=project_native_note(note,result['entry'],result['runtime'],prepared=item['prepared'],
            policy=item['policy'],resources=self._resources(result),model_mod=model_mod,note_mod=note_mod,
            original_model_mod=self.original_models[str(mid)]['mod'],original_note_mod=note['payload']['mod'])
        model=projected['note']['model']
        if mid in self.models and self.models[mid]!=model:raise ValueError('inconsistent compiled model projection')
        self.models[mid]=model;self.compiled_notes.add(nid)
        projected_note=projected['note']
        _,header=split_native_delivery_meta(
            projected_note['fields'][projected_note['field_names'].index('Meta')])
        self.record_media_consumers(header,projected.get('media_stages',{}))
        for name,raw in projected['media'].items():
            digest=hashlib.sha256(raw).hexdigest()
            if name in self.media_pins:
                if self.media_pins[name]!=digest:raise ValueError('compiled media address collides')
                continue
            if not self.media:
                self.media_folder=self.folder/'compiled-media';self.media_folder.mkdir()
            path=self.media_folder/name
            with path.open('xb') as stream:
                if stream.write(raw)!=len(raw):raise OSError('incomplete compiled media write')
            self.media[name]=path;self.media_pins[name]=digest
        self.evidence.append({'note_id':nid,'source_sha256':item['source_sha256'],'record':result['record'],
            'html':result['entry']['html'],'profile':result['entry']['profile'],'runtime':result['runtime'],
            **({'runtime_projection':result['runtime_projection']} if 'runtime_projection' in result else {})})
        return projected['note']

    def record_media_consumers(self,header,media_stages):
        """Aggregate authenticated projection facts before physical-media dedup.

        Cached deliveries use this same path after authenticating their inputs.
        None is sticky: any unknown use excludes that physical alias globally.
        """
        from .study_compiled_native import NATIVE_INITIAL_STAGES
        consumer=(header['id'],header['entry']['profile']['sha256'])
        for binding in header['transport'].values():
            alias=binding['src'];stages=media_stages.get(alias)
            if stages is None:
                self.media_consumers[alias]=None
            elif (not isinstance(stages,frozenset) or not stages or
                    not stages<=NATIVE_INITIAL_STAGES):
                raise ValueError('invalid internal native loading-stage evidence')
            elif alias not in self.media_consumers or self.media_consumers[alias] is not None:
                self.media_consumers.setdefault(alias,set()).update((*consumer,stage) for stage in stages)

    def bundle_media(self,native):
        """Readdress only staged Meta tokens after the common projection ends.

        Bundle bodies remain read-only file sequences until ZIP streaming; a
        second copy of all carriers is never materialized on disk or in RAM.
        """
        if not self.compiled_notes:return
        from .study_native_carrier import plan_native_carrier_bundles,NativeCarrierBundle
        from .study_compiled_native import rebind_native_media_transport
        plan=plan_native_carrier_bundles(self.media,self.media_pins,consumers=self.media_consumers)
        replacements=plan['replacements'];changed=0
        for nid in sorted(self.compiled_notes):
            row=native.execute('select mid,flds from notes where id=?',(nid,)).fetchone()
            if row is None:raise ValueError('compiled staged note is missing')
            fields=row[1].split('\x1f')
            names=[field['name'] for field in self.models[row[0]]['flds']]
            if names.count('Meta')!=1 or len(names)!=len(fields):
                raise ValueError('compiled staged Meta field schema differs')
            index=names.index('Meta')
            rebound=rebind_native_media_transport(fields[index],replacements)
            if rebound!=fields[index]:
                fields[index]=rebound
                native.execute('update notes set flds=? where id=?',('\x1f'.join(fields),nid));changed+=1
        self.media,self.media_pins=plan['media'],plan['media_pins']
        groups=[{'alias':name,'sha256':value.sha256,'bytes':value.size,'members':len(value.members)}
                for name,value in self.media.items() if isinstance(value,NativeCarrierBundle)]
        self.bundle_report={'schema':'study-native-carrier-bundles.v1','rebound_notes':changed,
                            'rebound_aliases':len(replacements),'groups':groups}

    def finish(self):
        if set(self.delivery)-self.seen:raise ValueError('compiled delivery references unknown native notes')
        if set(self.versions['models'])!=set(self.models) or set(self.versions['notes'])!=self.compiled_notes:
            raise ValueError('registered version map does not exactly cover compiled models/notes')
        return {'schema':'study-native-compiled-export.v1','compiled_notes':len(self.compiled_notes),
            'models':sorted(self.models),'notes':self.evidence,
            **({'carrier_bundles':self.bundle_report} if self.bundle_report is not None else {})}


def _modern_prefix_descriptor(value):
    if type(value) is not dict or set(value)!={'path','sha256'}:
        raise ValueError('modern prefix requires exactly path and sha256')
    path,pin=value['path'],value['sha256']
    if (type(path) is not str or not path or any(ord(char)<32 or ord(char)==127 for char in path)
            or not Path(path).is_absolute() or '..' in Path(path).parts
            or type(pin) is not str or re.fullmatch('[a-f0-9]{64}',pin) is None):
        raise ValueError('modern prefix requires an absolute path and SHA256 pin')
    return {'path':path,'sha256':pin}


def export_book(value,book_id,output,*,format='apkg',callback=None,compiled_delivery=None,native_versions=None,field_script_protection=False,modern_prefix=None):
    """Export the original projection, or an explicitly supplied native delivery.

    Native delivery maps integer note IDs to ``{result, prepared, policy,
    source_sha256}``. The result is the unchanged CompiledBuild output (or its
    explicit compatible runtime projection); no producer runs here. Versions
    are ``{'models': {integer_id: mod}, 'notes': {integer_id: mod}}`` and must
    equal the current registered projection. Models cannot mix capabilities.
    ``modern_prefix`` is an explicit path/SHA descriptor for codec-only reuse;
    the current source is still generated and authenticated in this snapshot.
    """
    destination=c.guard_new_output(output)
    if format not in OUTPUT_FORMATS:raise ValueError('unknown output format')
    if modern_prefix is not None:
        if format!='apkg-modern':raise ValueError('modern prefix is explicit to apkg-modern export')
        modern_prefix=_modern_prefix_descriptor(modern_prefix)
    if type(field_script_protection) is not bool or field_script_protection and (compiled_delivery is not None or native_versions is not None):
        raise ValueError('field-script protection is explicit to the default inline projection')
    if format=='apkg-modern':_require_modern_codec()
    destination.parent.mkdir(parents=True,exist_ok=True)
    with c.connect(value,readonly=True) as db,db.transaction():
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        book=project_book(db,book_id)
        options={} if compiled_delivery is None and native_versions is None else {
            'compiled_delivery':compiled_delivery,'native_versions':native_versions}
        if field_script_protection:options['field_script_protection']=True
        if modern_prefix is not None:options['modern_prefix']=modern_prefix
        report=_export_projected(db,book,destination,format=format,callback=callback,**options)
        return {**report,'output':str(destination.resolve()),'book_id':book_id,'catalog_revision':book['revision']}


def _export_projected(db,book,destination,*,format,callback=None,staging=None,compiled_delivery=None,native_versions=None,field_script_protection=False,modern_prefix=None):
    """One output core. The caller owns the explicit db, projection and TX.

    A batch supplies its own new private staging directory, retaining it on
    failure. The single API retains its historical temporary-stage lifecycle.
    """
    if modern_prefix is not None and format!='apkg-modern':
        raise ValueError('modern prefix is explicit to apkg-modern export')
    # A registered policy becomes the normal shared export behavior. Until
    # registration, old callers and running consumers keep their old projection.
    runtime=book.get('runtime_revision')
    if (compiled_delivery is None and native_versions is None and isinstance(runtime,dict)
            and 'field_script_transport' in runtime):field_script_protection=True
    if field_script_protection:
        if compiled_delivery is not None or native_versions is not None:
            raise ValueError('field-script protection cannot wrap compiled delivery')
        from .study_field_scripts import project_inline_book
        book=project_inline_book(book)
    if staging is None:
        if format=='apkg-modern':
            # Like batch exports, keep intermediate evidence. Do not recursively
            # remove private stages that may also contain another actor's files.
            temporary=Path(tempfile.mkdtemp(prefix='.study-modern-build-',dir=destination.parent))
            try:
                prefix_options={} if modern_prefix is None else {'modern_prefix':modern_prefix}
                report=_export_projected(db,book,destination,format=format,callback=callback,
                    staging=temporary,compiled_delivery=compiled_delivery,native_versions=native_versions,
                    field_script_protection=field_script_protection,**prefix_options)
            except BaseException as error:
                error.add_note('Modern export scratch retained in '+str(temporary))
                raise
            return {**report,'retained_staging':str(temporary)}
        with tempfile.TemporaryDirectory(prefix='.study-build-',dir=destination.parent) as temporary:
            options={} if compiled_delivery is None and native_versions is None else {
                'compiled_delivery':compiled_delivery,'native_versions':native_versions}
            if field_script_protection:options['field_script_protection']=True
            return _export_projected(db,book,destination,format=format,callback=callback,staging=Path(temporary),**options)
    if format not in APKG_FORMATS and (compiled_delivery is not None or native_versions is not None):
        raise ValueError('native compiled delivery is explicit to APKG export')
    options={} if compiled_delivery is None and native_versions is None else {
        'compiled_delivery':compiled_delivery,'native_versions':native_versions}
    if format in APKG_FORMATS:
        if format=='apkg-modern':
            legacy=staging/'legacy';legacy.mkdir(mode=0o700)
            report=_apkg(db,book,legacy,'source.apkg',callback,**options)
            prefix_options={} if modern_prefix is None else {'modern_prefix':modern_prefix}
            report=_modern_container(legacy/'source.apkg',staging/'result.apkg',report,callback,**prefix_options)
        else:report=_apkg(db,book,staging,destination.name,callback,**options)
    else:report=_web(db,book,staging,callback)
    if field_script_protection:report={**report,'field_script_transport':book['field_script_transport']}
    result=(staging/'result.apkg' if format=='apkg-modern' else
            staging/destination.name if format=='apkg' else staging/'web')
    if destination.exists() or destination.is_symlink():raise FileExistsError('output appeared during generation')
    if format=='apkg-modern':
        _publish_modern_file(result,destination,report)
    elif format=='apkg':
        os.link(result,destination)
    else:
        _publish_web_directory(result,destination)
        with (destination/'COMPLETE.json').open('x',encoding='utf-8') as stream:stream.write(c.canonical(report))
    return report


def _publish_modern_file(source,destination,report):
    """Hold the verified FD; rehash at most one external ctime-only change."""
    def need(value,message):
        if not value:raise ValueError('modern publication '+message)
    def signature(value):
        return (value.st_dev,value.st_ino,value.st_mode,value.st_size,value.st_mtime_ns,value.st_ctime_ns)
    descriptor=os.open(source,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(descriptor,'rb') as stream:
        before=signature(os.fstat(stream.fileno()))
        need(stat.S_ISREG(before[2]) and before==signature(source.lstat()),'source identity changed')
        need(type(report['bytes']) is int and before[3]==report['bytes'],'source size differs')
        def verify_bytes():
            stream.seek(0)
            need(hashlib.file_digest(stream,'sha256').hexdigest()==report['sha256'],'source SHA differs')
        ctime_rechecked=False
        def verify_stable(expected,paths,phase):
            nonlocal ctime_rechecked
            verify_bytes()
            current=signature(os.fstat(stream.fileno()))
            need(all(signature(path.lstat())==current for path in paths),phase+' path identity changed')
            if current!=expected:
                need(not ctime_rechecked and current[:5]==expected[:5],phase+' changed during verification')
                ctime_rechecked=True
                # Ctime alone cannot prove unchanged bytes. Re-read the same held
                # FD against the codec's independent output pin, then require
                # strict six-part stability across that entire second read.
                verify_bytes()
            need(current==signature(os.fstat(stream.fileno())) and
                 all(signature(path.lstat())==current for path in paths),phase+' changed during verification')
            return current
        before=verify_stable(before,(source,),'source')
        os.link(source,destination,follow_symlinks=False)
        linked=signature(os.fstat(stream.fileno()))
        # Our hardlink changes ctime. Other identity/size/mode/mtime parts must
        # remain those just hashed; both named paths must refer to this held FD.
        need(before[:5]==linked[:5] and linked==signature(source.lstat())==signature(destination.lstat()),
             'linked output identity changed')
        # The link's own expected ctime is a separate baseline, not an external
        # recheck allowance. The one allowance is shared by both hash phases.
        verify_stable(linked,(source,destination),'linked output')
        directory=os.open(destination.parent,os.O_RDONLY)
        try:os.fsync(directory)
        finally:os.close(directory)


def _modern_container(source,destination,report,callback,*,modern_prefix=None):
    """Container-only delivery after the same authored/native projection."""
    from .study_modern_convert import convert_legacy_apkg
    from .study_modern_recompress import recompress_modern_apkg
    prefix_options={}
    if modern_prefix is not None:
        modern_prefix=_modern_prefix_descriptor(modern_prefix)
        prefix_options={'prefix':modern_prefix['path'],'expected_prefix_sha256':modern_prefix['sha256']}
    # Internal progress is summarized to avoid flooding CLI output once per
    # media file. The normal projection callback still runs in the same TX.
    if callback:callback({'stage':'modern-container-convert'})
    modern=destination.parent/'standard-modern.apkg'
    converted=convert_legacy_apkg(source,modern,expected_source_sha256=report['sha256'])
    if callback:callback({'stage':'modern-container-recompress','bytes':converted['output_bytes']})
    packed=recompress_modern_apkg(modern,destination,expected_source_sha256=converted['output_sha256'],**prefix_options)
    container={'format':'modern-v3','source_bytes':report['bytes'],'source_sha256':report['sha256'],
            'standard_bytes':converted['output_bytes'],'standard_sha256':converted['output_sha256'],
            'level':packed['level'],'window_log':packed['window_log'],'threads':packed['threads'],
            'frame_count':packed['frame_count'],'replaced_frames':packed['replaced_frames'],
            'saved_frame_bytes':packed['saved_frame_bytes'],
            'zstandard_version':packed['zstandard_version'],
            'raw_content_changed':False,'source_identity_sha256_unchanged':
                converted['source_identity_sha256_unchanged'] and packed['source_identity_sha256_unchanged']}
    if modern_prefix is not None:
        container.update(prefix=modern_prefix,reused_frames=packed['reused_prefix_frames'])
    return {**report,'format':'apkg-modern','bytes':packed['output_bytes'],'sha256':packed['output_sha256'],
            'container':container}


def _publish_web_directory(source,destination):
    """No-clobber publication at every directory/file boundary."""
    destination.mkdir()
    for child in source.iterdir():
        if child.is_dir():_publish_web_directory(child,destination/child.name)
        else:os.link(child,destination/child.name)


def _rmdir_empty(path):
    try:path.rmdir()
    except OSError as error:
        if error.errno not in {errno.ENOTEMPTY,errno.EEXIST}:raise


def _batch_requests(requests):
    if type(requests) is not list or not requests:raise ValueError('a nonempty explicit export request list is required')
    result,identities,names=[],set(),set()
    reserved={'manifest.json','complete.json','failed.json','.partial'}
    for row in requests:
        if type(row) is not dict or set(row)!={'book_id','format','name'}:
            raise ValueError('each batch request requires exactly book_id, format and name')
        book,format,name=row['book_id'],row['format'],row['name']
        if type(book) is not str or not book or '\0' in book or type(format) is not str or format not in OUTPUT_FORMATS:
            raise ValueError('invalid batch book or output format')
        if (type(name) is not str or not name or name.startswith('.') or
                any(char in name for char in '/\\\0') or any(ord(char)<32 or ord(char)==127 for char in name)):
            raise ValueError('batch output name must be a direct nonprivate path member')
        key=unicodedata.normalize('NFD',name).casefold()
        if key in reserved or key in names or (book,format) in identities:
            raise ValueError('duplicate or reserved batch output name/book-format')
        identities.add((book,format));names.add(key);result.append(dict(row))
    return result


def _batch_snapshot(db):
    database,schema,snapshot,isolation,readonly=db.execute(
        "select current_database(),current_schema(),pg_current_snapshot()::text,"
        "current_setting('transaction_isolation'),current_setting('transaction_read_only')").fetchone()
    if isolation!='repeatable read' or readonly!='on':raise ValueError('batch export requires read-only repeatable read')
    revision=db.execute('select coalesce(max(id),0) from events').fetchone()[0]
    return {'database':database,'schema':schema,'snapshot':snapshot,'isolation':isolation,
            'read_only':True,'catalog_revision':revision}


def _book_snapshot_pins(db,book):
    source=db.execute('select s.source_id,s.collection_id,s.col_payload_id,x.manifest_id '
        'from book_sources s join sources x on x.id=s.source_id where s.book_id=%s',(book['id'],)).fetchone()
    if source is None or source[1]!=book['collection_id']:raise ValueError('projected book source differs from snapshot')
    binding=presentation.registry(db)['books'].get(book['id'],{})
    references=set(binding.get('resources',{}).values())
    for parts in binding.get('models',{}).values():references.update(parts.values())
    components=dict(db.execute('select distinct c.id,c.current_id from components c '
        'where c.id in (select component_id from note_fields where book_id=%s) or c.id=ANY(%s) '
        'order by c.id',(book['id'],sorted(references))).fetchall())
    if not references.issubset(components):raise ValueError('missing projected presentation component')
    pin=lambda value:hashlib.sha256(c.canonical(value).encode()).hexdigest()
    return {'catalog_revision':book['revision'],
            'source':dict(zip(('source_id','collection_id','col_payload_id','manifest_id'),source)),
            'manifest_sha256':pin(book['manifest']),'models_sha256':pin(book['models']),
            'components':components,'components_sha256':pin(components),
            'content_mods_sha256':pin(book['content_mods']),
            'semantic_projections_sha256':pin(book['semantic_projections']),
            'runtime_revision':book['runtime_revision'],
            'runtime':{'sources':book['runtime']['sources'],'aliases':book['runtime']['aliases'],
                       'generated':{name:hashlib.sha256(raw).hexdigest()
                                    for name,raw in sorted(book['runtime']['generated'].items())}}}


def _unlink_owned(path,identity):
    try:
        current=path.lstat()
        if (current.st_dev,current.st_ino)==identity:path.unlink()
    except FileNotFoundError:pass


def _verify_batch_complete(path,identity,raw):
    descriptor=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        before=os.fstat(descriptor)
        if (before.st_dev,before.st_ino)!=identity:
            raise OSError('batch completion path identity changed')
        actual=os.pread(descriptor,len(raw)+1,0)
        after=os.fstat(descriptor);current=path.lstat()
        signature=lambda value:(value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns,value.st_ctime_ns)
        if (actual!=raw or signature(before)!=signature(after) or signature(current)!=signature(after)):
            raise OSError('batch completion bytes or path changed')
    finally:os.close(descriptor)


def _publish_batch_complete(destination,raw):
    """Expose only a fully written, closed marker, without replacing a file."""
    descriptor,name=tempfile.mkstemp(prefix='.batch-complete-',dir=destination)
    temporary=Path(name);current=os.fstat(descriptor)
    identity=current.st_dev,current.st_ino
    complete=destination/'COMPLETE.json'
    try:
        writer=os.dup(descriptor)
        try:stream=os.fdopen(writer,'wb')
        except BaseException:
            os.close(writer)
            raise
        with stream as target:
            if target.write(raw)!=len(raw):raise OSError('incomplete batch completion write')
            target.flush();os.fsync(target.fileno())
        _verify_batch_complete(temporary,identity,raw)
        # Same-directory hardlink is atomic and refuses a racing destination.
        # Keep the original owned fd alive so replacement cannot recycle its inode.
        os.link(temporary,complete)
        _verify_batch_complete(temporary,identity,raw)
        _verify_batch_complete(complete,identity,raw)
        _unlink_owned(temporary,identity)
    except BaseException:
        _unlink_owned(complete,identity)
        raise
    finally:
        try:
            try:_unlink_owned(temporary,identity)
            except OSError:pass  # A failed private-temp cleanup never replaces another file.
        finally:os.close(descriptor)


def export_batch(value,requests,output,*,callback=None,compiled_delivery=None,native_versions=None,field_script_protection=False,modern_prefixes=None):
    """Export requested books/formats from ONE read-only RR snapshot.

    Requests are ``[{book_id, format: 'web'|'apkg'|'apkg-modern', name: direct-child-name}]``.
    The new batch root's COMPLETE.json is authoritative for the whole batch;
    child web COMPLETE files alone do not make a partial batch complete.
    Failed/cancelled builds keep completed children, the current .partial stage
    and a bounded failure record. No existing destination is replaced/deleted.
    Success retains nonempty private .partial build evidence too: no recursive
    cleanup is attempted. Only named artifacts belong to the delivery set;
    retained stages are excluded from it even when root COMPLETE is present.
    This neither initializes PG nor writes a derived cache into the source TX.
    Optional native delivery/version maps add one outer book-ID level to the
    single-book contract, and apply only to explicitly selected APKG requests.
    ``modern_prefixes`` maps exact modern artifact names to path/SHA descriptors;
    no prefix lookup, retry or source-generation shortcut is implicit.
    """
    requests=_batch_requests(requests)
    prefixes={}
    if modern_prefixes is not None:
        modern_names={row['name'] for row in requests if row['format']=='apkg-modern'}
        if (type(modern_prefixes) is not dict or any(type(name) is not str for name in modern_prefixes)
                or not set(modern_prefixes)<=modern_names):
            raise ValueError('modern prefixes must select exact apkg-modern artifact names')
        prefixes={name:_modern_prefix_descriptor(value) for name,value in modern_prefixes.items()}
    if type(field_script_protection) is not bool or field_script_protection and (compiled_delivery is not None or native_versions is not None):
        raise ValueError('field-script protection is explicit to the default inline projection')
    if any(row['format']=='apkg-modern' for row in requests):_require_modern_codec()
    if compiled_delivery is not None or native_versions is not None:
        books={row['book_id'] for row in requests if row['format'] in APKG_FORMATS}
        if (type(compiled_delivery) is not dict or type(native_versions) is not dict or
                set(compiled_delivery)!=set(native_versions) or not set(compiled_delivery)<=books or
                any(type(key) is not str for key in compiled_delivery)):
            raise ValueError('batch native delivery/version maps must select the same requested APKG books')
    path=Path(output).expanduser()
    if '..' in path.parts:raise ValueError('batch output must not contain parent traversal')
    destination=c.guard_new_output(path)
    destination.parent.mkdir(parents=True,exist_ok=True)
    report=None;reserved=False;artifacts=[]
    try:
        with c.connect(value,readonly=True) as db,db.transaction():
            db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            snapshot=_batch_snapshot(db)
            books={}
            for row in requests:
                key=row['book_id']
                if key not in books:books[key]=project_book(db,key)
            if any(book['revision']!=snapshot['catalog_revision'] for book in books.values()):
                raise ValueError('book projection revision differs from the batch snapshot')
            pins={key:_book_snapshot_pins(db,book) for key,book in books.items()}
            destination.mkdir(mode=0o700);reserved=True
            partial=destination/'.partial';partial.mkdir(mode=0o700)
            for index,row in enumerate(requests):
                staging=partial/f'{index:04d}';staging.mkdir(mode=0o700)
                options={'field_script_protection':True} if field_script_protection else {}
                if row['format'] in APKG_FORMATS and compiled_delivery is not None and row['book_id'] in compiled_delivery:
                    options={'compiled_delivery':compiled_delivery[row['book_id']],
                             'native_versions':native_versions[row['book_id']]}
                if row['name'] in prefixes:options['modern_prefix']=prefixes[row['name']]
                artifact=_export_projected(db,books[row['book_id']],destination/row['name'],
                    format=row['format'],callback=callback,staging=staging,**options)
                artifacts.append({**row,'report':artifact,
                                  'report_sha256':hashlib.sha256(c.canonical(artifact).encode()).hexdigest()})
                _rmdir_empty(staging)
            _rmdir_empty(partial)
            report={'schema':'study-catalog-export-batch.v1','generator':'anki_pipeline.study_catalog_export',
                    'snapshot':snapshot,'books':pins,'artifacts':artifacts}
        # Closing the read-only transaction must also succeed before completion.
        raw=(c.canonical(report)+'\n').encode()
        with (destination/'manifest.json').open('xb') as stream:
            if stream.write(raw)!=len(raw):raise OSError('incomplete batch manifest write')
            stream.flush();os.fsync(stream.fileno())
        _publish_batch_complete(destination,c.canonical({'schema':'study-catalog-export-batch-complete.v1',
            'manifest_sha256':hashlib.sha256(raw).hexdigest(),'manifest_bytes':len(raw),
            'artifacts':len(artifacts)}).encode())
        return report
    except BaseException as error:
        if reserved:
            try:
                with (destination/'FAILED.json').open('x',encoding='utf-8') as stream:
                    stream.write(c.canonical({'schema':'study-catalog-export-batch-failed.v1',
                        'error_type':type(error).__name__,'completed':[row['name'] for row in artifacts]}))
            except OSError:pass  # Preserve a racing actor's file and the original failure.
        raise


def _apkg(db,book,folder,name,callback,*,compiled_delivery=None,native_versions=None):
    compiled=(_CompiledNativeExport(book,folder,compiled_delivery,native_versions)
              if compiled_delivery is not None or native_versions is not None else None)
    collection=folder/book['manifest']['collection_entry']
    with collection.open('xb') as stream:c.write_object(db,book['collection_id'],stream)
    changed=0;count=0;created=0
    with closing(sqlite3.connect(collection)) as native, native:
        if json.loads(book['col']['models'])!=book['models']:
            native.execute('update col set models=?',(c.canonical(book['models']),))
        for nid, in db.execute('select note_id from notes where book_id=%s order by ordinal',(book['id'],)):
            note=project_note(db,book,nid)
            if compiled is not None:note=compiled.project(note)
            fields='\x1f'.join(note['fields'])
            row=native.execute('select guid,mid,flds,mod from notes where id=?',(nid,)).fetchone()
            if row is None and book['manifest'].get('collection_mode')=='skeleton':
                sort_value,checksum=field_cache(note['fields'],note['model'])
                payload={**note['payload'],'flds':fields,'sfld':sort_value,'csum':checksum}
                if note['content_mod'] is not None:payload['mod']=note['content_mod']
                columns=[r[1] for r in native.execute('pragma table_info(notes)')]
                native.execute('insert into notes values('+','.join('?' for _ in columns)+')',[payload[name] for name in columns])
                created+=1;row=(note['guid'],note['model_id'],fields,payload['mod'])
            if row is None or row[0]!=note['guid'] or row[1]!=note['model_id']:raise ValueError('native identity differs from catalog')
            if row[2]!=fields or (note['content_mod'] is not None and note['content_mod']>row[3]):
                if note['content_mod'] is None or note['content_mod']<=row[3]:
                    raise ValueError('shared field revision has no newer committed native note version')
                plain,checksum=field_cache(note['fields'],note['model'])
                native.execute('update notes set flds=?,sfld=?,csum=?,mod=?,usn=-1 where id=?',
                               (fields,plain,checksum,note['content_mod'],nid));changed+=1
            count+=1
        if compiled is not None:compiled.bundle_media(native)
        compiled_report=compiled.finish() if compiled is not None else None
        if compiled is not None and compiled.models:
            models={**book['models'],**{str(mid):model for mid,model in compiled.models.items()}}
            native.execute('update col set models=?',(c.canonical(models),))
        if book['manifest'].get('collection_mode')=='skeleton':
            columns=[r[1] for r in native.execute('pragma table_info(cards)')]
            for payload_id, in db.execute('select payload_id from native_cards where book_id=%s order by native_id',(book['id'],)):
                payload=c.get_json(db,payload_id)
                native.execute('insert into cards values('+','.join('?' for _ in columns)+')',[payload[name] for name in columns])
        if native.execute('select count(*) from notes').fetchone()[0]!=count:raise ValueError('incomplete catalog note coverage')
        if native.execute('pragma integrity_check').fetchone()[0]!='ok':raise ValueError('generated Anki database failed integrity check')
    package=folder/name
    with zipfile.ZipFile(package,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        info=_zip_info(book['manifest']['collection_entry'],book['manifest']['collection_zip_info'])
        with collection.open('rb') as source,archive.open(info,'w',force_zip64=True) as target:shutil.copyfileobj(source,target,1024*1024)
        resources={name:(book['runtime']['sources'].get(name,key),metadata) for name,key,metadata in db.execute('select name,object_id,zip_info_id from resource_aliases where book_id=%s',(book['id'],))}
        for index,(member,name) in enumerate(book['manifest']['media'].items()):
            key,metadata=resources[name];_write_member(archive,db,key,_zip_info(member,c.get_json(db,metadata)))
            if callback and index and index%10000==0:callback({'stage':'export-media','book_id':book['id'],'completed':index})
        for member,extra in book['manifest']['extra_members'].items():_write_member(archive,db,extra['object_id'],_zip_info(member,extra['zip_info']))
        media_index=dict(book['manifest']['media']);next_member=0
        generated=dict(book['runtime']['generated'])
        if compiled is not None:
            for alias,path in compiled.media.items():
                if alias in resources:
                    if hashlib.sha256(c.get_object(db,resources[alias][0])).hexdigest()!=compiled.media_pins[alias]:
                        raise ValueError('compiled media collides with original package media')
                    continue
                if alias in generated:
                    if hashlib.sha256(generated[alias]).hexdigest()!=compiled.media_pins[alias]:
                        raise ValueError('compiled media collides with shared runtime media')
                    continue
                generated[alias]=path
        for alias,raw in sorted(generated.items()):
            if alias in resources:continue
            while str(next_member) in media_index or str(next_member) in book['manifest']['extra_members']:next_member+=1
            member=str(next_member);media_index[member]=alias
            from .study_native_carrier import NativeCarrierBundle
            if isinstance(raw,(Path,NativeCarrierBundle)):
                def blocks(value):
                    if isinstance(value,NativeCarrierBundle):
                        try:yield from value.iter_chunks()
                        except ValueError as error:
                            raise ValueError('compiled staging media bytes changed') from error
                    else:
                        with value.open('rb') as source:yield from iter(lambda:source.read(1024*1024),b'')
                with archive.open(member,'w',force_zip64=True) as target:
                    digest=hashlib.sha256()
                    for block in blocks(raw):
                        if target.write(block)!=len(block):raise OSError('incomplete compiled package media write')
                        digest.update(block)
                    if digest.hexdigest()!=compiled.media_pins[alias]:
                        raise ValueError('compiled staging media bytes changed')
            else:archive.writestr(member,raw,compress_type=zipfile.ZIP_DEFLATED,compresslevel=9)
        archive.writestr('media',c.canonical(media_index).encode() if generated else c.get_object(db,book['manifest']['media_index_id']))
    with package.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
    return {'schema':'study-catalog-export.v1','format':'apkg','notes':count,'media':len(media_index),'shared_field_changes':changed,'created_notes':created,
            'bytes':package.stat().st_size,'sha256':digest,'generator':'anki_pipeline.study_catalog_export','projection':'project_book/project_note',
            **({'compiled_delivery':compiled_report} if compiled is not None else {})}


def _card_page(note,base,*,styles_href=None,template_ordinal=0,math_href=None,mount_audit=None):
    front,back=_render_note(note,template_ordinal)
    # Native Anki mounts one side at a time. Mounting two source templates in
    # the same DOM runs both scripts, duplicates IDs and breaks disclosures.
    # srcdoc gives the browser adapter the same one-active-document lifecycle;
    # replacing it also stops audio/timers from the previous side.
    def side(content):
        def sound(match):
            filename=html.unescape(match[1])
            return '<audio controls preload="none" src="'+quote(filename,safe='')+'"></audio>'
        content=re.sub(r'\[sound:([^\]\r\n]+)\]',sound,content)
        return ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<base href="'+html.escape(base,quote=True)+'">'+
            ('<link rel="stylesheet" href="'+html.escape(styles_href,quote=True)+'">' if styles_href else '<style>'+note['model']['css']+'</style>')+
            (study_catalog_math.header(math_href) if math_href else '')+
            '</head><body class="card">'+content+'</body></html>')
    sides=[side(front),side(back)]
    if mount_audit is not None:mount_audit.observe(sides)
    payload=c.canonical(sides).replace('<','\\u003c')
    return study_catalog_web.card_shell(payload,base)


def _web_model(model,media,cache):
    """Keep CSS and field-independent template scripts once per exact version.

    The source templates still pass through the same Python field renderer.
    This changes resource delivery only; neither host recomputes source facts.
    """
    key=model['id']
    if key in cache:return cache[key]
    result=copy.deepcopy(model)
    def asset(text,suffix):
        name='_study_'+hashlib.sha256(text.encode()).hexdigest()+'.'+suffix
        path=media/name
        if not path.exists():path.write_text(text)
        return name
    css=asset(result['css'],'css');result['css']=''
    def script(match):
        attributes,body=match[1],match[2]
        if not body or '{{' in body or re.search(r'\bsrc\s*=|\btype\s*=\s*[\"\']application/(?:json|ld\+json)',attributes,re.I):return match[0]
        return '<script'+attributes+' src="'+asset(body,'js')+'"></script>'
    for template in result['tmpls']:
        for side in ('qfmt','afmt'):
            template[side]=re.sub(r'<script\b([^>]*)>(.*?)</script\s*>',script,template[side],flags=re.I|re.S)
    cache[key]=result,css
    return result,css


def _web_catalog_notes(db,book):
    """Use the same projected notes and ordered native membership for both APIs."""
    for nid, in db.execute('select note_id from notes where book_id=%s order by ordinal',(book['id'],)):
        note=project_note(db,book,nid)
        natives=db.execute('select n.native_id,n.ordinal,u.name from native_cards n join units u on u.book_id=n.book_id and u.id=n.unit_id where n.book_id=%s and n.note_id=%s order by n.ordinal',(book['id'],nid)).fetchall()
        yield note,natives


def _web_catalog_rows(book,note,natives):
    """Keep native identities, label fallbacks and historical deep links exact."""
    values=dict(zip(note['field_names'],note['fields']))
    label=html.unescape(values.get('Word',values.get('Title',note['fields'][note['model'].get('sortf',0)])))
    for native_id,ordinal,unit in natives:
        if not 0<=ordinal<len(note['model']['tmpls']):raise ValueError('native card references missing template')
        # A model may have several templates but only one native card here.
        parts=('page',book['id'],note['guid'])
        filename=c.identity(*parts,*(() if len(natives)==1 else (ordinal,)))+'.html'
        card_id=note['id'] if len(natives)==1 else str(native_id)
        yield {'id':card_id,'guid':note['guid'],
            'word':label,'label':label+(' · '+note['model']['tmpls'][ordinal]['name'] if len(natives)>1 else ''),
            'template':note['model']['tmpls'][ordinal]['name'],'template_ordinal':ordinal,
            'unit':unit,'url':'cards/'+filename,'ordinal':note['ordinal'],'native_id':native_id}


def _web_catalog_document(book,cards):
    return {'schema':'shared-book-web.v1','book_id':book['id'],'title':book['title'],'scope':book['scope'],
            'cards':cards,'catalog_revision':book['revision']}


def project_web_catalog(db,book):
    """Return the full web catalog without rendering cards or accessing media.

    The caller owns one read-only snapshot and its project_book() result. Notes,
    native cards and units use the same projection/order as the complete export;
    classification refreshes therefore need no second content generator.
    Serialize the returned document with c.canonical(), as the full export does.
    """
    return _web_catalog_document(book,[row for note,natives in _web_catalog_notes(db,book)
                                      for row in _web_catalog_rows(book,note,natives)])


def _web(db,book,folder,callback):
    root=folder/'web';cards=root/'cards';media=root/'media';cards.mkdir(parents=True);media.mkdir()
    from .study_catalog_navigation import catalog_navigation_metadata,note_navigation_metadata
    retained=db.execute('select value from metadata where key=%s',('source.catalog.'+book['id'],)).fetchone()
    grouping=catalog_navigation_metadata(json.loads(c.get_object(db,retained[0])),grouping_only=True)['cards'] if retained else {}
    metadata={'cards':{},'provenance':{'kind':'current-projected-fields','grouping_source_sha256':retained[0] if retained else None}}
    members=[]
    catalog=[];model_cache={};math_href=None;mount_audit=study_catalog_web.SharedMountAudit()
    for index,(note,natives) in enumerate(_web_catalog_notes(db,book)):
        from . import study_catalog_math
        needs_math=study_catalog_math.required(note['fields'])
        if needs_math and math_href is None:math_href=study_catalog_math.write_assets(db,media)
        web_model,css=_web_model(note['model'],media,model_cache)
        original=grouping.get(note['id'],{})
        summary=note_navigation_metadata(note,source_entry={'deckName':original.get('deck_name')})
        web_note={**note,'model':web_model}
        for row in _web_catalog_rows(book,web_note,natives):
            (root/row['url']).write_text(_card_page(web_note,'../media/',styles_href=css,template_ordinal=row['template_ordinal'],math_href=math_href if needs_math else None,mount_audit=mount_audit))
            card_id=row['id']
            metadata['cards'][card_id]=summary
            # Retained inventories can omit a separate package guide. New
            # content added to that book still belongs in its directory.
            if note['id'] in grouping or note['kind']!='guide':members.append(card_id)
            catalog.append(row)
        if callback and index and index%500==0:callback({'stage':'export-web-cards','book_id':book['id'],'completed':index})
    resources=0
    for name,key in db.execute('select name,object_id from resource_aliases where book_id=%s order by name',(book['id'],)):
        key=book['runtime']['sources'].get(name,key)
        if Path(name).name!=name:raise ValueError('unsafe resource alias')
        with (media/name).open('xb') as stream:c.write_object(db,key,stream)
        resources+=1
    for alias,raw in sorted(book['runtime']['generated'].items()):
        path=media/alias
        if path.exists():
            if path.read_bytes()!=raw:raise ValueError('runtime alias collides with another generated resource')
            continue
        path.write_bytes(raw);resources+=1
    full_catalog=_web_catalog_document(book,catalog)
    (root/'catalog.json').write_text(c.canonical(full_catalog))
    if retained:metadata['member_ids']=members
    from .study_catalog_web_delivery import build_library
    from .study_compiled_build import CompiledBuild
    from urllib.parse import quote
    with CompiledBuild(folder/'complete-web-build') as builder:
        completed=build_library(root,full_catalog,study_catalog_web.audited_shared_config(root,mount_audit),
            builder=builder,metadata=metadata,callback=callback,
            source_url='https://study.invalid/exports/'+quote(book['id'],safe='')+'/index.html')
    delivery={'report':{**completed['report']['prepared'],'compiled_delivery':completed['report']['compiled']}}
    navigation={key:completed['report'][key] for key in
                ('navigation_bytes','navigation_cards','runtime_bytes','navigation_gzip_bytes')}
    return {'schema':'study-catalog-export.v1','format':'web','notes':index+1 if catalog else 0,'cards':len(catalog),'media':resources,
            'generator':'anki_pipeline.study_catalog_export','projection':'project_book/project_note','delivery':delivery['report'],**navigation}


def _library_html(title):
    """Compatibility wrapper for the subject-neutral browser host."""
    return study_catalog_web.library_html(title)


def verify_catalog(value,*,deep=False):
    problems=[]
    with c.connect(value,readonly=True) as db,db.transaction():
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        pending=db.execute("select count(*) from sources where status<>'complete'").fetchone()[0]
        if pending:problems.append({'kind':'incomplete_sources','count':pending})
        for sid,name,count in db.execute('select source_id,name,row_count from archive_tables'):
            actual=db.execute('select count(*) from archive_rows where source_id=%s and table_name=%s',(sid,name)).fetchone()[0]
            if actual!=count:problems.append({'kind':'archive_count','source':sid,'table':name,'expected':count,'actual':actual})
        for book,card,expected in db.execute('select book_id,source_card_id,expected_occurrences from analyses'):
            actual=db.execute('select count(*) from analysis_occurrences where book_id=%s and source_card_id=%s',(book,card)).fetchone()[0]
            if actual!=expected:problems.append({'kind':'physical_count','book':book,'card':card,'expected':expected,'actual':actual})
        checked=0
        if deep:
            class Sink:
                def write(self,_):pass
            with db.cursor(name='verify_objects') as cursor:
                cursor.itersize=64
                cursor.execute('select id,codec,byte_length,data from objects')
                for key,codec,size,data in cursor:
                    c.write_encoded_object(key,codec,size,data,Sink());checked+=1
            for sid,name,expected,seal in db.execute('select source_id,name,row_count,row_digest from archive_tables'):
                digest=hashlib.sha256();count=0
                class RowsDigest:
                    def write(self,part):digest.update(part)
                with db.cursor(name='verify_archive_rows') as cursor:
                    cursor.itersize=64
                    cursor.execute('select r.ordinal,o.id,o.codec,o.byte_length,o.data from archive_rows r join objects o on o.id=r.payload_id '
                        'where r.source_id=%s and r.table_name=%s order by r.ordinal',(sid,name))
                    for ordinal,key,codec,size,data in cursor:
                        if ordinal!=count:raise ValueError('history archive has a missing or duplicated row ordinal')
                        c.write_encoded_object(key,codec,size,data,RowsDigest());digest.update(b'\n');count+=1
                if count!=expected or digest.hexdigest()!=seal:
                    problems.append({'kind':'archive_digest','source':sid,'table':name})
    return {'schema':'study-catalog-verification.v1','ok':not problems,'engine':'postgresql','problems':problems,'objects_deep_verified':checked}
