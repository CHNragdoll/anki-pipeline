"""One complete web delivery pipeline and immutable existing-export derivative.

This never projects notes, opens PG, changes source wrappers/media/catalog, or
builds native packages. The same build_library entry is usable by fresh export
and by the standalone derivative driver. Existing navigation is reused exactly.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
from urllib.parse import urljoin, urlsplit

from . import study_catalog_web as web
from . import study_catalog_web_materialize as materialize
from .study_compiled_schedule import StageSeparatedBuild as CompiledBuild

METADATA_LIMIT = 64 * 1024 * 1024
_HASH = re.compile(r'[a-f0-9]{64}')
_CONFIG = re.compile(rb'<script id="study-library-config" type="application/json">(.*?)</script>', re.S)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def _decode(raw):
    def pairs(rows):
        value = {}
        for key, item in rows:
            if key in value:
                raise ValueError('duplicate metadata key')
            value[key] = item
        return value
    return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs)


def _six(value):
    return [value.st_dev, value.st_ino, value.st_mode, value.st_size,
            value.st_mtime_ns, value.st_ctime_ns]


def _read(path, expected=None, *, limit=METADATA_LIMIT, keep=True):
    """Hash the actual read buffer on one FD; reject path/FD or six drift."""
    path = Path(path)
    if expected is not None and (not isinstance(expected, str) or not _HASH.fullmatch(expected)):
        raise ValueError('exact external SHA required')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or _six(path.lstat()) != _six(before)
                or limit is not None and before.st_size > limit):
            raise ValueError('source must be a bounded stable regular file')
        digest, pieces, count = hashlib.sha256(), [], 0
        while raw := os.read(fd, 1024 * 1024):
            digest.update(raw); count += len(raw)
            if keep:
                pieces.append(raw)
        pin = digest.hexdigest()
        if (_six(os.fstat(fd)) != _six(before) or _six(path.lstat()) != _six(before)
                or count != before.st_size or expected is not None and pin != expected):
            raise ValueError('source SHA/identity changed during read: ' + path.name)
        return b''.join(pieces) if keep else None, {'path': str(path.absolute()), 'bytes': count,
                                                   'sha256': pin, 'six': _six(before)}
    finally:
        os.close(fd)


def _again(receipt):
    _, actual = _read(receipt['path'], receipt['sha256'], limit=None, keep=False)
    if actual != receipt:
        raise ValueError('source identity changed after preparation')


def _local(root, name):
    parsed = urlsplit(name)
    if (not isinstance(name, str) or parsed.scheme or parsed.netloc or parsed.query or parsed.fragment
            or Path(name).name != name or '\\' in name or name in {'.', '..'}):
        raise ValueError('local metadata basename required')
    return root / name


def library_config(raw):
    matches = list(_CONFIG.finditer(raw))
    if len(matches) != 1:
        raise ValueError('one common library configuration required')
    value = _decode(matches[0][1])
    if (type(value) is not dict or set(value) != {'navigation', 'navigationGzip', 'initial', 'total',
                                                'totals', 'initialPath', 'sharedFrame'}):
        raise ValueError('common library configuration fields differ')
    return value


def _preserved_navigation(root, catalog, config, shared):
    """Use the original navigation byte stream, never reconstruct metadata."""
    name = config['navigation']
    match = re.fullmatch(r'_study_navigation_([a-f0-9]{64})\.json', name or '')
    if not match:
        raise ValueError('content-addressed original navigation required')
    raw, _ = _read(_local(root, name), match[1])
    nav = _decode(raw)
    rows = nav.get('cards')
    if (nav.get('schema') != 'study-navigation.v2' or not isinstance(rows, list)
            or [row[0] for row in rows] != [card['id'] for card in catalog['cards']]
            or [row[4] for row in rows] != [card['url'] for card in catalog['cards']]
            or nav.get('catalog_revision') != catalog.get('catalog_revision')
            or config['totals'] != nav.get('totals') or config['total'] != nav['totals']['cards']):
        raise ValueError('original navigation identity/count/revision differs')
    packed_bytes, packed_sha = 0, None
    if config['navigationGzip'] is not None:
        if config['navigationGzip'] != name + '.gz':
            raise ValueError('original compressed navigation name differs')
        packed, _ = _read(_local(root, config['navigationGzip']))
        with gzip.GzipFile(fileobj=io.BytesIO(packed)) as stream:
            if stream.read(len(raw) + 1) != raw:
                raise ValueError('original compressed navigation differs')
        packed_bytes, packed_sha = len(packed), _sha(packed)
    html = web.library_html(catalog['title'], navigation_href=name,
        navigation_gzip_href=config['navigationGzip'], initial=config['initial'], total=config['total'],
        totals=config['totals'], initial_path=config['initialPath'], shared_frame=shared)
    with (root / 'index.html').open('xb') as stream:
        stream.write(html.encode())
    return {'navigation_bytes': len(raw), 'navigation_cards': len(rows),
            'navigation_gzip_bytes': packed_bytes, 'runtime_bytes': len(web.HOST_RUNTIME.encode()),
            'navigation_sha256': _sha(raw), 'navigation_gzip_sha256': packed_sha,
            'navigation_bytes_unchanged': True}


def build_library(root, catalog, shared_config, *, source_url, builder, metadata=None,
                  navigation_config=None, callback=None, prepare_only=False):
    """Prepare -> original shared producer -> envelope -> common navigation.

    A fresh exporter supplies its existing metadata. An existing-export caller
    supplies its authenticated navigation config and original nav files instead.
    Unknown scripts are a failed compiled delivery, never silent optimization
    fallback. Native-free/authored cards keep their original complete capability.
    """
    root = Path(root)
    if (metadata is None) == (navigation_config is None):
        raise ValueError('exactly one navigation metadata or preserved config is required')
    prepared = materialize.prepare_library(root, catalog, shared_config, callback=callback)
    if prepared['report']['fallbacks'] or prepared['report']['prepared'] != len(catalog['cards']):
        raise ValueError('complete web delivery has unaudited fallback cards')
    if prepare_only:
        nav = (_preserved_navigation(root, catalog, navigation_config, prepared['config'])
               if navigation_config is not None else web.write_library(root, catalog, metadata, shared_frame=prepared['config']))
        return {'config': prepared['config'], 'report': {'schema': 'study-web-preparation.v1',
                'prepared': prepared['report'], 'phase': 'prepared-only-not-complete-delivery', **nav}}
    raw, _ = _read(root / prepared['config']['preparedIndex']['src'],
                   prepared['config']['preparedIndex']['sha256'])
    rules = _decode(raw)['cards']
    if set(rules) != {card['id'] for card in catalog['cards']}:
        raise ValueError('prepared index coverage differs')
    results, modes = {}, {'compiled': 0, 'authored': 0}
    for number, card in enumerate(catalog['cards'], 1):
        _, wrapper = _read(root / card['url'], limit=None, keep=False)
        rule = rules[card['id']]
        result = builder.build(root, {'path': card['url'], 'sha256': wrapper['sha256']},
            {'path': rule['src'], 'sha256': rule['sha256']},
            identity=catalog['book_id'] + ':' + card['id'], policy=prepared['config']['policy'], source_url=source_url)
        if result.get('mode') not in modes:
            raise ValueError('unknown common compiled build mode')
        modes[result['mode']] += 1; results[card['id']] = result
        if callback:
            callback({'stage': 'export-web-compile', 'book_id': catalog['book_id'],
                      'completed': number, 'total': len(catalog['cards']), **modes})
    attached = materialize.attach_compiled_library(root, catalog, prepared['config'], results)
    if attached['report']['compiled'] != modes['compiled']:
        raise ValueError('compiled envelope coverage differs')
    nav = (_preserved_navigation(root, catalog, navigation_config, attached['config'])
           if navigation_config is not None else web.write_library(root, catalog, metadata, shared_frame=attached['config']))
    return {'config': attached['config'], 'report': {'schema': 'study-complete-web-delivery.v1',
            'prepared': prepared['report'], 'compiled': attached['report'], 'modes': modes, **nav}}


def _tree_files(root):
    yield root / 'catalog.json'
    for name in ('cards', 'media'):
        directory = root / name
        if not directory.is_dir() or directory.is_symlink():
            raise ValueError('raw source tree must be a real directory')
        for folder, directories, files in os.walk(directory, followlinks=False):
            directories.sort(); files.sort()
            if any((Path(folder) / child).is_symlink() for child in directories):
                raise ValueError('raw source directory symlink differs')
            for child in files:
                yield Path(folder) / child


def _inventory(source, ledger, derived=None):
    digest, count, size = hashlib.sha256(), 0, 0
    with ledger.open('xb' if derived is None else 'rb') as stream:
        for path in _tree_files(source):
            relative = path.relative_to(source).as_posix()
            _, receipt = _read(path, limit=None, keep=False)
            row = {'path': relative, **{key: receipt[key] for key in ('bytes', 'sha256', 'six')}}
            raw = _json(row) + b'\n'
            if derived is None:
                stream.write(raw)
            else:
                if stream.readline() != raw:
                    raise ValueError('source cards/media/catalog SHA/six changed')
                _, copied = _read((derived / relative).resolve(strict=True), receipt['sha256'], limit=None, keep=False)
                if copied['six'] != receipt['six']:
                    raise ValueError('derived raw input does not retain source identity')
            digest.update(raw); count += 1; size += receipt['bytes']
        if derived is not None and stream.read(1):
            raise ValueError('raw source membership changed')
        if derived is None:
            stream.flush(); os.fsync(stream.fileno())
    return {'sha256': digest.hexdigest(), 'files': count, 'raw_bytes': size}


def derive_batch(source, destination, *, expected_complete_sha256, base_url, node='node',
                 heap_mb=4096, callback=None, builder_factory=None, final_check=None, prepare_only=False):
    """Derive all web artifacts of ONE completed RR batch; never touch APKGs.

    Outputs retain source raw trees by explicit read-only-use symlinks. Before
    and after full SHA/six ledgers cover every raw file; no source hardlinks,
    chmod, cleanup, database connection, source COMPLETE or live entry writes.
    """
    from .study_catalog_export import _publish_batch_complete
    source = Path(source).resolve(strict=True)
    destination = Path(destination)
    destination = destination.parent.resolve(strict=True) / destination.name
    if destination.exists() or destination.is_symlink():
        raise FileExistsError('derivative destination already exists')
    if destination.is_relative_to(source) or source.is_relative_to(destination):
        raise ValueError('derivative and source directories must be independent')
    origin = urlsplit(base_url)
    if origin.scheme not in {'http', 'https'} or not origin.netloc or origin.query or origin.fragment or origin.username or origin.password:
        raise ValueError('plain logical base URL required')
    complete_raw, complete_pin = _read(source / 'COMPLETE.json', expected_complete_sha256)
    complete = _decode(complete_raw)
    if (set(complete) != {'schema', 'artifacts', 'manifest_sha256', 'manifest_bytes'}
            or complete['schema'] != 'study-catalog-export-batch-complete.v1'):
        raise ValueError('completed parent batch required')
    manifest_raw, manifest_pin = _read(source / 'manifest.json', complete['manifest_sha256'])
    manifest = _decode(manifest_raw)
    if (manifest_pin['bytes'] != complete['manifest_bytes'] or manifest.get('schema') != 'study-catalog-export-batch.v1'
            or complete['artifacts'] != len(manifest['artifacts']) or manifest['snapshot'].get('read_only') is not True
            or manifest['snapshot'].get('isolation') != 'repeatable read'):
        raise ValueError('parent manifest/snapshot differs')
    jobs, seen = [], set()
    for row in manifest['artifacts']:
        if row['report_sha256'] != _sha(_json(row['report'])):
            raise ValueError('parent artifact report SHA differs')
        if row['format'] != 'web':
            continue
        name = row['name']; _local(source, name)
        if name in seen:
            raise ValueError('duplicate parent web artifact')
        seen.add(name); root = source / name
        marker_raw, marker = _read(root / 'COMPLETE.json')
        if marker_raw != _json(row['report']):
            raise ValueError('parent web completion differs from batch report')
        catalog_raw, catalog_pin = _read(root / 'catalog.json'); catalog = _decode(catalog_raw)
        index_raw, index_pin = _read(root / 'index.html'); config = library_config(index_raw)
        if (catalog.get('schema') != 'shared-book-web.v1' or catalog['book_id'] != row['book_id']
                or catalog['catalog_revision'] != manifest['snapshot']['catalog_revision']
                or manifest['books'][row['book_id']]['catalog_revision'] != catalog['catalog_revision']
                or len(catalog['cards']) != row['report']['cards']):
            raise ValueError('parent web identity/revision/count differs')
        jobs.append((row, root, catalog, config, (marker, catalog_pin, index_pin)))
    if not jobs:
        raise ValueError('parent batch has no web artifacts')
    destination.mkdir(mode=0o700, parents=False)
    builds = destination / '.build'; builds.mkdir(mode=0o700)
    reports, final_checks = [], []
    try:
        for row, source_root, catalog, config, receipts in jobs:
            root = destination / row['name']; root.mkdir(mode=0o700)
            receipts = list(receipts)
            links = {}
            for name in ('cards', 'media', 'catalog.json'):
                target = source_root / name
                (root / name).symlink_to(target, target_is_directory=name != 'catalog.json'); links[name] = str(target)
            for key in ('navigation', 'navigationGzip'):
                if config[key] is None:
                    continue
                raw, receipt = _read(_local(source_root, config[key])); receipts.append(receipt)
                with _local(root, config[key]).open('xb') as stream:
                    stream.write(raw)
            ledger = root / 'source-files.jsonl'
            before = _inventory(source_root, ledger)
            shared = {**config['sharedFrame'], 'policy': dict(config['sharedFrame']['policy'])}
            # A source policy is only a census. Rebuild exact approvals from its
            # script identities and the CURRENT audited constants, including the
            # field-restoration additions; no unknown script is silently allowed.
            audit = web.SharedMountAudit()
            audit.external.update(shared['policy']['external'])
            for pin in web.AUDITED_MOUNT_EXTERNAL_SHA256:
                for alias in ('_study_' + pin + '.js', '_study_field_script_' + pin + '.js'):
                    if (root / 'media' / alias).is_file():
                        audit.external.add(alias)
            audit.inline = {item['sha256']: item['source'] for item in shared['policy']['inline']}
            shared = web.audited_shared_config(root, audit)
            from contextlib import nullcontext
            context = (nullcontext(None) if prepare_only else
                       builder_factory(builds / row['name']) if builder_factory is not None else
                       CompiledBuild(builds / row['name'], node=node, heap_mb=heap_mb))
            with context as builder:
                delivery = build_library(root, catalog, shared, builder=builder,
                    source_url=urljoin(base_url.rstrip('/') + '/', row['name'] + '/index.html'),
                    navigation_config=config, callback=callback, prepare_only=prepare_only)
            for name, target in links.items():
                if not (root / name).is_symlink() or os.readlink(root / name) != target:
                    raise ValueError('derived raw input link changed')
            after = _inventory(source_root, ledger, root)
            if before != after:
                raise ValueError('raw source inventory changed')
            for name, target in links.items():
                if not (root / name).is_symlink() or os.readlink(root / name) != target:
                    raise ValueError('derived raw input link changed')
            for receipt in receipts:
                _again(receipt)
            report = {'schema': 'study-web-delivery-derivation.v1', 'book_id': row['book_id'],
                'source_web_report_sha256': row['report_sha256'], 'source_metadata': list(receipts),
                'source_files': before, 'source_ledger': 'source-files.jsonl',
                'raw_cards_media_catalog_SHA_six_unchanged': True, 'delivery': delivery['report']}
            with (root / 'DERIVATION.json').open('xb') as stream:
                stream.write(_json(report))
            reports.append({'name': row['name'], **report})
            final_checks.append((source_root, root, ledger, links, receipts, before))
        # A later book may have changed an earlier symlinked source. Completion
        # belongs to the WHOLE batch, not the last per-book observation.
        for source_root, root, ledger, links, receipts, before in final_checks:
            for name, target in links.items():
                if not (root / name).is_symlink() or os.readlink(root / name) != target:
                    raise ValueError('derived raw input link changed before batch completion')
            if _inventory(source_root, ledger, root) != before:
                raise ValueError('raw source inventory changed before batch completion')
            for receipt in receipts:
                _again(receipt)
        if final_check is not None:
            final_check()
        _again(complete_pin); _again(manifest_pin)
        result = {'schema': 'study-web-batch-preparation.v1' if prepare_only else 'study-web-batch-derivation.v1', 'parent_complete': complete_pin,
            'parent_manifest': manifest_pin, 'snapshot': manifest['snapshot'],
            'source_book_pins': {key: {'sha256': _sha(_json(value)), 'catalog_revision': value['catalog_revision']}
                                 for key, value in manifest['books'].items()}, 'webs': reports,
            'native_artifacts_regenerated': False, 'native_artifacts_rehashed': False}
        raw = _json(result)
        with (destination / 'manifest.json').open('xb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        authority = destination / 'preparation-authority' if prepare_only else destination
        if prepare_only:
            authority.mkdir(mode=0o700)
        _publish_batch_complete(authority, _json({'schema': 'study-web-batch-preparation-complete.v1' if prepare_only else 'study-web-batch-derivation-complete.v1',
            'manifest_sha256': _sha(raw), 'manifest_bytes': len(raw), 'webs': len(reports)}))
        return result
    except BaseException as error:
        try:
            with (destination / 'FAILED.json').open('xb') as stream:
                stream.write(_json({'schema': 'study-web-derivation-failed.v1', 'type': type(error).__name__,
                                    'completed': [row['name'] for row in reports]}))
        except OSError:
            pass
        raise
