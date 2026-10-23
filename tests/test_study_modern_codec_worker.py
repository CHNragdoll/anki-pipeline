"""Tiny actual codec subprocesses; no PostgreSQL, SDK, GUI or user files."""
from contextlib import closing,nullcontext,redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import resource
import sqlite3
import sys
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch
import zipfile

import zstandard
from anki_pipeline import study_catalog_export as exporter
from anki_pipeline import study_modern_codec_worker as worker
from anki_pipeline.study_modern_recompress import RecompressionLimits


class ModernCodecWorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve()
        with closing(sqlite3.connect(':memory:')) as db:
            db.execute('create table source(value blob)')
            db.execute('insert into source values(?)',(b'original\x00sqlite\xff',))
            db.commit();self.sqlite=db.serialize()
        self.audio=b'ID3'+bytes(range(256))*20
        self.source=self.root/'source.apkg'
        with zipfile.ZipFile(self.source,'x',compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('collection.anki2',self.sqlite)
            archive.writestr('media',json.dumps({'4':'声音.mp3'},ensure_ascii=False))
            archive.writestr('4',self.audio)
            archive.writestr('extra.txt',b'original extra')
        self.report={'format':'apkg','bytes':self.source.stat().st_size,
                     'sha256':hashlib.sha256(self.source.read_bytes()).hexdigest(),'notes':1}

    def test_parent_lifetime_highwater_does_not_poison_actual_codec_processes(self):
        highwater=600*1024**2//(1 if sys.platform=='darwin' else 1024)
        destination=self.root/'result.apkg';events=[]
        with patch.object(resource,'getrusage',return_value=types.SimpleNamespace(ru_maxrss=highwater)):
            result=exporter._modern_container(self.source,destination,self.report,events.append)
        self.assertTrue(result['container']['source_identity_sha256_unchanged'])
        self.assertEqual(result['sha256'],hashlib.sha256(destination.read_bytes()).hexdigest())
        self.assertEqual([e['stage'] for e in events],['modern-container-convert','modern-container-recompress'])
        with zipfile.ZipFile(destination) as archive:
            self.assertEqual(archive.read('meta'),b'\x08\x03')
            self.assertEqual(zstandard.ZstdDecompressor().decompress(archive.read('collection.anki21b')),self.sqlite)
            self.assertEqual(zstandard.ZstdDecompressor().decompress(archive.read('0')),self.audio)
            self.assertEqual(archive.read('extra.txt'),b'original extra')
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(),self.report['sha256'])



    def test_child_guards_and_errors_remain_strict_and_stdout_stays_clean(self):
        destination=self.root/'blocked.apkg';captured=io.StringIO()
        limits=RecompressionLimits(wall_seconds=30,rss_bytes=512*1024**2,free_bytes=0,
            output_bytes=8*1024**2,member_encoded_bytes=4*1024**2,member_raw_bytes=4*1024**2)
        with redirect_stdout(captured),self.assertRaisesRegex(ValueError,'worker failed.*|source SHA256 differs'):
            worker.run_codec('convert',self.source,destination,expected_source_sha256='0'*64,limits=limits)
        self.assertEqual(captured.getvalue(),'');self.assertFalse(destination.exists());self.assertTrue(self.source.exists())
        # Parent reports zero; an actual fresh child must still reject a one-byte
        # RSS limit, demonstrating that its budget check has not been removed.
        tiny=RecompressionLimits(wall_seconds=30,rss_bytes=1,free_bytes=0)
        with patch.object(resource,'getrusage',return_value=types.SimpleNamespace(ru_maxrss=0)),self.assertRaisesRegex(ValueError,'RSS budget exceeded'):
            worker.run_codec('convert',self.source,destination,expected_source_sha256=self.report['sha256'],limits=tiny)
        self.assertFalse(destination.exists())

    def test_subprocess_uses_fixed_module_cwd_and_exact_timeout(self):
        limits=RecompressionLimits(wall_seconds=13,rss_bytes=512*1024**2,free_bytes=0)
        with patch.object(worker.subprocess,'run',side_effect=subprocess.TimeoutExpired('codec',13)) as run:
            with self.assertRaisesRegex(TimeoutError,'wall budget'):
                worker.run_codec('convert',self.source,self.root/'unused.apkg',
                    expected_source_sha256=self.report['sha256'],limits=limits,expected_source_bytes=self.report['bytes'])
        args,kwargs=run.call_args
        self.assertEqual(args[0],[sys.executable,'-B','-m','anki_pipeline.study_modern_codec_worker'])
        self.assertEqual(kwargs['cwd'],Path(worker.__file__).resolve().parent.parent)
        self.assertEqual(kwargs['timeout'],13);self.assertEqual(kwargs['stdout'],subprocess.PIPE);self.assertEqual(kwargs['stderr'],subprocess.PIPE)
        request=json.loads(kwargs['input']);self.assertEqual(request['limits']['rss_bytes'],512*1024**2)
        self.assertEqual(request['options'],{'expected_source_bytes':self.report['bytes']})
        with patch.object(worker.subprocess,'run') as run,self.assertRaisesRegex(ValueError,'unsupported codec operation'):
            worker.run_codec('exec',self.source,self.root/'unused.apkg',expected_source_sha256=self.report['sha256'])
        run.assert_not_called()


    def test_cli_returns_error_json_without_final_publication(self):
        from anki_pipeline import study_catalog_cli as cli
        destination=self.root/'not-published.apkg'
        limits=RecompressionLimits(wall_seconds=30,rss_bytes=512*1024**2,free_bytes=0)
        def failed_export(*args,**kwargs):
            return worker.run_codec('convert',self.source,destination,
                expected_source_sha256='0'*64,limits=limits)
        for bad_json in (False,True):
            with self.subTest(bad_json=bad_json):
                captured=io.StringIO()
                response=subprocess.CompletedProcess([],0,stdout='not JSON',stderr='')
                context=patch.object(worker.subprocess,'run',return_value=response) if bad_json else nullcontext()
                with context,patch.object(exporter,'export_book',side_effect=failed_export),redirect_stdout(captured):
                    code=cli.main(['export','--book','synthetic','--format','apkg-modern','--output',str(destination)])
                self.assertEqual(code,2);error=json.loads(captured.getvalue())
                self.assertFalse(error['ok']);self.assertEqual(error['error'],'ValueError')
                self.assertFalse(destination.exists());self.assertFalse((self.root/'COMPLETE.json').exists())
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(),self.report['sha256'])

if __name__=='__main__':unittest.main(verbosity=2)


