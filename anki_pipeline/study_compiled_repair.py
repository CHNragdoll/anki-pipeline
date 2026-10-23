"""Explicit, pinned repair routing around the unchanged common builders.

Only listed normalized artifacts may start a producer. Everything else goes
through MapBuilder and retains its fail-closed cache contract. This module must
be included in the caller's frozen source manifest, outside the original fifteen
producer dependencies. It never changes cache rows or their duplicate checks.
"""
from __future__ import annotations

import copy
import hashlib
import os
from pathlib import Path
import re

from . import study_compiled_build as shared
from . import study_compiled_preparation as preparation
from . import study_compiled_resume as resume
from . import study_compiled_schedule as schedule
from .study_owned_output_publication import owned_output_receipts

SCHEMA = 'study-compiled-repair-plan.v1'
_HASH = re.compile('[a-f0-9]{64}')


def _descriptor(value):
    if (type(value) is not dict or set(value) != {'path', 'sha256'}
            or type(value['path']) is not str or not value['path']
            or type(value['sha256']) is not str or not _HASH.fullmatch(value['sha256'])):
        raise ValueError('repair requires an exact path/SHA descriptor')
    return copy.deepcopy(value)


class _ReceiptMedia(shared.inputs.materializer.ReadOnlyMedia):
    """Keep original decoding, with every selected local input held to one view."""
    def __init__(self, folder, receipts):
        super().__init__(folder)
        self.receipts = receipts

    def local(self, name):
        path = super().local(name)
        _, receipt = resume.delivery._read(path, keep=False)
        previous = self.receipts.items.get(receipt['path'])
        if previous is not None and previous != receipt:
            raise ValueError('normalization media changed within the repair snapshot')
        self.receipts.items[receipt['path']] = receipt
        return path


