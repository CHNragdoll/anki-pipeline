"""Exact common runtime revision for complete ordinary examples.

Only the two authenticated source modules containing the same legacy loader are
eligible. No resource URL expression or dependency is rewritten by this bridge.
"""
from __future__ import annotations
import hashlib
from pathlib import Path

_SOURCE_MODULES = frozenset({
    '5c361607267287f859150ac4f7716d05b94a6ee5bebc0478d11660e947b6a15e',
    'be39224f5f2d47eee8cad80060aeb364e72448b5cd1c11a7f7c8fd8d999e1b93',
})
_LEGACY_SHA = '17b5c61a67f0efa96251065352361c0c8afadb61a417a3c2ed5bb611006ec0d7'
_CURRENT_SHA = '9c85093bd59b3bf2efac98745d1e91d74302053207017762f853ba4c67169216'
_TEMPLATES = Path(__file__).with_name('templates')


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def completion_runtime(source):
    """Return the one explicit loader revision; unknown modules fail closed."""
    if not isinstance(source, str) or _sha(source.encode()) not in _SOURCE_MODULES:
        raise ValueError('unknown original ordinary-example runtime')
    legacy = (_TEMPLATES / 'slim-apkg-v2-legacy.js').read_text()
    current = (_TEMPLATES / 'slim-apkg-v2.js').read_text()
    if _sha(legacy.encode()) != _LEGACY_SHA or source.count(legacy) != 1:
        raise ValueError('original ordinary-example loader differs')
    if _sha(current.encode()) != _CURRENT_SHA:
        raise ValueError('approved ordinary-example completion loader differs')
    return source.replace(legacy, current, 1)


def validate_completion_runtime(source, revised):
    if revised != completion_runtime(source):
        raise ValueError('ordinary-example runtime revision is not the exact approved replacement')
