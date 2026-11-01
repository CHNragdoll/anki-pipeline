import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('restore_minimum', Path(__file__).resolve().parents[1] / 'scripts/restore_minimum_storage.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

class RestoreTests(unittest.TestCase):
    def test_zstd_uses_path_and_reports_missing_dependency(self):
        with patch.object(m.shutil, 'which', return_value='/usr/bin/zstd'):
            self.assertEqual(m.zstd_binary(), '/usr/bin/zstd')
        with patch.object(m.shutil, 'which', return_value=None), patch.object(m.Path, 'is_file', return_value=False):
            with self.assertRaisesRegex(FileNotFoundError, 'zstd is required'):
                m.zstd_binary()

    def test_file_restore_checks_bytes_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); raw=b'complete bilingual content\n'*100
            packed=root/'content.zst'; packed.write_bytes(subprocess.check_output([m.zstd_binary(),'-q','-c'],input=raw))
            row={'kind':'file','archive':str(packed),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'mode':0o600,'mtime_ns':1700000000000000000}
            target=root/'restored';m.restore_file(row,target,[root],root)
            self.assertEqual(target.read_bytes(),raw)
            with self.assertRaises(FileExistsError):m.restore_file(row,target,[root],root)
            target.unlink();row['sha256']='0'*64
            with self.assertRaises(ValueError):m.restore_file(row,target,[root],root)
            self.assertFalse(target.exists());self.assertFalse(list(root.glob('.restore-*')))

    def test_chunks_verify_each_member_and_full_identity(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);parts=[b'one',b'two',b'one'];chunks=[]
            for raw in parts:
                sha=hashlib.sha256(raw).hexdigest();(root/sha).write_bytes(raw);chunks.append({'sha256':sha,'bytes':len(raw)})
            raw=b''.join(parts);row={'kind':'chunks','chunks':chunks,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'mode':0o600,'mtime_ns':1700000000000000000}
            target=root/'original';m.restore_file(row,target,[root],root);self.assertEqual(target.read_bytes(),raw)
            target.unlink();(root/chunks[0]['sha256']).write_bytes(b'bad')
            with self.assertRaises(ValueError):m.restore_file(row,target,[root],root)
            self.assertFalse(target.exists())

    def test_parent_symlink_outside_scope_rejected(self):
        with tempfile.TemporaryDirectory() as a,tempfile.TemporaryDirectory() as b:
            root=Path(a);(root/'escape').symlink_to(b,target_is_directory=True)
            with self.assertRaises(ValueError):m.checked_path(str(root/'escape/file'),[root])

    def test_directory_restore_checks_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);raw=b'original html';buf=io.BytesIO()
            with tarfile.open(fileobj=buf,mode='w') as tar:
                entry=tarfile.TarInfo('entries/file.html');entry.size=len(raw);tar.addfile(entry,io.BytesIO(raw))
                alias=tarfile.TarInfo('entries/alias.html');alias.type=tarfile.LNKTYPE;alias.linkname='entries/file.html';tar.addfile(alias)
            archive=root/'entries.tar.zst';archive.write_bytes(subprocess.check_output([m.zstd_binary(),'-q','-c'],input=buf.getvalue()))
            manifest=root/'manifest.json.gz'
            with gzip.open(manifest,'wt') as f:json.dump({'entries/file.html':{'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}},f)
            row={'archive':str(archive),'file_manifest':str(manifest)};target=root/'entries'
            m.restore_directory(row,target,[root],root);self.assertEqual((target/'file.html').read_bytes(),raw)
            self.assertEqual((target/'alias.html').stat().st_ino,(target/'file.html').stat().st_ino)
            with self.assertRaises(FileExistsError):m.restore_directory(row,target,[root],root)

if __name__=='__main__':unittest.main()
