"""Physical ZIP transport checks; all archives and mutations are disposable."""
import hashlib
import io
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

from anki_pipeline import study_apkg_repack as repack


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def records(path):
    raw = path.read_bytes()
    with zipfile.ZipFile(path) as archive:
        entries = sorted(archive.infolist(), key=lambda item: item.header_offset)
        ends = [item.header_offset for item in entries[1:]] + [archive.start_dir]
        return {item.filename: raw[item.header_offset:end] for item, end in zip(entries, ends)}


class NonSeekable(io.BytesIO):
    def seek(self, *args):
        raise io.UnsupportedOperation('fixture is a streaming writer')


class RepackApkgTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='study-apkg-repack-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source.apkg'
        self.destination = self.root / 'new.apkg'
        self.contents = {'collection.anki21': b'old collection', 'media': b'{"0":"original.mp3"}',
                         '0': bytes(range(256)) * 128, '音频😀': b'original stored media\x00\xff'}
        with zipfile.ZipFile(self.source, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
            archive.comment = '原注释😀'.encode()
            for name, data in self.contents.items():
                info = zipfile.ZipInfo(name, (2024, 2, 4, 6, 8, 10))
                info.comment = b'member comment'
                info.extra = struct.pack('<HH4s', 0xcafe, 4, b'keep')
                info.external_attr = 0o100640 << 16
                archive.writestr(info, data, compress_type=(zipfile.ZIP_STORED if name == '音频😀'
                                                           else zipfile.ZIP_DEFLATED), compresslevel=1)

    def repack(self, replacements=None, **options):
        return repack.repack_apkg(self.source, self.destination, replacements or {},
            expected_source_sha256=options.pop('expected_source_sha256', sha(self.source)), **options)

    def test_preserves_stored_and_deflated_records_and_replaces_only_explicit_members(self):
        before = self.source.read_bytes(); original_records = records(self.source)
        replacement = self.root / 'new-collection'
        replacement.write_bytes(b'new collection\x00\xff' * 200)
        replacements = {'collection.anki21': replacement, 'media': b'{"0":"original.mp3","1":"new.js"}'}
        receipt = self.repack(replacements)
        self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual(replacement.read_bytes(), b'new collection\x00\xff' * 200)
        actual_records = records(self.destination)
        for name in self.contents.keys() - replacements.keys():
            self.assertEqual(actual_records[name], original_records[name], name)
        with zipfile.ZipFile(self.source) as source, zipfile.ZipFile(self.destination) as actual:
            self.assertEqual(actual.namelist(), source.namelist())
            self.assertEqual(actual.comment, source.comment)
            self.assertIsNone(actual.testzip())
            for name, data in self.contents.items():
                expected = replacements.get(name, data)
                expected = expected.read_bytes() if isinstance(expected, Path) else expected
                self.assertEqual(actual.read(name), expected, name)
                if name in replacements:
                    self.assertEqual(actual.getinfo(name).compress_type, zipfile.ZIP_DEFLATED)
                else:
                    for attribute in ['date_time', 'comment', 'extra', 'external_attr', 'flag_bits',
                                      'CRC', 'file_size', 'compress_size', 'compress_type']:
                        self.assertEqual(getattr(actual.getinfo(name), attribute),
                                         getattr(source.getinfo(name), attribute), attribute)
        self.assertEqual(receipt['source_sha256'], hashlib.sha256(before).hexdigest())
        self.assertEqual(receipt['copied_members'], 2)
        self.assertEqual(receipt['replaced_members'], 2)
        self.assertEqual(receipt['copied_record_bytes'], sum(len(original_records[name]) for name in ['0', '音频😀']))
        self.assertEqual(receipt['destination_bytes'], self.destination.stat().st_size)

    def test_replacement_uses_standard_deflate_level_nine(self):
        raw = bytes(range(256)) * 512
        self.repack({'collection.anki21': raw})
        reference = self.root / 'reference.zip'
        with zipfile.ZipFile(self.source) as source, zipfile.ZipFile(reference, 'w') as target:
            target.writestr(source.getinfo('collection.anki21'), raw,
                            compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        self.assertEqual(records(self.destination)['collection.anki21'], records(reference)['collection.anki21'])

    def test_non_ascii_cp437_filename_is_rejected_before_destination_creation(self):
        with zipfile.ZipFile(self.source, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('x.bin', b'CP437 named member')
            archive.writestr('replace', b'old')
        with zipfile.ZipFile(self.source) as archive:
            local = archive.getinfo('x.bin').header_offset
            central = archive.start_dir
        raw = bytearray(self.source.read_bytes())
        # Construct a valid legacy name by changing only same-length name bytes
        # and clearing UTF-8 in both standard-library-generated headers.
        self.assertEqual(raw[local + 30:local + 35], b'x.bin')
        self.assertEqual(raw[central + 46:central + 51], b'x.bin')
        raw[local + 30:local + 35] = raw[central + 46:central + 51] = b'\x82.bin'
        for flags_at in [local + 6, central + 8]:
            flags = struct.unpack_from('<H', raw, flags_at)[0]
            struct.pack_into('<H', raw, flags_at, flags & ~0x800)
        self.source.write_bytes(raw)
        with zipfile.ZipFile(self.source) as archive:
            self.assertEqual(archive.read('é.bin'), b'CP437 named member')
            self.assertFalse(archive.getinfo('é.bin').flag_bits & 0x800)
        with self.assertRaisesRegex(ValueError, 'encoding.*unsupported|unsupported.*encoding'):
            self.repack({'replace': b'new'})
        self.assertFalse(self.destination.exists())

    def test_ascii_filename_with_utf8_flag_is_rejected_before_destination_creation(self):
        with zipfile.ZipFile(self.source, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('ascii.bin', b'ASCII with explicit UTF-8 flag')
            archive.writestr('replace', b'old')
        with zipfile.ZipFile(self.source) as archive:
            local = archive.getinfo('ascii.bin').header_offset
            central = archive.start_dir
        raw = bytearray(self.source.read_bytes())
        for flags_at in [local + 6, central + 8]:
            flags = struct.unpack_from('<H', raw, flags_at)[0]
            struct.pack_into('<H', raw, flags_at, flags | 0x800)
        self.source.write_bytes(raw)
        with zipfile.ZipFile(self.source) as archive:
            self.assertEqual(archive.read('ascii.bin'), b'ASCII with explicit UTF-8 flag')
            self.assertTrue(archive.getinfo('ascii.bin').flag_bits & 0x800)
        with self.assertRaisesRegex(ValueError, 'encoding.*unsupported|unsupported.*encoding'):
            self.repack({'replace': b'new'})
        self.assertFalse(self.destination.exists())

    def test_mismatched_local_filename_or_flags_are_rejected_before_destination_creation(self):
        original = self.source.read_bytes()
        with zipfile.ZipFile(self.source) as archive:
            local = archive.getinfo('0').header_offset
        for changed in ['filename', 'flags']:
            raw = bytearray(original)
            if changed == 'filename':
                raw[local + 30] = ord('1')
            else:
                flags = struct.unpack_from('<H', raw, local + 6)[0]
                struct.pack_into('<H', raw, local + 6, flags ^ 0x800)
            self.source.write_bytes(raw)
            with self.subTest(changed=changed), self.assertRaisesRegex(ValueError, 'local.*name|local.*flag'):
                self.repack({'media': b'new'})
            self.assertFalse(self.destination.exists())

    def test_success_fsyncs_the_owned_output_after_complete_zip_bytes_are_flushed(self):
        original_fsync = os.fsync
        synced = []

        def inspect_and_sync(descriptor):
            actual = os.fstat(descriptor)
            named = self.destination.stat()
            self.assertEqual((actual.st_dev, actual.st_ino), (named.st_dev, named.st_ino))
            with zipfile.ZipFile(self.destination) as archive:
                self.assertEqual(archive.read('media'), b'new manifest')
                self.assertIsNone(archive.testzip())
            synced.append(descriptor)
            original_fsync(descriptor)

        with patch.object(repack.os, 'fsync', side_effect=inspect_and_sync):
            self.repack({'media': b'new manifest'})
        self.assertEqual(len(synced), 1)

    def test_fsync_failure_returns_no_receipt_and_preserves_the_new_incomplete_target(self):
        before = self.source.read_bytes()
        with patch.object(repack.os, 'fsync', side_effect=OSError('fixture fsync failure')):
            with self.assertRaisesRegex(OSError, 'fixture fsync failure'):
                self.repack({'media': b'new manifest'})
        self.assertEqual(self.source.read_bytes(), before)
        self.assertTrue(self.destination.is_file())

    def test_preserves_prefix_and_original_central_order_when_it_differs_from_physical_order(self):
        prefix = b'opaque ZIP prefix\x00\xff\r\n'
        with self.source.open('wb') as stream:
            stream.write(prefix)
            with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr('first', b'old first')
                archive.writestr('second', b'unchanged second')
                archive.filelist.reverse()  # Valid central order independent of local order.
        before = records(self.source)
        receipt = self.repack({'first': b'new first with a different length'})
        self.assertEqual(self.destination.read_bytes()[:len(prefix)], prefix)
        self.assertEqual(records(self.destination)['second'], before['second'])
        self.assertEqual(receipt['preserved_prefix_bytes'], len(prefix))
        with zipfile.ZipFile(self.destination) as archive:
            self.assertEqual(archive.namelist(), ['second', 'first'])
            self.assertEqual(archive.read('first'), b'new first with a different length')
            self.assertEqual(archive.read('second'), b'unchanged second')

    def test_empty_archive_and_no_replacements_produce_a_valid_new_archive(self):
        with zipfile.ZipFile(self.source, 'w') as archive:
            archive.comment = b'empty archive'
        receipt = self.repack()
        self.assertEqual(receipt['copied_members'], 0)
        self.assertEqual(receipt['replaced_members'], 0)
        with zipfile.ZipFile(self.destination) as archive:
            self.assertEqual(archive.namelist(), [])
            self.assertEqual(archive.comment, b'empty archive')
            self.assertIsNone(archive.testzip())

    def test_force_zip64_local_header_is_copied_byte_for_byte(self):
        with zipfile.ZipFile(self.source, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('replace', b'old')
            with archive.open('forced', 'w', force_zip64=True) as stream:
                stream.write(b'forced ZIP64 payload' * 200)
        before = records(self.source)['forced']
        self.assertEqual(before[18:26], b'\xff' * 8, 'fixture has ZIP64 local sizes')
        self.repack({'replace': b'new and longer payload'})
        self.assertEqual(records(self.destination)['forced'], before)
        with zipfile.ZipFile(self.destination) as archive:
            self.assertEqual(archive.read('forced'), b'forced ZIP64 payload' * 200)
            self.assertIsNone(archive.testzip())

    def test_nonseekable_data_descriptors_including_zip64_are_copied_with_the_records(self):
        streaming = NonSeekable()
        with zipfile.ZipFile(streaming, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('replace', b'old')
            archive.writestr('descriptor', b'normal descriptor payload' * 100)
            with archive.open('descriptor64', 'w', force_zip64=True) as stream:
                stream.write(b'ZIP64 descriptor payload' * 100)
        self.source.write_bytes(streaming.getvalue())
        before = records(self.source)
        self.assertIn(b'PK\x07\x08', before['descriptor'][-16:])
        self.assertIn(b'PK\x07\x08', before['descriptor64'][-24:])
        self.repack({'replace': b'new value at a different offset'})
        actual = records(self.destination)
        for name in ['descriptor', 'descriptor64']:
            self.assertEqual(actual[name], before[name])
        with zipfile.ZipFile(self.destination) as archive:
            self.assertEqual(archive.read('descriptor'), b'normal descriptor payload' * 100)
            self.assertEqual(archive.read('descriptor64'), b'ZIP64 descriptor payload' * 100)
            self.assertIsNone(archive.testzip())

    def test_zip64_central_directory_for_more_than_65535_members(self):
        with zipfile.ZipFile(self.source, 'w', compression=zipfile.ZIP_STORED) as archive:
            for index in range(65536):
                archive.writestr(str(index), b'')
        before = records(self.source)
        receipt = self.repack({'0': b'new first member'})
        self.assertEqual(receipt['copied_members'], 65535)
        self.assertEqual(receipt['replaced_members'], 1)
        actual = records(self.destination)
        self.assertEqual({name: raw for name, raw in actual.items() if name != '0'},
                         {name: raw for name, raw in before.items() if name != '0'})
        self.assertIn(b'PK\x06\x06', self.destination.read_bytes()[-100:])
        with zipfile.ZipFile(self.destination) as archive:
            self.assertEqual(len(archive.infolist()), 65536)
            self.assertEqual(archive.read('0'), b'new first member')
            self.assertIsNone(archive.testzip())

    def test_wrong_external_sha_fails_before_creating_destination(self):
        for pin in ['0' * 64, 'invalid', None]:
            with self.subTest(pin=pin), self.assertRaisesRegex(ValueError, 'SHA|sha256'):
                self.repack(expected_source_sha256=pin)
            self.assertFalse(self.destination.exists())

    def test_duplicate_unknown_members_and_invalid_replacement_types_are_rejected(self):
        for replacements in [{'missing': b'new'}, {'media': bytearray(b'bad')}, {17: b'bad'}]:
            with self.subTest(replacements=replacements), self.assertRaises(ValueError):
                self.repack(replacements)
            self.assertFalse(self.destination.exists())
        with warnings.catch_warnings(), zipfile.ZipFile(self.source, 'w') as archive:
            warnings.simplefilter('ignore', UserWarning)
            archive.writestr('duplicate', b'first')
            archive.writestr('duplicate', b'second')
        with self.assertRaisesRegex(ValueError, 'duplicate|unique'):
            self.repack({'duplicate': b'new'})
        self.assertFalse(self.destination.exists())

    def test_existing_destination_including_a_source_hardlink_is_untouched(self):
        self.destination.write_bytes(b'foreign output')
        with self.assertRaises(FileExistsError):
            self.repack({'media': b'new'})
        self.assertEqual(self.destination.read_bytes(), b'foreign output')
        self.destination.unlink()
        os.link(self.source, self.destination)
        before = self.source.read_bytes()
        with self.assertRaises(FileExistsError):
            self.repack({'media': b'new'})
        self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual(self.destination.read_bytes(), before)

    def test_source_must_be_a_regular_file_and_not_a_symlink(self):
        regular = self.root / 'regular.apkg'
        self.source.rename(regular)
        self.source.symlink_to(regular)
        with self.assertRaisesRegex(ValueError, 'regular|symlink'):
            self.repack()
        self.assertFalse(self.destination.exists())
        self.source.unlink(); self.source.mkdir()
        with self.assertRaisesRegex(ValueError, 'regular'):
            repack.repack_apkg(self.source, self.destination, {}, expected_source_sha256='0' * 64)
        self.assertFalse(self.destination.exists())

    def test_source_mutation_during_copy_is_rejected_without_touching_replacements(self):
        replacement = self.root / 'replacement'
        replacement.write_bytes(b'private replacement')
        original_copy = repack._copy_range
        changed = False

        def mutate(*args):
            nonlocal changed
            original_copy(*args)
            if not changed:
                changed = True
                with self.source.open('r+b') as stream:
                    stream.write(b'changed source')

        with patch.object(repack, '_copy_range', side_effect=mutate):
            with self.assertRaisesRegex(ValueError, 'source.*changed'):
                self.repack({'media': replacement})
        self.assertEqual(replacement.read_bytes(), b'private replacement')
        self.assertTrue(self.destination.is_file(), 'failed new output is deliberately retained')

    def test_source_path_replacement_is_detected_even_when_open_fd_bytes_are_unchanged(self):
        original_copy = repack._copy_range
        changed = False

        def replace_path(*args):
            nonlocal changed
            original_copy(*args)
            if not changed:
                changed = True
                raw = self.source.read_bytes()
                self.source.rename(self.root / 'original-retained.apkg')
                self.source.write_bytes(raw)

        with patch.object(repack, '_copy_range', side_effect=replace_path):
            with self.assertRaisesRegex(ValueError, 'source.*changed'):
                self.repack({'media': b'new'})

    def test_failure_never_removes_a_foreign_destination_path_or_replacement_file(self):
        replacement = self.root / 'replacement'
        replacement.write_bytes(b'private replacement')

        def fail_after_path_replacement(*args):
            self.destination.rename(self.root / 'own-incomplete.apkg')
            self.destination.write_bytes(b'foreign path replacement')
            raise OSError('fixture copy failure')

        with patch.object(repack, '_copy_range', side_effect=fail_after_path_replacement):
            with self.assertRaisesRegex(OSError, 'fixture copy failure'):
                self.repack({'media': replacement})
        self.assertEqual(self.destination.read_bytes(), b'foreign path replacement')
        self.assertEqual(replacement.read_bytes(), b'private replacement')
        self.assertTrue((self.root / 'own-incomplete.apkg').exists())


if __name__ == '__main__':
    unittest.main()
