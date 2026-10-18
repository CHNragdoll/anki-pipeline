"""Verify master-generated packages in a disposable native Anki collection.

Never accepts a user collection/profile path. Source and candidate packages are
read-only; reviewed/suspended/flagged study state exists only in TemporaryDirectory.
Native NFC normalization is reported separately from exact field and media bytes.
ZIP member parity and browser/phone display checks are outside this command.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unicodedata
import zipfile


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def compare_fields(guid, expected, actual):
    """Accept only exact text or Anki's NFC normalization, per field value."""
    if actual is None:
        raise ValueError('native note missing for GUID '+guid)
    expected_fields=expected.split('\x1f');actual_fields=actual.split('\x1f')
    if len(expected_fields)!=len(actual_fields):
        raise ValueError('native field count differs for GUID '+guid)
    counts={'values_checked':len(expected_fields),'values_raw_equal':0,'values_nfc_normalized':0}
    for index,(original,imported) in enumerate(zip(expected_fields,actual_fields)):
        if imported==original:
            counts['values_raw_equal']+=1
        elif imported==unicodedata.normalize('NFC',original):
            counts['values_nfc_normalized']+=1
        else:
            offset=next((i for i,(a,b) in enumerate(zip(imported,original)) if a!=b),min(len(imported),len(original)))
            raise ValueError('native field differs for GUID '+guid+', field '+str(index)+' at '+str(offset))
    return counts



_CHUNK = 1024 * 1024
_MAX_SQLITE_BYTES = 8 * 1024 ** 3
_MAX_INDEX_BYTES = 64 * 1024 ** 2
_MAX_WINDOW_BYTES = 128 * 1024 ** 2


def _bounded_bytes(stream, limit):
    value = bytearray()
    while block := stream.read(min(_CHUNK, limit + 1 - len(value))):
        value.extend(block)
        if len(value) > limit:
            raise ValueError('expected archive metadata limit exceeded')
    return bytes(value)


def _zstd_chunks(archive, member, limit, *, expected_size=None, max_window_bytes=_MAX_WINDOW_BYTES):
    # Optional verification dependency, never an import-time Anki dependency.
    import zstandard as zstd
    if archive.getinfo(member).compress_type != zipfile.ZIP_STORED:
        raise ValueError('modern zstd frame must be ZIP Stored')
    with archive.open(member) as incoming:
        header = incoming.read(18)  # Maximum standard frame-header length.
        if not header.startswith(b'\x28\xb5\x2f\xfd'):
            raise ValueError('expected standard zstd frame')
        try:
            parameters = zstd.get_frame_parameters(header)
            if parameters.window_size > max_window_bytes:
                raise ValueError('expected zstd window limit exceeded')
            if parameters.dict_id:
                raise ValueError('unexpected zstd frame dictionary')
            declared = parameters.content_size
            if declared != zstd.CONTENTSIZE_UNKNOWN:
                if declared > limit:
                    raise ValueError('expected decoded size limit exceeded')
                if expected_size is not None and declared != expected_size:
                    raise ValueError('expected media size differs from frame')
            # The pinned 0.23.0 C extension takes bytes here, as does the
            # frame-parameter window_size checked above (see real-frame test).
            decoder = zstd.ZstdDecompressor(max_window_size=max_window_bytes).decompressobj()
            total = 0
            compressed = header
            while compressed:
                if decoder.eof:
                    raise ValueError('extra bytes after zstd frame')
                decoded = decoder.decompress(compressed)
                # 256 input bytes can finish one pending <=128KiB block plus
                # at most 64 minimum-size RLE blocks: <8.3MiB per return value.
                # The decoder's history window was bounded before allocation.
                total += len(decoded)
                if total > limit:
                    raise ValueError('expected decoded size limit exceeded')
                if decoder.unused_data or decoder.unconsumed_tail:
                    raise ValueError('extra bytes after zstd frame')
                for start in range(0, len(decoded), _CHUNK):
                    yield decoded[start:start + _CHUNK]
                compressed = incoming.read(256)
            if not decoder.eof:
                raise ValueError('truncated zstd frame')
            if declared != zstd.CONTENTSIZE_UNKNOWN and total != declared:
                raise ValueError('zstd frame declared size differs')
            if expected_size is not None and total != expected_size:
                raise ValueError('expected media size differs')
        except zstd.ZstdError as error:
            raise ValueError('invalid zstd frame: ' + str(error)) from error


def _media_name(name):
    if (not isinstance(name, str) or not name or name in {'.', '..'} or
            any(ord(c) < 32 or c in '/\\:' for c in name) or
            len(name.encode('utf-8')) > 255 or unicodedata.normalize('NFC', name) != name):
        raise ValueError('unsafe expected media name')


