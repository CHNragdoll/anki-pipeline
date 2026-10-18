"""Read-only streaming modern APKG verifier. Does not import stream_convert.

Uses its own bounded mature-binding stream reader, never encoder helpers. Each
decoded byte is compared with source ZipExtFile chunks. No large payload buffering.
"""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
import zstandard as zstd_binding

CHUNK=1024*1024
INDEX_LIMIT=64*1024*1024
ZSTD='/opt/homebrew/Cellar/zstd/1.5.7_1/bin/zstd'
sys.path.insert(0,'/Applications/Anki.app/Contents/Resources/app_packages')
from anki.import_export_pb2 import PackageMetadata,MediaEntries


def sha_stream(f):
    h=hashlib.sha256()
    while raw:=f.read(CHUNK):h.update(raw)
    return h.hexdigest()

def ident(st):return [st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns]

def bounded(f,limit):
    out=bytearray()
    while raw:=f.read(min(CHUNK,limit+1-len(out))):
        out.extend(raw)
        if len(out)>limit:raise ValueError('index decompression limit')
    return bytes(out)

def decoded_check(compressed, expected=None, *, capture_limit=None, timeout=600):
    """Independent bounded decoder; no per-file processes or encoder imports."""
    count=0;h=hashlib.sha256();h1=hashlib.sha1();captured=bytearray();start=time.monotonic()
    decoder=zstd_binding.ZstdDecompressor(max_window_size=128*1024*1024)
    with decoder.stream_reader(compressed,read_size=CHUNK,read_across_frames=True,closefd=False) as reader:
        while raw:=reader.read(CHUNK):
            if time.monotonic()-start>timeout:raise TimeoutError('independent decoder deadline')
            count+=len(raw);h.update(raw);h1.update(raw)
            if expected is not None and expected.read(len(raw))!=raw:raise ValueError('decoded bytes differ from original source')
            if capture_limit is not None:
                if count>capture_limit:raise ValueError('decoded metadata exceeds cap')
                captured.extend(raw)
    if expected is not None and expected.read(1):raise ValueError('decoded payload truncated')
    return {'bytes':count,'sha256':h.hexdigest(),'sha1':h1.digest(),'captured':bytes(captured),
            'pid':None,'process_reaped':True,'decoder_backend':'independent-zstandard-stream-reader','decoder_subprocesses':0}


def raw_equal(a,b):
    h=hashlib.sha256();count=0
    while raw:=a.read(CHUNK):
        if b.read(len(raw))!=raw:raise ValueError('raw extra/fallback bytes differ')
        count+=len(raw);h.update(raw)
    if b.read(1):raise ValueError('raw destination has extra bytes')
    return count,h.hexdigest()


