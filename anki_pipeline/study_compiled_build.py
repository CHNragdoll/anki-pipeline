"""One sequential complete-card build shared by web and native delivery.

This is an export-stage artifact store, not an alternative content projection.
Source fields and native identities stay in the catalog. Both delivery hosts
receive the same authenticated HTML/profile bytes and original resources.
"""
from __future__ import annotations

import copy
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
from urllib.parse import urljoin, urlsplit

from . import study_compiled as inputs
from .study_compiled_runtime import CURRENT_RUNTIME_SHA256

COMPILED = Path(__file__).parent / 'compiled'
RUNTIME_SHA256 = CURRENT_RUNTIME_SHA256
_HASH = re.compile('[a-f0-9]{64}')
_MAX = 128 * 1024 * 1024


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _read(path, expected, size=None):
    if not isinstance(expected, str) or not _HASH.fullmatch(expected):
        raise ValueError('complete artifact SHA-256 required')
    with Path(path).open('rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > _MAX:
            raise ValueError('artifact must be a bounded regular file')
        raw = stream.read(_MAX + 1)
        after = os.fstat(stream.fileno())
    if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) !=
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) or
            len(raw) != before.st_size or _sha(raw) != expected or
            size is not None and len(raw) != size):
        raise ValueError('artifact bytes differ from their pin')
    return raw


def _write_all(stream, raw):
    view = memoryview(raw)
    while view:
        count = stream.write(view)
        if not isinstance(count, int) or count <= 0 or count > len(view):
            raise OSError('artifact write made no valid progress')
        view = view[count:]


def _clear_job(stage, descriptor):
    """Clear only the successful job's held directory, never a replaced path.

    The empty directory is retained as a build-key receipt. Anchoring every
    child operation to the open fd also closes a path swap after the check.
    """
    actual, owned = Path(stage).lstat(), os.fstat(descriptor)
    if ((actual.st_dev, actual.st_ino) != (owned.st_dev, owned.st_ino) or
            not stat.S_ISDIR(actual.st_mode)):
        raise ValueError('shared build scratch directory ownership changed')
    if not shutil.rmtree.avoids_symlink_attacks:
        raise RuntimeError('safe fd-relative scratch cleanup is unavailable')
    for name in os.listdir(descriptor):
        child = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        if stat.S_ISDIR(child.st_mode):
            shutil.rmtree(name, dir_fd=descriptor)
        else:
            os.unlink(name, dir_fd=descriptor)


class ArtifactStore:
    """Publish complete, checked bytes under no-clobber content addresses."""
    def __init__(self, directory):
        self.root = Path(directory).absolute()
        self.root.mkdir()  # A caller must supply its own new private directory.
        self.assets = self.root / 'assets'
        self.assets.mkdir()

    def put(self, raw, suffix):
        if not isinstance(raw, bytes) or len(raw) > _MAX or suffix not in {'js', 'json', 'html', 'css'}:
            raise ValueError('unsupported bounded artifact')
        pin = _sha(raw)
        name = '_qa_compiled_' + pin + '.' + suffix
        target = self.assets / name
        if target.exists() or target.is_symlink():
            if target.is_symlink():
                raise ValueError('artifact address is a symlink')
            _read(target, pin, len(raw))
            return {'src': name, 'sha256': pin}
        descriptor, temporary = tempfile.mkstemp(prefix='.partial-', dir=self.assets)
        temporary = Path(temporary)
        owned = os.fstat(descriptor)
        linked = False
        try:
            with os.fdopen(descriptor, 'w+b', buffering=0) as stream:
                _write_all(stream, raw)
                stream.flush()
                os.fsync(stream.fileno())
                _read(temporary, pin, len(raw))
                try:
                    os.link(temporary, target)
                    linked = True
                except FileExistsError:
                    if target.is_symlink():
                        raise ValueError('artifact address became a symlink')
                    _read(target, pin, len(raw))
                if linked:
                    actual = target.lstat()
                    if (actual.st_dev, actual.st_ino) != (owned.st_dev, owned.st_ino):
                        raise ValueError('published artifact inode differs')
                    _read(target, pin, len(raw))
        except BaseException:
            if linked:
                try:
                    actual = target.lstat()
                    if (actual.st_dev, actual.st_ino) == (owned.st_dev, owned.st_ino):
                        target.unlink()
                except FileNotFoundError:
                    pass
            raise
        finally:
            try:
                actual = temporary.lstat()
                if (actual.st_dev, actual.st_ino) == (owned.st_dev, owned.st_ino):
                    temporary.unlink()
            except FileNotFoundError:
                pass
        return {'src': name, 'sha256': pin}

    def descriptor(self, asset):
        raw = _read(self.assets / asset['src'], asset['sha256'])
        return {'path': str(self.assets / asset['src']), 'sha256': asset['sha256'], 'bytes': len(raw)}


