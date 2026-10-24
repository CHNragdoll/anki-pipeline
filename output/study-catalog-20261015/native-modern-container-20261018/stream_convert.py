"""Private streaming legacy-v4 APKG -> modern container converter.

No Collection/native export call, no field parsing, no media pruning. Explicit
whole-source SHA/size, no-clobber output directory, one compressed member temp,
1 MiB payload chunks. Successful publication retains the partial as a hardlink;
failures retain partial evidence. This is not wired into the production exporter.
"""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import threading
import time
import unicodedata
import zipfile
import zstandard as zstd_binding
from zstandard import backend_c

APP = Path('/Applications/Anki.app/Contents/Resources/app_packages')
PROTO_SHA = 'e263f87352f28d1c0ab144855bedb5e0c287091ff71c305c222758d39dfe087a'
ZSTD = Path('/opt/homebrew/Cellar/zstd/1.5.7_1/bin/zstd')
ZSTD_SHA = 'aff8169fb421bb925fb16c44a7e0143fa2c7a941dc45cce76b15062a2ce54917'
CHUNK = 1024 * 1024
WINDOW_LOG = 27
MAX_OUTPUT_BYTES = 1300000000
MAX_MEMBER_ENCODED_BYTES = 128 * 1024 * 1024
BINDING_VERSION = '0.23.0'
BINDING_WHEEL_SHA = '38302b78a850ff82656beaddeb0bb989a0322a8bbb1bf1ab10c17506681d772a'
BINDING_EXTENSION_SHA = 'abed74ba4c1d96defee82cdd8cc0164063137d5e0f15900bfa037ed8f5637266'
MAX_INDEX = 64 * 1024 * 1024
MAX_ENTRIES = 250000
RESERVE = 128 * 1024 * 1024
sys.path.insert(0, str(APP))
from anki.import_export_pb2 import PackageMetadata, MediaEntries


def digest_stream(stream):
    h = hashlib.sha256()
    while part := stream.read(CHUNK): h.update(part)
    return h.hexdigest()


def pin(path):
    with Path(path).open('rb') as f: digest = digest_stream(f)
    return {'path':str(Path(path).absolute()),'sha256':digest,'bytes':Path(path).stat().st_size}


def identity(s):
    return {k:getattr(s,k) for k in ['st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns']}


def same_file(path, st):
    return identity(os.stat(path, follow_symlinks=False)) == identity(st)


def dump_new(path, value):
    with Path(path).open('x') as f:
        json.dump(value,f,ensure_ascii=False,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())


def bounded_read(stream, maximum):
    out = bytearray()
    while part := stream.read(min(CHUNK, maximum + 1 - len(out))):
        out.extend(part)
        if len(out) > maximum: raise ValueError('bounded metadata limit exceeded')
    return bytes(out)


def safe_alias(name):
    if (not isinstance(name,str) or not name or len(name.encode('utf-8')) > 255 or
        unicodedata.normalize('NFC',name) != name or
        any(ord(c)<32 or c in '\\/:<>"|?*' for c in name) or name.endswith((' ','.')) or
        name in {'.','..'} or re.fullmatch(r'(?i:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?',name)):
        raise ValueError('modern requires canonical safe media aliases; no renaming permitted')


def unique_object(pairs):
    result={}
    for key,value in pairs:
        if key in result: raise ValueError('duplicate media map key')
        result[key]=value
    return result


def stop_process(proc):
    if proc.poll() is None:
        proc.terminate()
        try: proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill();proc.wait(timeout=5)