def verify(source, source_sha, source_bytes, candidate, candidate_sha, candidate_bytes, fallback, fallback_sha):
    start=time.monotonic();fds=[];streams=[];opened=[]
    try:
        for path,expected,expected_size in [(source,source_sha,source_bytes),(candidate,candidate_sha,candidate_bytes)]:
            path=Path(path).absolute();fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW);f=os.fdopen(fd,'rb');streams.append(f)
            before=os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or before.st_size!=expected_size or sha_stream(f)!=expected:raise ValueError('archive source/candidate pin mismatch')
            f.seek(0);opened.append((path,expected,ident(before)));fds.append(fd)
        with zipfile.ZipFile(streams[0]) as old,zipfile.ZipFile(streams[1]) as new:
            if len(new.namelist())!=len(set(new.namelist())):raise ValueError('duplicate modern member')
            if any(x.compress_type!=zipfile.ZIP_STORED for x in new.infolist()):raise ValueError('modern members must be ZIP Stored')
            if old.comment!=new.comment:raise ValueError('archive comment changed')
            metadata=PackageMetadata.FromString(new.read('meta'))
            if metadata.version!=PackageMetadata.VERSION_LATEST:raise ValueError('wrong modern version')
            with old.open('media') as f:media=json.loads(bounded(f,INDEX_LIMIT))
            with new.open('media') as f:decoded=decoded_check(f,capture_limit=INDEX_LIMIT)
            entries=MediaEntries.FromString(decoded['captured'])
            pairs=sorted(media.items(),key=lambda row:int(row[0]))
            if len(entries.entries)!=len(pairs):raise ValueError('media count differs')
            expected_names={'meta','media','collection.anki21b','collection.anki2'}|{str(i) for i in range(len(pairs))}
            original_reserved={'media','collection.anki2'}|set(media)
            extras=set(old.namelist())-original_reserved;expected_names|=extras
            if set(new.namelist())!=expected_names:raise ValueError('member set differs')
            with old.open('collection.anki2') as expected,new.open('collection.anki21b') as actual:
                collection=decoded_check(actual,expected)
            rows=[];all_sha=hashlib.sha256()
            for i,((member,alias),entry) in enumerate(zip(pairs,entries.entries)):
                if entry.name!=alias or entry.HasField('legacy_zip_filename'):raise ValueError('media alias/index changed')
                with old.open(member) as expected,new.open(str(i)) as actual:result=decoded_check(actual,expected)
                if result['bytes']!=entry.size or result['sha1']!=entry.sha1:raise ValueError('media size/SHA1 metadata differs')
                # Store only a rolling digest here. A converter ledger already
                # carries per-file pins; no full collection/media payload table.
                row=json.dumps([member,str(i),alias,result['bytes'],result['sha256']],ensure_ascii=False,separators=(',',':')).encode()
                all_sha.update(row+b'\n')
            for name in sorted(extras):
                with old.open(name) as a,new.open(name) as b:raw_equal(a,b)
            with Path(fallback).open('rb') as f:
                if sha_stream(f)!=fallback_sha:raise ValueError('fallback pin changed')
                f.seek(0)
                with new.open('collection.anki2') as b:raw_equal(f,b)
        for f,(path,expected,before) in zip(streams,opened):
            f.seek(0)
            if sha_stream(f)!=expected or ident(os.fstat(f.fileno()))!=before or ident(os.stat(path,follow_symlinks=False))!=before:
                raise ValueError('archive changed during independent verification')
        return {'schema':'study-modern-stream-independent.v1','status':'PASS','source_sha256':source_sha,'candidate_sha256':candidate_sha,
                'sqlite':{k:collection[k] for k in ['bytes','sha256']},'media_count':len(pairs),'extra_count':len(extras),
                'all_media_aliases_raw_bytes_size_sha1_exact':True,'per_media_checks_rolling_sha256':all_sha.hexdigest(),
                'all_original_sqlite_bytes_exact':True,'all_original_extra_bytes_exact':True,'source_candidate_before_after_identity_sha_exact':True,
                'payload_chunk_bytes':CHUNK,'index_limit_bytes':INDEX_LIMIT,'all_decoder_processes_and_threads_reaped':True,
                'decoder_backend':'independent-zstandard-stream-reader','decoder_subprocesses':0,
                'elapsed_seconds':round(time.monotonic()-start,6)}
    finally:
        for f in streams:f.close()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['source','candidate','fallback','report']:p.add_argument('--'+name,required=True,type=Path)
    for name in ['source','candidate','fallback']:p.add_argument('--expected-'+name+'-sha256',required=True)
    p.add_argument('--expected-source-bytes',required=True,type=int);p.add_argument('--expected-candidate-bytes',required=True,type=int)
    a=p.parse_args()
    if a.report.exists():raise FileExistsError(a.report)
    r=verify(a.source,a.expected_source_sha256,a.expected_source_bytes,a.candidate,a.expected_candidate_sha256,a.expected_candidate_bytes,a.fallback,a.expected_fallback_sha256)
    with a.report.open('x') as f:json.dump(r,f,ensure_ascii=False,indent=2);f.write('\n')
    print(json.dumps(r))
