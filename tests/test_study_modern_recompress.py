"""Small synthetic modern containers; no Anki, protobuf or SQLite parsing."""
import hashlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

import zstandard as zstd
from anki_pipeline import study_modern_recompress as modern
from anki_pipeline.study_modern_recompress import RecompressionLimits, recompress_modern_apkg


class RecompressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.limits = RecompressionLimits(wall_seconds=30, rss_bytes=512*1024**2,
            free_bytes=0, output_bytes=16*1024**2, member_encoded_bytes=8*1024**2,
            member_raw_bytes=8*1024**2)

    def frame(self, raw, level=-5):
        return zstd.ZstdCompressor(level=level, write_content_size=True, write_checksum=True).compress(raw)

    def package(self, changes=None, *, duplicate=False, encrypted=False):
        raw = {'collection.anki21b': b'SQLite format 3\0'+bytes(range(256))*2048,
               'media': b'opaque protobuf index', '0': b'abcdefghijk'*40000,
               '1': b''}
        values = {'meta':b'\x08\x03', 'collection.anki2':b'fallback exact bytes',
                  'extra/name.txt':b'\x00opaque extra\xff', **{k:self.frame(v) for k,v in raw.items()}}
        values.update(changes or {})
        path = self.root/('source-'+str(len(list(self.root.glob('source*'))))+'.apkg')
        with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_STORED) as archive:
            archive.comment = b'archive comment\x00'
            for name,value in values.items():
                info=zipfile.ZipInfo(name,(2026,10,19,0,0,0));info.comment=b'entry comment'
                if name == 'extra/name.txt':
                    info.compress_type = zipfile.ZIP_DEFLATED
                    with archive.open(info, 'w', force_zip64=True) as stream:stream.write(value)
                else:archive.writestr(info,value)
            if duplicate:
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore');archive.writestr('0',values['0'])
        if encrypted:
            data=bytearray(path.read_bytes());position=0
            while True:
                position=data.find(b'PK\x01\x02',position)
                if position<0:break
                data[position+8]|=1;position+=4
            path.write_bytes(data)
        return path,raw

    def run_package(self, source, **kwargs):
        destination=self.root/'result.apkg'
        report=recompress_modern_apkg(source,destination,
            expected_source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),limits=self.limits,**kwargs)
        return destination,report

    def test_all_payloads_names_comments_and_empty_frame_are_lossless(self):
        source,raw=self.package();before=source.read_bytes();destination,report=self.run_package(source)
        self.assertEqual(source.read_bytes(),before)
        with zipfile.ZipFile(source) as a,zipfile.ZipFile(destination) as b:
            self.assertEqual(a.namelist(),b.namelist());self.assertEqual(a.comment,b.comment)
            for name in a.namelist():
                self.assertEqual(a.getinfo(name).comment,b.getinfo(name).comment)
                self.assertEqual(b.getinfo(name).compress_type,zipfile.ZIP_STORED)
                if name in raw:
                    self.assertEqual(zstd.ZstdDecompressor().decompress(b.read(name)),raw[name])
                    self.assertLessEqual(len(b.read(name)),len(a.read(name)))
                else:self.assertEqual(a.read(name),b.read(name))
        self.assertEqual(report['frame_count'],4)
        self.assertTrue(report['source_identity_sha256_unchanged'])
        self.assertTrue(any(item['retained_original'] for item in report['frames']))
        self.assertTrue(any(not item['retained_original'] for item in report['frames']))
        self.assertTrue(all(item['raw_sha256']==hashlib.sha256(raw[item['name']]).hexdigest() for item in report['frames']))
        self.assertEqual(report['output_sha256'],hashlib.sha256(destination.read_bytes()).hexdigest())
        with zipfile.ZipFile(source) as a,zipfile.ZipFile(destination) as b:
            for item in report['frames']:
                if item['retained_original']:self.assertEqual(a.read(item['name']),b.read(item['name']))
                else:
                    header=zstd.get_frame_parameters(b.read(item['name']))
                    self.assertTrue(header.has_checksum);self.assertEqual(header.content_size,item['raw_bytes'])
                    self.assertLessEqual(header.window_size,1<<27)
        self.assertFalse(list(Path(report['work_directory']).glob('frame-*')))

    def test_failed_member_retains_own_partial_and_frame_temp(self):
        frame=self.frame(b'x'*1000);bad=frame[:-1]+bytes([frame[-1]^1])
        source,_=self.package({'0':bad});sentinel=self.root/'unrelated';sentinel.write_bytes(b'preserve')
        with self.assertRaises(zstd.ZstdError):self.run_package(source)
        work,=self.root.glob('result.apkg.recompress-*')
        self.assertTrue((work/'package.partial').is_file())
        self.assertTrue(list(work.glob('frame-*.zstd')))
        self.assertEqual(sentinel.read_bytes(),b'preserve')

    def test_opaque_metadata_extensions_and_lazy_dependency_import(self):
        source,_=self.package({'meta':b'\x08\x03\x12\x03xyz'})
        destination,_=self.run_package(source)
        with zipfile.ZipFile(destination) as archive:self.assertEqual(archive.read('meta'),b'\x08\x03\x12\x03xyz')
        result=subprocess.run([sys.executable,'-B','-c',
            'import sys; import anki_pipeline.study_modern_recompress; assert "zstandard" not in sys.modules'],
            capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_public_defaults_and_level_window_validation(self):
        self.assertEqual(RecompressionLimits().rss_bytes,512*1024**2)
        self.assertEqual(RecompressionLimits().free_bytes,1024**3)
        source,_=self.package();pin=hashlib.sha256(source.read_bytes()).hexdigest()
        for kwargs in ({'level':0},{'level':23},{'window_log':28},{'window_log':9}):
            with self.subTest(kwargs=kwargs),self.assertRaises(ValueError):
                recompress_modern_apkg(source,self.root/'invalid.apkg',expected_source_sha256=pin,
                                      limits=self.limits,**kwargs)
        self.assertFalse((self.root/'invalid.apkg').exists())

    def test_corrupt_checksum_truncation_pledge_and_concatenation_reject(self):
        good=self.frame(b'x'*1000)
        for frame in (good[:-1]+bytes([good[-1]^1]),good[:-1],good+good,
                      good[:5]+bytes([good[5]^1])+good[6:]):
            with self.subTest(frame=frame[:12]):
                source,_=self.package({'0':frame})
                with self.assertRaises((ValueError,zstd.ZstdError)):self.run_package(source)
                self.assertFalse((self.root/'result.apkg').exists())

    def test_unknown_size_wrong_version_duplicate_and_encryption_reject(self):
        unknown=zstd.ZstdCompressor(write_content_size=False,write_checksum=True).compress(b'payload')
        for kwargs in ({'changes':{'0':unknown}},{'changes':{'meta':b'\x08\x02'}},
                       {'duplicate':True},{'encrypted':True}):
            with self.subTest(kwargs=kwargs):
                source,_=self.package(**kwargs)
                with self.assertRaises(ValueError):self.run_package(source)
                self.assertFalse((self.root/'result.apkg').exists())

    def test_wrong_sha_existing_destination_and_source_change_do_not_publish(self):
        source,_=self.package();destination=self.root/'result.apkg'
        with self.assertRaises(ValueError):recompress_modern_apkg(source,destination,expected_source_sha256='0'*64,limits=self.limits)
        self.assertFalse(destination.exists());destination.write_bytes(b'foreign')
        with self.assertRaises(FileExistsError):self.run_package(source)
        self.assertEqual(destination.read_bytes(),b'foreign')
        other=self.root/'changed-result.apkg';changed=False
        def mutate(event):
            nonlocal changed
            if event['phase']=='frame' and not changed:
                changed=True
                with source.open('ab') as f:f.write(b'changed')
        with self.assertRaises(ValueError):recompress_modern_apkg(source,other,
            expected_source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),limits=self.limits,callback=mutate)
        self.assertFalse(other.exists())

    def test_callback_races_cannot_clobber_or_publish_a_changed_partial(self):
        source,_=self.package();pin=hashlib.sha256(source.read_bytes()).hexdigest()
        destination=self.root/'raced.apkg'
        def foreign(event):
            if event['phase']=='ready_to_publish':destination.write_bytes(b'foreign')
        with self.assertRaises(FileExistsError):
            recompress_modern_apkg(source,destination,expected_source_sha256=pin,limits=self.limits,callback=foreign)
        self.assertEqual(destination.read_bytes(),b'foreign')
        destination=self.root/'changed-partial.apkg'
        def change(event):
            if event['phase']=='ready_to_publish':
                work,=self.root.glob('changed-partial.apkg.recompress-*')
                (work/'package.partial').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'partial changed'):
            recompress_modern_apkg(source,destination,expected_source_sha256=pin,limits=self.limits,callback=change)
        self.assertFalse(destination.exists())

    def test_completed_partial_ctime_only_change_requires_held_fd_content_proof(self):
        source,_=self.package();changed=[]
        def metadata(event):
            if event['phase']=='ready_to_publish':
                work,=self.root.glob('result.apkg.recompress-*');partial=work/'package.partial'
                before=modern._identity(partial.stat())
                os.chmod(partial,partial.stat().st_mode)
                after=modern._identity(partial.stat())
                self.assertEqual(before[:5],after[:5]);self.assertNotEqual(before[5],after[5])
                changed.append((before,after))
        destination,report=self.run_package(source,callback=metadata)
        self.assertEqual(len(changed),1)
        evidence=report['completed_partial_identity_change']
        self.assertEqual(evidence['before'],list(changed[0][0]))
        self.assertEqual(evidence['fd_after'],list(changed[0][1]))
        self.assertEqual(evidence['fd_after'],evidence['path_after'])
        self.assertTrue(evidence['encoded_sha256_verified'])
        self.assertEqual(evidence['encoded_sha256'],report['output_sha256'])
        self.assertEqual(evidence['actual_sha256'],report['output_sha256'])
        self.assertEqual(report['output_sha256'],hashlib.sha256(destination.read_bytes()).hexdigest())

    def test_first_final_sha_content_change_cannot_become_trusted_baseline(self):
        source,_=self.package();original=modern.hashlib.sha256;attacks=[]
        def during_digest_creation(*args,**kwargs):
            import inspect
            caller=inspect.currentframe().f_back
            if (caller.f_code.co_name=='recompress_modern_apkg' and caller.f_locals.get('completed') is not None
                    and 'output_digest' not in caller.f_locals and not attacks):
                work,=self.root.glob('result.apkg.recompress-*');partial=work/'package.partial';before=partial.stat()
                with zipfile.ZipFile(partial) as package:
                    info=package.getinfo('collection.anki2');offset=info.header_offset
                with partial.open('r+b') as stream:
                    stream.seek(offset);header=stream.read(30)
                    data_offset=offset+30+int.from_bytes(header[26:28],'little')+int.from_bytes(header[28:30],'little')
                    stream.seek(data_offset);byte=stream.read(1);stream.seek(data_offset);stream.write(bytes([byte[0]^1]))
                os.utime(partial,ns=(before.st_atime_ns,before.st_mtime_ns))
                after=partial.stat();self.assertEqual(modern._identity(before)[:5],modern._identity(after)[:5]);self.assertNotEqual(before.st_ctime_ns,after.st_ctime_ns)
                attacks.append(partial)
            return original(*args,**kwargs)
        with patch.object(modern.hashlib,'sha256',during_digest_creation),self.assertRaisesRegex(ValueError,'changed during.*SHA') as caught:
            self.run_package(source)
        self.assertEqual(len(attacks),1);self.assertFalse((self.root/'result.apkg').exists())
        with zipfile.ZipFile(attacks[0]) as damaged,self.assertRaises(zipfile.BadZipFile):damaged.read('collection.anki2')
        self.assertIn('owned completed partial identities','\n'.join(caught.exception.__notes__))

    def output_requalification_input_case(self,which):
        source,raw=self.package();prefix=self.prefix_package(source,raw);target=source if which=='source' else prefix
        ready=[];changed=[];original=modern._copy_encoded
        def metadata(event):
            if event['phase']=='ready_to_publish':
                work,=self.root.glob('result.apkg.recompress-*');partial=work/'package.partial'
                os.chmod(partial,partial.stat().st_mode);ready.append(True)
        def change_input_after_output_read(stream,output,expected,size,budget):
            result=original(stream,output,expected,size,budget)
            if ready and output is None and not changed:
                before=target.stat();os.chmod(target,before.st_mode);after=target.stat()
                self.assertEqual(modern._identity(before)[:5],modern._identity(after)[:5]);self.assertNotEqual(before.st_ctime_ns,after.st_ctime_ns);changed.append(True)
            return result
        with patch.object(modern,'_copy_encoded',change_input_after_output_read),self.assertRaisesRegex(ValueError,'source identity changed'):
            self.run_package(source,prefix=prefix,expected_prefix_sha256=hashlib.sha256(prefix.read_bytes()).hexdigest(),callback=metadata)
        self.assertEqual(changed,[True]);self.assertFalse((self.root/'result.apkg').exists())

    def test_output_requalification_cannot_hide_source_drift(self):
        self.output_requalification_input_case('source')

    def test_output_requalification_cannot_hide_prefix_drift(self):
        self.output_requalification_input_case('prefix')

    def test_completed_partial_content_change_with_restored_mtime_is_rejected(self):
        source,_=self.package();changed=[]
        def corrupt(event):
            if event['phase']=='ready_to_publish':
                work,=self.root.glob('result.apkg.recompress-*');partial=work/'package.partial'
                before=partial.stat()
                with partial.open('r+b') as stream:
                    byte=stream.read(1);stream.seek(0);stream.write(bytes([byte[0]^1]))
                os.utime(partial,ns=(before.st_atime_ns,before.st_mtime_ns));changed.append(partial)
                self.assertEqual(modern._identity(before)[:5],modern._identity(partial.stat())[:5])
        with self.assertRaisesRegex(ValueError,'encoded copy SHA differs') as caught:
            self.run_package(source,callback=corrupt)
        self.assertTrue(all(key in '\n'.join(caught.exception.__notes__) for key in ('before','fd_after','path_after','actual_sha256','encoded_sha256')))
        self.assertTrue(changed[0].exists());self.assertFalse((self.root/'result.apkg').exists())

    def test_completed_partial_mode_mtime_size_or_inode_change_is_rejected(self):
        for change in ('mode','mtime','size','inode'):
            source,_=self.package();destination=self.root/(change+'.apkg');touched=[]
            def mutate(event):
                if event['phase']!='ready_to_publish':return
                work,=self.root.glob(change+'.apkg.recompress-*');partial=work/'package.partial';before=partial.stat()
                if change=='mode':os.chmod(partial,before.st_mode ^ 0o100)
                elif change=='mtime':os.utime(partial,ns=(before.st_atime_ns,before.st_mtime_ns-1))
                elif change=='size':
                    with partial.open('ab') as stream:stream.write(b'x')
                else:partial.rename(work/'held-original');partial.write_bytes(b'foreign')
                touched.append(partial)
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,'completed partial changed') as caught:
                recompress_modern_apkg(source,destination,expected_source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),limits=self.limits,callback=mutate)
            self.assertFalse(destination.exists());self.assertTrue(touched[0].exists())
            self.assertIn('owned completed partial identities','\n'.join(caught.exception.__notes__))

    def test_completed_partial_change_during_requalification_fails(self):
        source,_=self.package();ready=[];actual_copy=modern._copy_encoded;changed=[]
        def metadata(event):
            if event['phase']=='ready_to_publish':
                work,=self.root.glob('result.apkg.recompress-*');partial=work/'package.partial'
                os.chmod(partial,partial.stat().st_mode);ready.append(partial)
        def mutate_after_sha(stream,target,expected,size,budget):
            result=actual_copy(stream,target,expected,size,budget)
            if ready and target is None and not changed:
                os.chmod(ready[0],ready[0].stat().st_mode);changed.append(True)
            return result
        with patch.object(modern,'_copy_encoded',mutate_after_sha),self.assertRaisesRegex(ValueError,'changed during SHA requalification') as caught:
            self.run_package(source,callback=metadata)
        self.assertEqual(changed,[True]);self.assertFalse((self.root/'result.apkg').exists())
        self.assertIn('fd_after','\n'.join(caught.exception.__notes__))

    def test_completed_partial_second_ctime_change_is_not_retried(self):
        source,_=self.package();original=modern._verify_completed_partial;calls=[]
        def first_ctime(stream,path,before,digest,budget,**kwargs):
            if not calls:os.chmod(path,path.stat().st_mode)
            calls.append(kwargs['requalified']);return original(stream,path,before,digest,budget,**kwargs)
        def second_ctime(event):
            if event['phase']=='ready_to_publish':
                work,=self.root.glob('result.apkg.recompress-*');partial=work/'package.partial';os.chmod(partial,partial.stat().st_mode)
        with patch.object(modern,'_verify_completed_partial',first_ctime),self.assertRaisesRegex(ValueError,'changed repeatedly'):
            self.run_package(source,callback=second_ctime)
        self.assertEqual(calls,[False,True]);self.assertFalse((self.root/'result.apkg').exists())

    def test_completed_partial_held_fd_path_disagreement_is_rejected(self):
        source,_=self.package();original=modern._temp_evidence;ready=[]
        def callback(event):
            if event['phase']=='ready_to_publish':ready.append(True)
        def disagree(stream,path,before):
            value=original(stream,path,before)
            if ready and path.name=='package.partial':value['path_after'][5]+=1
            return value
        with patch.object(modern,'_temp_evidence',disagree),self.assertRaisesRegex(ValueError,'FD/path identity differs'):
            self.run_package(source,callback=callback)
        self.assertFalse((self.root/'result.apkg').exists())

    def test_completed_output_read_fd_remains_open_during_callback_and_link(self):
        source,_=self.package();original_open=modern.os.open;original_link=modern.os.link;held=[];observed=[]
        def opened(path,flags,*args,**kwargs):
            fd=original_open(path,flags,*args,**kwargs)
            if Path(path).name=='package.partial' and flags & os.O_NOFOLLOW:held.append(fd)
            return fd
        def callback(event):
            if event['phase']=='ready_to_publish':
                self.assertEqual(len(held),1);observed.append(os.fstat(held[0]).st_ino)
        def linked(path,destination,**kwargs):
            self.assertEqual(os.fstat(held[0]).st_ino,Path(path).stat().st_ino);observed.append(os.fstat(held[0]).st_ino)
            return original_link(path,destination,**kwargs)
        with patch.object(modern.os,'open',opened),patch.object(modern.os,'link',linked):destination,_=self.run_package(source,callback=callback)
        self.assertEqual(observed,[destination.stat().st_ino]*2)
        with self.assertRaises(OSError):os.fstat(held[0])

    def test_source_and_prefix_ctime_only_change_remain_strict(self):
        for which in ('source','prefix'):
            source,raw=self.package();prefix=self.prefix_package(source,raw);target=source if which=='source' else prefix
            def metadata(event):
                if event['phase']=='ready_to_publish':os.chmod(target,target.stat().st_mode)
            with self.subTest(which=which),self.assertRaisesRegex(ValueError,'source identity changed'):
                self.run_package(source,prefix=prefix,expected_prefix_sha256=hashlib.sha256(prefix.read_bytes()).hexdigest(),callback=metadata)
            self.assertFalse((self.root/'result.apkg').exists())

    def test_partial_replacement_after_writer_closes_is_not_reowned(self):
        source,_=self.package();original_open=Path.open;swapped=[]
        foreign=b'FOREIGN NOT AN APKG'
        def swap_on_close(path,mode='r',*args,**kwargs):
            stream=original_open(path,mode,*args,**kwargs)
            if path.name!='package.partial' or mode!='xb':return stream
            class Writer:
                def __enter__(self):return stream.__enter__()
                def __exit__(self,*error):
                    result=stream.__exit__(*error)
                    if error[0] is None:
                        path.rename(path.with_name('original.partial'))
                        path.write_bytes(foreign);swapped.append(path)
                    return result
            return Writer()
        with patch.object(Path,'open',swap_on_close):
            with self.assertRaisesRegex(ValueError,'owned output|owned partial'):
                self.run_package(source)
        self.assertEqual(len(swapped),1)
        self.assertEqual(swapped[0].read_bytes(),foreign)
        self.assertTrue(swapped[0].with_name('original.partial').is_file())
        self.assertFalse((self.root/'result.apkg').exists())

    def test_publication_must_link_the_verified_owned_output(self):
        source,_=self.package();foreign=self.root/'foreign';foreign.write_bytes(b'foreign')
        real_link=modern.os.link
        def wrong_link(source,destination,**kwargs):
            return real_link(foreign,destination,**kwargs)
        with patch.object(modern.os,'link',wrong_link):
            with self.assertRaisesRegex(ValueError,'published partial identity changed'):
                self.run_package(source)
        self.assertEqual((self.root/'result.apkg').read_bytes(),b'foreign')
        self.assertEqual(foreign.read_bytes(),b'foreign')

    def temp_after_decode(self, action):
        original=modern._decode;changed=[]
        def decode(stream,*args):
            result=original(stream,*args)
            if not changed and isinstance(getattr(stream,'name',None),int):
                paths=list(self.root.glob('*.recompress-*/frame-*.zstd'))
                if paths:
                    action(stream,paths[0]);changed.append(paths[0])
            return result
        return patch.object(modern,'_decode',decode),changed

    def test_owned_temp_ctime_only_change_requires_content_proof(self):
        source,_=self.package()
        def metadata(stream,path):
            before=modern._identity(os.fstat(stream.fileno()))
            os.chmod(path,os.fstat(stream.fileno()).st_mode)
            after=modern._identity(os.fstat(stream.fileno()))
            self.assertEqual(before[:5],after[:5]);self.assertNotEqual(before[5],after[5])
        injection,changed=self.temp_after_decode(metadata)
        with injection:destination,report=self.run_package(source)
        self.assertEqual(len(changed),1)
        evidence=report['frames'][0]['temp_identity_change']
        self.assertEqual(evidence['before'][:5],evidence['fd_after'][:5])
        self.assertEqual(evidence['fd_after'],evidence['path_after'])
        self.assertTrue(evidence['encoded_sha256_verified'])
        self.assertTrue(destination.is_file())

    def test_owned_temp_copy_content_change_is_rejected_with_evidence(self):
        source,_=self.package()
        def corrupt(stream,path):
            before=path.stat();stream.seek(-1,2);byte=stream.read(1)
            stream.seek(-1,2);stream.write(bytes([byte[0]^1]));stream.flush()
            os.utime(path,ns=(before.st_atime_ns,before.st_mtime_ns))
        injection,changed=self.temp_after_decode(corrupt)
        with injection,self.assertRaisesRegex(ValueError,'encoded copy SHA') as caught:
            self.run_package(source)
        self.assertEqual(len(changed),1)
        self.assertTrue(all(word in '\n'.join(caught.exception.__notes__) for word in ('before','fd_after','path_after')))
        self.assertFalse((self.root/'result.apkg').exists())
        self.assertTrue(changed[0].is_file())

    def test_owned_temp_wrong_inode_is_rejected_with_evidence(self):
        source,_=self.package()
        def replace(stream,path):
            path.rename(path.with_suffix('.kept'));path.write_bytes(b'foreign')
        injection,changed=self.temp_after_decode(replace)
        with injection,self.assertRaisesRegex(ValueError,'owned frame temp identity changed') as caught:
            self.run_package(source)
        self.assertEqual(len(changed),1)
        self.assertTrue(all(word in '\n'.join(caught.exception.__notes__) for word in ('before','fd_after','path_after')))
        self.assertEqual(changed[0].read_bytes(),b'foreign')
        self.assertFalse((self.root/'result.apkg').exists())

    def prefix_package(self,source,raw,*,change=None,names=None):
        path=self.root/('prefix-'+str(len(list(self.root.glob('prefix-*'))))+'.apkg')
        with zipfile.ZipFile(source) as incoming,zipfile.ZipFile(path,'w') as prefix:
            prefix.comment=incoming.comment
            selected=names if names is not None else incoming.namelist()[:4]
            for name in selected:
                value=self.frame(raw[name],level=19) if name in raw else incoming.read(name)
                if change:value=change(name,value)
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore');prefix.writestr(incoming.getinfo(name),value)
        return path

    def test_authenticated_prefix_skips_collection_compression(self):
        source,raw=self.package();prefix=self.prefix_package(source,raw);before=prefix.read_bytes()
        factory=zstd.ZstdCompressor;calls=[]
        def compressor(**kwargs):
            real=factory(**kwargs)
            class Compressor:
                def compressobj(self,*,size):
                    calls.append(size)
                    self_outer.assertNotEqual(size,len(raw['collection.anki21b']))
                    return real.compressobj(size=size)
            return Compressor()
        self_outer=self
        with patch.object(zstd,'ZstdCompressor',compressor):
            destination,report=self.run_package(source,prefix=prefix,
                expected_prefix_sha256=hashlib.sha256(before).hexdigest())
        self.assertTrue(calls)
        self.assertEqual(report['reused_prefix_frames'],1)
        self.assertEqual(report['prefix_authenticated_members'],4)
        self.assertEqual(report['prefix_sha256'],hashlib.sha256(before).hexdigest())
        self.assertEqual(prefix.read_bytes(),before)
        with zipfile.ZipFile(destination) as output:
            for name,value in raw.items():self.assertEqual(zstd.ZstdDecompressor().decompress(output.read(name)),value)

    def test_invalid_prefix_pin_names_payload_and_opaque_fail_closed(self):
        source,raw=self.package()
        cases=(('missing-pin',None,None),('wrong-pin',None,None),
               ('bad-raw',lambda n,v:self.frame(b'X'*len(raw[n]),19) if n in raw else v,None),
               ('bad-checksum',lambda n,v:v[:-1]+bytes([v[-1]^1]) if n in raw else v,None),
               ('bad-opaque',lambda n,v:v+b'changed' if n=='collection.anki2' else v,None),
               ('bad-names',None,['collection.anki21b']),('duplicate',None,['meta','meta']),
               ('encrypted',None,None))
        for label,change,names in cases:
            with self.subTest(label=label):
                prefix=self.prefix_package(source,raw,change=change,names=names)
                if label=='encrypted':
                    data=bytearray(prefix.read_bytes());position=data.index(b'PK\x01\x02')
                    data[position+8]|=1;prefix.write_bytes(data)
                kwargs={'prefix':prefix}
                if label!='missing-pin':kwargs['expected_prefix_sha256']='0'*64 if label=='wrong-pin' else hashlib.sha256(prefix.read_bytes()).hexdigest()
                with self.assertRaises((ValueError,zstd.ZstdError)):self.run_package(source,**kwargs)
                self.assertFalse((self.root/'result.apkg').exists())

    def test_prefix_and_source_drift_prevent_publication(self):
        for which in ('prefix','source'):
            with self.subTest(which=which):
                source,raw=self.package();prefix=self.prefix_package(source,raw);changed=[]
                def mutate(event):
                    if event['phase']=='frame' and not changed:
                        with (prefix if which=='prefix' else source).open('ab') as stream:stream.write(b'changed')
                        changed.append(True)
                with self.assertRaisesRegex(ValueError,'source identity changed'):
                    self.run_package(source,prefix=prefix,expected_prefix_sha256=hashlib.sha256(prefix.read_bytes()).hexdigest(),callback=mutate)
                self.assertTrue(changed)
                self.assertFalse((self.root/'result.apkg').exists())

    def test_explicit_guards_and_symlink_reject_without_publication(self):
        source,_=self.package();pin=hashlib.sha256(source.read_bytes()).hexdigest()
        for limits in (RecompressionLimits(free_bytes=10**30),RecompressionLimits(rss_bytes=1,free_bytes=0),
                       RecompressionLimits(wall_seconds=1e-12,free_bytes=0),RecompressionLimits(output_bytes=1,free_bytes=0),
                       RecompressionLimits(member_encoded_bytes=1,free_bytes=0),RecompressionLimits(member_raw_bytes=1,free_bytes=0)):
            with self.subTest(limits=limits),self.assertRaises((ValueError,TimeoutError)):
                recompress_modern_apkg(source,self.root/'guard.apkg',expected_source_sha256=pin,limits=limits)
            self.assertFalse((self.root/'guard.apkg').exists())
        link=self.root/'link.apkg';link.symlink_to(source)
        with self.assertRaises(ValueError):recompress_modern_apkg(link,self.root/'link-result.apkg',expected_source_sha256=pin,limits=self.limits)
        self.assertFalse((self.root/'link-result.apkg').exists())

    def test_decoder_caps_window_if_source_changes_after_scan(self):
        frame=self.frame(b'x'*1000)
        # A valid unknown-size frame with a 256MiB window. This models replaced
        # decode bytes, independently of the earlier valid small-header scan.
        changed=frame[:4]+bytes([4,144])+frame[7:]
        self.assertEqual(zstd.get_frame_parameters(changed).window_size,1<<28)
        budget=modern._Budget(self.limits,self.root)
        with self.assertRaisesRegex(zstd.ZstdError,'memory'):
            modern._decode(io.BytesIO(changed),zstd,budget,1000,lambda raw:None)

    def test_fifo_swap_between_lstat_and_open_cannot_block(self):
        script='''import os,tempfile
from pathlib import Path
from anki_pipeline.study_modern_recompress import _PinnedSource,_Budget,RecompressionLimits
with tempfile.TemporaryDirectory() as folder:
 p=Path(folder)/'source';p.write_bytes(b'x')
 class Swapped:
  def lstat(self):
   before=p.lstat();p.unlink();os.mkfifo(p);return before
  def __fspath__(self):return str(p)
 try:
  with _PinnedSource(Swapped(),'0'*64,_Budget(RecompressionLimits(free_bytes=0),Path(folder))):pass
 except ValueError:pass
 else:raise AssertionError('FIFO swap was accepted')
'''
        result=subprocess.run([sys.executable,'-B','-c',script],capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)


if __name__=='__main__':unittest.main()