def dependencies():
    result={}
    for name,path,expected in [('protobuf',APP/'anki/import_export_pb2.pyc',PROTO_SHA),('zstd',ZSTD,ZSTD_SHA)]:
        got=pin(path)
        if got['sha256'] != expected: raise ValueError(name+' dependency pin changed')
        result[name]=got
    if zstd_binding.__version__ != BINDING_VERSION or zstd_binding.backend != 'cext':
        raise ValueError('isolated zstandard binding version/backend differs')
    receipt=json.loads((Path(__file__).resolve().parent/'WHEEL.json').read_text())
    wheel=pin(receipt['wheel']['path']);extension=pin(backend_c.__file__)
    if wheel['sha256']!=BINDING_WHEEL_SHA or extension['sha256']!=BINDING_EXTENSION_SHA:
        raise ValueError('isolated binding wheel/extension pin differs')
    result['binding']={'version':BINDING_VERSION,'wheel':wheel,'extension':extension,
                       'zstd_version':list(zstd_binding.ZSTD_VERSION),'window_log':WINDOW_LOG}
    return result


def check_space(directory, reserve):
    free=shutil.disk_usage(directory).free
    if free < reserve: raise OSError('free space reserve reached; owned partial retained')
    return free


def compress_member_cli(reader, expected_size, work, *, timeout=600, reserve=RESERVE, zstd=ZSTD):
    """Input reader is consumed once. Child stdout is a real file, not a pipe."""
    temp=work/'current.zstd.partial';errors=work/'current.stderr.partial'
    if temp.exists() or errors.exists(): raise FileExistsError('prior member partial exists')
    h256=hashlib.sha256();h1=hashlib.sha1();count=0;started=time.monotonic()
    proc=None;timer=None;timed_out=threading.Event()
    check_space(work,reserve)
    with temp.open('xb') as out, errors.open('xb') as err:
        owned_temp=os.fstat(out.fileno());owned_err=os.fstat(err.fileno())
        try:
            proc=subprocess.Popen([str(zstd),'-q','-c','-9','--single-thread'],stdin=subprocess.PIPE,stdout=out,stderr=err)
            def expire():
                timed_out.set()
                if proc.poll() is None: proc.kill()
            timer=threading.Timer(timeout,expire);timer.daemon=True;timer.start()
            try:
                while raw := reader.read(CHUNK):
                    count += len(raw)
                    if count > expected_size: raise ValueError('source member grew beyond ZIP size')
                    h256.update(raw);h1.update(raw)
                    view=memoryview(raw)
                    while view:
                        n=proc.stdin.write(view)
                        if not n: raise OSError('short/zero child stdin write')
                        view=view[n:]
                    if count % (32*CHUNK) < CHUNK: check_space(work,reserve)
                proc.stdin.close()
                code=proc.wait(timeout=timeout)
                if count != expected_size: raise ValueError('source ZIP member size differs')
                if code or timed_out.is_set(): raise RuntimeError('zstd failed or timed out: '+str(code))
            finally:
                if proc.stdin and not proc.stdin.closed:
                    try: proc.stdin.close()
                    except BrokenPipeError: pass
                stop_process(proc)
            out.flush();os.fsync(out.fileno());err.flush()
        finally:
            if timer is not None: timer.cancel();timer.join(timeout=5)
            if proc is not None: stop_process(proc)
    if os.stat(errors).st_size: raise RuntimeError('unexpected zstd stderr; evidence retained')
    return {'path':temp,'errors':errors,'temp_identity':identity(owned_temp),'err_identity':identity(owned_err),
            'bytes':count,'sha256':h256.hexdigest(),'sha1':h1.digest(),'encoded_bytes':temp.stat().st_size,
            'elapsed_seconds':round(time.monotonic()-started,6),'pid':proc.pid,'process_reaped':proc.poll() is not None}


class BoundedOutput:
    """Preserve file semantics while enforcing private byte and live-free limits."""
    def __init__(self,stream,maximum,directory,reserve):
        self._stream=stream;self._maximum=maximum;self._directory=directory;self._reserve=reserve
    def write(self,raw):
        if self._stream.tell()+len(raw)>self._maximum:
            raise OSError('private output byte cap reached; owned partial retained')
        check_space(self._directory,len(raw)+self._reserve)
        return self._stream.write(raw)
    def __getattr__(self,name):
        return getattr(self._stream,name)


