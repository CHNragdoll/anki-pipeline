"""Pinned standard results-JSONL reuse; delegates all content checks/producers."""
from __future__ import annotations

import copy
import hashlib
import os
from pathlib import Path
import re
import stat
from urllib.parse import unquote, urljoin, urlsplit

from . import study_catalog_web_delivery as delivery
from . import study_catalog_web_materialize as materialize
from . import study_compiled_build as shared

_LINE = 65536
_ROW = 1024 * 1024
_FILE = 256 * 1024 * 1024
_ASSET = re.compile(r'_qa_compiled_([a-f0-9]{64})\.(?:json|html|js)')


def _same(left, right):
    return shared._json(left) == shared._json(right)


class _Receipts:
    def __init__(self):
        self.items = {}
        self._publication_active = False

    def _outside_publication(self):
        if self._publication_active:
            raise RuntimeError('receipt mutation/read cannot overlap first owned publication')

    def read(self, path, expected, *, size=None, keep=True):
        self._outside_publication()
        if size is not None and (type(size) is not int or not 0 <= size <= _FILE):
            raise ValueError('bounded exact asset byte count required')
        raw, receipt = delivery._read(path, expected, limit=_FILE, keep=keep)
        if size is not None and receipt['bytes'] != size:
            raise ValueError('cached asset byte count differs')
        name = receipt['path']
        old = self.items.get(name)
        if old is not None and old != receipt:
            raise ValueError('one source path changed within result reuse')
        self.items[name] = receipt
        return raw

    def check(self):
        self._outside_publication()
        for receipt in self.items.values():
            _, actual = delivery._read(receipt['path'], receipt['sha256'], limit=_FILE, keep=False)
            if actual != receipt:
                error = ValueError('cached/current resource changed before completion: ' + receipt['path'] +
                                   '; expected=' + repr(receipt) + '; actual=' + repr(actual))
                error.receipt_difference = {'expected': copy.deepcopy(receipt), 'actual': actual}
                raise error

    def admit_new_owned(self, receipt):
        """Admit a caller-created output after publication, never rebase an input."""
        self._outside_publication()
        if receipt['path'] in self.items or any(
                old['six'][:2] == receipt['six'][:2] for old in self.items.values()):
            raise ValueError('an existing receipt/inode cannot reenter owned publication')
        _, actual = delivery._read(receipt['path'], receipt['sha256'], limit=_FILE, keep=False)
        if actual != receipt:
            error = ValueError('owned output changed after publication: ' + receipt['path'] +
                               '; expected=' + repr(receipt) + '; actual=' + repr(actual))
            error.receipt_difference = {'expected': copy.deepcopy(receipt), 'actual': actual}
            raise error
        self.items[receipt['path']] = copy.deepcopy(receipt)

    def publish_new_owned(self, directory, directory_fd, outputs):
        """First publication and admission share held FDs, with no reopen gap.

        Only this synchronous call may mutate this collector until it returns.
        The helper authenticates creator pins and complete held-FD identities;
        all existing path/inode exclusion happens before its quiet/hash phase.
        After the final held-FD inspection, commit performs memory work only.
        """
        from .study_owned_output_publication import owned_output_receipts
        self._outside_publication()
        self._publication_active = True
        try:
            def prepare(initial):
                old_inodes = {tuple(row['six'][:2]) for row in self.items.values()}
                initial = copy.deepcopy(initial)
                for row in initial.values():
                    if row['path'] in self.items or tuple(row['six'][:2]) in old_inodes:
                        raise ValueError('an existing receipt/inode cannot reenter owned publication')
                collection, count = self.items, len(self.items)
                committed = False

                def commit(final):
                    nonlocal committed
                    if committed or self.items is not collection or len(self.items) != count:
                        raise ValueError('receipt collection changed during owned publication')
                    if set(final) != set(initial):
                        raise ValueError('owned publication batch membership changed')
                    updates = {}
                    for name, row in final.items():
                        before = initial[name]
                        if (set(row) != set(before) or
                                any(row[key] != before[key] for key in ('path', 'bytes', 'sha256')) or
                                row['six'][:5] != before['six'][:5] or row['path'] in self.items):
                            raise ValueError('owned publication fixed identity changed before admission')
                        updates[row['path']] = copy.deepcopy(row)
                    # No file I/O, old-inode scan or callback after final inspection.
                    self.items.update(updates)
                    committed = True
                return commit

            return owned_output_receipts(directory, directory_fd, outputs, prepare_admission=prepare)
        finally:
            self._publication_active = False


