"""Install exact static-export routes in the existing loopback bookshelf.

The legacy server lives in generated output. This tracked, reversible patcher
manages its narrow send_head hook without replacing its study API or database.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import runpy
import subprocess

if __package__:
    from .configure_preview_service import atomic_write, reload_service, runtime_preflight
else:
    from configure_preview_service import atomic_write, reload_service, runtime_preflight


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / 'anki_pipeline/preview_static_mounts.py'
MARKER = '# preview.static-mounts.v1'
LOADER = '''
# preview.static-mounts.v1
_PREVIEW_STATIC_RUNTIME = runpy.run_path(str(REPO_ROOT / 'anki_pipeline/preview_static_mounts.py'))
_PREVIEW_STATIC_MOUNTS = _PREVIEW_STATIC_RUNTIME['StaticMounts'].load(
    REPO_ROOT / 'data/web-study/service/static-mounts.json')
'''
HOOK = '''        try:
            mounted = _PREVIEW_STATIC_MOUNTS.resolve(self.path)
        except (OSError, ValueError, RuntimeError, _PREVIEW_STATIC_RUNTIME['MountDenied']):
            self.send_error(403)
            return None
        if mounted is not None:
            return _PREVIEW_STATIC_MOUNTS.send_head(self, mounted)
'''


def digest(raw: bytes | None) -> str | None:
    return hashlib.sha256(raw).hexdigest() if raw is not None else None


def patch_server(raw: bytes) -> bytes:
    source = raw.decode('utf-8')
    if MARKER in source:
        if source.count(LOADER) != 1 or source.count(HOOK) != 1:
            raise ValueError('Existing static route patch was independently changed')
        return raw
    anchors = ('import io\n', 'MAX_BODY_BYTES = 128 * 1024 * 1024\n', '    def send_head(self):\n')
    if any(source.count(anchor) != 1 for anchor in anchors):
        raise ValueError('Legacy bookshelf patch boundary changed')
    source = source.replace(anchors[0], anchors[0] + 'import runpy\n', 1)
    source = source.replace(anchors[1], anchors[1] + LOADER, 1)
    source = source.replace(anchors[2], anchors[2] + HOOK, 1)
    compile(source, '<bookshelf-static-routes>', 'exec')
    return source.encode('utf-8')


def read_optional(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def save_backup(path: Path, raw: bytes | None) -> str | None:
    if raw is None:
        return None
    try:
        with path.open('xb') as stream:
            path.chmod(0o600)
            stream.write(raw)
    except FileExistsError:
        if path.read_bytes() != raw:
            raise ValueError('Existing route backup differs from its pinned bytes') from None
    return str(path)


def validate_installed_server(server: Path) -> None:
    # run_name deliberately does not execute main, instantiate StudyStore, or
    # open the progress database. It validates the exact installed route config.
    namespace = runpy.run_path(str(server), run_name='preview_static_routes_preflight')
    if '_PREVIEW_STATIC_MOUNTS' not in namespace:
        raise ValueError('Static route preflight did not load the configured roots')


def restore_files(record: dict, names=('server', 'config')) -> None:
    originals = {}
    for name in names:
        backup = record[f'{name}_backup']
        original = Path(backup).read_bytes() if backup is not None else None
        if digest(original) != record[f'{name}_before_sha256']:
            raise ValueError('Static route recovery backup digest differs')
        originals[name] = original
    for name in names:
        if digest(read_optional(Path(record[name]))) != record[f'{name}_after_sha256']:
            raise RuntimeError('Static route files were subsequently edited; automatic rollback refused')
    for name in names:
        path = Path(record[name])
        # Recheck immediately before each mutation as well as the batch
        # preflight: another writer may act while the preceding file is saved.
        if digest(read_optional(path)) != record[f'{name}_after_sha256']:
            raise RuntimeError('Static route files were subsequently edited; automatic rollback refused')
        raw = originals[name]
        if raw is None:
            path.unlink()
        else:
            atomic_write(path, raw, record[f'{name}_mode'])


def configure(manifest: Path, server: Path, receipt: Path, *, expected_server_sha256: str,
              service_plist: Path, reload: bool = False) -> dict:
    manifest = manifest.resolve(strict=True)
    receipt = receipt.resolve()
    server = server.resolve(strict=True)
    config = ROOT / 'data/web-study/service/static-mounts.json'
    if config.resolve().is_relative_to(ROOT / 'output'):
        raise ValueError('Runtime configuration must remain outside the HTTP document root')
    before = server.read_bytes()
    if digest(before) != expected_server_sha256:
        raise ValueError('Existing server bytes changed; recheck before applying')
    old_config = read_optional(config)
    entries = json.loads(manifest.read_text(encoding='utf-8'))
    runtime = runpy.run_path(str(RUNTIME))
    runtime['StaticMounts'](entries)
    configuration = json.dumps({'schema': 'preview.static-mounts.v1', 'mounts': entries},
                               ensure_ascii=False, indent=2).encode() + b'\n'
    updated = patch_server(before)
    if receipt.exists():
        raise FileExistsError('Preserve the previous route installation receipt')
    if reload:
        runtime_preflight(service_plist.read_bytes())
    receipt.parent.mkdir(parents=True, exist_ok=True)
    record = {'schema': 'bookshelf.static-routes.install.v1', 'server': str(server),
              'config': str(config), 'server_before_sha256': digest(before),
              'server_after_sha256': digest(updated), 'config_before_sha256': digest(old_config),
              'config_after_sha256': digest(configuration), 'runtime_sha256': digest(RUNTIME.read_bytes()),
              'server_backup': save_backup(receipt.parent / f'server-before-{digest(before)[:16]}.py', before),
              'config_backup': save_backup(receipt.parent / f'mounts-before-{digest(old_config)}.json', old_config),
              'server_mode': server.stat().st_mode & 0o777,
              'config_mode': config.stat().st_mode & 0o777 if config.exists() else 0o600,
              'route_count': len(entries)}
    if server.read_bytes() != before or read_optional(config) != old_config:
        raise ValueError('Static route inputs changed during preparation')
    with receipt.open('x', encoding='utf-8') as stream:
        receipt.chmod(0o600)
        json.dump(record, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    changed = []
    reloading_started = False
    try:
        if read_optional(config) != old_config:
            raise RuntimeError('Static route configuration changed before installation')
        atomic_write(config, configuration, 0o600)
        changed.append('config')
        if server.read_bytes() != before:
            raise RuntimeError('Existing server changed before installation')
        atomic_write(server, updated, record['server_mode'])
        changed.append('server')
        validate_installed_server(server)
        if reload:
            reloading_started = True
            reload_service(service_plist)
    except Exception:
        restore_files(record, tuple(changed))
        if reloading_started:
            subprocess.run(['launchctl', 'bootstrap', f'gui/{os.getuid()}', str(service_plist)],
                           check=False)
        raise
    return {**record, 'reloaded': reload}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--server', type=Path, default=ROOT / 'output/web-study/server.py')
    parser.add_argument('--service-plist', type=Path, default=ROOT / 'data/web-study/service/com.chnragdoll.anki-bookshelf.plist')
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--expected-server-sha256')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--reload', action='store_true')
    parser.add_argument('--rollback', action='store_true')
    args = parser.parse_args()
    if not args.apply:
        parser.error('Use --apply only after reviewing the exact manifest and server digest')
    if args.rollback:
        record = json.loads(args.receipt.read_text())
        if record.get('schema') != 'bookshelf.static-routes.install.v1':
            parser.error('Unexpected static route receipt')
        if args.reload:
            runtime_preflight(args.service_plist.read_bytes())
        restore_files(record)
        if args.reload:
            reload_service(args.service_plist)
        print(json.dumps({'restored': True, 'server': record['server']}))
    else:
        if not args.manifest or not args.expected_server_sha256:
            parser.error('--manifest and --expected-server-sha256 are required')
        print(json.dumps(configure(args.manifest, args.server, args.receipt,
            expected_server_sha256=args.expected_server_sha256,
            service_plist=args.service_plist, reload=args.reload), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