class ExpectedArchive:
    """Read actual candidate bytes; only the expected SQLite is materialized."""
    def __init__(self, archive):
        self.archive = archive
        listed = archive.namelist(); names = set(listed)
        if len(listed) != len(names):
            raise ValueError('duplicate expected archive member')
        self.version = None
        if 'meta' in names:
            from anki.import_export_pb2 import PackageMetadata
            with archive.open('meta') as stream:
                metadata = PackageMetadata.FromString(_bounded_bytes(stream, 1024))
            self.version = metadata.version
            if self.version not in (PackageMetadata.VERSION_LEGACY_1,
                                    PackageMetadata.VERSION_LEGACY_2, PackageMetadata.VERSION_LATEST):
                raise ValueError('unsupported expected package version')
        self.modern = self.version == 3
        if self.modern:
            from anki.import_export_pb2 import MediaEntries
            if 'collection.anki21b' not in names:
                raise ValueError('modern expected collection missing')
            self.entry = 'collection.anki21b'
            raw = bytearray()
            for block in _zstd_chunks(archive, 'media', _MAX_INDEX_BYTES):
                raw.extend(block)
            entries = MediaEntries.FromString(bytes(raw)).entries
            if len(entries) > 250000:
                raise ValueError('expected media entry count limit exceeded')
            self.media = []
            for index, item in enumerate(entries):
                if len(item.sha1) != 20:
                    raise ValueError('expected media SHA1 must contain 20 bytes')
                member = str(item.legacy_zip_filename) if item.HasField('legacy_zip_filename') else str(index)
                self.media.append((member, item.name, item.size, item.sha1))
        else:
            if 'collection.anki21b' in names:
                raise ValueError('modern expected collection requires version 3')
            self.entry = 'collection.anki21' if 'collection.anki21' in names else 'collection.anki2'
            def unique(pairs):
                value = {}
                for key, child in pairs:
                    if key in value:
                        raise ValueError('duplicate legacy media member')
                    value[key] = child
                return value
            with archive.open('media') as stream:
                mapping = json.loads(_bounded_bytes(stream, _MAX_INDEX_BYTES), object_pairs_hook=unique)
            if not isinstance(mapping, dict):
                raise ValueError('expected legacy media map required')
            self.media = [(member, name, None, None) for member, name in mapping.items()]
        if self.entry not in names or archive.getinfo(self.entry).is_dir():
            raise ValueError('expected collection missing')
        members, aliases = set(), set()
        for member, name, _, _ in self.media:
            _media_name(name)
            if (not isinstance(member, str) or member not in names or
                    member in {'meta', 'media', 'collection.anki2', 'collection.anki21', 'collection.anki21b'} or
                    archive.getinfo(member).is_dir() or member in members or name in aliases):
                raise ValueError('ambiguous or missing expected media member/name')
            members.add(member); aliases.add(name)
        self.receipt = {'format': 'modern-v3' if self.modern else 'legacy',
                        'package_version': self.version, 'collection': None,
                        'media_manifest': 'zstd-official-MediaEntries' if self.modern else 'legacy-JSON'}

    def _chunks(self, member, limit, expected_size=None):
        if self.modern:
            yield from _zstd_chunks(self.archive, member, limit, expected_size=expected_size)
        else:
            if self.archive.getinfo(member).file_size > limit:
                raise ValueError('expected decoded size limit exceeded')
            with self.archive.open(member) as stream:
                yield from iter(lambda: stream.read(_CHUNK), b'')

    def write_collection(self, path, *, max_bytes=_MAX_SQLITE_BYTES):
        size = 0; digest = hashlib.sha256()
        with Path(path).open('xb') as target:
            for block in self._chunks(self.entry, max_bytes):
                target.write(block); size += len(block); digest.update(block)
        self.receipt['collection'] = {'member': self.entry, 'bytes': size, 'sha256': digest.hexdigest()}

    def verify_media(self, directory):
        for member, name, size, expected_sha1 in self.media:
            actual = Path(directory) / name
            if actual.is_symlink() or not actual.is_file():
                raise ValueError('expected media file missing or not regular: ' + name)
            expected_sha256 = hashlib.sha256(); actual_sha256 = hashlib.sha256(); sha1 = hashlib.sha1()
            with actual.open('rb') as stream:
                for block in self._chunks(member, size if self.modern else self.archive.getinfo(member).file_size,
                                          expected_size=size):
                    expected_sha256.update(block); sha1.update(block)
                    got = stream.read(len(block)); actual_sha256.update(got)
                    if got != block:
                        raise ValueError('native media bytes differ: ' + name)
                if stream.read(1):
                    raise ValueError('native media bytes differ: ' + name)
            if expected_sha1 is not None and sha1.digest() != expected_sha1:
                raise ValueError('expected media SHA1 differs: ' + name)
            if expected_sha256.digest() != actual_sha256.digest():
                raise ValueError('native media bytes SHA256 differ: ' + name)
        return {'files_checked': len(self.media), 'sha256_exact': True, 'missing_count': 0,
                'decoded_size_sha1_exact': self.modern}