class _Log:
    def __init__(self, descriptor):
        if set(descriptor) != {'path', 'sha256', 'bytes', 'assets'}:
            raise ValueError('cache file requires external pin/bytes and assets root')
        self.path, self.assets = Path(descriptor['path']), Path(descriptor['assets'])
        if not self.path.is_absolute() or not self.assets.is_absolute():
            raise ValueError('cache paths must be absolute')
        if type(descriptor['bytes']) is not int or not 0 <= descriptor['bytes'] <= _FILE:
            raise ValueError('cache file byte limit differs')
        self.fd = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            before = os.fstat(self.fd)
            if not stat.S_ISREG(before.st_mode) or before.st_size != descriptor['bytes']:
                raise ValueError('cache file must be bounded regular bytes')
            self.before = delivery._six(before)
            self.descriptor = descriptor
            self.check()
        except BaseException:
            os.close(self.fd)
            raise

    def check(self):
        if self.before != delivery._six(os.fstat(self.fd)) or self.before != delivery._six(self.path.lstat()):
            raise ValueError('pinned results file FD/path identity changed: ' + repr({'path': str(self.path), 'before': self.before, 'fd': delivery._six(os.fstat(self.fd)), 'path_now': delivery._six(self.path.lstat())}))

    def rows(self):
        digest, pending, offset, total = hashlib.sha256(), b'', 0, 0
        while raw := os.read(self.fd, _LINE):
            total += len(raw)
            if total > _FILE:
                raise ValueError('cache file grew beyond limit')
            digest.update(raw)
            pending += raw
            while b'\n' in pending:
                line, pending = pending.split(b'\n', 1)
                line += b'\n'
                if len(line) > _ROW:
                    raise ValueError('cache JSONL row exceeds limit')
                yield offset, line
                offset += len(line)
            if len(pending) > _ROW:
                raise ValueError('cache JSONL row exceeds limit')
        self.check()
        if total != self.descriptor['bytes'] or digest.hexdigest() != self.descriptor['sha256']:
            raise ValueError('external results file SHA/bytes differs')
        # A crashed producer's final partial row is never an accepted success.

    def read(self, offset, length, expected):
        self.check()
        raw = os.pread(self.fd, length, offset)
        self.check()
        if len(raw) != length or hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError('cached result row changed')
        return shared.inputs._json(raw)

    def close(self):
        os.close(self.fd)


class ResultCache:
    """One externally pinned cache index; never trusts identity alone."""
    def __init__(self, descriptor):
        if set(descriptor) != {'path', 'sha256'}:
            raise ValueError('cache index requires an external descriptor')
        raw, self.index_receipt = delivery._read(descriptor['path'], descriptor['sha256'])
        value = shared.inputs._json(raw)
        if (set(value) != {'schema', 'files', 'completed_semantic'} or
                value['schema'] != 'study-complete-result-cache.v1' or
                not isinstance(value['files'], list) or len(value['files']) > 64 or
                not isinstance(value['completed_semantic'], dict)):
            raise ValueError('cache index schema differs')
        self.logs, self.rows, self.completed = [], {}, value['completed_semantic']
        seen = set()
        try:
            for item in value['files']:
                log = _Log(item)
                self.logs.append(log)
                for offset, line in log.rows():
                    row = shared.inputs._json(line)
                    if row.get('status') not in {'ok', 'failed'}:
                        raise ValueError('unknown cache row status')
                    identity = row.get('identity')
                    if type(identity) is not str or not identity or len(identity) > 1024:
                        raise ValueError('bounded result identity required')
                    if row['status'] != 'ok':
                        continue
                    if identity in seen or len(seen) >= 100000:
                        raise ValueError('duplicate or excessive successful cache identities')
                    seen.add(identity)
                    if row.get('result', {}).get('mode') == 'authored':
                        continue  # Original cheap source validation is always rerun.
                    self.rows[identity] = (log, offset, len(line), shared._sha(line))
            if set(self.completed) - self.rows.keys():
                raise ValueError('semantic reuse descriptor has no cached success')
        except BaseException:
            self.close()
            raise

    def get(self, identity):
        item = self.rows.get(identity)
        if item is None:
            return None
        log, offset, length, pin = item
        return log.read(offset, length, pin), log.assets

    def check(self):
        delivery._again(self.index_receipt)
        for log in self.logs:
            log.check()

    def close(self):
        for log in self.logs:
            log.close()
        self.logs = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        try:
            if exc[0] is None:
                self.check()
        finally:
            self.close()


class _ValidationOnly:
    def publish(self, prefix, suffix, raw):
        return prefix + shared._sha(raw) + suffix