class RepairBuilder:
    """Same build API; one externally approved changed set per private store.

    ``plan`` is an externally pinned absolute file. Its exact schema is
    ``{schema, sources, dependencies, changed}``, with each changed row exactly
    ``{identity, base_artifact, artifact}``. Artifact descriptors are root-relative
    and use the normal common builder's path/SHA shape. Use one plan per book
    when the caller creates one builder per book. The caller owns ``cache`` and
    may share ``receipts`` across all books for a final global drift check.
    """
    def __init__(self, cache, directory, *, plan, receipts=None, node='node', heap_mb=4096):
        self.receipts = receipts if receipts is not None else resume._Receipts()
        self.plan = _descriptor(plan)
        if not Path(self.plan['path']).is_absolute():
            raise ValueError('repair plan requires an absolute external path')
        raw = self.receipts.read(self.plan['path'], self.plan['sha256'])
        value = shared.inputs._json(raw)
        self.sources = preparation.source_pins()
        self.dependencies = shared.CompiledBuild._dependencies()
        if (type(value) is not dict or set(value) != {'schema', 'sources', 'dependencies', 'changed'}
                or value['schema'] != SCHEMA or value['sources'] != self.sources
                or value['dependencies'] != self.dependencies or type(value['changed']) is not list
                or len(value['changed']) > 100000):
            raise ValueError('repair plan schema/helper/dependencies differ')
        self.changed = {}
        for row in value['changed']:
            if type(row) is not dict or set(row) != {'identity', 'base_artifact', 'artifact'}:
                raise ValueError('repair plan changed row differs')
            identity = row['identity']
            if (type(identity) is not str or not identity or len(identity) > 1024
                    or '\x00' in identity or identity in self.changed):
                raise ValueError('duplicate or invalid repair identity')
            base, current = _descriptor(row['base_artifact']), _descriptor(row['artifact'])
            for descriptor in (base, current):
                path = Path(descriptor['path'])
                if path.is_absolute() or '..' in path.parts or '\\' in descriptor['path']:
                    raise ValueError('repair artifacts must be relative common source paths')
            if base['sha256'] == current['sha256']:
                raise ValueError('repair plan must describe an actual artifact change')
            self.changed[identity] = {'base_artifact': base, 'artifact': current}
        self.builder = schedule.StageSeparatedBuild(directory, node=node, heap_mb=heap_mb)
        os.chmod(self.builder.store.root, 0o700)  # This constructor just created it.
        os.chmod(self.builder.store.assets, 0o700)
        self.owned_directories = {path: self._directory_identity(path.lstat()) for path in
                                 (self.builder.store.root, self.builder.store.assets)}
        self.mapper = resume.MapBuilder(cache, source_builder=self.builder, receipts=self.receipts)
        self.log_path = self.builder.store.root / 'results-repaired.jsonl'
        descriptor = os.open(self.log_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
            getattr(os, 'O_NOFOLLOW', 0), 0o600)
        self.log = os.fdopen(descriptor, 'wb')
        self.log_digest, self.log_bytes = hashlib.sha256(), 0
        self.seen, self.completed = {}, set()
        self.closed, self.failed, self.final_report = False, False, None

    def _authority(self):
        if preparation.source_pins() != self.sources or shared.CompiledBuild._dependencies() != self.dependencies:
            raise ValueError('repair helper or original dependencies changed during the snapshot')
        if any(self._directory_identity(path.lstat()) != identity
               for path, identity in self.owned_directories.items()):
            raise ValueError('repair output directory ownership changed')

    @staticmethod
    def _directory_identity(value):
        return value.st_dev, value.st_ino, value.st_mode, value.st_uid

    def _publish_owned(self, outputs):
        assets = self.builder.store.assets
        fresh = {name: pin for name, pin in outputs.items()
                 if str(assets / name) not in self.receipts.items}
        if not fresh:
            return
        self._authority()
        fd = os.open(assets, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            if self._directory_identity(os.fstat(fd)) != self.owned_directories[assets]:
                raise ValueError('repair output directory FD ownership changed')
            published = owned_output_receipts(assets, fd, fresh)
            for receipt in published.values():
                self.receipts.admit_new_owned(receipt)
        finally:
            os.close(fd)
        self._authority()

    def _current(self, root, descriptor):
        path = shared.inputs._local(root, descriptor['path'])
        return self.receipts.read(path, descriptor['sha256'])

    def _register_rebuilt(self, result):
        # These bytes are newly written in this builder's private store. No
        # input/cached receipt is replaced: publication precedes first admission.
        self._publish_owned({result['record']['src']: result['record']['sha256']})
        record = shared.inputs._json(self.mapper._asset(self.builder.store.assets, result['record']))
        outputs = {row['src']: row['sha256'] for row in record['evidence'].values()}
        for descriptor in result['resources'].values():
            if Path(descriptor['path']).parent == self.builder.store.assets:
                outputs[Path(descriptor['path']).name] = descriptor['sha256']
        self._publish_owned(outputs)
        for descriptor in result['resources'].values():
            if set(descriptor) != {'path', 'sha256', 'bytes'}:
                raise ValueError('rebuilt resource descriptor differs')
            self.receipts.read(descriptor['path'], descriptor['sha256'], size=descriptor['bytes'], keep=False)
        for descriptor in record['evidence'].values():
            self.mapper._asset(self.builder.store.assets, descriptor)

    def build(self, root, wrapper, artifact, *, identity, policy, source_url):
        if self.closed or self.failed:
            raise RuntimeError('repair builder is closed or failed; no automatic fallback')
        root = Path(root)
        try:
            self._authority()
            selected = self.changed.get(identity)
            if selected is None:
                return self.mapper.build(root, wrapper, artifact,
                    identity=identity, policy=policy, source_url=source_url)
            if artifact != selected['artifact']:
                raise ValueError('repair current artifact differs from its approved identity')
            base = selected['base_artifact']
            # Authenticate the complete original cache capability first, including
            # policy, URL, resources, immutable record and original build key.
            self.mapper.build(root, wrapper, base, identity=identity, policy=policy, source_url=source_url)
            wrapper_raw = self._current(root, _descriptor(wrapper))
            base_raw, current_raw = self._current(root, base), self._current(root, artifact)
            value = shared.inputs._json(current_raw)
            proof = value.get('field_script_normalization')
            if (not value.get('modules') or type(proof) is not dict
                    or proof.get('schema') != 'study-prepared-field-normalization.v1'
                    or proof.get('base_artifact_sha256') != base['sha256'] or proof.get('sources') != self.sources):
                raise ValueError('repair artifact lacks its approved field normalization')
            normalized, evidence = preparation.normalize_artifact(base_raw, wrapper_raw,
                _ReceiptMedia(root / 'media', self.receipts))
            if evidence is None or normalized != current_raw or evidence != proof:
                raise ValueError('repair normalization differs from its authenticated base')
            result = self.builder.build(root, wrapper, artifact,
                identity=identity, policy=policy, source_url=source_url)
            if result.get('mode') != 'compiled' or result.get('identity') != identity:
                raise ValueError('repair did not return the original compiled builder contract')
            self._register_rebuilt(result)
            pin = shared._sha(shared._json(result))
            if identity in self.seen and self.seen[identity] != pin:
                raise ValueError('one repaired identity returned different results')
            if identity not in self.seen:
                row = {'status': 'ok', 'identity': identity, 'result': result,
                       'repair_plan_sha256': self.plan['sha256'], **selected}
                raw = shared._json(row) + b'\n'
                shared._write_all(self.log, raw)
                self.log.flush(); os.fsync(self.log.fileno())
                self.log_digest.update(raw); self.log_bytes += len(raw)
                self.seen[identity] = pin
            self.completed.add(identity)
            return result
        except BaseException:
            self.failed = True
            raise

    def check(self):
        self._authority()
        self.mapper.check()

    def close(self, *, complete=True):
        if self.closed:
            return
        try:
            self.builder.close()
            if complete and not self.failed:
                self.check()
                if self.completed != set(self.changed):
                    raise ValueError('repair did not process the exact approved changed set')
                self.log.flush(); os.fsync(self.log.fileno())
                before = os.fstat(self.log.fileno())
                raw = self.receipts.read(self.log_path, self.log_digest.hexdigest(), size=self.log_bytes)
                after, named = os.fstat(self.log.fileno()), self.log_path.lstat()
                if resume.delivery._six(before) != resume.delivery._six(after) or resume.delivery._six(after) != resume.delivery._six(named):
                    raise ValueError('owned repair result log identity changed')
                self.final_report = {'schema': 'study-compiled-repair-result.v1',
                    'plan': self.plan, 'sources': self.sources, 'dependencies': self.dependencies,
                    'repaired': len(self.completed),
                    'results': {'path': str(self.log_path.resolve()), 'sha256': shared._sha(raw),
                        'bytes': len(raw), 'assets': str(self.builder.store.assets.resolve())}}
        except BaseException:
            self.failed = True
            raise
        finally:
            self.log.close()
            self.closed = True

    def report(self):
        if not self.closed or self.failed or self.final_report is None:
            raise ValueError('a complete successful repair is required')
        return copy.deepcopy(self.final_report)

    def __enter__(self):
        return self

    def __exit__(self, kind, error, traceback):
        try:
            self.close(complete=error is None)
        except BaseException as closing:
            if error is None:
                raise
            error.add_note('repair worker close also failed: ' + type(closing).__name__)
