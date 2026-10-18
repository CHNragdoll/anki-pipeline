"""Synthetic legacy containers; no collection import, app or user database."""
import hashlib
from contextlib import closing
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

import zstandard as zstd
from anki_pipeline import study_modern_convert as convert
from anki_pipeline.study_modern_recompress import RecompressionLimits

try:
    from anki.import_export_pb2 import PackageMetadata,MediaEntries
except ImportError:
    PackageMetadata=MediaEntries=None


class ModernConvertTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.limits=RecompressionLimits(wall_seconds=30,rss_bytes=512*1024**2,free_bytes=0,
            output_bytes=8*1024**2,member_encoded_bytes=4*1024**2,member_raw_bytes=4*1024**2)
        with closing(sqlite3.connect(':memory:')) as db:
            db.execute('create table original(value blob)');db.execute('insert into original values(?)',(b'\x00source\xff',))
            db.commit()
            self.sqlite=db.serialize()
        with closing(sqlite3.connect(':memory:')) as db:
            db.execute('create table notice(message text)');self.fallback=db.serialize()

    def package(self,*,mapping=None,changes=None,duplicate=False):
        mapping={'7':'原音频.mp3','2':'voice.bin'} if mapping is None else mapping
        values={'collection.anki2':self.sqlite,'media':json.dumps(mapping,ensure_ascii=False).encode(),
                '7':b'ID3'+bytes(range(256))*2000,'2':b'\x00\xffaudio bytes','extra/readme.txt':b'exact extra\x00\xff'}
        values.update(changes or {})
        path=self.root/('source-'+str(len(list(self.root.glob('source*'))))+'.apkg')
        with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            archive.comment=b'original archive comment'
            for name,raw in values.items():
                info=zipfile.ZipInfo(name,(2026,10,19,1,2,4));info.comment=b'original entry comment'
                info.compress_type=zipfile.ZIP_DEFLATED
                with archive.open(info,'w',force_zip64=True) as stream:stream.write(raw)
            if duplicate:
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore');archive.writestr('7',values['7'])
        return path,values

    def run_convert(self,source,**kwargs):
        return convert.convert_legacy_apkg(source,self.root/'modern.apkg',
            expected_source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
            limits=self.limits,fallback_collection=self.fallback,**kwargs)

    def test_every_original_payload_is_lossless_and_container_is_standard(self):
        source,values=self.package();before=source.read_bytes()
        report=self.run_convert(source,expected_source_bytes=len(before));destination=self.root/'modern.apkg'
        self.assertEqual(report['status'],'COMPLETE');self.assertTrue(report['source_identity_sha256_unchanged'])
        self.assertEqual(report['output_sha256'],hashlib.sha256(destination.read_bytes()).hexdigest())
        self.assertEqual(report['output_bytes'],destination.stat().st_size)
        self.assertEqual(report['media_count'],2);self.assertEqual(report['extra_count'],1)
        self.assertEqual(source.read_bytes(),before)
        with zipfile.ZipFile(source) as old,zipfile.ZipFile(destination) as modern:
            self.assertEqual(modern.comment,old.comment)
            self.assertEqual(set(modern.namelist()),{'meta','collection.anki21b','collection.anki2','media','0','1','extra/readme.txt'})
            self.assertEqual(modern.read('meta'),b'\x08\x03')
            self.assertTrue(all(info.compress_type==zipfile.ZIP_STORED for info in modern.infolist()))
            self.assertEqual(modern.read('collection.anki2'),self.fallback)
            self.assertEqual(modern.read('extra/readme.txt'),values['extra/readme.txt'])
            for new,original in [('collection.anki21b','collection.anki2'),('0','2'),('1','7')]:
                encoded=modern.read(new);header=zstd.get_frame_parameters(encoded)
                self.assertTrue(header.has_checksum);self.assertEqual(header.content_size,len(values[original]))
                self.assertLessEqual(header.window_size,1<<27)
                self.assertEqual(zstd.ZstdDecompressor().decompress(encoded),values[original])
                self.assertEqual(modern.getinfo(new).comment,old.getinfo(original).comment)
        self.assertFalse(list(Path(report['work_directory']).glob('member-*')))

    @unittest.skipIf(PackageMetadata is None,'requires official Anki protobuf reader on test PYTHONPATH')
    def test_official_reader_accepts_version_and_media_entries(self):
        source,values=self.package();self.run_convert(source)
        with zipfile.ZipFile(self.root/'modern.apkg') as archive:
            meta=PackageMetadata.FromString(archive.read('meta'))
            self.assertEqual(meta.version,PackageMetadata.VERSION_LATEST)
            entries=MediaEntries.FromString(zstd.ZstdDecompressor().decompress(archive.read('media'))).entries
            self.assertEqual([entry.name for entry in entries],['voice.bin','原音频.mp3'])
            for entry,old in zip(entries,['2','7']):
                self.assertEqual(entry.size,len(values[old]));self.assertEqual(entry.sha1,hashlib.sha1(values[old]).digest())
                self.assertFalse(entry.HasField('legacy_zip_filename'))

    def test_default_fallback_has_one_stable_upgrade_notice(self):
        source,_=self.package()
        result=convert.convert_legacy_apkg(source,self.root/'modern.apkg',
            expected_source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),limits=self.limits)
        with zipfile.ZipFile(self.root/'modern.apkg') as archive:raw=archive.read('collection.anki2')
        with closing(sqlite3.connect(':memory:')) as db:
            db.deserialize(raw);self.assertEqual(db.execute('select count(*) from notes').fetchone()[0],1)
            self.assertEqual(db.execute('select count(*) from cards').fetchone()[0],1)
            self.assertIn('升级',db.execute('select flds from notes').fetchone()[0])
        self.assertEqual(raw,convert._fallback_collection())
        self.assertEqual(result['fallback_sha256'],hashlib.sha256(raw).hexdigest())

    def test_empty_media_and_empty_payload_are_supported(self):
        source,_=self.package(mapping={},changes={'media':b'{}','2':b'extra numeric'})
        # Unmapped numeric members cannot be silently dropped or reassigned.
        with self.assertRaises(ValueError):self.run_convert(source)
        empty=self.root/'empty-media.apkg'
        with zipfile.ZipFile(empty,'w') as archive:
            archive.writestr('collection.anki2',self.sqlite);archive.writestr('media',b'{}')
        report=convert.convert_legacy_apkg(empty,self.root/'empty-modern.apkg',limits=self.limits,
            expected_source_sha256=hashlib.sha256(empty.read_bytes()).hexdigest(),fallback_collection=self.fallback)
        self.assertEqual(report['media_count'],0)
        with zipfile.ZipFile(self.root/'empty-modern.apkg') as archive:
            self.assertEqual(zstd.ZstdDecompressor().decompress(archive.read('media')),b'')
        source,_=self.package(mapping={'2':'empty.bin','7':'voice.mp3'},changes={'2':b''})
        self.run_convert(source)
        with zipfile.ZipFile(self.root/'modern.apkg') as archive:
            self.assertEqual(zstd.ZstdDecompressor().decompress(archive.read('0')),b'')

    def test_bad_maps_reserved_names_duplicate_and_encryption_fail_closed(self):
        cases=({'media':b'{"2":"a","2":"b"}'},{'media':b'[]'},
               {'media':b'{"02":"a"}'},{'media':b'{"99":"missing"}'},
               {'media':b'{"2":"same","7":"same"}'},{'media':b'{"2":"../escape","7":"ok"}'},
               {'meta':b'\x08\x03'},{'collection.anki21b':b'modern input'})
        for changes in cases:
            with self.subTest(changes=changes):
                source,_=self.package(changes=changes)
                with self.assertRaises(ValueError):self.run_convert(source)
                self.assertFalse((self.root/'modern.apkg').exists())
        for kind in ('duplicate','encrypted'):
            source,_=self.package(duplicate=kind=='duplicate')
            if kind=='encrypted':
                raw=bytearray(source.read_bytes());position=raw.index(b'PK\x01\x02');raw[position+8]|=1;source.write_bytes(raw)
            with self.subTest(kind=kind),self.assertRaises(ValueError):self.run_convert(source)
            self.assertFalse((self.root/'modern.apkg').exists())

    def test_source_pin_size_change_and_target_race_do_not_publish(self):
        source,_=self.package();pin=hashlib.sha256(source.read_bytes()).hexdigest();destination=self.root/'modern.apkg'
        for kwargs in ({'expected_source_sha256':'0'*64},{'expected_source_bytes':source.stat().st_size+1}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):
                convert.convert_legacy_apkg(source,destination,limits=self.limits,fallback_collection=self.fallback,
                    **({'expected_source_sha256':pin}|kwargs))
            self.assertFalse(destination.exists())
        def mutate(event):
            if event['phase']=='ready_to_publish':
                with source.open('ab') as stream:stream.write(b'changed')
        with self.assertRaises(ValueError):self.run_convert(source,callback=mutate)
        self.assertFalse(destination.exists())
        source,_=self.package()
        def foreign(event):
            if event['phase']=='ready_to_publish':destination.write_bytes(b'foreign')
        with self.assertRaises(FileExistsError):self.run_convert(source,callback=foreign)
        self.assertEqual(destination.read_bytes(),b'foreign')
        with self.assertRaises(FileExistsError):self.run_convert(source)

    def test_partial_replacement_is_not_claimed(self):
        source,_=self.package()
        def replace(event):
            if event['phase']=='ready_to_publish':
                work,=self.root.glob('modern.apkg.convert-*');path=work/'package.partial'
                path.rename(work/'original.kept');path.write_bytes(b'foreign')
        with self.assertRaises(ValueError):self.run_convert(source,callback=replace)
        self.assertFalse((self.root/'modern.apkg').exists())
        self.assertTrue(next(self.root.glob('modern.apkg.convert-*')).joinpath('original.kept').exists())

    def test_foreign_member_temp_is_not_deleted(self):
        source,_=self.package();original=convert._decode;changed=[]
        def replace(stream,*args):
            result=original(stream,*args)
            if not changed:
                path,=self.root.glob('modern.apkg.convert-*/member-*.zstd')
                path.rename(path.with_suffix('.kept'));path.write_bytes(b'foreign');changed.append(path)
            return result
        with patch.object(convert,'_decode',replace),self.assertRaisesRegex(ValueError,'owned frame temp identity changed'):
            self.run_convert(source)
        self.assertEqual(changed[0].read_bytes(),b'foreign')
        self.assertFalse((self.root/'modern.apkg').exists())

    def test_explicit_resource_guards_and_bad_fallback(self):
        source,_=self.package();pin=hashlib.sha256(source.read_bytes()).hexdigest()
        for limits in (RecompressionLimits(free_bytes=10**30),RecompressionLimits(rss_bytes=1,free_bytes=0),
                       RecompressionLimits(wall_seconds=1e-12,free_bytes=0),RecompressionLimits(output_bytes=1,free_bytes=0),
                       RecompressionLimits(member_raw_bytes=1,free_bytes=0),RecompressionLimits(member_encoded_bytes=1,free_bytes=0)):
            with self.subTest(limits=limits),self.assertRaises((ValueError,TimeoutError)):
                convert.convert_legacy_apkg(source,self.root/'modern.apkg',expected_source_sha256=pin,
                    fallback_collection=self.fallback,limits=limits)
            self.assertFalse((self.root/'modern.apkg').exists())
        with self.assertRaises(ValueError):
            convert.convert_legacy_apkg(source,self.root/'modern.apkg',expected_source_sha256=pin,
                fallback_collection=b'not SQLite',limits=self.limits)

    def test_import_has_no_optional_codec_dependency_or_local_app_requirement(self):
        result=subprocess.run([sys.executable,'-B','-c',
            'import sys;import anki_pipeline.study_modern_convert;assert "zstandard" not in sys.modules;assert "genanki" not in sys.modules;assert "anki" not in sys.modules'],
            capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)


if __name__=='__main__':unittest.main()
