"""Explicit legacy learning URLs backed by authenticated current web exports.

This authenticates resource identity, not client compatibility. The exported
wrapper uses study-flip/study-side and serialized authored sides. A legacy
preview-flip/front/back consumer or plaintext-only audio extractor must keep
the explicit v1 compatibility path until its own integration is accepted.
Construction only reads small catalogs; card bodies are opened by the original
StaticMounts/Resource HTTP and audio paths, never parsed or rewritten here.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import PurePosixPath
import re
from types import MappingProxyType
import unicodedata
from urllib.parse import urlsplit

from .preview_static_mounts import MountDenied, StaticMounts, request_path


class PreviewRouteError(ValueError):
    """A projection does not exactly cover its approved learning identities."""


def _require(condition, message):
    if not condition:
        raise PreviewRouteError(message)


def _integer(value):
    return type(value) is int and 0 <= value <= 2**53 - 1


def _text(value):
    return type(value) is str and bool(value) and '\0' not in value


def _stamp(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _namespace_alias(path):
    # Classify only; never silently rewrite a card/media request. Repeated '/'
    # and case/Unicode aliases can otherwise miss our deny and reach a legacy
    # file on the case-insensitive, normalization-insensitive host filesystem.
    return unicodedata.normalize('NFD', re.sub('/+', '/', path)).casefold()


def _read_catalog(mounts, prefix, sha256, size):
    _require(type(sha256) is str and re.fullmatch('[a-f0-9]{64}', sha256) and
             type(size) is int and 0 < size <= 32 * 1024 * 1024, 'invalid projection catalog pin')
    url = prefix + 'catalog.json'
    resource = mounts.resolve(url)
    _require(resource is not None, 'projection catalog is not mounted')
    stream, before = resource.open()
    with stream:
        raw = stream.read(size + 1)
        _require(len(raw) == size and _stamp(os.fstat(stream.fileno())) == _stamp(before) and
                 _stamp(resource.path.lstat()) == _stamp(before), 'projection catalog changed during read')
        _require(hashlib.sha256(raw).hexdigest() == sha256, 'projection catalog SHA differs from its pin')
        again = mounts.resolve(url)  # Includes the original catalog-alias guard.
        _require(again is not None and (again.path, again.root) == (resource.path, resource.root),
                 'projection catalog alias changed during read')

    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, 'duplicate projection catalog field')
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda _: _require(False, 'nonfinite projection JSON'))
    except (ValueError, UnicodeError) as error:
        raise PreviewRouteError('invalid projection catalog JSON') from error


def _old_card_path(value):
    _require(_text(value), 'legacy card URL is missing')
    parsed = urlsplit(value)
    _require(not (parsed.scheme or parsed.netloc or parsed.query or parsed.fragment) and
             request_path(value) == value and '%' not in value and '//' not in value,
             'legacy card URL is not canonical')
    path = PurePosixPath(value)
    _require(path.parent.name == 'cards' and re.fullmatch(r'[A-Za-z0-9_-]+\.html', path.name),
             'legacy card URL must be a direct cards member')
    return str(path.parent.parent).rstrip('/') + '/'


def _members(value, approved, revision):
    _require(type(value) is dict and set(value) ==
             {'schema','book_id','title','scope','cards','catalog_revision'} and
             value['schema'] == 'shared-book-web.v1' and value['book_id'] == approved['book_id'] and
             _text(value['title']) and type(value['scope']) is dict and type(value['cards']) is list and
             _integer(value['catalog_revision']) and value['catalog_revision'] >= revision,
             'projection catalog schema, source book or revision differs')
    result, ids, urls = {}, set(), set()
    fields = {'id','guid','native_id','template_ordinal','word','label','unit','ordinal','template','url'}
    for card in value['cards']:
        _require(type(card) is dict and set(card) == fields and
                 all(_text(card[name]) for name in ('id','guid','label','unit','template','url')) and
                 type(card['word']) is str and
                 all(_integer(card[name]) for name in ('native_id','template_ordinal','ordinal')) and
                 re.fullmatch(r'cards/[a-f0-9]{64}\.html', card['url']),
                 'invalid projection card identity or URL')
        _require(card['native_id'] not in result and card['id'] not in ids and card['url'] not in urls,
                 'duplicate projection native, card identity or wrapper URL')
        result[card['native_id']] = card
        ids.add(card['id']); urls.add(card['url'])
    _require(len(result) == approved['native_cards'], 'projection native count differs')
    return result


class StudyPreviewRoutes(StaticMounts):
    """Reuse formal mounts and their guards, adding only approved URL aliases.

    The provider calls this *after* authenticating report/bindings against the
    canonical native identities in its existing read-only RR transaction.
    ``books`` retain the legacy StudyStore shape. No implicit new learning row,
    prefix guessing, redirect, source SQL, card-body read or file write occurs.
    """
    def __init__(self, mounts, books, registrations, report):
        _require(isinstance(mounts, StaticMounts) and not isinstance(mounts, StudyPreviewRoutes),
                 'formal StaticMounts are required for v2 projections')
        self._formal = mounts
        self.mounts = mounts.mounts  # Preserve the original HTTP/audio privacy-root capability.
        approved = {row['legacy_book']: row for row in report['books']}
        _require(set(books) == set(registrations) == set(approved), 'projection book coverage differs')
        routes, media_routes = {}, {}
        for key, registration in registrations.items():
            descriptor = registration['projection']
            _require(type(descriptor) is dict and set(descriptor) ==
                     {'url_mount','catalog_sha256','catalog_bytes'}, 'invalid projection registration fields')
            prefix = descriptor['url_mount']
            _require(type(prefix) is str and
                     re.fullmatch(r'/study-catalog-\d{8}/master-[a-z0-9_-]+-web-v3/', prefix) and
                     prefix in mounts.mounts, 'projection must name a registered formal v3 mount')
            members = _members(_read_catalog(mounts, prefix, descriptor['catalog_sha256'],
                                             descriptor['catalog_bytes']), approved[key], report['catalog_revision'])
            bindings = [row for row in report['bindings'] if row['legacy']['book'] == key]
            excluded = [row for row in report['excluded_from_legacy_learning_catalog']
                        if row['book_id'] == approved[key]['book_id']]
            targets = [row['target'] for row in bindings] + excluded
            _require(len(targets) == len(members) and
                     {row['native_id'] for row in targets} == set(members),
                     'projection must cover exactly approved bindings and exclusions')
            old_cards = {row['id']: row for row in books[key]['cards']}
            _require(len(old_cards) == len(bindings) and
                     {row['legacy']['card_id'] for row in bindings} == set(old_cards),
                     'legacy route membership differs from approved bindings')
            book_prefixes = set()
            for binding in bindings:
                target = binding['target']; old_id = binding['legacy']['card_id']
                current = members[target['native_id']]
                _require(current['guid'] == target['guid'] and
                         current['template_ordinal'] == target['template_ordinal'],
                         'projection native GUID/template differs')
                if binding['evidence'] == 'exact-source-card-id':
                    _require(current['id'] == old_id, 'projection source card ID differs')
                elif binding['evidence'] == 'exact-guide-proof':
                    proof = report['guide_proofs'].get(key, {})
                    _require(proof.get('id') == old_id and current['id'] == target['guid'] and
                             all(proof.get(name) == target[name]
                                 for name in ('guid','native_id','note_id','template_ordinal')),
                             'projection guide requires its explicit approved exception')
                else:
                    raise PreviewRouteError('unsupported projection binding evidence')
                old_url = old_cards[old_id]['previewUrl']
                book_prefixes.add(_old_card_path(old_url))
                _require(old_url not in routes, 'duplicate legacy card URL')
                formal_url = prefix + current['url']
                _require(mounts.resolve(formal_url) is not None, 'projection wrapper is not mounted')
                routes[old_url] = formal_url
            for item in excluded:
                current = members[item['native_id']]
                _require(current['id'] == item['id'] and current['guid'] == item['guid'] and
                         current['template_ordinal'] == item['template_ordinal'],
                         'projection excluded identity differs')
            _require(len(book_prefixes) == 1, 'each legacy book needs one unambiguous card directory')
            old_prefix = book_prefixes.pop()
            directories = [_namespace_alias(old_prefix + kind + '/') for kind in ('cards', 'media')]
            existing = [_namespace_alias(other + kind + '/')
                        for other in media_routes for kind in ('cards', 'media')]
            _require(not any(left.startswith(right) or right.startswith(left)
                             for left in directories for right in existing), 'legacy resource prefixes overlap')
            _require(not any(left.startswith(right) or right.startswith(left)
                             for left in directories for right in map(_namespace_alias, mounts.mounts)),
                     'legacy and formal resource prefixes overlap')
            media_routes[old_prefix] = prefix
        self._cards = MappingProxyType(routes)
        self._prefixes = MappingProxyType(media_routes)

    def resolve(self, target):
        path = request_path(target)
        if path in self._cards:
            return self._formal.resolve(self._cards[path])
        alias = _namespace_alias(path)
        for old_prefix, formal_prefix in self._prefixes.items():
            for kind in ('cards', 'media'):
                directory = old_prefix + kind
                if path == directory or path.startswith(directory + '/'):
                    if kind == 'cards':
                        raise MountDenied('Unmapped legacy card is not an approved projection')
                    # The formal resolver still enforces aliases, confinement,
                    # private suffixes and later symlink-retarget protection.
                    result = self._formal.resolve(formal_prefix + path[len(old_prefix):])
                    if result is None:
                        raise MountDenied('Legacy media is not an approved projection')
                    return result
                protected = _namespace_alias(directory)
                if alias == protected or alias.startswith(protected + '/'):
                    raise MountDenied('Noncanonical legacy resource namespace is not an approved projection')
        return self._formal.resolve(target)
