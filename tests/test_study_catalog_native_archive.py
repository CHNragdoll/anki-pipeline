"""Small expected-archive checks; never create an SDK Collection or import APKG."""
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
import zipfile

from scripts import verify_study_catalog_native as verifier


class LegacyExpectedArchiveTests(unittest.TestCase):
    def test_legacy_sqlite_and_every_media_byte_remain_checked(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);media=root/'actual';media.mkdir();(media/'voice.mp3').write_bytes(b'audio')
            packed=io.BytesIO()
            with zipfile.ZipFile(packed,'w') as z:
                z.writestr('collection.anki2',b'legacy-sqlite');z.writestr('media',json.dumps({'0':'voice.mp3'}));z.writestr('0',b'audio')
            with zipfile.ZipFile(packed) as z:
                expected=verifier.ExpectedArchive(z);path=root/'expected.anki2'
                expected.write_collection(path,max_bytes=64)
                self.assertEqual(path.read_bytes(),b'legacy-sqlite')
                self.assertEqual(expected.verify_media(media)['files_checked'],1)
                self.assertEqual(expected.receipt['format'],'legacy')
                (media/'voice.mp3').write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError,'media bytes'):expected.verify_media(media)
                with self.assertRaises(FileExistsError):expected.write_collection(path,max_bytes=64)

    def test_legacy_unsafe_alias_duplicate_map_and_size_limit_fail_closed(self):
        for mapping in ('{"0":"../escape"}', '{"0":"a","0":"b"}', '{"0":"a","1":"a"}'):
            packed=io.BytesIO()
            with zipfile.ZipFile(packed,'w') as z:
                z.writestr('collection.anki2',b'12345');z.writestr('media',mapping);z.writestr('0',b'a');z.writestr('1',b'b')
            with zipfile.ZipFile(packed) as z,self.assertRaises(ValueError):verifier.ExpectedArchive(z)
        with tempfile.TemporaryDirectory() as folder:
            packed=io.BytesIO()
            with zipfile.ZipFile(packed,'w') as z:
                z.writestr('collection.anki2',b'12345');z.writestr('media','{}')
            with zipfile.ZipFile(packed) as z,self.assertRaisesRegex(ValueError,'limit'):
                verifier.ExpectedArchive(z).write_collection(Path(folder)/'new',max_bytes=4)


class ModernExpectedArchiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:import zstandard
        except ImportError as error:raise unittest.SkipTest('optional zstandard binding unavailable') from error
        app=Path('/Applications/Anki.app/Contents/Resources/app_packages')
        if not app.is_dir():raise unittest.SkipTest('official installed Anki protobuf SDK unavailable')
        sys.path.insert(0,str(app))
        try:
            from anki.import_export_pb2 import PackageMetadata,MediaEntries
        except ImportError as error:raise unittest.SkipTest('official Anki protobuf SDK unavailable') from error
        cls.zstd=zstandard;cls.Metadata=PackageMetadata;cls.Media=MediaEntries

    def package(self,*,version=3,sql=None,media=b'audio',name='voice.mp3',size=None,sha1=None,change=None):
        sql=sql if sql is not None else b'modern-sqlite'
        encode=lambda value:self.zstd.ZstdCompressor(write_checksum=True).compress(value)
        entries=self.Media();entries.entries.add(name=name,size=len(media) if size is None else size,
            sha1=hashlib.sha1(media).digest() if sha1 is None else sha1)
        members={'meta':self.Metadata(version=version).SerializeToString(),
                 'collection.anki2':b'COMPATIBILITY FALLBACK, NOT THE EXPECTED DATABASE',
                 'collection.anki21b':encode(sql),'media':encode(entries.SerializeToString()),'0':encode(media)}
        if change:change(members)
        packed=io.BytesIO()
        with zipfile.ZipFile(packed,'w') as z:
            for key,value in members.items():z.writestr(key,value)
        return packed

    def test_real_sdk_protobuf_and_actual_sqlite_are_decoded_without_fallback_or_media_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'fixture';db=sqlite3.connect(source)
            db.execute('create table notes(guid text,flds text)');db.execute('insert into notes values (?,?)',('g','中文😀\x1fe\u0301'));db.commit();db.close()
            raw=source.read_bytes();media=root/'media';media.mkdir();(media/'voice.mp3').write_bytes(b'audio')
            with zipfile.ZipFile(self.package(sql=raw)) as z:
                expected=verifier.ExpectedArchive(z);path=root/'expected'
                expected.write_collection(path,max_bytes=len(raw))
                self.assertEqual(path.read_bytes(),raw)
                with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as check:
                    self.assertEqual(check.execute('select * from notes').fetchall(),[('g','中文😀\x1fe\u0301')])
                self.assertEqual(expected.verify_media(media),{'files_checked':1,'sha256_exact':True,'missing_count':0,
                    'decoded_size_sha1_exact':True})
                self.assertEqual(expected.receipt['collection']['sha256'],hashlib.sha256(raw).hexdigest())
                self.assertEqual(expected.receipt['package_version'],3)
                self.assertEqual(sorted(p.name for p in media.iterdir()),['voice.mp3'])
                (media/'voice.mp3').write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError,'media bytes'):expected.verify_media(media)

    def test_version_missing_collection_bad_frame_suffix_and_truncation_are_rejected(self):
        cases=[('version',dict(version=0)),('collection',dict(change=lambda m:m.pop('collection.anki21b'))),
               ('frame',dict(change=lambda m:m.update(media=b'not zstd'))),
               ('frame',dict(change=lambda m:m.update(media=m['media'][:-1]))),
               ('frame',dict(change=lambda m:m.update(media=m['media']+b'garbage'))),
               ('frame',dict(change=lambda m:m.update(media=m['media']+m['media'])))]
        for reason,options in cases:
            with self.subTest(options=options),zipfile.ZipFile(self.package(**options)) as z,self.assertRaisesRegex(ValueError,reason):
                verifier.ExpectedArchive(z)
        for mutate in (lambda data:data[:-1],lambda data:data+b'x',lambda data:data+data):
            with self.subTest(mutate=mutate),tempfile.TemporaryDirectory() as folder:
                with zipfile.ZipFile(self.package(change=lambda m:m.update({'collection.anki21b':mutate(m['collection.anki21b'])}))) as z:
                    expected=verifier.ExpectedArchive(z)
                    with self.assertRaisesRegex(ValueError,'frame'):expected.write_collection(Path(folder)/'new',max_bytes=64)

    def test_media_size_sha1_actual_bytes_and_unsafe_names_are_rejected(self):
        for options in ({'size':4},{'sha1':b'\x00'*20}):
            with self.subTest(options=options),tempfile.TemporaryDirectory() as folder:
                root=Path(folder);(root/'voice.mp3').write_bytes(b'audio')
                with zipfile.ZipFile(self.package(**options)) as z:
                    expected=verifier.ExpectedArchive(z)
                    with self.assertRaisesRegex(ValueError,'size|SHA1'):expected.verify_media(root)
        for name in ('../escape','x/y','x\\y','C:escape','\x00','.','..',''):
            with self.subTest(name=name),zipfile.ZipFile(self.package(name=name)) as z,self.assertRaisesRegex(ValueError,'media name'):
                verifier.ExpectedArchive(z)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'voice.mp3').write_bytes(b'audio')
            for change in (lambda m:m.update({'0':m['0'][:-1]}),lambda m:m.update({'0':m['0']+b'x'})):
                with zipfile.ZipFile(self.package(change=change)) as z:
                    expected=verifier.ExpectedArchive(z)
                    with self.assertRaisesRegex(ValueError,'frame'):expected.verify_media(root)

    def test_validly_recompressed_media_tampering_and_invalid_frame_checksum_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'voice.mp3').write_bytes(b'other')
            changed=self.package(change=lambda m:m.update({'0':self.zstd.ZstdCompressor(write_checksum=True).compress(b'other')}))
            with zipfile.ZipFile(changed) as z:
                expected=verifier.ExpectedArchive(z)
                with self.assertRaisesRegex(ValueError,'SHA1'):expected.verify_media(root)
            corrupt=self.package(change=lambda m:m.update({'0':m['0'][:-1]+bytes([m['0'][-1]^1])}))
            (root/'voice.mp3').write_bytes(b'audio')
            with zipfile.ZipFile(corrupt) as z:
                expected=verifier.ExpectedArchive(z)
                with self.assertRaisesRegex(ValueError,'frame'):expected.verify_media(root)

    def test_hidden_incomplete_checksum_is_a_meaningful_stream_reader_counterexample(self):
        # The older stream_reader loop returns all bytes despite missing CRC.
        raw=b'unchanged bytes'*100;frame=self.zstd.ZstdCompressor(write_checksum=True).compress(raw)
        with self.zstd.ZstdDecompressor().stream_reader(io.BytesIO(frame[:-1])) as stream:
            self.assertEqual(stream.read(),raw)
        with zipfile.ZipFile(self.package(change=lambda m:m.update({'collection.anki21b':frame[:-1]}))) as z:
            with tempfile.TemporaryDirectory() as folder,self.assertRaisesRegex(ValueError,'truncated zstd frame'):
                verifier.ExpectedArchive(z).write_collection(Path(folder)/'new',max_bytes=len(raw))

    def test_legacy_metadata_versions_still_select_plain_legacy_sqlite_and_json_media(self):
        for version in (1,2):
            packed=io.BytesIO()
            with zipfile.ZipFile(packed,'w') as z:
                z.writestr('meta',self.Metadata(version=version).SerializeToString())
                z.writestr('collection.anki2',b'old');z.writestr('collection.anki21',b'preferred')
                z.writestr('media','{}')
            with zipfile.ZipFile(packed) as z:
                expected=verifier.ExpectedArchive(z)
                with tempfile.TemporaryDirectory() as folder:
                    path=Path(folder)/'new';expected.write_collection(path,max_bytes=16)
                    self.assertEqual(path.read_bytes(),b'preferred')
                self.assertEqual(expected.receipt['format'],'legacy')

    def test_cext_window_limit_uses_bytes_for_a_real_half_mib_window(self):
        raw=bytes(range(256))*2048
        frame=self.zstd.ZstdCompressor(write_checksum=True).compress(raw)
        window=self.zstd.get_frame_parameters(frame).window_size
        self.assertGreater(window,128*1024);self.assertLess(window,128*1024*1024)
        # zstandard 0.23.0's actual C extension forwards this value in bytes.
        # Dividing the 128MiB limit by 1024 incorrectly caps it at 128KiB.
        if self.zstd.__version__=='0.23.0' and self.zstd.backend=='cext':
            with self.assertRaisesRegex(self.zstd.ZstdError,'too much memory'):
                self.zstd.ZstdDecompressor(max_window_size=128*1024).decompressobj().decompress(frame)
        packed=io.BytesIO()
        with zipfile.ZipFile(packed,'w') as z:z.writestr('frame',frame)
        with zipfile.ZipFile(packed) as z:
            self.assertEqual(b''.join(verifier._zstd_chunks(z,'frame',len(raw),expected_size=len(raw))),raw)
            with self.assertRaisesRegex(ValueError,'window limit'):
                b''.join(verifier._zstd_chunks(z,'frame',len(raw),max_window_bytes=128*1024))

    def test_declared_limits_are_checked_before_decode_and_duplicate_members_reject(self):
        with tempfile.TemporaryDirectory() as folder:
            with zipfile.ZipFile(self.package(sql=b'x'*1000)) as z:
                expected=verifier.ExpectedArchive(z)
                with self.assertRaisesRegex(ValueError,'limit'):expected.write_collection(Path(folder)/'new',max_bytes=999)
            with zipfile.ZipFile(self.package()) as z:
                with self.assertRaisesRegex(ValueError,'window'):
                    b''.join(verifier._zstd_chunks(z,'collection.anki21b',1024,max_window_bytes=1))
        packed=self.package()
        with zipfile.ZipFile(packed,'a') as z:
            with self.assertWarns(UserWarning):z.writestr('media',b'duplicate')
        with zipfile.ZipFile(packed) as z,self.assertRaisesRegex(ValueError,'duplicate'):verifier.ExpectedArchive(z)


if __name__=='__main__':unittest.main()
