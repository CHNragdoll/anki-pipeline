"""Prepare small private A/B parents from the frozen full-HOST QA text only.

Default dry run never writes. --write-private creates only new files beside this
script. It never installs into the export, executes JS or constructs a packet.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import stat

HERE = Path(__file__).resolve().parent
BASELINE = Path('/private/tmp/study-compiled-2026-v3-frozen-profile-qa-20261017-dP6sM3')
BASELINE_SEAL = '4131b465d93a3ade3d9e796c03bf00492cd2b4afbe8dbeb87f0e5cc38de3eeb6'
CARD = 'ae098143139042ef971c4912aa263598c08bcef1300ec68a9aa7565dba4ea576'
HOST_PIN = '6a96b752945c0d62130c56f8958977ddaa6bcc9611742b4df3c149bf5e0143da'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def small_file(path, pin):
    path = Path(path)
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_size > 1024 * 1024:
        raise ValueError('Pinned small QA source differs')
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), 'rb') as stream:
        original = os.fstat(stream.fileno())
        raw = stream.read(1024 * 1024 + 1)
        before = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        def identity(current):
            return current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns, current.st_ctime_ns
        if (identity(original) != before or identity(os.fstat(stream.fileno())) != before
                or identity(path.lstat()) != before or len(raw) != info.st_size or sha(raw) != pin):
            raise ValueError('Pinned small QA source changed')
        return raw


def literal(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).replace('<', r'\u003c').encode()


def render_parent(parent, config, collector, old_frame, frame, *, variant, frame_pin):
    """Change only the sharedFrame HTML and collector metadata literal."""
    if variant not in ('A', 'B'):
        raise ValueError('Unknown transport variant')
    original_config = json.loads(config)
    if original_config['sharedFrame']['html'].encode() != old_frame:
        raise ValueError('Original QA frame differs')
    old_literal, new_literal = literal(old_frame.decode()), literal(frame.decode())
    if config.count(old_literal) != 1:
        raise ValueError('Original QA frame literal is not unique')
    new_config = config.replace(old_literal, new_literal, 1)
    undone = json.loads(new_config)
    undone['sharedFrame']['html'] = original_config['sharedFrame']['html']
    if undone != original_config:
        raise ValueError('Transport changed another HOST setting')
    text = collector.decode()
    prefix = ' const metadata='
    if text.count(prefix) != 1:
        raise ValueError('Original collector metadata differs')
    offset = text.index(prefix) + len(prefix)
    metadata, length = json.JSONDecoder().raw_decode(text[offset:])
    updated = dict(metadata, case_id='compiled-largest2026-gzip-transport-' + variant,
                   candidate_identity='same-full-HOST-source-chain-transport-only-' + variant,
                   candidate_frame_sha256=frame_pin, transport_variant=variant,
                   parent_template_sha256=sha(parent))
    encoded = json.dumps(updated, ensure_ascii=False, separators=(',', ':'))
    new_collector = (text[:offset] + encoded + text[offset + length:]).encode()
    if (new_collector.decode()[:offset] + text[offset:offset + length]
            + new_collector.decode()[offset + len(encoded):]) != text:
        raise ValueError('Collector logic changed')
    block = b'<script id="study-compiled-profile-qa-clock">\n' + collector + b'\n</script>\n'
    new_block = b'<script id="study-compiled-profile-qa-clock">\n' + new_collector + b'\n</script>\n'
    if parent.count(config) != 1 or parent.count(block) != 1:
        raise ValueError('Original complete HOST parent format differs')
    result = parent.replace(config, new_config, 1).replace(block, new_block, 1)
    if result.replace(new_block, block, 1).replace(new_config, config, 1) != parent:
        raise ValueError('Parent inverse does not recover the frozen original')
    return result, new_collector


def build(freeze_pin, candidate):
    candidate = Path(candidate).resolve(strict=True)
    seal = json.loads(small_file(BASELINE / 'SEALS.json', BASELINE_SEAL))['files']
    def old(name):
        return small_file(BASELINE / name, seal[name]['sha256'])
    parent = old('_qa_compiled_profile_58668d2b6479.html')
    config, collector = old('qa-config.literal'), old('collector.js')
    baseline_frame = old('candidate-frame.html')
    hosts = []
    for value in re.findall(br'<script[^>]+src=["\']([^"\']+)', parent):
        if value.startswith(b'data:text/javascript;base64,'):
            code = base64.b64decode(value.split(b',', 1)[1], validate=True)
            if sha(code) == HOST_PIN:
                hosts.append(code)
    if (len(hosts) != 1 or not all(name in hosts[0] for name in
            (b'async function fetchCard(', b'async function preparedCard(', b'async function mountSharedCard(',
             b"wrapperDelivery==='source-gzip.v1'"))):
        raise ValueError('Original complete HOST source chain differs')
    frozen = json.loads(small_file(candidate / 'FROZEN.json', freeze_pin))
    files = {row['path']: row for row in frozen['files']}
    variants = {}
    for variant, name, frame_name in (('A', 'baseline-candidate-frame.html', 'baseline-candidate-frame.js'),
                                       ('B', 'candidate-frame.html', 'candidate-frame.js')):
        frame = small_file(candidate / name, files[name]['sha256'])
        small_file(candidate / frame_name, files[frame_name]['sha256'])
        if variant == 'A' and frame != baseline_frame:
            raise ValueError('A is not the original 052ccc54 frame HTML')
        rendered, new_collector = render_parent(parent, config, collector, baseline_frame, frame,
                                                variant=variant, frame_pin=files[frame_name]['sha256'])
        variants[variant] = {'parent': rendered, 'collector': new_collector,
                             'frame_sha256': files[frame_name]['sha256'], 'frame_html_sha256': files[name]['sha256']}
    proof = {'schema': 'study-compiled-transport-parent-proof.v1', 'card_id': CARD,
             'baseline_seal_sha256': BASELINE_SEAL, 'candidate_freeze_sha256': freeze_pin,
             'original_full_host_sha256': HOST_PIN, 'original_parent_sha256': sha(parent),
             'same_host_fetchCard_wrapper_prepared_chain': True, 'direct_mount_packet': False,
             'collector_logic_exact_except_metadata': True, 'fullgate_and_10s_unchanged': True,
             'original_flip_and_manual_JSON_download_preserved': True,
             'source_DOM_or_semantic_parses': 0, 'browser_runs': 0, 'server_started': False,
             'routes_required': ['A/index.html', 'B/index.html', 'same navigation/raw+gzip',
                 'same prepared index/raw+gzip', 'same source wrapper/raw+gzip',
                 'same front/complete artifacts and native module', 'exact original CSS/native/media closure',
                 'compiled raw html/profile/runtime for A+B', 'three explicit compiled .gz carriers for B'],
             'unknown_routes': '404; no directory fallback',
             'variants': {key: {'parent_sha256': sha(value['parent']), 'bytes': len(value['parent']),
                               'collector_sha256': sha(value['collector']), 'frame_sha256': value['frame_sha256'],
                               'frame_html_sha256': value['frame_html_sha256'],
                               'path': key + '/index.html#card=' + CARD} for key, value in variants.items()}}
    return variants, proof


def write_new(path, raw):
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate-stage', type=Path, required=True)
    parser.add_argument('--candidate-freeze-sha256', required=True)
    parser.add_argument('--write-private', action='store_true')
    args = parser.parse_args()
    variants, proof = build(args.candidate_freeze_sha256, args.candidate_stage)
    if args.write_private:
        info = HERE.lstat()
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError('Owned private output directory is required')
        outputs = {HERE / (key + '-parent.html'): value['parent'] for key, value in variants.items()}
        outputs.update({HERE / (key + '-collector.js'): value['collector'] for key, value in variants.items()})
        outputs[HERE / 'parent-proof.json'] = (json.dumps(proof, indent=2) + '\n').encode()
        if any(path.exists() or path.is_symlink() for path in outputs):
            raise ValueError('Private parent output already exists; never overwrite')
        for path, raw in outputs.items():
            write_new(path, raw)
    print(json.dumps({'mode': 'private-parent-written' if args.write_private else 'dry-run', **proof}, indent=2))


if __name__ == '__main__':
    main()
