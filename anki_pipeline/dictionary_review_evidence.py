"""Read-only source binding for newly reviewed dictionary definitions.

The registry must already have been checked against actual native entries by
the caller. This module never opens dictionary archives or fetches URLs.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
import re
from urllib.parse import urlsplit


_HASH = re.compile(r'[0-9a-f]{64}\Z')
_IDENTITY = ('provider', 'source_entry_id', 'raw_sha256', 'sense_id')
_OFFICIAL_HOSTS = ('dictionary.cambridge.org', 'oxfordlearnersdictionaries.com',
                   'collinsdictionary.com', 'merriam-webster.com', 'ldoceonline.com',
                   'macmillandictionary.com', 'dictionary.com', 'pons.com', 'ahdictionary.com',
                   'britannica.com')


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _text(value, label):
    _require(isinstance(value, str) and bool(value.strip()), f'Missing {label}')
    return value


def _normal(value):
    return ' '.join(value.split())


class _VisibleHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style'}:
            self.hidden += 1
        if tag in {'br', 'p', 'div', 'li', 'section', 'tr'}:
            self.parts.append(' ')

    def handle_endtag(self, tag):
        if tag in {'script', 'style'}:
            self.hidden = max(0, self.hidden - 1)
        if tag in {'p', 'div', 'li', 'section', 'tr'}:
            self.parts.append(' ')

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def _capture_text(pin):
    path = Path(_text(pin.get('capture_file'), 'capture_file'))
    _require(path.suffix.lower() in {'.txt', '.md', '.html', '.htm', '.json', '.jsonl'},
             'Capture must be a UTF-8 text file, not a raw dictionary archive')
    expected = pin.get('capture_sha256')
    _require(isinstance(expected, str) and _HASH.fullmatch(expected), 'Invalid capture SHA256')
    try:
        raw = path.read_bytes()
        text = raw.decode('utf-8')
    except (OSError, UnicodeError) as exc:
        raise ValueError('Capture is unavailable or is not UTF-8') from exc
    _require(hashlib.sha256(raw).hexdigest() == expected, 'Capture SHA256 mismatch')
    if pin.get('raw_sha256') is not None:
        _require(pin['raw_sha256'] == expected, 'Capture raw SHA256 mismatch')
    return text, {**deepcopy(pin), 'capture_file': str(path.resolve()), 'capture_sha256': expected}


def _official_capture(pin, english=None, chinese=None):
    _require(pin.get('provider') == 'official_web', 'Official capture requires official_web provider')
    url = urlsplit(_text(pin.get('source_url'), 'official source URL'))
    hostname = (url.hostname or '').lower()
    _require(url.scheme in {'http', 'https'} and not url.username and not url.password
             and any(hostname == host or hostname.endswith('.' + host) for host in _OFFICIAL_HOSTS),
             'Capture URL is not an official dictionary source')
    raw, normalized_pin = _capture_text(pin)
    visible = raw
    if pin.get('capture_format', 'text') == 'html':
        parser = _VisibleHTML()
        parser.feed(raw)
        parser.close()
        visible = ''.join(parser.parts)
    else:
        _require(pin.get('capture_format', 'text') == 'text', 'Unsupported dictionary capture format')
    # Browser source-view decorations are not part of the dictionary wording.
    # Source-view links can wrap real definition words. Preserve their visible
    # label while dropping reference IDs and optional trailing domain markers.
    visible = re.sub(r'cite([^]*)', lambda match:
        match[1].split('†')[1] if '†' in match[1] else '', visible)
    visible = re.sub(r'(?m)^\s*L[0-9]+:\s?', '', visible)
    visible = _normal(unescape(visible))
    declared = pin.get('original_definition_text')
    if english is not None:
        _require(_normal(_text(declared, 'captured full English definition')) == _normal(english),
                 'Captured full English definition does not match the decision')
        _require(_normal(english) in visible, 'Full English definition is absent from official capture')
    if chinese:
        _require(chinese in visible, 'Original Chinese translation is absent from official capture')
    return {'kind': 'official_capture', 'source_ref_pin': normalized_pin,
            'english_definition': declared or '', 'original_chinese': chinese or ''}


def _native_source(pin, registry, english=None, *, require_english=True):
    _require(all(key in pin and pin[key] is not None for key in _IDENTITY),
             'Native registry pin lacks source identity')
    _require(isinstance(pin['raw_sha256'], str) and _HASH.fullmatch(pin['raw_sha256']),
             'Invalid native registry raw SHA256')
    candidates = []
    for row in registry:
        source = row.get('source_ref') if isinstance(row, dict) else None
        if not isinstance(source, dict) or any(source.get(key) != pin[key] for key in _IDENTITY):
            continue
        if pin.get('sense_ref') is not None and row.get('sense_ref') != pin['sense_ref']:
            continue
        if any(pin[key] != value for key, value in source.items() if key in pin):
            continue
        candidates.append(row)
    _require(bool(candidates), 'Source pin does not match the actual native registry')
    _require(all(row.get('native_definition_valid') is True and row.get('raw_entry_valid') is True
                 for row in candidates), 'Native registry definition or raw entry is not validated')
    _require(all(isinstance(row.get('english'), str) and isinstance(row.get('chinese', ''), str)
                 for row in candidates), 'Native registry English and Chinese must be text')
    pairs = {(row['english'], row.get('chinese', '')) for row in candidates}
    _require(len(pairs) == 1, 'Native registry source identity has conflicting definitions')
    row = candidates[0]
    actual = row.get('english', '')
    if require_english:
        actual = _text(actual, 'native full English definition')
    if english is not None:
        _require(_normal(actual) == _normal(english), 'English is not the full native registry definition')
    if pin.get('original_definition_text') is not None:
        _require(_normal(_text(pin['original_definition_text'], 'pinned English definition')) == _normal(actual),
                 'Pinned English differs from the full native registry definition')
    return {'kind': 'native_registry',
            'source_ref_pin': {**deepcopy(row['source_ref']), 'sense_ref': row.get('sense_ref')},
            'english_definition': actual, 'original_chinese': row.get('chinese', '')}


def _source(pin, registry, english=None, chinese=None, *, require_english=True):
    _require(isinstance(pin, dict), 'Dictionary source pin must be an object')
    if pin.get('provider') == 'official_web':
        return _official_capture(pin, english, chinese)
    return _native_source(pin, registry, english, require_english=require_english)


def _search_evidence(value, registry):
    _require(isinstance(value, dict), 'Reviewed translation needs recorded bilingual_search evidence')
    queries = value.get('queries')
    _require(isinstance(queries, list) and bool(queries), 'bilingual_search needs actual queries')
    normalized = [_text(item.get('query') if isinstance(item, dict) else item, 'bilingual search query')
                  for item in queries]
    pins = value.get('source_pins')
    _require(isinstance(pins, list) and bool(pins), 'bilingual_search needs actual source pins')
    sources = [_source(pin, registry) for pin in pins]
    result = {'queries': normalized, 'sources': sources}
    if 'capture_file' in value or 'capture_sha256' in value:
        text, pin = _capture_text(value)
        _require(all(query in text for query in normalized), 'Search queries are absent from recorded capture')
        result['capture_file'], result['capture_sha256'] = pin['capture_file'], pin['capture_sha256']
    return result


def validate_new_sense(decision, *, registry=()):
    """Validate full native EN and original/cross-source/reviewed CN provenance.

    Return new normalized evidence without modifying the decision or registry.
    Registry rows must be freshly validated by the caller; official captures
    are read and SHA-256 checked on every call.
    """
    _require(isinstance(decision, dict), 'New-sense decision must be an object')
    explanation, sense = decision.get('dictionary_explanation'), decision.get('new_sense')
    _require(isinstance(explanation, dict) and isinstance(sense, dict),
             'New sense requires dictionary_explanation and new_sense')
    english = _text(explanation.get('english_definition'), 'full English definition')
    _require(_normal(_text(sense.get('original_english'), 'new-sense original English')) == _normal(english),
             'New-sense original English differs from dictionary explanation')
    text = _text(sense.get('text'), 'new-sense Chinese text')
    kind = sense.get('translation_kind')
    _require(kind in {'original', 'cross_dictionary_original', 'reviewed_translation'},
             'Unknown new-sense translation kind')
    registry = tuple(registry)
    declared_chinese = explanation.get('original_chinese', '')
    _require(isinstance(declared_chinese, str), 'Original Chinese must be text')
    primary = _source(explanation.get('source_ref_pin'), registry, english, declared_chinese)
    actual_pin = primary['source_ref_pin']
    if explanation.get('source') is not None:
        _require(explanation['source'] == actual_pin['provider'], 'Explanation provider differs from actual source')
    if explanation.get('exact_entry') is not None:
        _require(explanation['exact_entry'] == actual_pin.get('source_headword'),
                 'Explanation entry differs from actual source headword')
    native_chinese = primary['original_chinese']
    _require(declared_chinese == native_chinese, 'Explanation Chinese differs from actual native Chinese')
    result = {'schema': 'dictionary-review-evidence.v1', 'translation_kind': kind,
              'english_definition': primary['english_definition'], 'text': text,
              'original_chinese': native_chinese, 'primary_source': primary}
    if kind == 'original':
        _require(bool(native_chinese.strip()) and sense.get('original_chinese') == native_chinese
                 and text == native_chinese, 'Original Chinese must exactly match actual native Chinese')
    elif kind == 'cross_dictionary_original':
        secondary = explanation.get('secondary_source', sense.get('secondary_source'))
        _require(isinstance(secondary, dict), 'Cross-dictionary Chinese requires secondary_source')
        secondary_pin = secondary.get('source_ref_pin', secondary)
        _require(isinstance(secondary_pin, dict), 'Secondary dictionary source pin must be an object')
        secondary_english = secondary.get('english_definition',
            secondary_pin.get('original_definition_text', ''))
        _require(isinstance(secondary_english, str), 'Secondary English must preserve native text')
        if not secondary_english.strip():
            _text(secondary.get('scope_reason'), 'Chinese-only secondary scope explanation')
            _require(secondary_pin.get('provider') != 'official_web',
                     'Chinese-only secondary source requires the validated native registry')
        secondary_chinese = _text(secondary.get('original_chinese'), 'secondary original Chinese')
        source = _source(secondary_pin, registry, secondary_english, secondary_chinese,
            require_english=False)
        identity = lambda pin: tuple(pin.get(key) for key in ('provider', 'source_entry_id', 'raw_sha256'))
        _require(identity(source['source_ref_pin']) != identity(primary['source_ref_pin']),
                 'Cross-dictionary Chinese needs an independent source')
        _require(source['original_chinese'] == secondary_chinese == sense.get('original_chinese') == text,
                 'Cross-dictionary Chinese must exactly match actual secondary native Chinese')
        result['secondary_source'] = source
        result['original_chinese'] = source['original_chinese']
    else:
        _require(sense.get('original_chinese', '') == native_chinese,
                 'Reviewed translation cannot invent or hide original Chinese')
        result['bilingual_search'] = _search_evidence(
            explanation.get('bilingual_search', sense.get('bilingual_search')), registry)
    return result