def compress_member(reader, expected_size, work, *, timeout=600, reserve=RESERVE, zstd=ZSTD, window_log=WINDOW_LOG):
    """One independent bounded zstd frame, no per-member codec process.

    The legacy CLI is retained only for the two explicit fake-child contracts.
    A real member uses the pinned official binding, a pledged source size and a
    single-thread context. Deadline checks occur between bounded 1MiB calls.
    """
    if Path(zstd)!=ZSTD:
        return compress_member_cli(reader,expected_size,work,timeout=timeout,reserve=reserve,zstd=zstd)
    if type(expected_size) is not int or expected_size<0 or not 10<=window_log<=27:
        raise ValueError('invalid explicit member size/window bound')
    if timeout<=0:
        raise ValueError('member timeout must be positive')
    temp=work/'current.zstd.partial';errors=work/'current.stderr.partial'
    if temp.exists() or errors.exists():raise FileExistsError('prior member partial exists')
    h256=hashlib.sha256();h1=hashlib.sha1();count=0;started=time.monotonic()
    check_space(work,reserve)
    params=zstd_binding.ZstdCompressionParameters.from_level(
        9,window_log=window_log,threads=0,write_content_size=1,write_checksum=1)
    compressor=zstd_binding.ZstdCompressor(compression_params=params)
    with temp.open('xb') as out,errors.open('xb') as err:
        owned_temp=os.fstat(out.fileno());owned_err=os.fstat(err.fileno())
        guarded=BoundedOutput(out,MAX_MEMBER_ENCODED_BYTES,work,reserve)
        with compressor.stream_writer(guarded,size=expected_size,closefd=False) as writer:
            while raw:=reader.read(CHUNK):
                if time.monotonic()-started>timeout:raise TimeoutError('binding member deadline')
                count+=len(raw)
                if count>expected_size:raise ValueError('source member grew beyond ZIP size')
                h256.update(raw);h1.update(raw)
                if writer.write(raw)!=len(raw):raise OSError('short binding write')
                if count%(32*CHUNK)<CHUNK:check_space(work,reserve)
            if count!=expected_size:raise ValueError('source ZIP member size differs')
        if time.monotonic()-started>timeout:raise TimeoutError('binding member deadline')
        out.flush();os.fsync(out.fileno());err.flush()
    return {'path':temp,'errors':errors,'temp_identity':identity(owned_temp),'err_identity':identity(owned_err),
            'bytes':count,'sha256':h256.hexdigest(),'sha1':h1.digest(),'encoded_bytes':temp.stat().st_size,
            'elapsed_seconds':round(time.monotonic()-started,6),'pid':None,'process_reaped':True,
            'backend':'zstandard-python-cext','codec_subprocesses':0,'level':9,'window_log':window_log}


def zip_info(name, source=None):
    info=zipfile.ZipInfo(name,source.date_time if source else (1980,1,1,0,0,0))
    info.compress_type=zipfile.ZIP_STORED
    if source:
        for attr in ['create_system','external_attr','internal_attr','comment']:
            setattr(info,attr,getattr(source,attr))
    return info


def copy_stream(reader, writer):
    count=0;h=hashlib.sha256()
    while part:=reader.read(CHUNK):
        writer.write(part);count+=len(part);h.update(part)
    return count,h.hexdigest()


def clean_current(result):
    # Only files created by this member are candidates for cleanup. A foreign
    # replacement is never deleted and causes fail-closed evidence retention.
    for key,ikey in [('path','temp_identity'),('errors','err_identity')]:
        path=result[key];now=os.stat(path,follow_symlinks=False)
        before=result[ikey]
        if now.st_dev != before['st_dev'] or now.st_ino != before['st_ino']:
            raise OSError('member temporary ownership changed')
        path.unlink()