class BuildWorker:
    """A single persistent Node process. Observation timeouts never restart it."""
    def __init__(self, log, *, node='node', heap_mb=4096):
        if type(heap_mb) is not int or not 512 <= heap_mb <= 16384:
            raise ValueError('explicit Node heap must be between 512 and 16384 MiB')
        self.log = Path(log).open('xb')
        try:
            self.process = subprocess.Popen(
                [str(node), '--max-old-space-size=' + str(heap_mb), '--expose-gc',
                 str(COMPILED / 'build-worker.cjs')], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=self.log, bufsize=0)
        except BaseException:
            self.log.close()
            raise
        self.sequence = 0
        self.broken = False

    def run(self, operation, request, output):
        if self.broken or self.process.poll() is not None:
            raise RuntimeError('shared worker is no longer available; no automatic restart')
        if operation not in {'semantic', 'profile'}:
            raise ValueError('unknown shared build operation')
        self.sequence += 1
        identifier = str(self.sequence)
        command = _json({'id': identifier, 'operation': operation,
                         'request': str(Path(request).resolve()), 'output': str(Path(output).absolute())}) + b'\n'
        try:
            _write_all(self.process.stdin, command)
            line = self.process.stdout.readline(16385)
            if not line.endswith(b'\n') or len(line) > 16384:
                raise RuntimeError('shared worker closed or returned an oversized response')
            result = inputs._json(line)
            if result.get('id') != identifier or type(result.get('ok')) is not bool:
                raise RuntimeError('shared worker response identity differs')
        except BaseException:
            self.broken = True
            raise
        if not result['ok']:
            raise ValueError('shared ' + operation + ' failed: ' + str(result.get('error', {}).get('message', 'unknown error')))
        report = result.get('report', {})
        expected_path = Path(output).absolute() / 'report.json'
        if (set(report) != {'path', 'sha256', 'bytes'} or report['path'] != str(expected_path) or
                type(report['bytes']) is not int or report['bytes'] < 1):
            self.broken = True
            raise RuntimeError('shared worker report descriptor differs')
        raw = _read(report['path'], report['sha256'], report['bytes'])
        data = inputs._json(raw)
        if data.get('schema') != 'study-compiled-' + ('semantic' if operation == 'semantic' else 'profile') + '-result.v1':
            self.broken = True
            raise RuntimeError('shared worker report schema differs')
        return report, data

    def close(self):
        if not self.process.stdin.closed:
            self.process.stdin.close()
        # EOF drains the process. There is no idle timeout/retry or job restart.
        code = self.process.wait()
        self.process.stdout.close()
        self.log.close()
        if code:
            raise RuntimeError('shared worker exited with status ' + str(code))


class _Styles(HTMLParser):
    def __init__(self):
        super().__init__()
        self.names = set()

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == 'link' and values.get('rel', '').lower() == 'stylesheet' and values.get('href'):
            self.names.add(values['href'])


