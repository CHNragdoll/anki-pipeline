"""Confined, sealed presentation derivatives for shared exam source adapters."""
from __future__ import annotations

import hashlib
import json
import math
import re
import struct
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote, urlsplit

IMAGE_SUFFIXES = frozenset({'.svg', '.png', '.jpg', '.jpeg', '.gif', '.webp'})


def image_dimensions(data, suffix):
    """Return positive intrinsic CSS-pixel dimensions when explicitly available."""
    if suffix.lower() == '.png':
        if len(data) < 24 or data[:8] != b'\x89PNG\r\n\x1a\n' or data[12:16] != b'IHDR':
            return None
        width, height = struct.unpack('>II', data[16:24])
    elif suffix.lower() == '.svg':
        if re.search(rb'<!DOCTYPE|<!ENTITY', data, re.I):
            return None
        try:
            root = ET.fromstring(data)
        except ET.ParseError:
            return None
        if root.tag.rsplit('}', 1)[-1] != 'svg':
            return None
        factors = {'': 1, 'px': 1, 'pt': 96 / 72, 'pc': 16,
                   'in': 96, 'cm': 96 / 2.54, 'mm': 96 / 25.4, 'q': 96 / 101.6}

        def length(value):
            match = re.fullmatch(r'\s*([+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*([a-zA-Z]*)\s*', value or '')
            if not match or match[2].lower() not in factors:
                return None
            return float(match[1]) * factors[match[2].lower()]

        width, height = length(root.get('width')), length(root.get('height'))
        try:
            box = [float(part) for part in re.split(r'[\s,]+', root.get('viewBox', '').strip())]
            if len(box) == 4 and all(math.isfinite(x) for x in box) and box[2] > 0 and box[3] > 0:
                if width is None and height is not None:
                    width = height * box[2] / box[3]
                elif height is None and width is not None:
                    height = width * box[3] / box[2]
                elif width is None and height is None:
                    width, height = box[2:]
        except ValueError:
            pass
    else:
        return None
    if width is None or height is None or not all(math.isfinite(x) and x > 0 for x in (width, height)):
        return None
    return {'width': width, 'height': height}


def _local_path(root, value):
    if not isinstance(value, str) or not value:
        raise ValueError('redraw path must be a relative local path')
    decoded = unquote(value)
    url = urlsplit(decoded)
    path = Path(decoded)
    if (url.scheme or url.netloc or url.query or url.fragment or path.is_absolute()
            or '\\' in decoded or '\x00' in decoded or '..' in path.parts):
        raise ValueError('redraw path must be a confined local path')
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError('redraw path escapes asset root')
    return resolved


def sealed_bytes(path, seal=None):
    """Read a source or its recovery cache, validating the original seal."""
    source = path
    if seal:
        state = path.stat()
        if (state.st_size, state.st_mtime_ns) != (seal['source_bytes'], seal['source_mtime_ns']):
            raise ValueError('sealed source image metadata changed')
        if seal.get('source_path') and Path(seal['source_path']).resolve() != path:
            raise ValueError('sealed source image path differs')
        source = Path(seal['path']).resolve(strict=True)
    data = source.read_bytes()
    if seal and hashlib.sha256(data).hexdigest() != seal['sha256']:
        raise ValueError('sealed image bytes differ')
    return source, data


def resolve_redraws(asset_root, overrides, manifest_path):
    """Apply only selected original images; never read unrelated image bytes.

    Replacement cache seals may be supplied in the same overrides dictionary.
    Original seals remain independently recorded in derivative provenance.
    """
    root = Path(asset_root).resolve(strict=True)
    raw = Path(manifest_path).read_bytes()
    manifest = json.loads(raw)
    if not isinstance(manifest, dict) or manifest.get('version') != 1 or not isinstance(manifest.get('images'), list):
        raise ValueError('unsupported redraw manifest')
    mappings = {}
    for entry in manifest['images']:
        if not isinstance(entry, dict):
            raise ValueError('invalid redraw manifest entry')
        original = _local_path(root, entry.get('original'))
        replacement = _local_path(root, entry.get('replacement'))
        if original in mappings:
            raise ValueError('duplicate redraw original mapping')
        if replacement.suffix.lower() not in IMAGE_SUFFIXES:
            raise ValueError('unsupported redraw presentation suffix')
        mappings[original] = (replacement, entry)
    if any(replacement in mappings for replacement, _ in mappings.values()):
        raise ValueError('redraw chains and cycles are not supported')
    result = dict(overrides)
    manifest_sha = hashlib.sha256(raw).hexdigest()
    for original, (replacement, entry) in mappings.items():
        original_seal = overrides.get(str(original))
        if original_seal is None:
            continue
        _, original_data = sealed_bytes(original, original_seal)
        replacement_seal = overrides.get(str(replacement))
        recovered, replacement_data = sealed_bytes(replacement, replacement_seal)
        original_sha = hashlib.sha256(original_data).hexdigest()
        replacement_sha = hashlib.sha256(replacement_data).hexdigest()
        for field, actual in (('sourceSha256', original_sha), ('replacementSha256', replacement_sha)):
            if field in entry and entry[field] != actual:
                raise ValueError('redraw manifest ' + field + ' differs')
        result[str(original)] = {
            **original_seal,
            'path': str(recovered), 'sha256': replacement_sha, 'bytes': len(replacement_data),
            'presentation_suffix': replacement.suffix.lower(),
            'derivative': {
                'original_sha256': original_sha, 'replacement_sha256': replacement_sha,
                'original_dimensions': image_dimensions(original_data, original.suffix),
                'replacement_dimensions': image_dimensions(replacement_data, replacement.suffix),
                'manifest_sha256': manifest_sha, 'replacement_source_path': str(replacement),
                'original_seal': dict(original_seal),
                'replacement_seal': dict(replacement_seal) if replacement_seal else None,
            },
        }
    return result