def convert(source, expected_sha, expected_bytes, output_dir, fallback, fallback_sha, *, timeout=600, reserve=RESERVE, zstd=ZSTD, max_output_bytes=MAX_OUTPUT_BYTES):
    source=Path(source).absolute();output_dir=Path(output_dir).absolute();fallback=Path(fallback).absolute()
    if not re.fullmatch('[0-9a-f]{64}',expected_sha) or not isinstance(expected_bytes,int) or expected_bytes<=0:
        raise ValueError('explicit source SHA and byte count required')
    if type(max_output_bytes) is not int or max_output_bytes<=0:raise ValueError('positive output cap required')
    dep=dependencies()
    if Path(zstd)!=ZSTD: raise ValueError('non-pinned CLI is test-only via compress_member')
    fd=os.open(source,os.O_RDONLY|os.O_NOFOLLOW)
    source_fp=os.fdopen(fd,'rb');start=time.monotonic();report=None;owned_dir=None
    try:
        before=os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size!=expected_bytes: raise ValueError('source type/bytes mismatch')
        if digest_stream(source_fp)!=expected_sha: raise ValueError('source SHA mismatch')
        source_fp.seek(0)
        with zipfile.ZipFile(source_fp) as incoming:
            infos=incoming.infolist();names=[i.filename for i in infos]
            if len(infos)>MAX_ENTRIES or len(names)!=len(set(names)): raise ValueError('duplicate/too many source ZIP members')
            if any(i.flag_bits&1 for i in infos): raise ValueError('encrypted member unsupported')
            if 'collection.anki2' not in names or any(n in names for n in ['meta','collection.anki21','collection.anki21b']):
                raise ValueError('requires explicit legacy-v4 collection.anki2 input')
            with incoming.open('media') as f: mapping=json.loads(bounded_read(f,MAX_INDEX),object_pairs_hook=unique_object)
            if not isinstance(mapping,dict) or any(not isinstance(k,str) or not re.fullmatch(r'0|[1-9][0-9]*',k) for k in mapping):
                raise ValueError('invalid media map')
            if len(mapping)>MAX_ENTRIES or len(set(mapping.values()))!=len(mapping): raise ValueError('duplicate media aliases')
            for alias in mapping.values():safe_alias(alias)
            original_members=set(mapping)
            if not original_members.issubset(names): raise ValueError('media map member missing')
            if any(incoming.getinfo(n).file_size>0xffffffff for n in original_members):
                raise ValueError('modern media size exceeds protobuf uint32')
            reserved_members=original_members|{'collection.anki2','media'}
            extras=[i for i in infos if i.filename not in reserved_members]
            if any(re.fullmatch('[0-9]+',i.filename) for i in extras): raise ValueError('unmapped numeric extra would collide')
            fallback_info=pin(fallback)
            if fallback_info['sha256']!=fallback_sha or fallback_info['bytes']>1024*1024: raise ValueError('fallback pin/size mismatch')
            with fallback.open('rb') as f:
                if f.read(16)!=b'SQLite format 3\0': raise ValueError('fallback is not pinned SQLite')
            output_dir.mkdir(mode=0o700)
            owned_dir=os.stat(output_dir,follow_symlinks=False)
            work=output_dir/'members';work.mkdir(mode=0o700)
            partial=output_dir/'modern.apkg.partial';final=output_dir/'modern.apkg';ledger_path=output_dir/'members.jsonl'
            raw_total=sum(i.file_size for i in infos)
            largest=max((i.file_size for i in infos),default=0)
            disk={'free_before':check_space(output_dir,reserve),'max_output_bytes':max_output_bytes,'max_member_encoded_bytes':MAX_MEMBER_ENCODED_BYTES,'source_archive_bytes':expected_bytes,
                  'source_decompressed_member_sum':raw_total,'largest_raw_member':largest,
                  'fallback_bytes':fallback_info['bytes'],'reserve_bytes':reserve,
                  'simultaneous_member_temp':'one zstd member; while copying it also exists inside partial ZIP',
                  'reference_scenario_not_upper_bound':int(expected_bytes*1.25)+largest+2*MAX_INDEX+reserve,
                  'reference_scenario_basis':'125% source ZIP size + largest raw member as temp allowance + two 64MiB metadata budgets + reserve; not a promised compression ratio',
                  'strict_whole_output_bound_not_used_as_gate':'unknown until real metadata/bounds assessed; checks use actual temp bytes and live free space'}
            dump_new(output_dir/'STARTED.json',{'source':str(source),'expected_sha256':expected_sha,'identity_before':identity(before),
                                              'compression':{'backend':'zstandard-python-cext','version':BINDING_VERSION,'level':9,'threads':0,'window_log':WINDOW_LOG},'disk':disk,'dependencies':dep})
            entries=MediaEntries();counts={'media':0,'extra':0,'zstd_members':0,'zstd_processes':0};codec_seconds=0.0
            with partial.open('xb') as output, ledger_path.open('x') as ledger:
                output=BoundedOutput(output,max_output_bytes,output_dir,reserve)
                owned_output=os.fstat(output.fileno())
                with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_STORED,allowZip64=True) as outgoing:
                    outgoing.comment=incoming.comment
                    outgoing.writestr(zip_info('meta'),PackageMetadata(version=PackageMetadata.VERSION_LATEST).SerializeToString())
                    def emit_compressed(old_name,new_name,reader,size,kind,original_info=None):
                        nonlocal codec_seconds
                        result=compress_member(reader,size,work,timeout=timeout,reserve=reserve)
                        check_space(output_dir,result['encoded_bytes']+reserve)
                        with result['path'].open('rb') as f,outgoing.open(zip_info(new_name,original_info),'w',force_zip64=True) as dest:
                            written,_=copy_stream(f,dest)
                        if written!=result['encoded_bytes']:raise OSError('temporary copy length differs')
                        counts['zstd_members']+=1;counts['zstd_processes']+=result.get('codec_subprocesses',1);codec_seconds+=result['elapsed_seconds']
                        row={k:result[k] for k in ['bytes','sha256','encoded_bytes','elapsed_seconds','pid','process_reaped']}
                        row.update({'kind':kind,'source_member':old_name,'modern_member':new_name,'sha1':result['sha1'].hex()})
                        ledger.write(json.dumps(row,ensure_ascii=False)+'\n');ledger.flush()
                        clean_current(result)
                        return result
                    info=incoming.getinfo('collection.anki2')
                    with incoming.open(info) as f:collection=emit_compressed('collection.anki2','collection.anki21b',f,info.file_size,'collection',info)
                    with fallback.open('rb') as f,outgoing.open(zip_info('collection.anki2'),'w',force_zip64=True) as dest:
                        copied,dummy_sha=copy_stream(f,dest)
                    if copied!=fallback_info['bytes'] or dummy_sha!=fallback_sha:raise ValueError('fallback changed during read')
                    for index,(old_member,alias) in enumerate(sorted(mapping.items(),key=lambda pair:int(pair[0]))):
                        info=incoming.getinfo(old_member)
                        with incoming.open(info) as f:result=emit_compressed(old_member,str(index),f,info.file_size,'media',info)
                        entries.entries.add(name=alias,size=result['bytes'],sha1=result['sha1'])
                        counts['media']+=1
                    if entries.ByteSize()>MAX_INDEX:raise ValueError('modern media index exceeds metadata budget')
                    index_raw=entries.SerializeToString()
                    emit_compressed('media','media',io.BytesIO(index_raw),len(index_raw),'protobuf-media-index')
                    for info in extras:
                        check_space(output_dir,info.file_size+reserve)
                        with incoming.open(info) as f,outgoing.open(zip_info(info.filename,info),'w',force_zip64=True) as dest:
                            size,digest=copy_stream(f,dest)
                        if size!=info.file_size:raise ValueError('extra size mismatch')
                        ledger.write(json.dumps({'kind':'extra','source_member':info.filename,'modern_member':info.filename,'bytes':size,'sha256':digest})+'\n')
                        counts['extra']+=1
                output.flush();os.fsync(output.fileno());ledger.flush();os.fsync(ledger.fileno())
                if not same_file(partial,os.fstat(output.fileno())):raise OSError('output partial ownership changed')
                output.seek(0) if output.readable() else None
            # Full source raw SHA + identity recheck after all compressed reads.
            source_fp.seek(0);after_sha=digest_stream(source_fp);after=os.fstat(fd)
            if after_sha!=expected_sha or identity(before)!=identity(after) or not same_file(source,after):
                raise ValueError('source changed; no final published')
            partial_pin=pin(partial);st=os.stat(partial,follow_symlinks=False)
            if (st.st_dev,st.st_ino)!=(owned_output.st_dev,owned_output.st_ino):raise OSError('partial replaced before publish')
            # No-replace hardlink; keep the owned partial too, so cleanup cannot
            # unlink a concurrently replaced path. Both names use one disk object.
            os.link(partial,final,follow_symlinks=False)
            final_stat=os.stat(final,follow_symlinks=False)
            if (final_stat.st_dev,final_stat.st_ino)!=(owned_output.st_dev,owned_output.st_ino):raise OSError('published ownership mismatch')
            directory_fd=os.open(output_dir,os.O_RDONLY)
            try:os.fsync(directory_fd)
            finally:os.close(directory_fd)
            report={'schema':'study-modern-stream-conversion.v1','status':'COMPLETE','source':{'path':str(source),'sha256':expected_sha,'bytes':expected_bytes},
                    'source_identity_before':identity(before),'source_identity_after':identity(after),'input_sha256_before_after_equal':True,
                    'modern':{**partial_pin,'path':str(final)},'partial_retained_as_same_inode':str(partial),
                    'counts':counts,'collection_logical':{k:collection[k] for k in ['bytes','sha256','encoded_bytes']},
                    'ledger':pin(ledger_path),'codec_elapsed_seconds_sum':round(codec_seconds,6),'elapsed_seconds':round(time.monotonic()-start,6),
                    'payload_chunk_bytes':CHUNK,'metadata_cap_bytes':MAX_INDEX,'disk':disk,'free_after':shutil.disk_usage(output_dir).free,
                    'all_zstd_processes_reaped':True,'native_export_used':False,'semantic_payload_changed':False,'independent_verification_pending':True}
            dump_new(output_dir/'COMPLETE.json',report)
            return report
    except BaseException as exc:
        if (owned_dir is not None and output_dir.is_dir() and
            (os.stat(output_dir,follow_symlinks=False).st_dev,os.stat(output_dir,follow_symlinks=False).st_ino)==(owned_dir.st_dev,owned_dir.st_ino) and
            not (output_dir/'FAILED.json').exists()):
            try:dump_new(output_dir/'FAILED.json',{'status':'FAILED','type':type(exc).__name__,'error':str(exc),'partial_evidence_retained':True})
            except Exception:pass
        raise
    finally:source_fp.close()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',required=True,type=Path);p.add_argument('--expected-source-sha256',required=True)
    p.add_argument('--expected-source-bytes',required=True,type=int);p.add_argument('--output-dir',required=True,type=Path)
    p.add_argument('--fallback',required=True,type=Path);p.add_argument('--expected-fallback-sha256',required=True)
    p.add_argument('--max-output-bytes',type=int,default=MAX_OUTPUT_BYTES)
    p.add_argument('--member-timeout',type=int,default=600);p.add_argument('--free-reserve-bytes',type=int,default=RESERVE)
    a=p.parse_args()
    r=convert(a.source,a.expected_source_sha256,a.expected_source_bytes,a.output_dir,a.fallback,a.expected_fallback_sha256,
              timeout=a.member_timeout,reserve=a.free_reserve_bytes,max_output_bytes=a.max_output_bytes)
    print(json.dumps({'status':r['status'],'modern':r['modern'],'counts':r['counts'],'elapsed_seconds':r['elapsed_seconds']}))