class CompiledBuild:
    """Per-snapshot source identity cache and shared delivery artifact store."""
    def __init__(self, directory, *, node='node', heap_mb=4096):
        self.store = ArtifactStore(directory)
        self.work = self.store.root / 'work'
        self.work.mkdir()
        self.node, self.heap_mb, self.worker = node, heap_mb, None
        self.cache = {}
        self.dependencies = self._dependencies()
        runtime = (COMPILED / 'card-runtime.js').read_bytes()
        if _sha(runtime) != RUNTIME_SHA256:
            raise ValueError('common complete-card runtime pin differs')
        self.runtime = self.store.put(runtime, 'js')

    @staticmethod
    def _dependencies():
        paths = [Path(__file__), Path(__file__).with_name('study_compiled_runtime.py'), Path(inputs.__file__), Path(inputs.materializer.__file__),
                 Path(inputs.web.__file__)]
        paths += [COMPILED / name for name in (
            'semantic-producer.cjs', 'semantic-helpers.js', 'stream-serializer.mjs',
            'profile-emitter.cjs', 'profile-ast.cjs', 'normalize-bank.cjs',
            'build-worker.cjs', 'card-runtime.js', 'numbering-preparation.cjs')]
        return {path.name: _sha(path.read_bytes()) for path in paths}

    def _run(self, operation, request, output):
        if self.worker is None:
            self.worker = BuildWorker(self.store.root / 'worker.log', node=self.node, heap_mb=self.heap_mb)
        return self.worker.run(operation, request, output)

    def build(self, root, wrapper, artifact, *, identity, policy, source_url):
        """Build once per explicit identity; callers receive independent metadata."""
        if not isinstance(identity, str) or not identity or len(identity) > 1024:
            raise ValueError('a bounded namespaced source identity is required')
        if self._dependencies() != self.dependencies:
            raise ValueError('shared build dependencies changed during the snapshot')
        root = Path(root).absolute()
        _, wrapper_raw = inputs._descriptor(root, wrapper)
        _, artifact_raw = inputs._descriptor(root, artifact)
        prepared = inputs._json(artifact_raw)
        key = _sha(_json({'identity': identity, 'wrapper': wrapper, 'artifact': artifact,
                          'policy': policy, 'source_url': source_url, 'dependencies': self.dependencies}))
        if identity in self.cache:
            old_key, result = self.cache[identity]
            if old_key != key:
                raise ValueError('source identity changed within one shared export snapshot')
            self._verify_cached_result(result)
            return copy.deepcopy(result)
        if (prepared.get('schema') != 'study-prepared-card.v1' or
                prepared.get('source_wrapper_sha256') != _sha(wrapper_raw) or
                not isinstance(prepared.get('modules'), dict)):
            raise ValueError('prepared source binding differs')
        if not prepared['modules']:
            payload = inputs.web.card_payload(wrapper_raw)
            if prepared.get('source_payload_sha256') != _sha(payload):
                raise ValueError('authored source payload binding differs')
            sides = inputs._json(payload)
            if not isinstance(sides, list) or len(sides) != 2 or len(prepared.get('sides', [])) != 2:
                raise ValueError('authored source requires both complete sides')
            for source, side in zip(sides, prepared['sides']):
                proof = side.get('proof', {})
                if (proof.get('source_sha256') != _sha(source.encode()) or
                        proof.get('expanded_sha256') != _sha(side['html'].encode()) or
                        proof.get('registry_pins') != sorted(side['registry']) or
                        any(_sha(text.encode()) != pin for pin, text in side['registry'].items())):
                    raise ValueError('authored side proof differs')
            result = {'mode': 'authored', 'identity': identity, 'source_unchanged': True,
                      'source_wrapper_sha256': wrapper['sha256'], 'source_artifact_sha256': artifact['sha256']}
            self.cache[identity] = key, result
            return copy.deepcopy(result)
        stage = self.work / key
        stage.mkdir()
        stage_fd = os.open(stage, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            semantic_inputs = inputs.build_semantic_request(root, wrapper, artifact, stage / 'semantic-inputs',
                                                            policy=policy, source_url=source_url)
            semantic_descriptor, semantic_report = self._run('semantic', semantic_inputs['request']['path'], stage / 'semantic')
            profile_inputs = inputs.build_profile_request(semantic_inputs['request'],
                {name: semantic_descriptor[name] for name in ('path', 'sha256')},
                stage / 'profile-inputs', media=root / 'media')
            profile_descriptor, profile_report = self._run('profile', profile_inputs['request']['path'], stage / 'profile')
            result = self._publish(root, identity, key, prepared, stage, semantic_inputs,
                                   semantic_report, profile_inputs, profile_report)
            _clear_job(stage, stage_fd)
        except BaseException as error:
            # Retain this private job for diagnosis; never delete source/live output.
            try:
                failure_fd = os.open('FAILED.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                     0o600, dir_fd=stage_fd)
                with os.fdopen(failure_fd, 'wb', buffering=0) as stream:
                    _write_all(stream, _json({'identity': identity, 'error': str(error)[:1024], 'build_key': key}))
            except OSError:
                pass
            raise
        finally:
            os.close(stage_fd)
        self.cache[identity] = key, result
        return copy.deepcopy(result)

    def _verify_cached_result(self, result):
        if result['mode'] != 'compiled':
            return
        for asset in (result['entry']['html'], result['entry']['profile'], result['runtime'], result['record']):
            self.store.descriptor(asset)
        record = inputs._json(_read(self.store.assets / result['record']['src'], result['record']['sha256']))
        for asset in record['evidence'].values():
            self.store.descriptor(asset)
        for descriptor in result['resources'].values():
            _read(descriptor['path'], descriptor['sha256'], descriptor['bytes'])

    def _publish(self, root, identity, key, prepared, stage, semantic_inputs, semantic_report, profile_inputs, profile_report):
        def child(name):
            descriptor = profile_report[name]
            if (set(descriptor) != {'path', 'sha256', 'bytes'} or
                    not isinstance(descriptor['path'], str) or Path(descriptor['path']).name != descriptor['path'] or
                    descriptor['path'] in {'.', '..'} or '\\' in descriptor['path']):
                raise ValueError('invalid completed profile child')
            return _read(stage / 'profile' / descriptor['path'], descriptor['sha256'], descriptor['bytes'])
        html, profile_raw, anchors_raw = child('delivery_html'), child('profile'), child('anchors')
        child('fields')
        if profile_report.get('history_scope') is not None:
            child('history_scope')
        profile, anchors = inputs._json(profile_raw), inputs._json(anchors_raw)
        if (anchors.get('schema') != 'study-compiled-card-interactions.v1' or anchors.get('version') != 1 or
                profile.get('schema') != anchors['schema'] or profile.get('version') != 1 or
                anchors.get('bindings') != profile.get('bindings') or
                anchors.get('profileSha256') != _sha(profile_raw) or anchors.get('htmlSha256') != _sha(html) or
                profile_report.get('external_bindings') != anchors['bindings']):
            raise ValueError('completed delivery/profile binding differs')
        request = inputs._json(Path(semantic_inputs['request']['path']).read_bytes())
        if (anchors['bindings'].get('sourceArtifactSha256') != request['artifact']['sha256'] or
                anchors['bindings'].get('sourceWrapperSha256') != prepared['source_wrapper_sha256'] or
                anchors['bindings'].get('sourcePayloadSha256') != prepared['source_payload_sha256']):
            raise ValueError('completed delivery/source binding differs')
        entry = {'decoded': True, 'source': {
            'wrapper_sha256': prepared['source_wrapper_sha256'], 'payload_sha256': prepared['source_payload_sha256'],
            'side_sha256': prepared['sides'][1]['proof']['source_sha256'],
            'expanded_sha256': prepared['sides'][1]['proof']['expanded_sha256'],
            'registry_pins': prepared['sides'][1]['proof']['registry_pins']},
            'module': {name: request['module'][name] for name in ('original_sha256', 'sha256')},
            'anchors': anchors, 'html': self.store.put(html, 'html'), 'profile': self.store.put(profile_raw, 'json')}
        resources = {}
        def resource(url, raw, suffix):
            asset = self.store.put(raw, suffix)
            if url in resources and resources[url]['sha256'] != asset['sha256']:
                raise ValueError('one logical resource changed within the shared build')
            resources[url] = self.store.descriptor(asset)
        for url, descriptor in request['resources'].items():
            resource(url, inputs._absolute(descriptor), 'css' if urlsplit(url).path.endswith('.css') else 'js')
        for asset in (entry['html'], entry['profile'], self.runtime):
            resources[urljoin(request['source_url'], asset['src'])] = self.store.descriptor(asset)
        styles = _Styles()
        for side in prepared['sides']:
            styles.feed(side['html'])
        for name in sorted(styles.names):
            file = inputs._local(root / 'media', name)
            resource(urljoin(request['base_url'], name), file.read_bytes(), 'css')
        for slot in profile.get('historySlots', []):
            for part in slot['parts']:
                # The profile request already authenticated the original AS logical
                # bytes. Preserve its inert carrier verbatim for native file access.
                decoded = inputs.materializer.ReadOnlyMedia(root / 'media')
                decoded.read({'src': part['src'], 'sha256': part['sha256']})
                for proof in decoded.proofs.values():
                    original = inputs._local(root / 'media', proof['name'])
                    resource(urljoin(request['base_url'], proof['name']),
                             _read(original, proof['resource_sha256']), 'js')
                for evidence in part['evidence']:
                    file = inputs._local(root / 'media', evidence['media'])
                    resource(urljoin(request['base_url'], evidence['media']),
                             _read(file, evidence['resourceSha256']), 'js')
        evidence_files = {}
        evidence_names = ['source_proof', 'reconciliation', 'capture_inverse', 'metadata']
        if semantic_report.get('initial_numbering') is not None:
            evidence_names.append('initial_numbering')
        for name in evidence_names:
            descriptor = semantic_report[name]
            if (Path(descriptor['path']).name != descriptor['path'] or descriptor['path'] in {'.', '..'} or
                    '\\' in descriptor['path']):
                raise ValueError('invalid completed semantic evidence child')
            raw = _read(stage / 'semantic' / descriptor['path'], descriptor['sha256'], descriptor['bytes'])
            evidence_files[name] = self.store.put(raw, 'json')
        record = {'schema': 'study-complete-card-build.v1', 'identity': identity, 'build_key': key,
                  'dependencies': self.dependencies, 'source_request_sha256': semantic_inputs['request']['sha256'],
                  'profile_request_sha256': profile_inputs['request']['sha256'],
                  'semantic_report': semantic_report, 'profile_report': profile_report,
                  'evidence': evidence_files,
                  'entry': entry, 'runtime': self.runtime,
                  'resources': {url: {k: v for k, v in item.items() if k != 'path'} for url, item in resources.items()},
                  'native_update_or_client_acceptance': False}
        record_asset = self.store.put(_json(record), 'json')
        return {'mode': 'compiled', 'identity': identity, 'entry': entry, 'runtime': self.runtime,
                'resources': resources, 'record': record_asset, 'build_key': key}

    def close(self):
        if self.worker is not None:
            self.worker.close()
            self.worker = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        try:
            self.close()
        except Exception as error:
            if exc is None:
                raise
            exc.add_note('shared worker close also failed: ' + str(error))