def verify(source,candidate,report):
    report=Path(report)
    if report.exists():raise FileExistsError('native evidence must be a new output')
    # Native modules ship with the installed application, independently of the
    # Python generator. This is a local acceptance command, not a dependency.
    sys.path.insert(0,'/Applications/Anki.app/Contents/Resources/app_packages')
    from anki.collection import Collection
    from anki.import_export_pb2 import ImportAnkiPackageOptions,ImportAnkiPackageRequest
    before={str(p):sha(p) for p in (source,candidate)};started=time.monotonic()
    field_evidence={'notes_checked':0,'notes_raw_equal':0,'notes_nfc_normalized':0,
                    'values_checked':0,'values_raw_equal':0,'values_nfc_normalized':0}
    with tempfile.TemporaryDirectory(prefix='study-native-qa-') as folder:
        col=Collection(str(Path(folder)/'collection.anki2'))
        try:
            def load(path):
                col.import_anki_package(ImportAnkiPackageRequest(package_path=str(Path(path).resolve()),
                    options=ImportAnkiPackageOptions(with_scheduling=True)))
                col.models._clear_cache()
            def identities():return col.db.all('select id,guid,mid from notes order by id')
            def states():
                fields=[r[1] for r in col.db.all('pragma table_info(cards)')]
                keep=[i for i,name in enumerate(fields) if name not in {'mod','usn'}]
                return [[r[i] for i in keep] for r in col.db.all('select * from cards order by id')]
            load(source);notes=col.note_count();cards=col.card_count()
            cid=col.db.scalar('select id from cards where type=0 and queue>=0 order by id limit 1')
            if cid is None:raise ValueError('acceptance source needs one fresh test card')
            col.decks.select(col.get_card(cid).did);col.sched.reset()
            queued=col.sched.get_queued_cards(fetch_limit=1).cards[0]
            reviewed=col.get_card(queued.card.id);reviewed.start_timer()
            col.sched.answer_card(col.sched.build_answer(card=reviewed,states=queued.states,rating=3))
            col.sched.suspend_cards([reviewed.id]);col.set_user_flag_for_cards(3,[reviewed.id])
            old_ids=identities();old_states=states();old_log=col.db.all('select * from revlog order by id')
            assert old_log
            for _ in range(2):
                load(candidate)
                assert (col.note_count(),col.card_count())==(notes,cards)
                assert identities()==old_ids and states()==old_states
                assert col.db.all('select * from revlog order by id')==old_log
            with zipfile.ZipFile(candidate) as archive:
                expected=ExpectedArchive(archive)
                # Only one private expected SQLite, never a second media tree.
                expected_path=Path(folder)/'candidate-readonly.anki2'
                expected.write_collection(expected_path)
                raw=sqlite3.connect(expected_path.as_uri()+'?mode=ro',uri=True)
                try:
                    for guid,fields in raw.execute('select guid,flds from notes'):
                        got=col.db.scalar('select flds from notes where guid=?',guid)
                        counts=compare_fields(guid,fields,got)
                        field_evidence['notes_checked']+=1
                        field_evidence['notes_raw_equal' if got==fields else 'notes_nfc_normalized']+=1
                        for key,value in counts.items():field_evidence[key]+=value
                finally:raw.close()
                assert field_evidence['notes_checked']==notes
                media_evidence=expected.verify_media(col.media.dir())
                archive_evidence=expected.receipt
            rendered=0
            for cid in col.db.list('select id from cards order by id limit 12'):
                card=col.get_card(cid);question=card.question();answer=card.answer()
                assert isinstance(question,str) and question.strip()
                assert isinstance(answer,str) and answer.strip()
                rendered+=1
            assert not col.media.check().missing
        finally:col.close()
    assert all(sha(p)==digest for p,digest in before.items())
    result={'schema':'study-native-acceptance.v2','source':str(source),'candidate':str(candidate),
        'sha256':before,'notes':notes,'cards':cards,'duplicate_update_imports':2,
        'identity_schedule_flags_revlog_preserved':True,
        'field_verification':{**field_evidence,'all_values_exact_or_nfc':True},
        'media_verification':media_evidence,'expected_archive':archive_evidence,
        'source_candidate_package_bytes_unchanged':True,
        'source_candidate_zip_member_parity_verified_by_this_command':False,
        'native_rendered_samples':rendered,
        'native_render_scope':'nonempty question/answer strings from Anki template renderer',
        'actual_user_profile_modified':False,'browser_visual_verified':False,'phone_verified':False,
        'elapsed_seconds':round(time.monotonic()-started,2)}
    report.parent.mkdir(parents=True,exist_ok=True)
    with report.open('x') as output:output.write(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--candidate',type=Path,required=True);parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args();print(json.dumps(verify(args.source,args.candidate,args.report),ensure_ascii=False))
