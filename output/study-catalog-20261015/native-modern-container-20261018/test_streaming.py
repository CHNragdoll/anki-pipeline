"""Only bounded synthetic fixtures; no Collection, GUI, real APKG, or PG."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
import stream_convert as sc
import independent_verify as iv
SOURCE=ROOT/'fixtures/source-legacy.apkg'
FALLBACK=ROOT/'fixtures/fallback.anki2'
SOURCE_SHA='984ebbda2292e50f0f0d6df30c885ae962f3a2ccb738937d5a3587400c391666'
FALLBACK_SHA='002eb310edeb31bd32829516752f68b0ea6f027be12e2667cde2dbb33ad500e5'

class LazyBoundedReader:
    def __init__(self,size):self.remaining=size;self.calls=0;self.maximum_request=0
    def read(self,n):
        if n<=0 or n>sc.CHUNK:raise AssertionError('unbounded payload read')
        self.maximum_request=max(self.maximum_request,n);self.calls+=1
        take=min(n,self.remaining);self.remaining-=take
        return b'X'*take

class StreamingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases=ROOT/'cases-full-final';cls.cases.mkdir()
        cls.good=cls.cases/'small-success'
        cls.result=sc.convert(SOURCE,SOURCE_SHA,19949,cls.good,FALLBACK,FALLBACK_SHA)
        cls.verified=iv.verify(SOURCE,SOURCE_SHA,19949,cls.good/'modern.apkg',cls.result['modern']['sha256'],cls.result['modern']['bytes'],FALLBACK,FALLBACK_SHA)
        sc.dump_new(cls.good/'INDEPENDENT.json',cls.verified)

    def test_private_output_cap_refuses_extra_byte_without_writing(self):
        f=io.BytesIO();out=sc.BoundedOutput(f,4,self.cases,0)
        self.assertEqual(out.write(b'abcd'),4)
        with self.assertRaisesRegex(OSError,'byte cap'):
            out.write(b'e')
        self.assertEqual(f.getvalue(),b'abcd')
        out.seek(0);self.assertEqual(out.write(b'xy'),2)
        self.assertEqual(f.getvalue(),b'xycd')

    def test_live_reserve_refuses_write_without_mutation(self):
        f=io.BytesIO();out=sc.BoundedOutput(f,100,self.cases,sc.RESERVE)
        with patch.object(sc,'check_space',side_effect=OSError('free space reserve')):
            with self.assertRaisesRegex(OSError,'reserve'):
                out.write(b'x')
        self.assertEqual(f.getvalue(),b'')

    def test_real_stream_converter_and_independent_decoder(self):
        self.assertEqual(self.verified['status'],'PASS')
        self.assertEqual(self.verified['media_count'],7)
        self.assertTrue(self.verified['all_original_sqlite_bytes_exact'])
        self.assertTrue(self.verified['all_original_extra_bytes_exact'])
        self.assertTrue(self.verified['all_media_aliases_raw_bytes_size_sha1_exact'])
        self.assertEqual(self.result['counts']['zstd_members'],9)
        self.assertEqual(self.result['counts']['zstd_processes'],0)
        self.assertTrue(self.result['all_zstd_processes_reaped'])
        self.assertEqual(os.stat(self.good/'modern.apkg').st_ino,os.stat(self.good/'modern.apkg.partial').st_ino)

    def test_payload_reader_requests_never_exceed_one_mib(self):
        d=self.cases/'bounded-reader';d.mkdir();size=3*sc.CHUNK+31
        reader=LazyBoundedReader(size)
        result=sc.compress_member(reader,size,d)
        self.assertEqual(reader.maximum_request,sc.CHUNK)
        self.assertGreater(reader.calls,3)
        with result['path'].open('rb') as f:decoded=iv.decoded_check(f,LazyBoundedReader(size))
        self.assertEqual(decoded['bytes'],size)
        self.assertTrue(decoded['process_reaped'])
        sc.clean_current(result)

    def test_wrong_pin_creates_no_output(self):
        dest=self.cases/'wrong-pin'
        with self.assertRaisesRegex(ValueError,'source SHA mismatch'):
            sc.convert(SOURCE,'0'*64,19949,dest,FALLBACK,FALLBACK_SHA)
        self.assertFalse(dest.exists())

    def test_existing_foreign_output_directory_is_untouched(self):
        dest=self.cases/'foreign';dest.mkdir();(dest/'keep').write_bytes(b'foreign')
        with self.assertRaises(FileExistsError):sc.convert(SOURCE,SOURCE_SHA,19949,dest,FALLBACK,FALLBACK_SHA)
        self.assertEqual(sorted(x.name for x in dest.iterdir()),['keep'])
        self.assertEqual((dest/'keep').read_bytes(),b'foreign')

    def test_failure_retains_partial_without_final(self):
        dest=self.cases/'failure'
        with patch.object(sc,'compress_member',side_effect=RuntimeError('injected member failure')):
            with self.assertRaisesRegex(RuntimeError,'injected'):
                sc.convert(SOURCE,SOURCE_SHA,19949,dest,FALLBACK,FALLBACK_SHA)
        self.assertTrue((dest/'modern.apkg.partial').is_file())
        self.assertTrue((dest/'FAILED.json').is_file())
        self.assertFalse((dest/'modern.apkg').exists())

    def test_source_identity_change_refuses_publication(self):
        copied=self.cases/'mutating.apkg';shutil.copyfile(SOURCE,copied)
        dest=self.cases/'mutating-output';original=sc.clean_current;changed=False
        def cleanup(r):
            nonlocal changed
            original(r)
            if not changed:
                changed=True;s=os.stat(copied);os.utime(copied,ns=(s.st_atime_ns,s.st_mtime_ns+1000000))
        with patch.object(sc,'clean_current',side_effect=cleanup):
            with self.assertRaisesRegex(ValueError,'source changed'):
                sc.convert(copied,SOURCE_SHA,19949,dest,FALLBACK,FALLBACK_SHA)
        self.assertFalse((dest/'modern.apkg').exists())
        self.assertTrue((dest/'modern.apkg.partial').exists())

    def test_concurrent_foreign_final_is_not_overwritten(self):
        dest=self.cases/'foreign-final';real_link=os.link
        def injected(source,target,**kw):
            Path(target).write_bytes(b'foreign winner')
            return real_link(source,target,**kw)
        with patch.object(sc.os,'link',side_effect=injected):
            with self.assertRaises(FileExistsError):sc.convert(SOURCE,SOURCE_SHA,19949,dest,FALLBACK,FALLBACK_SHA)
        self.assertEqual((dest/'modern.apkg').read_bytes(),b'foreign winner')
        self.assertTrue((dest/'modern.apkg.partial').exists())
        self.assertFalse((dest/'COMPLETE.json').exists())

    def _fake_cli(self,folder,sleep):
        folder.mkdir();pid=folder/'child.pid';exe=folder/'fake-zstd'
        exe.write_text('#!'+sys.executable+'\nimport os,time,sys\nfrom pathlib import Path\nPath('+repr(str(pid))+').write_text(str(os.getpid()))\ntime.sleep('+repr(sleep)+')\nsys.stderr.write("injected error")\nsys.exit(7)\n')
        exe.chmod(0o700);return exe,pid

    def test_failed_child_is_reaped_and_partial_retained(self):
        folder=self.cases/'child-failure';exe,pid=self._fake_cli(folder,0)
        with self.assertRaises(Exception):sc.compress_member(io.BytesIO(b'x'),1,folder,zstd=exe)
        child=int(pid.read_text())
        with self.assertRaises(ProcessLookupError):os.kill(child,0)
        self.assertTrue((folder/'current.zstd.partial').exists())

    def test_timed_out_child_is_reaped(self):
        folder=self.cases/'child-timeout';exe,pid=self._fake_cli(folder,2)
        launched=[];real_popen=sc.subprocess.Popen
        def observed(*args,**kwargs):
            proc=real_popen(*args,**kwargs);launched.append(proc);return proc
        with patch.object(sc.subprocess,'Popen',side_effect=observed):
            with self.assertRaises(Exception):sc.compress_member(io.BytesIO(b'x'),1,folder,zstd=exe,timeout=.2)
        self.assertEqual(len(launched),1)
        child=launched[0].pid
        self.assertIsNotNone(launched[0].poll())
        with self.assertRaises(ProcessLookupError):os.kill(child,0)
        self.assertTrue((folder/'current.zstd.partial').exists())

    def test_independent_byte_compare_rejects_tampering(self):
        import zipfile
        target=self.cases/'tampered.apkg'
        with zipfile.ZipFile(self.good/'modern.apkg') as old,zipfile.ZipFile(target,'x') as new:
            for info in old.infolist():
                raw=old.read(info.filename)
                if info.filename=='0':raw=b'not zstd'
                new.writestr(info,raw)
        p=sc.pin(target)
        with self.assertRaises(Exception):iv.verify(SOURCE,SOURCE_SHA,19949,target,p['sha256'],p['bytes'],FALLBACK,FALLBACK_SHA)

if __name__=='__main__':unittest.main(verbosity=2)