class MapBuilder:
    """No producer/fallback. Same builder API accepted by common build_library."""
    def __init__(self, cache, *, source_builder=None, receipts=None):
        self.cache = cache
        self.source_builder = source_builder
        self.receipts = receipts if receipts is not None else _Receipts()

    def _asset(self, root, asset):
        if (set(asset) != {'src', 'sha256'} or not _ASSET.fullmatch(asset['src']) or
                not asset['src'].startswith('_qa_compiled_' + asset['sha256'] + '.')):
            raise ValueError('addressed cached record/evidence required')
        return self.receipts.read(root / asset['src'], asset['sha256'])

    def build(self, root, wrapper, artifact, *, identity, policy, source_url):
        root = Path(root)
        self.receipts.read(shared.inputs._local(root, wrapper['path']), wrapper['sha256'], keep=False)
        prepared_raw = self.receipts.read(shared.inputs._local(root, artifact['path']), artifact['sha256'])
        prepared = shared.inputs._json(prepared_raw)
        if prepared.get('source_wrapper_sha256') != wrapper['sha256']:
            raise ValueError('current prepared wrapper binding differs')
        if not prepared.get('modules'):
            if self.source_builder is None:
                raise ValueError('original authored source validator required')
            result = self.source_builder.build(root, wrapper, artifact, identity=identity, policy=policy, source_url=source_url)
            if result.get('mode') != 'authored' or self.source_builder.worker is not None:
                raise ValueError('authored validation started a producer or changed mode')
            return result
        found = self.cache.get(identity)
        if found is None:
            raise KeyError('no qualified compiled result for ' + identity)
        row, assets = found
        result = row.get('result')
        if not isinstance(result, dict) or result.get('mode') != 'compiled':
            raise ValueError('an explicit completed compiled result is required')
        record = shared.inputs._json(self._asset(assets, result['record']))
        dependencies = shared.CompiledBuild._dependencies()
        key = {'identity': identity, 'wrapper': wrapper, 'artifact': artifact,
               'policy': policy, 'source_url': source_url, 'dependencies': dependencies}
        origin = record.get('semantic_origin')
        completed = self.cache.completed.get(identity)
        if (origin is None) != (completed is None):
            raise ValueError('explicit original semantic reuse capability differs')
        if completed is not None:
            if (set(origin) != {'schema', 'semantic_preparation_rerun', 'source_request', 'source_report', 'source_generator'} or
                    origin['schema'] != 'study-pinned-semantic-reuse.v1' or origin['semantic_preparation_rerun'] is not False):
                raise ValueError('original semantic provenance schema differs')
            if set(completed) != {'request', 'report', 'generator'}:
                raise ValueError('completed semantic descriptor census differs')
            for name in ('request', 'report', 'generator'):
                descriptor = completed[name]
                if set(descriptor) != {'path', 'sha256'}:
                    raise ValueError('original completed descriptor shape differs')
                raw = self.receipts.read(descriptor['path'], descriptor['sha256'])
                stored = self._asset(assets, origin['source_' + name])
                if raw != stored:
                    raise ValueError('cached semantic provenance differs')
            key['completed_semantic'] = completed
        if (record.get('schema') != 'study-complete-card-build.v1' or
                not _same(record['dependencies'], dependencies) or
                record['identity'] != identity or result['identity'] != identity or
                record['build_key'] != shared._sha(shared._json(key)) or result['build_key'] != record['build_key']):
            raise ValueError('current wrapper/artifact/policy/URL/dependencies cache key differs')
        for name in ('entry', 'runtime'):
            if not _same(record[name], result[name]):
                raise ValueError('cached record/result structures differ')
        resources = result['resources']
        if not _same(record['resources'], {url: {k: v for k, v in item.items() if k != 'path'} for url, item in resources.items()}):
            raise ValueError('cached record/result resource pins differ')
        generated = {urljoin(source_url, asset['src']) for asset in
                     (result['entry']['html'], result['entry']['profile'], result['runtime'])}
        source = urlsplit(urljoin(source_url, './'))
        for url, descriptor in resources.items():
            if set(descriptor) != {'sha256', 'bytes', 'path'}:
                raise ValueError('complete resource descriptor required')
            self.receipts.read(descriptor['path'], descriptor['sha256'], size=descriptor['bytes'], keep=False)
            if url in generated:
                continue
            link = urlsplit(url)
            if ((source.scheme, source.netloc) != (link.scheme, link.netloc) or link.query or link.fragment or
                    not link.path.startswith(source.path)):
                raise ValueError('cached source resource leaves current root')
            path = shared.inputs._local(root, unquote(link.path[len(source.path):]))
            self.receipts.read(path, descriptor['sha256'], size=descriptor['bytes'], keep=False)
        for module in prepared['modules'].values():
            if resources.get(urljoin(source_url, module['src']), {}).get('sha256') != module['sha256']:
                raise ValueError('current prepared module is absent from cached resources')
        for descriptor in record['evidence'].values():
            self._asset(assets, descriptor)
        bindings = result['entry']['anchors']['bindings']
        if not _same(record['profile_report']['external_bindings'], bindings):
            raise ValueError('all profile-report external bindings must agree')
        expected = {'producerInputSha256': record['semantic_report']['bindings']['sha256'],
                    'materializerSha256': shared._sha(Path(materialize.__file__).read_bytes()),
                    'adapterSha256': shared.inputs._HELPERS_SHA256,
                    **{name: row[2] for name, row in shared.inputs._DELEGATES.items()}}
        if any(bindings.get(name) != value for name, value in expected.items()):
            raise ValueError('current producer/helper/delegate bindings differ')
        registry = prepared['sides'][1]['registry']
        if (bindings['rawSideSha256'] not in registry or bindings['rawIndexSha256'] not in registry or
                bindings['rawSideSha256'] == bindings['rawIndexSha256']):
            raise ValueError('original payload/index binding is outside current registry')
        # Original common validator reads every body/profile/runtime byte and
        # checks its exact 17/19 bindings. Only its copy destination is a no-op.
        materialize._compiled_web_entry(root, prepared, artifact, result, _ValidationOnly())
        self.cache.check()
        return copy.deepcopy(result)

    def check(self):
        self.cache.check()
        self.receipts.check()
