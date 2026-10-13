"""Build a new incremental preview from a committed residual checkpoint.

Only affected immutable card snapshots are read/rendered. The accepted database,
card pages, catalog and shell remain read-only; unchanged catalog rows continue
to reference their original URLs. This tool does not prepare a database, rebuild
a book, activate an entry point, or publish/import a package.
"""
from __future__ import annotations

import argparse
import ast
from contextlib import closing, ExitStack
from copy import deepcopy
import hashlib
import html
from html.parser import HTMLParser
import importlib.util
import json
import multiprocessing
from multiprocessing.connection import wait as wait_connections
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import tempfile
import time
import traceback
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from anki_pipeline import sense_frequency as sf, sense_display as sd
from anki_pipeline import native_example_usage as native_api
from anki_pipeline.sense_chunks import render_sentence_pair, _accent_chunks, _target_chunk_ids
from anki_pipeline.sense_groups import _pos
from anki_pipeline.packaging import (_highlight_example, _chunk_translation,
    _example_chunk_ranges, _annotate_sentence_chunks)
from anki_pipeline.native_example_usage import update_native_examples, restore_original
from scripts import update_exam_usage_preview as preview
from scripts import patch_exam_usage_preview as owner
from scripts.prepare_sense_frequency_records import class_aliases

SCHEMA = 'residual-optimization-preview-request.v1'
ARTIFACT = Path('residual-optimization-20261013/engineering/preview-own')
_HEX = re.compile(r'[a-f0-9]{64}')
SOURCE_PAPER_ROOT = ROOT.parent / 'exam-library/data/sources/exam-library/structured/papers/kaoyan'
SOURCE_SNAPSHOT_ROOT = ROOT.parent / 'exam-library/.local/kaoyan-content-audit-20261008/commit-candidate/checkout/data/sources/exam-library/structured/papers/kaoyan'
SOURCE_PDF_ROOT = ROOT.parent / 'exam-library/data/sources/kaoyan-web-2026-09-26/.firecrawl'
SOURCE_PDF_SNAPSHOT_ROOT = ROOT / 'output/residual-optimization-20261013/integration/source-content-snapshots'
RESIDUAL_KEYBOARD = r'''/* Reviewed residual spans reuse the existing bilingual click delegate. */
(function () {
  'use strict';
  var installed = new WeakMap();
  function install(doc) {
    if (installed.has(doc)) return installed.get(doc);
    var disposed = false;
    function keyboard(event) {
      if (disposed || event.defaultPrevented || event.repeat || event.ctrlKey || event.altKey || event.metaKey ||
          (event.key !== 'Enter' && event.key !== ' ')) return;
      var el = event.target;
      if (!el || !el.matches || !el.matches('.card-chunk[data-reviewed-chunk-projection="residual"]') ||
          !/^[0-9]+(?: [0-9]+)*$/.test(el.getAttribute('data-chunk-ids') || '') ||
          el.closest('a,button,input,select,textarea,summary,audio,video,[contenteditable],.sf-archived-example,.sf-inline-history')) return;
      var whole = (el.getAttribute('data-chunk-sentence-ids') || '').split(' ');
      if (el.getAttribute('data-chunk-ids').split(' ').every(function (id) { return whole.indexOf(id) >= 0; })) return;
      event.preventDefault();
      el.dispatchEvent(new doc.defaultView.MouseEvent('click', { bubbles: true, cancelable: true }));
    }
    var handle = { dispose: function () {
      if (disposed) return; disposed = true;
      doc.removeEventListener('keydown', keyboard, true); installed.delete(doc);
    } };
    installed.set(doc, handle); doc.addEventListener('keydown', keyboard, true); return handle;
  }
  window.AnkiResidualReviewedChunkRuntime = Object.freeze({ install: install });
})();
'''


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return preview.canonical(value)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def pin(path):
    path = Path(path).resolve(strict=True)
    require(path.suffix not in {'.sqlite3', '.db'}, 'database hashing is not part of preview rendering')
    return {'file': str(path), 'sha256': preview.file_sha(path)}


def checked(pin_value):
    require(isinstance(pin_value, dict) and Path(pin_value.get('file', '')).suffix not in
            {'.sqlite3', '.db'}, 'an immutable non-database file pin is required')
    return preview.pin_file(pin_value)


def read_json(pin_value):
    return preview._read_json(checked(pin_value))


def source_metadata(path):
    value = Path(path).stat()
    return {name: getattr(value, 'st_' + name, 0) for name in
            ('dev', 'ino', 'size', 'mtime_ns', 'ctime_ns', 'flags', 'mode')}


def source_content_transport(request, source_files, watched=None):
    """Explicit same-byte locators; never read or rewrite origin content."""
    value = request.get('source_content_snapshots')
    if value is None:
        return None
    require(isinstance(value, dict) and set(value) == {'file', 'sha256'}, 'source snapshot proof needs an exact pin')
    proof = read_json(value)
    require(proof.get('schema') == 'residual-source-paper-exact-snapshots.v1' and
            proof.get('readonly') is True and proof.get('origin_content_read_claim') is False and
            proof.get('original_sources_modified') is False and proof.get('verified_local_snapshot_content') is True and
            proof.get('all_exact') is True and proof.get('total') == 33 and
            isinstance(proof.get('rows'), list) and len(proof['rows']) == 33, 'source snapshot proof scope differs')
    expected = {path: checksum for path, checksum in source_files.items()
        if Path(path).parent == SOURCE_PAPER_ROOT and re.fullmatch(r'\d{4}-\d{2}\.json', Path(path).name)}
    require(len(expected) == 33, 'source snapshot transport requires all 33 registered writer paper pins')
    seen, content_paths = set(), set()
    for row in proof['rows']:
        origin = row.get('original_source', {})
        require(set(origin) == {'file', 'sha256'} and origin.get('file') in expected and
                origin.get('sha256') == expected[origin['file']] and _HEX.fullmatch(origin['sha256']) and
                row.get('snapshot_sha256') == origin['sha256'] and row.get('exact_original_pin') is True,
                'unregistered or mismatched original source snapshot pin')
        original, content = Path(origin['file']), Path(row.get('snapshot_file', ''))
        require(origin['file'] not in seen and str(content) not in content_paths,
                'duplicate or conflicting source snapshot identity')
        seen.add(origin['file']); content_paths.add(str(content))
        require(content == SOURCE_SNAPSHOT_ROOT / original.name and original != content and
                original.resolve(strict=True) == original and content.resolve(strict=True) == content and
                original.is_file() and content.is_file(), 'source snapshot locator escapes the finite archive scope')
        for path, field in ((original, 'original_metadata'), (content, 'snapshot_metadata')):
            metadata = row.get(field)
            require(isinstance(metadata, dict) and set(metadata) == set(source_metadata(path)) and
                    all(type(item) is int for item in metadata.values()) and source_metadata(path) == metadata,
                    'source snapshot ' + field + ' changed')
        require(row.get('snapshot_bytes') == row['snapshot_metadata']['size'], 'source snapshot byte count differs')
        checked({'file': str(content), 'sha256': origin['sha256']})
        require(source_metadata(original) == row['original_metadata'] and
                source_metadata(content) == row['snapshot_metadata'], 'source snapshot metadata changed during content read')
        if watched is not None:
            watched[str(content)] = origin['sha256']
    require(seen == set(expected), 'source snapshot transport omits registered origins')
    if watched is not None:
        watched[str(checked(value))] = value['sha256']
    return {'proof': deepcopy(value), 'rows': deepcopy(proof['rows']),
            'origin_content_read': False, 'snapshot_content_sha256_verified': True,
            'original_path_and_historical_content_identity_preserved': True}


def source_pdf_content_transport(request, source_files, watched=None):
    """Only the eight registered PDF evidence pins; no origin byte reads."""
    value = request.get('source_pdf_content_snapshots')
    if value is None:
        return None
    require(isinstance(value, dict) and set(value) == {'file', 'sha256'}, 'PDF snapshot proof needs an exact pin')
    proof = read_json(value)
    require(proof.get('schema') == 'residual-source-pdf-exact-snapshots.v1' and
            proof.get('readonly_originals') is True and proof.get('original_sources_modified') is False and
            proof.get('verified_local_snapshot_content') is True and proof.get('all_exact') is True and
            proof.get('total') == proof.get('expected_total') == 8 and
            isinstance(proof.get('rows'), list) and len(proof['rows']) == 8, 'PDF snapshot proof scope differs')
    expected = {path: checksum for path, checksum in source_files.items()
        if Path(path).parent == SOURCE_PDF_ROOT and re.fullmatch(r'\d{4}-\d{2}\.pdf', Path(path).name)}
    require(len(expected) == 8, 'PDF transport requires all eight registered writer PDF pins')
    seen, content_paths = set(), set()
    for row in proof['rows']:
        origin = row.get('original_source', {})
        require(set(origin) == {'file', 'sha256'} and origin.get('file') in expected and
                origin.get('sha256') == expected[origin['file']] and _HEX.fullmatch(origin['sha256']) and
                row.get('snapshot_sha256') == origin['sha256'] and row.get('exact_original_pin') is True and
                type(row.get('origin_content_read_claim')) is bool,
                'unregistered or mismatched original PDF snapshot pin')
        original, content = Path(origin['file']), Path(row.get('snapshot_file', ''))
        require(origin['file'] not in seen and str(content) not in content_paths,
                'duplicate or conflicting PDF snapshot identity')
        seen.add(origin['file']); content_paths.add(str(content))
        require(content == SOURCE_PDF_SNAPSHOT_ROOT / (origin['sha256'] + '.pdf') and original != content and
                original.resolve(strict=True) == original and content.resolve(strict=True) == content and
                original.is_file() and content.is_file(), 'PDF snapshot locator escapes the finite PDF scope')
        for path, field in ((original, 'original_metadata'), (content, 'snapshot_metadata')):
            metadata = row.get(field)
            require(isinstance(metadata, dict) and set(metadata) == set(source_metadata(path)) and
                    all(type(item) is int for item in metadata.values()) and source_metadata(path) == metadata,
                    'PDF snapshot ' + field + ' changed')
        require(row.get('snapshot_bytes') == row['snapshot_metadata']['size'], 'PDF snapshot byte count differs')
        checked({'file': str(content), 'sha256': origin['sha256']})
        require(source_metadata(original) == row['original_metadata'] and
                source_metadata(content) == row['snapshot_metadata'], 'PDF snapshot metadata changed during content read')
        if watched is not None:
            watched[str(content)] = origin['sha256']
    require(seen == set(expected), 'PDF snapshot transport omits registered origins')
    if watched is not None:
        watched[str(checked(value))] = value['sha256']
    return {'proof': deepcopy(value), 'rows': deepcopy(proof['rows']), 'domain': 'registered_firecrawl_pdf_evidence',
            'origin_content_read': False, 'snapshot_content_sha256_verified': True,
            'original_path_and_historical_content_identity_preserved': True}


def native_alias_content_transport(request, transport, watched=None):
    """Keep the approved alias proof byte-exact except its one content locator/seal."""
    value = request.get('native_source_aliases_content_transport')
    if value is None:
        require(transport is None or not request.get('native_source_aliases'),
                'source snapshots require an explicit inherited alias locator bridge')
        return None
    require(transport is not None and isinstance(value, dict) and
            set(value) == {'original_ledger', 'transported_ledger'} and
            value['transported_ledger'] == request.get('native_source_aliases'), 'alias content transport binding differs')
    original_path, transported_path = (checked(value[name]) for name in ('original_ledger', 'transported_ledger'))
    old_raw, new_raw = original_path.read_bytes(), transported_path.read_bytes()
    old, new = json.loads(old_raw), json.loads(new_raw)
    require(old.get('schema') == 'native-reviewed-jump-alias-ledger.v1', 'alias content transport schema differs')
    native_api._sealed(old, 'ledger_sha256'); native_api._sealed(new, 'ledger_sha256')
    source = old['source_files']['structured_source']
    matches = [row for row in transport['rows'] if row['original_source'] ==
               {'file': source['file'], 'sha256': source['sha256']}]
    require(len(matches) == 1 and matches[0]['snapshot_bytes'] == source['bytes'], 'alias source is outside registered snapshots')
    row = matches[0]
    expected = deepcopy(old)
    expected['source_files']['structured_source']['file'] = row['snapshot_file']
    expected.pop('ledger_sha256')
    expected['ledger_sha256'] = sd._sha(sd._json(expected))
    require(new == expected, 'alias transport changed semantics or other source locators')
    old_locator, new_locator = (json.dumps(path, ensure_ascii=False).encode() for path in (source['file'], row['snapshot_file']))
    old_seal, new_seal = (json.dumps(data['ledger_sha256']).encode() for data in (old, new))
    require(old_raw.count(old_locator) == old_raw.count(old_seal) == 1,
            'alias locator/seal replacement must be unique')
    require(new_raw == old_raw.replace(old_locator, new_locator).replace(old_seal, new_seal),
            'alias transport changes bytes outside its locator and seal')
    require(new_raw.replace(new_locator, old_locator).replace(new_seal, old_seal) == old_raw,
            'alias content locator inverse differs')
    if watched is not None:
        for capture in value.values():
            watched[str(checked(capture))] = capture['sha256']
    return {**deepcopy(value), 'original_structured_source': deepcopy(source),
            'snapshot_structured_source': deepcopy(new['source_files']['structured_source']),
            'all_semantic_fields_unchanged': True, 'all_other_ledger_bytes_unchanged': True,
            'exact_original_ledger_inverse': True}


def database_stat(path):
    value = Path(path).stat()
    return {name: getattr(value, 'st_' + name) for name in ('dev', 'ino', 'size', 'mtime_ns', 'ctime_ns')}


def checked_database(value):
    require(isinstance(value, dict) and isinstance(value.get('file'), str)
            and isinstance(value.get('stat'), dict) and value['stat'], 'database checkpoint lacks its stat')
    path = Path(value['file']).resolve(strict=True)
    require(path.is_file(), 'database is not a regular file')
    require(not any(Path(str(path) + suffix).exists() for suffix in ('-wal', '-shm', '-journal')),
            'checkpoint database must be standalone and committed')
    actual = database_stat(path)
    names = {'bytes': 'size', 'inode': 'ino', 'device': 'dev', **{key: key for key in actual}}
    require(all(key in names and actual[names[key]] == expected for key, expected in value['stat'].items()),
            'checkpoint database stat changed')
    return path, actual


def owned_readonly(path):
    """Certified standalone files must not acquire WAL/SHM/recovery sidecars."""
    db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro&immutable=1', uri=True)
    db.execute('PRAGMA query_only=ON')
    db.execute('PRAGMA foreign_keys=ON')
    return db


def snapshot(db, book, card, sid, checksum, *, active=False):
    saved = db.execute('SELECT payload FROM snapshots WHERE id=? AND book_id=? AND card_id=?',
                       (sid, book, card)).fetchone()
    require(saved is not None, 'exact immutable snapshot is absent')
    data = json.loads(saved[0])
    require(digest(data) == checksum and data.get('snapshot_id') == sid and
            data.get('book_id') == book and data.get('card_id') == card, 'snapshot payload binding differs')
    if active:
        require(db.execute('SELECT snapshot_id FROM active_snapshots WHERE book_id=? AND card_id=?',
                           (book, card)).fetchone() == (sid,), 'candidate active snapshot differs')
    return data


def local_url(value, web_root):
    parsed = urlsplit(value)
    require(isinstance(value, str) and parsed.path.startswith('/') and not parsed.scheme and
            not parsed.netloc and not parsed.query and not parsed.fragment and '%' not in value and
            '\\' not in value and not re.search(r'[\x00-\x20\x7f]', value), 'unsafe local preview URL')
    path = (web_root / parsed.path.lstrip('/')).resolve(strict=True)
    require(path.is_relative_to(web_root), 'preview URL escapes the web root')
    return path


class Shell(HTMLParser):
    def __init__(self, page):
        super().__init__()
        self.catalogs, self.scripts = [], []
        self.feed(page)

    def handle_starttag(self, tag, pairs):
        require(len(dict(pairs)) == len(pairs), 'duplicate shell attributes')
        attrs = dict(pairs)
        if 'data-catalog-url' in attrs:
            self.catalogs.append(attrs['data-catalog-url'])
        if tag == 'script' and attrs.get('src', '').endswith('/library-preview.js'):
            self.scripts.append(attrs['src'])


def load_book(book, web_root, runtime):
    shell_path = checked(book['entry'])
    catalog_path = checked(book['catalog'])
    page = shell_path.read_text()
    parsed = Shell(page)
    require(len(parsed.catalogs) == len(parsed.scripts) == 1, 'shell needs one exact catalog/runtime binding')
    require(local_url(parsed.catalogs[0], web_root) == catalog_path, 'shell/catalog binding differs')
    # Runtime is inherited as one pinned shared asset, including all its guards,
    # fine/bank/history/grouping handlers and sidecar hashes.
    require(local_url(parsed.scripts[0], web_root) == runtime, 'shell/runtime binding differs')
    catalog = read_json(book['catalog'])
    require(catalog.get('schema') == 'anki-web-catalog.v1' and isinstance(catalog.get('cards'), list)
            and isinstance(catalog.get('decks'), list), 'unknown catalog schema')
    rows = catalog['cards']
    require(len({row['id'] for row in rows}) == len(rows), 'duplicate catalog card')
    require(len(rows) == book['expected_cards'] == catalog['counts']['cards'], 'catalog card count changed')
    require(sum(row['exampleCount'] for row in rows) == catalog['counts']['examples'], 'catalog example count differs')
    assigned = []
    for deck in catalog['decks']:
        require(deck['count'] == len(deck['cardIds']), 'deck count differs')
        assigned.extend(deck['cardIds'])
    require(len(assigned) == len(set(assigned)) == len(rows) and set(assigned) == {row['id'] for row in rows},
            'catalog deck membership differs')
    return page, catalog


def rewrite_shell(page, catalog_url, runtime_url=None):
    parsed = Shell(page)
    require(len(parsed.catalogs) == 1, 'catalog attribute is not unique')
    old = 'data-catalog-url="' + html.escape(parsed.catalogs[0], quote=True) + '"'
    new = 'data-catalog-url="' + html.escape(catalog_url, quote=True) + '"'
    require(page.count(old) == 1, 'catalog binding is not an exact unique attribute')
    result = page.replace(old, new, 1)
    inverse = result.replace(new, old, 1)
    if runtime_url:
        require(len(parsed.scripts) == 1, 'runtime attribute is not unique')
        old_script = 'src="' + html.escape(parsed.scripts[0], quote=True) + '"'
        new_script = 'src="' + html.escape(runtime_url, quote=True) + '"'
        require(result.count(old_script) == 1, 'runtime binding is not exact')
        result = result.replace(old_script, new_script, 1)
        inverse = result.replace(new_script, old_script, 1).replace(new, old, 1)
    require(inverse == page, 'shell inverse differs')
    return result


def runtime_overlay(raw, output_url):
    """Add one exact candidate history namespace; preserve all other JS bytes."""
    text = raw.decode('utf-8')
    old = r'/^\/exam-usage-policy-20261012\/full-(2026|2027)-v4\/history\/[a-f0-9]{64}\.html$/.test(url.pathname),'
    require(text.count(old) == 1, 'accepted inline history guard is not unique')
    pattern = re.escape(output_url).replace('/', r'\/') + r'\/(redbook|redbook2027)\/history\/[a-f0-9]{64}\.html$'
    new = '(' + old[:-1] + ' || /^' + pattern + '/.test(url.pathname)),'
    revised = text.replace(old, new, 1)
    edits = [
        ('projectionHandle = null, bankHandle = null, groupHandle = null;',
         'projectionHandle = null, bankHandle = null, groupHandle = null, residualHandle = null;'),
        ('    function clearHandles() {\n', '    function clearHandles() {\n      if (residualHandle) residualHandle.dispose(); residualHandle = null;\n'),
        ('        groupHandle = window.AnkiSameSenseGroupRuntime.install(cardDocument);',
         '        groupHandle = window.AnkiSameSenseGroupRuntime.install(cardDocument);\n        residualHandle = window.AnkiResidualReviewedChunkRuntime.install(cardDocument);'),
    ]
    for before, after in edits:
        require(revised.count(before) == 1, 'residual runtime lifecycle hook is not unique')
        revised = revised.replace(before, after, 1)
    inverse = revised
    for before, after in reversed(edits):
        require(inverse.count(after) == 1, 'residual runtime inverse hook is not unique')
        inverse = inverse.replace(after, before, 1)
    require(inverse.replace(new, old, 1) == text, 'shared runtime inverse differs')
    return (RESIDUAL_KEYBOARD + revised).encode(), {'original_guard': old, 'new_guard': new,
        'keyboard_helper_sha256': sf._sha(RESIDUAL_KEYBOARD), 'lifecycle_edits': edits, 'inverse_exact': True}


def presentation(data, adapter=None, *, display_updates=None):
    updates = (data.get('exam_usage_policy', {}).get('residual_display_updates', [])
               if display_updates is None else display_updates)
    require(isinstance(updates, list), 'reviewed display ledger must be an array')
    if not updates:
        return deepcopy(data)
    require(adapter is not None, 'reviewed display updates need the pinned writer presentation adapter')
    view = (adapter(deepcopy(data)) if display_updates is None else
            adapter(deepcopy(data), display_updates=deepcopy(updates)))
    require(isinstance(view, dict), 'presentation adapter returned no record')
    # A presentation adapter can modify only display fields. Assignments,
    # meanings, raw source positions and occurrence/snapshot identities survive.
    old, new = deepcopy(data), deepcopy(view)
    for record in (old, new):
        for row in record.get('occurrences', []):
            row.pop('display', None)
    require(old == new, 'presentation adapter changed certified source/meaning/count data')
    return view


def load_adapter(pin_value):
    if pin_value is None:
        return None
    path = checked(pin_value)
    require(path.suffix == '.py' and path.parent in {ROOT / 'scripts', ROOT / 'anki_pipeline'} and
            'residual' in path.stem, 'presentation adapter must be the approved repository residual module')
    package = 'anki_pipeline' if path.parent == ROOT / 'anki_pipeline' else 'scripts'
    spec = importlib.util.spec_from_file_location(package + '._residual_preview_adapter', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    require(callable(getattr(module, 'presentation_record', None)), 'writer presentation_record API is absent')
    return module.presentation_record


def _span(value, text):
    require(isinstance(value, (list, tuple)) and len(value) == 2 and
            all(type(offset) is int for offset in value) and 0 <= value[0] < value[1] <= len(text),
            'reviewed presentation range is invalid')


def keyboard_chunks(fragment, view, first_id=0):
    """Reuse the inherited single capture keyboard bridge for new fine spans."""
    alignments = (view.get('alignment') or {}).get('alignments', [])
    english, chinese = view['english'], view['translation']
    def annotate(match):
        tag = match[0]
        ids = re.search(r'data-chunk-ids="([0-9 ]+)"', tag)
        if not ids:
            return tag
        whole = re.search(r'data-chunk-sentence-ids="([0-9 ]+)"', tag)
        excluded = set(whole[1].split()) if whole else set()
        eligible = [int(identity) - first_id for identity in ids[1].split() if identity not in excluded]
        require(all(0 <= index < len(alignments) for index in eligible), 'rendered fine ID has no reviewed alignment')
        if not eligible:
            return tag
        finest = min(eligible, key=lambda index: alignments[index]['en'][1] - alignments[index]['en'][0])
        chunk = alignments[finest]
        title = english[slice(*chunk['en'])] + ' ↔ ' + ' / '.join(chinese[slice(*span)] for span in chunk['zh'])
        return tag[:-1] + ' data-reviewed-chunk-projection="residual" tabindex="0" title="' + html.escape(title, quote=True) + '">'
    return re.sub(r'<span\b[^>]*\bclass="card-chunk(?: [^"]*)?"[^>]*>', annotate, fragment)


def finest_target_ids(en_chunks, alignment, targets):
    whole = {index for index, chunk in enumerate((alignment or {}).get('alignments', []))
             if chunk.get('note', '').startswith('整句对应：')}
    fine = [span for span in en_chunks if span[2] not in whole]
    return set().union(*(_target_chunk_ids(fine, target) for target in targets))


def validate_presentation_view(old, view):
    require(isinstance(view, dict) and isinstance(view.get('english'), str) and
            isinstance(view.get('translation'), str), 'reviewed presentation has no exact bilingual text')
    unsigned = deepcopy(view)
    claimed = unsigned.pop('display_hash', None)
    require(claimed == digest(unsigned), 'reviewed presentation hash differs')
    authority = view.get('residual_optimization')
    require(isinstance(authority, dict) and isinstance(authority.get('before'), dict) and
            isinstance(authority.get('after'), dict) and authority.get('before_sha256') == digest(authority['before']) and
            authority.get('after_sha256') == digest(authority['after']), 'new presentation ledger hashes differ')
    require(all(authority['before'].get(key) == old.get(key) for key in ('english', 'translation')) and
            all(authority['after'].get(key) == view.get(key) for key in ('english', 'translation', 'alignment')),
            'new presentation lacks the complete exact old/new display binding')
    require(authority.get('source_pins') or authority.get('decision', {}).get('original_source_pins'),
            'new presentation lacks reviewed source pins')
    require(view['english_hash'] == sf._sha(view['english']) and
            view['translation_hash'] == sf._sha(view['translation']), 'new presentation text hashes differ')
    if old['english'] != view['english']:
        require(authority['after'].get('target_range') == view.get('target_range'),
                'changed display English needs an explicit reviewed target coordinate')
    _span(view.get('target_range'), view['english'])
    for answer in view.get('cloze_answers', []):
        _span([answer.get('start'), answer.get('end')], view['english'])
        require(answer.get('word') == view['english'][answer['start']:answer['end']],
                'new presentation cloze answer differs from its exact range')
    # Use the shared renderer's existing exact alignment checks, without
    # pretending that a reviewed residual view is the old v2 source sidecar.
    flat = deepcopy(view)
    flat.pop('display', None)
    return keyboard_chunks(render_sentence_pair(flat), flat)


def _inside_history(node):
    parent = node.parent
    while parent is not None:
        if parent.classes.intersection({'sf-ownership-history', 'sf-archived-example',
                'sf-original-history-panel', 'sf-inline-history', 'sf-group-member-evidence'}):
            return True
        parent = parent.parent
    return False


def _comparison_markup(comparisons, first_id=0):
    if not comparisons:
        return ''
    require(isinstance(comparisons, list), 'reviewed source comparisons must be an array')
    pieces = []
    for comparison in comparisons:
        english, chinese = comparison.get('english'), comparison.get('translation')
        require(isinstance(english, str) and isinstance(chinese, str) and
                comparison.get('english_hash') == sf._sha(english) and
                comparison.get('translation_hash') == sf._sha(chinese), 'source comparison text/hash differs')
        chunks = comparison.get('chunks', [])
        alignments = []
        for chunk in chunks:
            _span(chunk['en'], english)
            require(chunk.get('en_fragment', english[slice(*chunk['en'])]) == english[slice(*chunk['en'])],
                    'source comparison English fragment differs')
            for span in chunk['zh']:
                _span(span, chinese)
            require(chunk.get('zh_fragments', [chinese[slice(*span)] for span in chunk['zh']]) ==
                    [chinese[slice(*span)] for span in chunk['zh']], 'source comparison Chinese fragment differs')
            alignments.append({'en': chunk['en'], 'zh': chunk['zh'], 'relation': chunk.get('relation', 'equivalent')})
        alignment = {'schema': 'codex-sentence-alignment.v1', 'englishHash': sf._sha(english),
            'translationHash': sf._sha(chinese), 'alignments': alignments}
        example = {'text': english, 'translation': chinese, 'translation_source': 'codex', 'translation_alignment': alignment}
        en_chunks, zh_chunks, _ = _example_chunk_ranges(example)
        en_chunks = [(left, right, identity + first_id) for left, right, identity in en_chunks]
        zh_chunks = [(left, right, identity + first_id) for left, right, identity in zh_chunks]
        comparison_id = first_id
        first_id += len(alignments)
        target = comparison.get('target_range')
        if target is not None:
            _span(target, english)
        en = _highlight_example(english, '', '', [], target_ranges=[tuple(target)] if target else [],
            chunk_ranges=en_chunks, preserve_source=True)
        zh = _chunk_translation(chinese, zh_chunks)
        comparison_view = {'english': english, 'translation': chinese, 'alignment': alignment}
        en = keyboard_chunks(en, comparison_view, comparison_id)
        zh = keyboard_chunks(zh, comparison_view, comparison_id)
        pieces.append('<details data-reviewed-source-comparison="residual"><summary>原译分块对照</summary>'
            '<div class="sf-sentence-pair example-card"><p class="sf-en">' + en + '</p><p class="sf-zh">' + zh + '</p></div>'
            '<p>' + html.escape(str(comparison.get('reason', ''))) + '</p><details><summary>完整来源依据</summary><pre>'
            + html.escape(canonical(comparison)) + '</pre></details></details>')
    return ''.join(pieces)


def project_displays(page, certified, shown, *, aliases=None):
    """Project only reviewed current pairs; immutable raw jumps never change."""
    old_rows = {row['occurrence_id']: row for row in certified['occurrences']}
    changed = {}
    for row in shown['occurrences']:
        old = old_rows[row['occurrence_id']]
        if row.get('display') != old.get('display'):
            pair = validate_presentation_view(old.get('display'), row['display'])
            require(row['occurrence_id'] in row['display']['residual_optimization'].get('occurrence_ids', []),
                    'new presentation ledger lacks the exact occurrence binding')
            base_id = len((row['display'].get('alignment') or {}).get('alignments', []))
            comparisons = row['display'].get('source_comparisons',
                row['display']['residual_optimization']['after'].get('source_comparisons', []))
            pair = pair[:-6] + _comparison_markup(comparisons, base_id) + '</div>'
            changed[row['occurrence_id']] = old, row['display'], pair
    if not changed:
        return page, [], {'changed_occurrences': 0, 'native_pairs': 0, 'sf_pairs': 0}
    parser = native_api._Offsets(page, aliases or {})
    edits, native_count, sf_count, seen_sf = [], 0, 0, set()
    for node in parser.root.walk():
        if _inside_history(node):
            continue
        if 'sf-example' in node.classes and node.attrs.get('data-sf-occurrence-id') in changed:
            identity = node.attrs['data-sf-occurrence-id']
            pairs = [child for child in node.children if 'sf-sentence-pair' in child.classes]
            require(len(pairs) == 1 and pairs[0].end is not None, 'current SF pair is not unique')
            old, view, pair = changed[identity]
            parsed_old = sd._Tree(page[pairs[0].start:pairs[0].end]).root
            en = sd._descendant(parsed_old, 'sf-en')
            zh = sd._descendant(parsed_old, 'sf-zh')
            # The shared renderer represents exact source newlines with <br>.
            # Its native reader replays those codepoints without normalization.
            require(en is not None and zh is not None and
                    sd._text_and_ranges(en)[0] == old['display']['english'] and
                    sd._text_and_ranges(zh)[0] == old['display']['translation'],
                    'current SF display text binding differs: ' + certified['book_id'] + '/' +
                    certified['card_id'] + '/' + identity)
            edits.append((pairs[0].start, pairs[0].end, pair))
            seen_sf.add(identity)
            sf_count += 1
        if node.tag != 'li' or 'example-card' not in node.classes or node.end is None:
            continue
        fragment = page[node.start:node.end]
        natives = sd._native_examples(fragment, aliases or {})
        require(len(natives) == 1, 'native pair is not unique')
        native = natives[0]
        matches = [(old, view) for old, view, _ in changed.values()
            if native_api._view(old, native, old.get('display')) is not None]
        if not matches:
            continue
        view = deepcopy(matches[0][1])
        require(all(other['english'] == view['english'] and other['translation'] == view['translation'] and
                    other.get('alignment') == view.get('alignment') and other.get('cloze_answers') == view.get('cloze_answers')
                    for _, other in matches), 'same native sentence has conflicting reviewed views')
        # Preserve all physical marks within this native example, requiring an
        # unchanged English coordinate system when an unmodified sibling exists.
        targets = {tuple(other['target_range']) for _, other in matches}
        matched_old_targets = {tuple(old['display']['target_range']) for old, _ in matches}
        siblings = set(map(tuple, native['target_ranges'])) - matched_old_targets
        require(not siblings or native['english'] == view['english'], 'changed English cannot guess sibling target offsets')
        targets.update(siblings)
        example = {'text': view['english'], 'translation': view['translation']}
        if view.get('alignment') is not None:
            example.update(translation_source='codex', translation_alignment=view['alignment'])
        en_chunks, zh_chunks, _ = _example_chunk_ranges(example)
        selected = finest_target_ids(en_chunks, view.get('alignment'), targets)
        en_html = _annotate_sentence_chunks(_accent_chunks(_highlight_example(view['english'], '', '', view.get('cloze_answers', []),
            target_ranges=sorted(targets), chunk_ranges=en_chunks, preserve_source=True), selected), view.get('alignment'))
        zh_html = _annotate_sentence_chunks(_accent_chunks(_chunk_translation(view['translation'], zh_chunks), selected), view.get('alignment'))
        en_html, zh_html = keyboard_chunks(en_html, view), keyboard_chunks(zh_html, view)
        en, zh = node.descendant('example-text'), node.descendant('example-translation')
        require(en.closed is not None and zh.closed is not None, 'native display boundaries are incomplete')
        labels = [part for part in zh.walk() if 'translate-tag' in part.classes]
        require(len(labels) <= 1 and (not labels or labels[0].parent is zh), 'native translation label boundary differs')
        left = labels[0].end if labels else zh.opened
        if page[left:zh.closed].startswith(' '):
            left += 1
        edits.extend([(en.opened, en.closed, native_api._source_classes(en_html, aliases or {})),
                      (left, zh.closed, native_api._source_classes(zh_html, aliases or {}))])
        comparison = _comparison_markup(view.get('source_comparisons',
                view['residual_optimization']['after'].get('source_comparisons', [])),
            max([len((view.get('alignment') or {}).get('alignments', [])) - 1,
                 *[int(value) for values in re.findall(r'data-chunk-ids="([0-9 ]+)"', fragment)
                   for value in values.split()]]) + 1)
        if comparison:
            edits.append((node.closed, node.closed, comparison))
        native_count += 1
    require(seen_sf == set(changed), 'reviewed display lacks its exact current SF occurrence')
    revised, inverse = preview.apply_edits(page, edits)
    require(preview.restore_edits(revised, inverse) == page, 'reviewed display inverse differs')
    return revised, inverse, {'changed_occurrences': len(changed), 'native_pairs': native_count, 'sf_pairs': sf_count}


def history_documents(db, data):
    """Read only exact old history documents; never recompute their authority."""
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    result = {}
    for row in data['occurrences']:
        for history in row.get('ownership_history', []):
            ref = history['source_history_ref']
            if ref['file'] in result:
                continue
            matches = []
            for table in ('exam_usage_history_documents', 'exam_usage_owner_patch_documents'):
                if table in tables:
                    matches.extend(db.execute('SELECT source_url,original_html FROM ' + table +
                        ' WHERE book_id=? AND card_id=? AND parent_snapshot_id=? AND document_sha256=?',
                        (history['book_id'], history['source_card_id'], history['source_parent_snapshot_id'], ref['sha256'])))
            require(matches and len(set(matches)) == 1, 'old history has no unique immutable complete document')
            url, original = matches[0]
            document = preview._history_document(history['source_word'], history['source_parent_snapshot_id'], url, original)
            require(sf._sha(document) == ref['sha256'], 'immutable history document SHA differs')
            result[ref['file']] = {'reference': deepcopy(ref), 'document_html': document, 'original_html': original,
                'original_html_sha256': sf._sha(original), 'inline_history_ids': [history['history_id']]}
    return result


def native_variant_transport(request, watched=None, observation=None):
    """Carry the finite approved addendum as a pin, never as a new alias rule."""
    value = request.get('native_variant_addendum')
    if value is None:
        return None
    require(isinstance(value, dict) and set(value) == {'file', 'sha256'},
            'native variant addendum requires an explicit file/SHA pin')
    body = read_json(value)
    owner.load_native_variant_addendum(value)  # Reuse every existing source/scope guard.
    captures = [value, body['frozen_primary_decisions_pin']]
    unread = []
    for alias in body['aliases']:
        for field in ('rawfile', 'target_rawfile'):
            if field not in alias:
                continue
            capture = alias[field]
            actual = Path(capture['file']).stat()
            # macOS SF_DATALESS: preserve the frozen reference without causing
            # CloudDocs hydration. The unchanged loader validates these exact
            # UTF-8 raw bytes through their indexed native SQLite entry.
            if getattr(actual, 'st_flags', 0) & 0x40000000:
                unread.append({'reference': deepcopy(capture), 'pin_basis': 'indexed_native_entry_utf8_sha256',
                    'file_bytes_read': False})
            else:
                captures.append(capture)
        captures.extend({'file': file, 'sha256': checksum} for file, checksum in alias.get('parser_pins', {}).items())
    for capture in captures:
        path = str(checked(capture))
        if watched is not None:
            require(path not in watched or watched[path] == capture['sha256'], 'native variant watched pin conflicts')
            watched[path] = capture['sha256']
    if observation is not None:
        observation.update({'pin': deepcopy(value), 'unread_dataless_references': unread,
            'source_entry_guard': 'Unchanged finite addendum loader replayed at start and end; exact indexed raw entries and frozen decisions.'})
    return deepcopy(value)


def native_history_metadata(prepared, db, ledger, *, target_urls=None, variant_pin=None, documents=None):
    """Replay actual per-row native history guards and collect every failure."""
    if not any(row.get('ownership_history') for row in prepared.get('occurrences', [])):
        return {'rows': len(prepared['occurrences']), 'history_rows': 0, 'histories': 0,
                'verified_history_rows': 0, 'failures': []}
    rows = native_api._rows(prepared)
    failures, verified, histories = [], 0, 0
    supplied = ledger.get('render_context', {}).get('ownership_history_documents', {})
    for identity, row in rows.items():
        history = row.get('ownership_history', [])
        if not history:
            continue
        histories += len(history)
        try:
            bound = (history_documents(db, {'occurrences': [row]}) if documents is None else
                {key: value for key, value in documents.items() if any(h['source_history_ref']['file'] == key for h in history)})
            require(all(key not in bound or value == bound[key] for key, value in supplied.items()),
                    'native history overlay conflicts with immutable document')
            bound.update(supplied)
            if variant_pin is not None:
                require('__owner_recovery_native_variant_addendum__' not in bound or
                    bound['__owner_recovery_native_variant_addendum__'] == variant_pin, 'native variant transport conflicts')
                bound['__owner_recovery_native_variant_addendum__'] = deepcopy(variant_pin)
            native_api._native_histories(prepared, {identity: row}, documents=bound, target_urls=target_urls)
            verified += 1
        except Exception as error:
            failures.append({'occurrence_id': identity, 'history_ids': [h.get('history_id') for h in history],
                'match_kinds': [h.get('match_kind', 'exact_span') for h in history],
                'error_type': type(error).__name__, 'error': str(error)})
    return {'rows': len(rows), 'history_rows': verified + len(failures), 'histories': histories,
            'verified_history_rows': verified, 'failures': failures}


def native_history_helper_binding():
    """Bind just the reused metadata functions and every unchanged core dependency."""
    source = Path(__file__).read_text()
    names = {'history_documents', 'native_variant_transport', 'native_history_metadata'}
    functions = {node.name: ast.get_source_segment(source, node) for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef) and node.name in names}
    require(set(functions) == names, 'native metadata helper scope is incomplete')
    dependencies = [Path(module.__file__) for module in (native_api, owner, sd, sf, preview)]
    dependencies.append(ROOT / 'anki_pipeline/ownership_history.py')
    return {'helper_sha256': digest(functions), 'core_pins': [pin(path) for path in dependencies]}


def native_history_context(request):
    return {field: deepcopy(request.get(field)) for field in
        ('checkpoint', 'books', 'native_variant_addendum', 'presentation_adapter', 'exam_base_url')}


def reuse_native_history_preflight(request, checkpoint, watched):
    value = request.get('native_history_preflight')
    if value is None:
        return None
    cache = read_json(value)
    require(cache.get('schema') == 'native-history-preflight-cache.v1' and
        cache.get('context') == native_history_context(request) and cache.get('helper_binding') == native_history_helper_binding(),
        'native history cached context/helper binding differs')
    evidence = read_json(cache['evidence'])
    require(evidence.get('schema') == 'native-ownership-history-metadata-preflight.v1' and
        evidence.get('status') == 'PASS' and evidence.get('failures') == [] and
        evidence.get('database_stat_before') == evidence.get('database_stat_after') == cache.get('database_stats'),
        'native history cache lacks its successful actual evidence')
    certified = read_json(evidence['request'])
    require(native_history_context(certified) == cache['context'], 'native history evidence request differs')
    stats = evidence['stats']
    require(stats.get('checked_cards') == len(checkpoint['cards']) and stats.get('checked_sides') == 2 * len(checkpoint['cards']) and
        stats.get('verified_history_rows') == stats.get('history_rows') == stats.get('histories'),
        'native history cached coverage differs')
    expected = [item[field] for item in checkpoint['cards'] for field in ('before_payload_file', 'payload_file', 'ledger_file')]
    require(cache.get('payload_pins') == expected, 'native history cached input inventory differs')
    for field, saved in zip(('parent_database', 'database'), cache['database_stats']):
        require(checked_database(checkpoint[field])[1] == saved, 'native history cached database stat differs')
    for capture in [value, cache['evidence'], evidence['request'], *expected, *evidence['watched_pins'],
                    *cache['helper_binding']['core_pins']]:
        watched[str(checked(capture))] = capture['sha256']
    native_variant_transport(request, watched)  # Exact indexed native entries, including the dataless reference.
    return {**stats, 'failures': [], 'reused_evidence': deepcopy(cache['evidence']),
        'reused_cache': deepcopy(value), 'helper_sha256': cache['helper_binding']['helper_sha256']}


def validate_auxiliary(entity, usage):
    require(entity.get('schema') == 'residual-auxiliary-lexeme.v1' and entity.get('learning_card') is False and
            entity.get('canonical_owner') is True and entity.get('native_definition') and entity.get('validated_source_evidence'),
            'auxiliary entry is not a sourced non-learning lexical entity')
    modern = 'definition_variants' in entity
    identity_kind = entity.get('canonical_identity_kind', entity.get('kind', 'dictionary_sense'))
    if 'canonical_identity_kind' in entity:
        require(identity_kind == 'lexical_owner', 'unsupported canonical auxiliary identity kind')
    identity = (['residual-lexical-owner.v1', entity['lemma'].casefold(), _pos(entity['pos']), identity_kind]
                if modern else [entity['lemma'].casefold(), entity['pos'], entity['validated_source_evidence']])
    require(entity['entity_id'] == digest(identity),
            'auxiliary lexical entity fingerprint differs')
    require(usage.get('schema') == 'residual-auxiliary-usage.v1' and usage.get('entity_id') == entity['entity_id'] and
            usage.get('learning_card') is False and usage.get('canonical_owner') is True and usage.get('status') == 'reviewed'
            and usage.get('physical_count') == 1 and usage.get('book_id') in {'redbook', 'redbook2027'},
            'auxiliary usage has no exact canonical physical owner')
    unsigned = {key: value for key, value in usage.items() if key not in {'review_seal', 'entity'}}
    require(usage.get('review_seal') == digest(unsigned) and usage.get('history_sha256') == digest(usage['origins']),
            'auxiliary complete usage/history seal differs')
    row = usage['row']
    _span(row['target_range'], row['english'])
    require(row['english_hash'] == sf._sha(row['english']) and row['translation_hash'] == sf._sha(row['translation']) and
            usage['occurrence_id'] == row['occurrence_id'] == digest([row['paper_id'], row['physical_source'], row['target_range']]),
            'auxiliary raw source/canonical full token differs')
    require(usage.get('origins'), 'auxiliary meaning/source origins differ')
    auxiliary_definition(entity, usage)
    for span in row['translation_ranges']:
        _span(span, row['translation'])
    require(usage.get('explanation_placement') == 'within_correct_target_sentence',
            'auxiliary transfer evidence must stay in its actual sentence')


def auxiliary_definition(entity, usage):
    if 'definition_variants' not in entity:
        require(usage['sense_id'] == digest([entity['entity_id'], entity['native_definition']]),
                'legacy auxiliary meaning/source differs')
        return entity
    variants = entity['definition_variants']
    require(isinstance(variants, list) and variants, 'auxiliary definition variants are absent')
    index = {}
    for variant in variants:
        identity = digest([variant['native_definition'], variant['validated_source_evidence']])
        require(variant['definition_id'] == identity and identity not in index,
                'auxiliary exact definition variant fingerprint differs')
        if entity.get('canonical_identity_kind') == 'lexical_owner':
            require(variant.get('kind') in {'dictionary_sense', 'contextual_usage'} and
                    variant.get('is_dictionary_native') is (variant['kind'] == 'dictionary_sense'),
                    'auxiliary native/context flags must belong to the exact definition')
        index[identity] = variant
    selected = usage.get('selected_definition_id')
    require(selected in index and usage['sense_id'] == digest([entity['entity_id'], selected]),
            'auxiliary usage lacks its exact selected meaning variant')
    supplied = usage.get('definition_variants')
    require(isinstance(supplied, list) and supplied and index[selected] in supplied and
            all(index.get(variant['definition_id']) == variant for variant in supplied),
            'auxiliary usage definition provenance differs from its entity')
    variant = index[selected]
    require(all(usage.get(field) == variant.get(field) for field in ('meaning_zh', 'meaning_en')),
            'auxiliary selected meaning text differs')
    selected_entity = {**entity, **variant}
    if variant['native_definition'] != entity['native_definition']:
        selected_entity['dictionary_evidence'] = {}  # Never label another variant with the first source.
    return selected_entity


def auxiliary_view(usage):
    """A reviewed completed view remains separate from the canonical physical row."""
    row = usage['row']
    view = usage.get('presentation')
    if view is None:
        return {**deepcopy(row), 'cloze_answers': [], 'source_comparisons': []}
    entry = view.get('residual_display_update')
    require(isinstance(entry, dict) and entry.get('before_sha256') == digest(entry['before']) and
            entry.get('after_sha256') == digest(entry['after']), 'auxiliary presentation ledger hashes differ')
    require(view.get('physical_occurrence_id') == usage['occurrence_id'] and
            all(view.get(field) == entry['after'].get(field) for field in
                ('english', 'english_hash', 'translation', 'translation_hash', 'alignment', 'source_comparisons')) and
            view['english_hash'] == sf._sha(view['english']) and view['translation_hash'] == sf._sha(view['translation']),
            'auxiliary presentation/current text binding differs')
    require(entry.get('decision', {}).get('original_source_pins'), 'auxiliary presentation lacks reviewed source pins')
    linked = []
    for origin in usage['origins']:
        parent = origin['source_parent_row']
        approved = parent.get('display') or parent
        if any(ref['book_id'] == usage['book_id'] and ref['card_id'] == origin['source_card_id'] and
               ref['occurrence_id'] == parent['occurrence_id'] for ref in entry.get('book_refs', [])):
            require(all(approved.get(field) == entry['before'].get(field) for field in ('english', 'translation')),
                    'auxiliary presentation original display differs')
            linked.append(approved)
    require(linked, 'auxiliary presentation has no exact original occurrence binding')
    # The writer already supplied this range; independently verify its unique,
    # source-preserving transform rather than finding a word in the card.
    target = sd._map_range(row['english'], row['target_range'], view['english'])
    require(target is not None and target == view.get('target_range') and
            row['english'][slice(*row['target_range'])] == view['english'][slice(*target)],
            'auxiliary completed full-lexeme range differs')
    answers = [approved.get('cloze_answers', []) for approved in linked if approved['english'] == view['english']]
    require(not answers or all(answer == answers[0] for answer in answers), 'auxiliary completed cloze evidence conflicts')
    result = {**deepcopy(row), **deepcopy(view), 'cloze_answers': answers[0] if answers else []}
    render_sentence_pair(result)  # Exact Unicode bounds/alignment validation.
    return result


def dictionary_source_names(*values):
    """Names from actual positive source fields; never infer a provider from a URL."""
    result, identities = [], set()
    children = ('selected', 'secondary_bilingual', 'dictionary_explanation', 'new_sense', 'native_definition',
        'native_base_evidence', 'primary_source', 'secondary_source', 'source_ref_pin', 'validated_source_evidence',
        'reused_chinese_source', 'sources')
    def visit(value):
        if isinstance(value, list):
            for item in value:
                visit(item)
            return
        if not isinstance(value, dict):
            return
        name = next((value[key] for key in ('archive_source', 'source_name_zh', 'dictionary', 'name', 'source_name_original')
            if isinstance(value.get(key), str) and value[key] and '语境' not in value[key] and value[key] != 'Context review'), None)
        if not name and value.get('source_type') in {'professional_original', 'exam_context_original'}:
            name = value.get('source_title')
        if name:
            name = re.sub(r'\.mdx$', '', Path(name).name, flags=re.I)
            lower = name.casefold()
            if 'oxford advanced' in lower or lower == 'oald10':
                name = '牛津高阶英汉双解词典'
            elif 'cambridge' in lower:
                name = '剑桥高级学习词典'
            identity = re.split(r'[（(]', name, maxsplit=1)[0]
            if identity not in identities:
                identities.add(identity)
                result.append(name)
        for key in children:
            visit(value.get(key))
    for value in values:
        visit(value)
    return result


def auxiliary_source_label(entity):
    native = entity['native_definition']
    proposal = native.get('new_sense', native)
    contextual = entity.get('kind') == 'contextual_usage' or entity.get('is_dictionary_native') is False
    kind = proposal.get('translation_kind', entity['validated_source_evidence'].get('translation_kind'))
    evidence = entity.get('dictionary_evidence', {})
    selected = evidence.get('selected') if isinstance(evidence, dict) else None
    names = dictionary_source_names(selected, native,
                                   entity['validated_source_evidence'])
    prefix = '；'.join(names) + ' · ' if names else ''
    if contextual or kind == 'contextual_review':
        return prefix + '语境用法（非词典原义）', '完整释义来源与语境审核依据'
    if kind in {'reviewed_translation', 'model_translation'} or proposal.get('chinese_translation_status') == 'model_translation':
        return prefix + '中文补译（原英文词典依据保留）', '原英文词典、双语检索与补译依据'
    if kind in {'cross_dictionary_original', 'original_chinese_reuse'}:
        return prefix + '跨词典原译', '原词典与另一词典原中文来源'
    return prefix + '原译', '原词典完整来源与定义依据'


def render_auxiliary(entity, usages, *, runtime_url, exam_base_url=None):
    """A real lexical entry; never a fake book-unit card or global history page."""
    unique, groups = {}, {}
    for usage in usages:
        validate_auxiliary(entity, usage)
        key = usage['book_id'], usage['occurrence_id']
        require(key not in unique, 'duplicate auxiliary book/canonical token')
        unique[key] = usage
        row = auxiliary_view(usage)
        identity = (row['paper_id'], canonical(row['physical_source']), row['english_hash'], row['translation_hash'],
                    usage['sense_id'], row['source'])
        groups.setdefault(identity, []).append(usage)
    require(usages, 'auxiliary entry has no actual usage')
    physical = {usage['occurrence_id'] for usage in usages}
    years = {}
    for oid in physical:
        usage = next(value for value in usages if value['occurrence_id'] == oid)
        year = int(usage['row']['paper_id'].split(':', 1)[1][:4])
        years[year] = years.get(year, 0) + 1
    source_label, source_details = auxiliary_source_label(entity)
    if entity.get('canonical_identity_kind') == 'lexical_owner':
        source_details = '完整词条来源与审核依据'
    pieces = ['<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
        '<title>' + html.escape(entity['lemma']) + ' · 辅助词条</title><style>body{margin:auto;padding:1rem;max-width:52rem;font:16px/1.7 system-ui;overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-width:100%}details{margin-block:.7rem}.sf-example{margin-block:1rem}.residual-meaning-source{font-size:.875rem;color:#666}.card-chunk-active{background:#fbe995}.sf-target-chunk{background:#fff5ce}mark{background:#ffeb94}[tabindex="0"]:focus-visible{outline:2px solid #1262a3}p{margin-block:.55rem}</style></head><body>',
        '<h1>' + html.escape(entity['lemma']) + '</h1><p>关联词条补充</p>',
        '<p class="residual-word-frequency">真题词频 · ' + str(len(physical)) + '次 / ' +
        html.escape('、'.join(str(year) for year in sorted(years))) + '</p>',
        '<section class="sf-report" data-learning-card="false" data-residual-auxiliary-entry="' + entity['entity_id'] + '">']
    for members in groups.values():
        selected_definition = auxiliary_definition(entity, members[0])
        meaning_source, _ = auxiliary_source_label(selected_definition)
        row = auxiliary_view(members[0])
        require(all(auxiliary_view(member).get('alignment') == row.get('alignment') for member in members),
                'same auxiliary physical sentence has conflicting original fine chunks')
        view = row
        example = {'text': row['english'], 'translation': row['translation']}
        if row.get('alignment') is not None:
            example.update(translation_source='codex', translation_alignment=row['alignment'])
        en_chunks, zh_chunks, _ = _example_chunk_ranges(example)
        targets = sorted({tuple(auxiliary_view(member)['target_range']) for member in members})
        selected = finest_target_ids(en_chunks, row.get('alignment'), targets)
        en = _annotate_sentence_chunks(_accent_chunks(_highlight_example(row['english'], '', '', view['cloze_answers'], target_ranges=targets,
            chunk_ranges=en_chunks, preserve_source=True), selected), row.get('alignment'))
        zh = _annotate_sentence_chunks(_accent_chunks(_chunk_translation(row['translation'], zh_chunks), selected), row.get('alignment'))
        en, zh = keyboard_chunks(en, view), keyboard_chunks(zh, view)
        pieces.append('<article class="sf-example"><p>' + html.escape(entity['pos'] + ' ' + selected_definition['meaning_zh']) +
            '</p><p>' + html.escape(selected_definition.get('meaning_en') or '') + '</p><p class="residual-meaning-source">' +
            html.escape(meaning_source) + '</p><p class="sf-source">' + html.escape(row['source']) + '</p>'
            '<div class="sf-sentence-pair example-card"><p class="sf-en">' + en + '</p><p class="sf-zh">' + zh + '</p></div>')
        if view.get('source_comparisons'):
            first_id = len((row.get('alignment') or {}).get('alignments', []))
            pieces.append(_comparison_markup(view['source_comparisons'], first_id))
        if exam_base_url:
            original = members[0]['row']
            jump = owner.original_paper_jump(original, original['target_range'], exam_base_url)
            pieces.append('<p><a href="' + html.escape(jump['latex_url'], quote=True) + '" target="_blank" rel="noopener">原卷 · LaTeX</a> · '
                '<a href="' + html.escape(jump['full_paper_url'], quote=True) + '" target="_blank" rel="noopener">原卷 · 完整图文</a></p>')
        for member in members:
            label = {'redbook': '2026红宝书', 'redbook2027': '2027红宝书'}[member['book_id']]
            pieces.append('<details class="residual-auxiliary-history" data-book-id="' + member['book_id'] + '"><summary>本句完整原转归依据 · ' + label + '</summary>')
            for origin in member['origins']:
                original = origin['source_parent_row']
                pieces.append('<p>原归属依据：' + html.escape(original.get('reason', '')) + '</p><p>正确词条转归依据：' +
                    html.escape(origin['decision'].get('reason', '')) + '</p><p>原目标范围：' +
                    html.escape(canonical(original['target_range'])) + '；当前完整词条范围：' + html.escape(canonical(member['row']['target_range'])) + '</p>'
                    '<details><summary>完整原双语记录、分块与审核证据</summary><pre>' + html.escape(canonical(origin)) + '</pre></details>')
            pieces.append('</details>')
        pieces.append('</article>')
    pieces.append('</section><details><summary>' + html.escape(source_details) + '</summary><pre>' + html.escape(canonical(entity)) + '</pre></details>'
        '<script src="' + html.escape(runtime_url, quote=True) + '"></script></body></html>')
    return ''.join(pieces), {'entity_id': entity['entity_id'], 'physical_occurrences': len(physical),
        'book_references': len(unique), 'visible_sentences': len(groups), 'learning_card': False}


def auxiliary_links(page, after, urls):
    usages = after.get('exam_usage_policy', {}).get('residual_auxiliary_usages', [])
    if not usages:
        return page, []
    found = {}
    for usage in usages:
        require(usage['entity_id'] in urls, 'source usage has no real auxiliary entity page')
        entity = usage.get('entity')
        require(entity is not None, 'source usage lacks its actual lexical entity')
        validate_auxiliary(entity, usage)
        found[usage['entity_id']] = entity['lemma']
    note = '<p class="residual-entity-links">正确词条：' + '；'.join('<a href="' + html.escape(urls[eid], quote=True) +
        '" target="_blank" rel="noopener">' + html.escape(lemma) + '（辅助词条）</a>' for eid, lemma in sorted(found.items())) + '</p>'
    backs = [node for node in native_api._Offsets(page, {}).root.walk() if node.attrs.get('id') == 'preview-back']
    require(len(backs) == 1 and backs[0].closed is not None, 'source card answer boundary is not unique')
    return preview.apply_edits(page, [(backs[0].closed, backs[0].closed, note)])


def source_auxiliary_cleanup(page, after, *, aliases=None):
    """Remove only exactly source-pinned wrong native marks/pairs now owned by an entity."""
    origins = [origin for usage in after.get('exam_usage_policy', {}).get('residual_auxiliary_usages', [])
               for origin in usage['origins'] if origin['source_card_id'] == after['card_id']]
    if not origins:
        return page, [], 0
    edits, removed = [], 0
    parser = native_api._Offsets(page, aliases or {})
    for node in parser.root.walk():
        if node.tag != 'li' or 'example-card' not in node.classes or node.end is None or _inside_history(node):
            continue
        native = sd._native_examples(page[node.start:node.end], aliases or {})[0]
        bad, alignment = set(), None
        for origin in origins:
            old = origin['source_parent_row']
            approved = old.get('display')
            matched = native_api._view(old, native, approved)
            if matched is not None:
                bad.add(tuple(matched['target_range']))
                alignment = matched.get('alignment')
        targets = set(map(tuple, native['target_ranges']))
        if not (bad & targets):
            continue
        kept = sorted(targets - bad)
        if not kept:
            edits.append((node.start, node.end, ''))
            removed += 1
            continue
        example = {'text': native['english'], 'translation': native['translation']}
        if alignment is not None:
            example.update(translation_source='codex', translation_alignment=alignment)
        en_chunks, _, _ = _example_chunk_ranges(example)
        fragment = _annotate_sentence_chunks(_highlight_example(native['english'], '', '', native['cloze_answers'],
            target_ranges=kept, chunk_ranges=en_chunks, preserve_source=True), alignment)
        en = node.descendant('example-text')
        edits.append((en.opened, en.closed, native_api._source_classes(fragment, aliases or {})))
    result, inverse = preview.apply_edits(page, edits)
    return result, inverse, removed


def definition_evidence(addition):
    if addition.get('kind') != 'contextual_usage':
        return preview.render_append_source_evidence(addition)
    require(addition.get('is_dictionary_native') is False and addition.get('native_base_evidence') and
            addition.get('context_evidence') and addition.get('source_pins') and addition.get('contextual_key'),
            'contextual meaning lacks explicit non-native source/context evidence')
    sense = addition['contextual_sense']
    require(sense.get('kind') == 'contextual_usage' and sense.get('is_dictionary_native') is False,
            'contextual source page cannot claim a native dictionary meaning')
    body = ('<h1>语境用法（非词典原义）</h1><p>词条：' + html.escape(addition['source_headword']) + '</p><p>' +
        html.escape(sense['pos'] + ' ' + sense['text']) + '</p><p>' + html.escape(sense['english']) +
        '</p><p>此补充释义来自逐句审核；原词典基础义、全文理由与来源原样保留。</p><details><summary>完整来源与语境审核依据</summary><pre>' +
        html.escape(canonical(addition)) + '</pre></details>')
    return ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" '
        'content="width=device-width,initial-scale=1"><title>语境用法</title><style>body{margin:auto;padding:1rem;max-width:52rem;'
        'font:16px/1.7 system-ui;overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere;max-width:100%}</style></head><body>' +
        body + '</body></html>')


def phrase_owner_histories(page, after, ledger):
    """Expose sealed source and companion records inside the canonical SF sentence."""
    supplied = ledger.get('companion_replacements', [])
    declared = after.get('exam_usage_policy', {}).get('residual_native_phrase_owners', [])
    actual = [row['semantic_review']['residual_owner_history'] for row in after['occurrences']
              if row.get('semantic_review', {}).get('residual_owner_history')]
    require(all(isinstance(items, list) and len({digest(item) for item in items}) == len(items)
                for items in (supplied, declared, actual)) and
            sorted(canonical(item) for item in supplied) == sorted(canonical(item) for item in declared) ==
            sorted(canonical(item) for item in actual), 'phrase owner history snapshot/ledger differ')
    if not actual:
        return page, []
    index = {row['occurrence_id']: row for row in after['occurrences']}
    parser = native_api._Offsets(page, {})
    edits, seen = [], set()
    for history in actual:
        identity = history['canonical_occurrence_id']
        require(identity in index and identity not in seen and history.get('schema') == 'residual-native-phrase-history.v1' and
                history['history_sha256'] == digest({key: value for key, value in history.items() if key != 'history_sha256'}) and
                history['source_book_id'] == after['book_id'] and history['canonical_owner_card_id'] == after['card_id'],
                'phrase owner canonical history/identity differs')
        row = index[identity]
        originals = []
        for field in ('source_parent_row', 'companion_parent_row'):
            original = history[field]
            require(history[field + '_sha256'] == digest(original), 'phrase complete original record SHA differs')
            if original is None:
                continue
            require(all(original[key] == row[key] for key in ('paper_id', 'physical_source', 'english_hash', 'translation_hash')) and
                    row['target_range'][0] <= original['target_range'][0] < original['target_range'][1] <= row['target_range'][1],
                    'phrase original component is not in this full physical token')
            originals.append((field, original))
        require(originals, 'phrase history lacks its full original records')
        articles = [node for node in parser.root.walk() if 'sf-example' in node.classes and
                    node.attrs.get('data-sf-occurrence-id') == identity and not _inside_history(node)]
        require(len(articles) == 1 and articles[0].closed is not None, 'phrase canonical sentence is absent or duplicated')
        pieces = ['<details class="residual-owner-history" data-history-sha256="' + history['history_sha256'] +
                  '"><summary>本句完整词组转归依据</summary><p>' + html.escape(history['decision']['reason']) + '</p>']
        for field, original in originals:
            label = '原来源词条记录' if field == 'source_parent_row' else '原对应成分记录'
            flat = {key: value for key, value in original.items() if key != 'display'}
            pieces.append('<details class="sf-archived-example"><summary>' + label + '</summary><p class="sf-source">' +
                html.escape(original['source']) + '</p>' + render_sentence_pair(flat) + '<p class="sf-reason">' +
                html.escape(original['reason']) + '</p><pre style="white-space:pre-wrap;overflow-wrap:anywhere">' +
                html.escape(canonical(original)) + '</pre></details>')
        pieces.append('<details><summary>完整原词组范围、两条源记录与审核证据</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">' +
                      html.escape(canonical(history)) + '</pre></details></details>')
        edits.append((articles[0].closed, articles[0].closed, ''.join(pieces)))
        seen.add(identity)
    return preview.apply_edits(page, edits)


def _phrase_history_markup(history):
    pieces = ['<details class="residual-owner-history" data-history-sha256="' + history['history_sha256'] +
        '"><summary>本句完整词组转归依据</summary><p>' + html.escape(history['decision']['reason']) + '</p>']
    for field, label in (('source_parent_row', '原来源词条记录'), ('companion_parent_row', '原对应成分记录')):
        original = history[field]
        if original is None:
            continue
        flat = {key: value for key, value in original.items() if key != 'display'}
        pieces.append('<details class="sf-archived-example"><summary>' + label + '</summary><p class="sf-source">' +
            html.escape(original['source']) + '</p>' + render_sentence_pair(flat) + '<p class="sf-reason">' +
            html.escape(original['reason']) + '</p><pre style="white-space:pre-wrap;overflow-wrap:anywhere">' +
            html.escape(canonical(original)) + '</pre></details>')
    pieces.append('<details><summary>完整原词组范围、两条源记录与审核证据</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">' +
        html.escape(canonical(history)) + '</pre></details></details>')
    return ''.join(pieces)


def residual_native_companions(page, before, after, ledger, *, aliases=None):
    """Detach only certified component replacements from the ordinary lane."""
    aliases = aliases or {}
    supplied = ledger.get('companion_replacements', [])
    declared = after.get('exam_usage_policy', {}).get('residual_native_phrase_owners', [])
    histories = [row['semantic_review']['residual_owner_history'] for row in after['occurrences']
        if row.get('semantic_review', {}).get('residual_owner_history')]
    require(all(isinstance(items, list) and len({digest(item) for item in items}) == len(items)
            for items in (supplied, declared, histories)) and
        sorted(map(canonical, supplied)) == sorted(map(canonical, declared)) == sorted(map(canonical, histories)),
        'residual native companion history declarations differ')
    if not histories:
        return before, after, []
    old_rows, new_rows = native_api._rows(before), native_api._rows(after)
    old_ids, new_ids, bindings = set(), set(), []
    nodes = list(_native_nodes(page, aliases))
    for history in histories:
        original, source = history.get('companion_parent_row'), history.get('source_parent_row')
        identity = history.get('canonical_occurrence_id'); row = new_rows.get(identity)
        require(history.get('schema') == 'residual-native-phrase-history.v1' and
            history.get('history_sha256') == digest({k: v for k, v in history.items() if k != 'history_sha256'}) and
            original is not None and source is not None and row is not None and
            history.get('source_book_id') == before['book_id'] == after['book_id'] and
            history.get('canonical_owner_card_id') == history.get('companion_card_id') == before['card_id'] == after['card_id'] and
            history.get('companion_parent_snapshot_id') == before['snapshot_id'] and
            history.get('companion_parent_row_sha256') == digest(original) and
            history.get('source_parent_row_sha256') == digest(source) and
            old_rows.get(original['occurrence_id']) == original and original['occurrence_id'] not in new_rows and
            identity not in old_rows and identity not in new_ids and original['occurrence_id'] not in old_ids,
            'residual native companion parent/row/hash binding differs')
        native_api._identity(row); native_api._identity(source)
        sense = next((sense for sense in after['senses'] if sense['sense_id'] == row.get('sense_id')), None)
        require(row.get('status') == 'reviewed' and row.get('reviewed_sense_id') == row['sense_id'] and
            row.get('assignment_context_hash') == sf._assignment_context(after, row) and sense is not None and
            history.get('native_scope', {}).get('kind') == 'native_phrase' and
            history['native_scope'].get('card_lemma') == before['word'] and
            history.get('book_decision', {}).get('source_parent_snapshot_id') == history.get('source_parent_snapshot_id'),
            'residual native companion reviewed sense/scope differs')
        chosen = history['book_decision'].get('target', {})
        policy = history['book_decision'].get('count_policy', {})
        technical_sense = chosen.get('technical_decision', {}).get('new_sense')
        require(chosen.get('card_id') == after['card_id'] and
            chosen.get('replace_occurrence_id') == original['occurrence_id'] and
            chosen.get('target_range') == row['target_range'] and chosen.get('translation_ranges') == row['translation_ranges'] and
            chosen.get('companion_source_row_sha256') == digest(original) and
            policy.get('companion_target_count_before') == policy.get('companion_target_count_after') == 1 and
            policy.get('companion_target_frequency_delta') == policy.get('extra_physical_occurrences') == 0 and
            (technical_sense is None or (technical_sense.get('pos'), technical_sense.get('text')) == (sense['pos'], sense['text'])) and
            len(before['occurrences']) == len(after['occurrences']), 'residual native companion decision/sense/count differs')
        for component in (original, source):
            require(all(component.get(key) == row.get(key) for key in ('paper_id', 'physical_source', 'english',
                'english_hash', 'translation', 'translation_hash', 'source_provenance', 'alignment')) and
                row['target_range'][0] <= component['target_range'][0] < component['target_range'][1] <= row['target_range'][1],
                'residual native companion physical pair/full span differs')
        require(row['target_range'] == [min(original['target_range'][0], source['target_range'][0]),
            max(original['target_range'][1], source['target_range'][1])], 'residual native phrase is not the exact component union')
        view = original.get('display')
        require(view is not None, 'residual native companion lacks its exact old display')
        sd.validate_display(view, original)
        require(view['english'] == row['english'] and view['translation'] == row['translation'] and
            view['target_range'] == original['target_range'], 'residual native companion requires exact original coordinates')
        matched = []
        for node, native in nodes:
            if native['jump'] != view['provenance'].get('native_jump'):
                continue
            actual = native_api._view(original, native, view)
            if actual is not None:
                require(native['target_ranges'] == [view['target_range']], 'residual native companion original mark differs')
                matched.append((node, native))
        require(len(matched) == 1, 'residual native companion source node is absent or duplicated')
        node, native = matched[0]
        bindings.append({'history': history, 'old_row': original, 'new_row': row, 'sense': sense,
            'source_native_sha256': sf._sha(page[node.start:node.end]), 'native': native})
        old_ids.add(original['occurrence_id']); new_ids.add(identity)
    projections = []
    for prepared, removed in ((before, old_ids), (after, new_ids)):
        projection = deepcopy(prepared)
        projection['occurrences'] = [row for row in projection['occurrences'] if row['occurrence_id'] not in removed]
        # The exact paired identities are independently handled here, including
        # their audit exclusion copies. All unrelated evidence remains intact.
        for container in (projection.get('candidate_scope', {}), projection.get('exam_usage_policy', {}),
                          projection.get('exam_usage_policy', {}).get('inherited_candidate_scope', {})):
            if 'excluded' in container:
                container['excluded'] = [item for item in container['excluded']
                    if item['occurrence']['occurrence_id'] not in old_ids | new_ids]
        projection['expected_occurrences'] = len(projection['occurrences'])
        projection.pop('snapshot_id'); projection['snapshot_id'] = digest(projection)
        native_api._rows(projection)
        projections.append(projection)
    return *projections, bindings


def render_residual_native_companions(page, bindings, *, aliases=None):
    """Rebind an existing native mark while keeping its raw source jump/fine pair."""
    if not bindings:
        return page, [], []
    aliases = aliases or {}
    edits, proof = [], []
    nodes = list(_native_nodes(page, aliases))
    for binding in bindings:
        original, row, history, expected = [binding[k] for k in ('old_row', 'new_row', 'history', 'native')]
        matches = [(node, native) for node, native in nodes if native == expected]
        require(len(matches) == 1, 'residual native companion changed during ordinary rendering')
        node, native = matches[0]
        en = node.descendant('example-text')
        view = original['display']
        example = {'text': native['english'], 'translation': native['translation'],
            'translation_source': 'codex', 'translation_alignment': view['alignment']}
        en_chunks, _, _ = _example_chunk_ranges(example)
        markup = _annotate_sentence_chunks(_highlight_example(native['english'], '', '', native['cloze_answers'],
            target_ranges=[row['target_range']], chunk_ranges=en_chunks, preserve_source=True), view['alignment'])
        edits.append((en.opened, en.closed, native_api._source_classes(markup, aliases)))
        sense = binding['sense']
        label = '<span class="residual-native-sense" style="font-size:12px;color:var(--muted,#63718a)">' + \
            html.escape(sense['pos'] + ' ' + sense['text']) + '</span>'
        history_block = '<div class="sf-native-ownership-history" data-native-ownership-history="residual-v1">' + \
            _phrase_history_markup(history) + '</div>'
        edits.append((node.closed, node.closed, label + history_block))
        proof.append({'old_occurrence_id': original['occurrence_id'], 'canonical_occurrence_id': row['occurrence_id'],
            'old_row_sha256': digest(original), 'new_row_sha256': digest(row), 'history_sha256': history['history_sha256'],
            'source_native_sha256': binding['source_native_sha256'], 'old_target_range': original['target_range'],
            'target_range': row['target_range'], 'translation_ranges': row['translation_ranges'],
            'preserved_fine_alignment_sha256': digest(view['alignment']), 'preserved_native_jump': native['jump']})
    revised, inverse = preview.apply_edits(page, edits)
    return revised, inverse, proof


def source_report_bridge(page, before, *, aliases=None):
    """Certify a derived common-sense source report before an owned scaffold.

    The legacy renderer expects every original dictionary ordinal, including
    rows suppressed by a certified common group. Its temporary scaffold carries
    only those immutable meanings; the renderer immediately replaces it. The
    complete source reports are retained by a separate byte inverse.
    """
    from anki_pipeline.sense_groups import display_report
    aliases = aliases or {}
    reports = [n for n in preview._Spans(page, aliases).nodes if n['kind'] == 'report']
    context = before['book_id'] + '/' + before['card_id']
    require(reports and all(n['attrs'].get('data-snapshot') == before['snapshot_id'] for n in reports),
            'source report snapshot differs: ' + context)
    normalize = lambda values: [' '.join(value.split()) for value in values]
    original = normalize([s['pos'] + ' ' + s['text'] for s in before['senses']])
    actual = normalize([value for n in reports for value in n['meanings']])
    if actual == original:
        return page, [], {'adapted': False}
    derived = display_report(sf.report_from_record(before))
    require(actual == normalize([s['pos'] + ' ' + s['text'] for s in derived['senses']]),
            'source report is not the certified parent common display: ' + context)
    provenance = before['definition_provenance']
    partitions = [(c['sense_start'], c['sense_start'] + c['sense_count'])
                  for c in provenance.get('components', [])]
    partitions += [(s['ordinal'], s['ordinal'] + 1) for s in
                   provenance.get('supplemental_definitions', {}).get('appended', [])]
    require(len(partitions) == len(reports) and partitions and partitions[0][0] == 0 and
            partitions[-1][1] == len(before['senses']) and
            all(0 <= start < end <= len(before['senses']) for start, end in partitions) and
            all(left[1] == right[0] for left, right in zip(partitions, partitions[1:])),
            'source report original component partitions differ: ' + context)
    parsed = native_api._Offsets(page, aliases)
    elements = {node.start: node for node in parsed.root.walk() if 'sf-report' in node.classes}
    rows = {row['occurrence_id']: row for row in before['occurrences']}
    excluded = {item['occurrence_id']: item['occurrence'] for item in
                before.get('exam_usage_policy', {}).get('excluded', [])}
    edits, seen, excluded_seen, proof_parts = [], set(), set(), []
    for index, (report, (start, end)) in enumerate(zip(reports, partitions)):
        groups = [s for s in derived['senses'] if start <= s['ordinal'] < end]
        require(normalize(report['meanings']) == normalize([s['pos'] + ' ' + s['text'] for s in groups]),
                'source report common component order differs: ' + context)
        element = elements[report['start']]
        counts = [sd._Tree(page[n.start:n.end]).root.text() for n in element.walk()
                  if 'sf-count' in n.classes and not _inside_history(n)]
        require(counts == [str(s['count']) + ' 次' for s in groups],
                'source report common counts differ: ' + context)
        group_nodes = [n for n in element.children if 'sf-sense' in n.classes or
                       {'sf-row', 'sf-empty'}.issubset(n.classes)]
        require(len(group_nodes) == len(groups), 'source report common group structure differs: ' + context)
        for group_node, group in zip(group_nodes, groups):
            members = [n.attrs.get('data-sf-occurrence-id') for n in group_node.walk()
                       if 'sf-example' in n.classes and not _inside_history(n)]
            expected_members = {r['occurrence_id'] for r in group['occurrences']}
            require(len(members) == len(expected_members) and set(members) == expected_members,
                    'source report common group membership differs: ' + context)
        expected_rows = [r for s in groups for r in s['occurrences']]
        if not index:
            expected_rows += derived['pending']
        expected_ids = {r['occurrence_id'] for r in expected_rows}
        current_ids = set()
        for article in element.walk():
            if 'sf-example' not in article.classes or _inside_history(article):
                continue
            identity = article.attrs.get('data-sf-occurrence-id')
            if identity in rows:
                require(identity in expected_ids and identity not in seen,
                        'source report common occurrence partition differs: ' + context)
                current_ids.add(identity); seen.add(identity)
                old = rows[identity]
            else:
                # Existing excluded diagnostics are evidence, never a counted
                # common-group member. They remain explicit and source-bound.
                require(identity in excluded and identity not in excluded_seen and
                        any('sf-pending' in n.classes for n in preview._ancestors(article)),
                        'source report has an uncertified extra occurrence: ' + context)
                excluded_seen.add(identity); old = excluded[identity]
            pairs = [n for n in article.children if 'sf-sentence-pair' in n.classes]
            require(len(pairs) == 1, 'source report original bilingual pair is not unique: ' + context)
            view = old.get('display') or old
            for name, field in (('sf-en', 'english'), ('sf-zh', 'translation')):
                node = pairs[0].descendant(name)
                tree = sd._Tree(page[node.opened:node.closed]).root
                require(sd._text_and_ranges(tree)[0] == view[field],
                        'source report original bilingual text differs: ' + context + '/' + identity)
        require(current_ids == expected_ids, 'source report common physical occurrence coverage differs: ' + context)
        meanings = ''.join('<div class="sf-row"><span class="sf-meaning"><span class="sf-pos">' +
            html.escape(s['pos']) + '</span> ' + html.escape(s['text']) + '</span></div>'
            for s in before['senses'][start:end])
        scaffold = ('<div class="sf-report" data-snapshot="' + before['snapshot_id'] +
                    '" data-residual-source-report-scaffold="v1">' + meanings + '</div>')
        edits.append((report['start'], report['end'], scaffold))
        proof_parts.append({'original_ordinals': [start, end], 'common_ordinals': [s['ordinal'] for s in groups],
            'counts': [s['count'] for s in groups], 'occurrence_ids_sha256': digest(sorted(current_ids)),
            'source_report_sha256': sf._sha(page[report['start']:report['end']])})
    require(seen == set(rows), 'source report total physical coverage differs: ' + context)
    bridged, inverse = preview.apply_edits(page, edits)
    require(preview.restore_edits(bridged, inverse) == page, 'source common-report bridge inverse differs')
    return bridged, inverse, {'adapted': True, 'snapshot_id': before['snapshot_id'],
        'definition_snapshot_id': before['definition_snapshot_id'], 'physical_occurrences': len(seen),
        'preserved_excluded_diagnostics': sorted(excluded_seen), 'original_senses_sha256': digest(before['senses']),
        'equivalence_certificates_sha256': digest(before.get('sense_group_equivalences', [])), 'partitions': proof_parts}


def source_class_aliases(page, shipped=None):
    """Read the shipped inline reverse map without executing source scripts."""
    result = dict(shipped or {})
    for script in re.finditer(r'<script\b[^>]*>([\s\S]*?)</script\s*>', page, re.I):
        for match in re.finditer(r'"classes"\s*:\s*(\{[^{}]*\})', script[1]):
            mapping = json.loads(match[1])
            require(isinstance(mapping, dict) and all(isinstance(alias, str) and
                    re.fullmatch(r'_r\d+', alias) and isinstance(original, str) and
                    re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]*', original) for alias, original in mapping.items()),
                    'source inline class map is malformed')
            for alias, original in mapping.items():
                require(alias not in result or result[alias] == original, 'source inline/shipped class aliases conflict')
                result[alias] = original
    return result


def _native_nodes(page, aliases):
    for node in native_api._Offsets(page, aliases).root.walk():
        if node.tag == 'li' and 'example-card' in node.classes and not _inside_history(node):
            ancestor = node.parent
            while ancestor is not None and not ancestor.attrs.get('data-native-ownership-history'):
                ancestor = ancestor.parent
            if ancestor is None:
                require(node.end is not None, 'native source node is unterminated')
                yield node, sd._native_examples(page[node.start:node.end], aliases)[0]


class _TextPositions(HTMLParser):
    """Map a plain text leaf to exact source bytes; tags are never serialized."""
    def __init__(self, fragment):
        super().__init__(convert_charrefs=False)
        self.fragment, self.cursor, self.leaves = fragment, 0, []
        self.lines = [0] + [i + 1 for i, char in enumerate(fragment) if char == '\n']
        self.feed(fragment)

    def position(self):
        line, column = self.getpos()
        return self.lines[line - 1] + column

    def handle_data(self, data):
        start = self.position()
        self.leaves.append((self.cursor, self.cursor + len(data), start, start + len(data)))
        self.cursor += len(data)

    def handle_entityref(self, name):
        self.reference('&' + name + ';')

    def handle_charref(self, name):
        self.reference('&#' + name + ';')

    def reference(self, raw):
        self.cursor += len(html.unescape(raw))

    def handle_starttag(self, tag, attrs):
        if tag == 'br':
            self.cursor += 1


def _insert_exact_native_mark(page, node, native, target, aliases):
    sd._span(target, native['english'], 'missing native mark range')
    require(all(not (a < target[1] and target[0] < b) for a, b in native['target_ranges']),
            'missing native mark overlaps an existing target')
    en = node.descendant('example-text')
    require(en.closed is not None, 'missing native mark text boundary is absent')
    fragment = page[en.opened:en.closed]
    tree = sd._Tree(fragment).root
    require(sd._text_and_ranges(tree)[0] == native['english'], 'native text leaf map differs')
    positions = _TextPositions(fragment)
    leaves = [part for part in positions.leaves if part[0] <= target[0] < target[1] <= part[1]]
    require(len(leaves) == 1, 'missing native mark needs one exact plain source leaf')
    cp_start, _, raw_start, _ = leaves[0]
    left, right = [en.opened + raw_start + value - cp_start for value in target]
    require(page[left:right] == native['english'][slice(*target)], 'native mark source slice differs')
    return (left, right, native_api._source_classes('<mark class="target-word">' + page[left:right] + '</mark>', aliases))


def native_missing_mark_bridge(page, before, after, *, aliases=None):
    """Temporarily restore certified old exclusions for the unchanged guard.

    The core immediately removes these non-counted marks again. A source row,
    reviewed transform and old exclusion authority, never a word search, are
    required. Unknown/reviewed missing marks remain guard failures.
    """
    from anki_pipeline.exam_library import _context_stem_targets
    from anki_pipeline.option_context import context_target_ranges
    aliases = aliases or {}
    old_rows, new_rows = native_api._rows(before), native_api._rows(after)
    exclusions = {}
    for prepared, side in ((before, 'before'), (after, 'after')):
        containers = [prepared.get('candidate_scope', {}), prepared.get('exam_usage_policy', {}),
                      prepared.get('exam_usage_policy', {}).get('inherited_candidate_scope', {})]
        for container in containers:
            for item in container.get('excluded', []):
                row = item['occurrence']; identity = native_api._identity(row)
                exclusions.setdefault(identity, {}).setdefault(side, []).append(item)
    evidence = dict(old_rows)
    for prepared in (before, after):
        for row in native_api._excluded(prepared):
            evidence.setdefault(row['occurrence_id'], row)
    approved = {identity: row['display'] for identity, row in evidence.items() if row.get('display')}
    by_anchor = {}
    for identity, row in evidence.items():
        anchors = set(sd._source_ids(row))
        view = approved.get(identity, {})
        jump = view.get('provenance', {}).get('native_jump')
        if jump:
            anchors.add(jump['sentence_id'])
        for anchor in anchors:
            by_anchor.setdefault(anchor, []).append((identity, row))
    edits, bindings = [], []
    nodes = list(_native_nodes(page, aliases))
    for node, native in nodes:
        if native['jump'] is None:
            continue
        projected, matches = {}, []
        for identity, row in by_anchor.get(native['jump']['sentence_id'], []):
            display = approved.get(identity)
            pinned = (display or {}).get('provenance', {}).get('native_jump')
            if pinned and native['jump']['sentence_id'] == pinned['sentence_id'] and native['jump'] != pinned:
                continue
            view = native_api._view(row, native, display)
            if view is not None:
                if view['target_range'] in native['target_ranges']:
                    matches.append((identity, row, view))
                else:
                    projected[identity] = (row, view['target_range'], {'kind': 'exact_native_anchor', 'view_hash': digest(view)})
        for _, _, view in matches:
            derived = view.get('derivation_payload') or {}
            if not all(key in derived for key in ('originalQuestionEnglish', 'questionEnglish',
                                                 'completedEnglish', 'stemSentenceRefs', 'optionSentenceRefs')):
                continue
            for key in ('stemSentenceRefs', 'optionSentenceRefs'):
                for ref in derived[key]:
                    for identity, row in by_anchor.get(ref['sentenceId'], []):
                        if identity in {item[0] for item in matches} or ref['sentenceId'] not in sd._source_ids(row):
                            continue
                        require(ref.get('englishHash') == row['english_hash'] and ref.get('english') == row['english'] and
                            ref.get('translationHash') == sf._sha(row['translation']) and ref.get('translationZh') == row['translation'] and
                            ref.get('reviewedContentHash') == row['source_provenance'].get('reviewedContentHash'),
                            'missing native mark source reference differs: ' + identity)
                        sentence = {'id': ref['sentenceId'], 'english': row['english']}
                        if key == 'stemSentenceRefs':
                            targets = _context_stem_targets({**derived, 'stemSentenceRefs': [ref]}, {ref['sentenceId']: sentence},
                                lambda source: [tuple(row['target_range'])] if source['id'] == sentence['id'] else [])
                            target = list(next(item[2] for item in targets)) if targets else None
                        else:
                            target = list(context_target_ranges(derived, sentence, [tuple(row['target_range'])])[0])
                        if target is None:
                            continue
                        if not derived.get('hasQuestionBlank'):
                            separator = derived['completedEnglish'].find('\n\n')
                            if separator >= 0:
                                target = [value - 1 if value > separator else value for value in target]
                        require(native['english'][slice(*target)] == row['english'][slice(*row['target_range'])],
                                'missing native mark exact projection text differs: ' + identity)
                        if target not in native['target_ranges']:
                            projected[identity] = (row, target, {'kind': key, 'reference': ref,
                                'derivation_sha256': digest(derived)})
        seen_targets = set()
        for identity, (row, target, projection) in projected.items():
            if projection['kind'] == 'exact_native_anchor' and not (
                    any(match[0] in new_rows for match in matches) and any(
                        other['jump'] is not None and other['jump'] != native['jump'] and
                        other['jump']['sentence_id'] == native['jump']['sentence_id'] and
                        other['english'] == native['english'] and other['translation'] == native['translation'] and
                        native_api._same_packed_native_source(other['jump'], native['jump'])
                        for _, other in nodes)):
                continue
            declared = exclusions.get(identity, {})
            if identity in old_rows or identity in new_rows or not declared.get('before') or not declared.get('after'):
                continue
            eligible = [item for item in declared['before'] if item in declared['after'] and
                item.get('exclusion_kind') == 'wrong_lemma' and row.get('status') in {'unmatched', 'ambiguous'}]
            if not eligible:
                continue
            item = eligible[0]; authority = item.get('authority', {}); legacy = authority.get('legacy_projection_proof', {})
            decision = legacy.get('decision', {})
            require(item['occurrence'] == row == legacy.get('occurrence') and
                authority.get('decision_sha256') == digest(decision) and
                (decision.get('book_id'), decision.get('card_id'), decision.get('occurrence_id')) ==
                (before['book_id'], before['card_id'], identity) and authority.get('accepted_helper') and
                decision.get('decision_after', {}).get('status') == row['status'],
                'missing native mark exclusion authority differs: ' + identity)
            sd.validate_display(row['display'], row)
            target_key = tuple(target)
            if target_key not in seen_targets:
                edits.append(_insert_exact_native_mark(page, node, native, target, aliases))
                seen_targets.add(target_key)
            bindings.append({'occurrence_id': identity, 'source_native_sha256': sf._sha(page[node.start:node.end]),
                'excluded_row_sha256': digest(row), 'excluded_item_sha256': digest(item), 'target_range': target,
                'projection': projection, 'excluded_from_counts': True})
    revised, inverse = preview.apply_edits(page, edits)
    return revised, inverse, {'schema': 'certified-native-excluded-mark-bridge.v1',
        'book_id': before['book_id'], 'card_id': before['card_id'], 'parent_snapshot_id': before['snapshot_id'],
        'snapshot_id': after['snapshot_id'], 'bindings': bindings, 'temporary_marks': len(edits)}


def dictionary_caption(page, ledger, *, aliases=None):
    """Use a neutral heading for a source-proven mixed primary definition.

    Only the plain, direct primary h3 is edited. Dictionary labels, nested
    evidence and all source text remain byte-identical and independently invertible.
    """
    additions = ledger.get('new_definitions', [])
    names = dictionary_source_names(additions)
    oxford = lambda name: name.startswith('牛津') or 'oxford' in name.casefold() or bool(
        re.fullmatch(r'oald\d*', name, re.I))
    mixed = any(item.get('kind') == 'contextual_usage' for item in additions) or any(
        not oxford(name) for name in names)
    if not mixed:
        return page, []
    parsed = native_api._Offsets(page, aliases or {})
    edits = []
    for content in parsed.root.walk():
        if (content.tag != 'div' or 'field-content' not in content.classes or
                content.parent is None or 'primary-definition' not in content.parent.classes):
            continue
        if not any('supplement-definition' in child.classes for child in content.children):
            continue
        titles = [child for child in content.children if child.tag == 'h3' and not child.children and
                  child.closed is not None and page[child.opened:child.closed] == '牛津释义']
        require(len(titles) <= 1, 'mixed primary definition has duplicate exact Oxford headings')
        edits.extend((title.opened, title.closed, '释义') for title in titles)
    require(len(edits) <= 1, 'mixed primary definition heading is not unique')
    return preview.apply_edits(page, edits)


def render_card(page, before, after, ledger, *, source_url, target_url, target_urls,
                aliases=None, source_aliases=None, documents=None, exam_base_url=None, adapter=None):
    """Adapt the existing base reversibly, then reuse the native/SF renderer."""
    aliases = source_class_aliases(page, aliases)
    base = list(re.finditer(r'<base\b[^>]*>', page, re.I))
    require(len(base) <= 1, 'source card has multiple base elements')
    asset_base = source_url
    base_inverse = []
    if base:
        href = re.search(r'\bhref\s*=\s*(["\'])([^"\']+)\1', base[0][0], re.I)
        require(href is not None, 'source card base has no unique href')
        asset_base = html.unescape(href[2])
        parsed = urlsplit(asset_base)
        require(asset_base.startswith('/') and not parsed.scheme and not parsed.netloc and
                not parsed.query and not parsed.fragment and not re.search(r'[\x00-\x20\x7f\\%]', asset_base), 'source asset base is unsafe')
        adapted, base_inverse = preview.apply_edits(page, [(base[0].start(), base[0].end(), '')])
    else:
        adapted = page
    adapted, source_bridge_inverse, source_bridge_proof = source_report_bridge(adapted, before, aliases=aliases)
    updates = ledger.get('residual_display_updates')
    if updates is not None:
        require(updates == ledger.get('render_context', {}).get('residual_display_updates'),
                'separate display ledger/render context differ')
    shown = presentation(after, adapter, display_updates=updates)
    documents = documents or {}
    adapted, missing_mark_inverse, missing_mark_proof = native_missing_mark_bridge(adapted, before, after, aliases=aliases)
    ordinary_before, ordinary_after, companions = residual_native_companions(adapted, before, after, ledger, aliases=aliases)
    native_after, full_pins = owner._native_owner_projection(ordinary_before, ordinary_after, documents, target_urls)
    native = update_native_examples(adapted, ordinary_before, native_after, aliases=aliases,
        **({'source_aliases': source_aliases} if source_aliases is not None else {}),
        **({'ownership_history_documents': documents, 'target_urls': target_urls, 'defer_ownership_coverage': True}
           if documents else {}))
    native_page, companion_inverse, companion_proof = render_residual_native_companions(native['page'], companions, aliases=aliases)
    additions = {}
    render_definitions = []
    for addition in ledger.get('new_definitions', []):
        names = dictionary_source_names(addition)
        kind = addition.get('translation_kind')
        marker = ('语境用法（非词典原义）' if addition.get('kind') == 'contextual_usage' else
                  '中文补译' if kind in {'reviewed_translation', 'model_translation'} else
                  '跨词典原译' if kind in {'cross_dictionary_original', 'original_chinese_reuse'} else '原译')
        rendered_addition = {**addition, 'source_name_zh': '；'.join(names) + (' · ' if names else '') + marker}
        if addition.get('kind') == 'contextual_usage':
            # The old renderer needs a source locator for its label. This is the
            # actual review key, explicitly labelled non-native above.
            rendered_addition['sense_ref'] = addition['contextual_key']
        render_definitions.append(rendered_addition)
        if addition['ordinal'] < len(before['senses']):
            continue  # A complete ledger also carries immutable earlier supplements.
        content = definition_evidence(addition)
        filename = sf._sha(content) + '.html'
        additions[addition['ordinal']] = (content, filename)
    source_prefix = target_url.rsplit('/web-preview/', 1)[0] + '/sources/'
    context = ledger.get('render_context', {})
    bound_targets = {tuple(item) for item in context.get('actual_bound_targets', [])}
    for usage in after.get('exam_usage_policy', {}).get('residual_auxiliary_usages', []):
        for origin in usage['origins']:
            if origin['source_card_id'] == after['card_id']:
                bound_targets.add((origin['source_parent_row']['occurrence_id'], usage['entity_id'], usage['occurrence_id']))
    jumps = owner._source_jumps(after, exam_base_url) if exam_base_url else None
    render_ledger = {**ledger, 'new_definitions': render_definitions}
    revised, inverse, frequency, breakdown = preview.render_page(native_page, before, after, render_ledger,
        source_url=asset_base, target_url=target_url, aliases=aliases, target_urls=target_urls,
        appended_source_urls={key: source_prefix + name for key, (_, name) in additions.items()},
        ownership_history_documents=documents, actual_bound_targets=bound_targets,
        transfer_failures=context.get('transfer_failures', {}), source_jumps=jumps)
    revised, projection_inverse, projection_stats = project_displays(revised, after, shown, aliases=aliases)
    revised, auxiliary_inverse, auxiliary_removed = source_auxiliary_cleanup(revised, after, aliases=aliases)
    revised, phrase_inverse = phrase_owner_histories(revised, after, ledger)
    revised, caption_inverse = dictionary_caption(revised, ledger, aliases=aliases)
    caption_restored = preview.restore_edits(revised, caption_inverse)
    restored = preview.restore_edits(preview.restore_edits(preview.restore_edits(preview.restore_edits(caption_restored,
        phrase_inverse), auxiliary_inverse), projection_inverse), inverse)
    restored = restore_original(preview.restore_edits(restored, companion_inverse), native['inverse'])
    restored = preview.restore_edits(restored, missing_mark_inverse)
    restored = preview.restore_edits(restored, source_bridge_inverse)
    require(preview.restore_edits(restored, base_inverse) == page, 'complete source/native/SF/base inverse differs')
    require('data-residual-source-report-scaffold=' not in revised, 'temporary source report scaffold escaped rendering')
    return revised, frequency, breakdown, {'base_inverse': base_inverse, 'native_inverse': native['inverse'],
        'report_inverse': inverse, 'display_projection_inverse': projection_inverse,
        'display_projection_stats': projection_stats, 'native_stats': native['stats'], 'asset_base': asset_base,
        'auxiliary_source_inverse': auxiliary_inverse, 'auxiliary_removed_native_examples': auxiliary_removed,
        'phrase_owner_history_inverse': phrase_inverse,
        'dictionary_caption_inverse': caption_inverse,
        'native_missing_mark_inverse': missing_mark_inverse, 'native_missing_mark_certification': missing_mark_proof,
        'residual_native_rebind_inverse': companion_inverse, 'residual_native_rebind': companion_proof,
        'ordinary_native_occurrences': len(ordinary_after['occurrences']),
        'ordinary_native_parent_snapshot_id': ordinary_before['snapshot_id'],
        'ordinary_native_snapshot_id': ordinary_after['snapshot_id'],
        'residual_native_occurrences': len(companions), 'authoritative_sf_occurrences': len(after['occurrences']),
        'source_report_bridge_inverse': source_bridge_inverse, 'source_report_bridge_certification': source_bridge_proof,
        'parent_snapshot_id': before['snapshot_id'], 'snapshot_id': after['snapshot_id'],
        'source_sha256': sf._sha(page), 'after_sha256': sf._sha(revised),
        'scope_ledger_sha256': digest(ledger), 'sf_only_owner_ids': sorted(full_pins or {})}, additions


def load_card_payloads(old_db, new_db, item):
    """Read one affected card; callers discard it before reading the next card."""
    key = item['book_id'], item['card_id']
    before = snapshot(old_db, *key, item['parent_snapshot_id'], item['parent_payload_sha256'], active=True)
    after = snapshot(new_db, *key, item['child_snapshot_id'], item['child_payload_sha256'], active=True)
    require(read_json(item['payload_file']) == after, 'exported child payload differs from committed snapshot')
    if item.get('before_payload_file'):
        require(read_json(item['before_payload_file']) == before, 'exported parent differs from baseline snapshot')
    require(before['word'] == after['word'] == item['word'], 'affected lexical card changed')
    require(len(before['occurrences']) == item['original_count'] and len(after['occurrences']) == item['new_count'],
            'affected count differs')
    if item.get('physical_updated') is False:
        require(before == after, 'display-only overlay changed the immutable physical snapshot')
    ledger = read_json(item['ledger_file'])
    updates = ledger.get('residual_display_updates')
    require(updates is None or updates == ledger.get('render_context', {}).get('residual_display_updates'),
            'separate display ledger/render context differ')
    documents = history_documents(new_db, after)
    supplied = ledger.get('render_context', {}).get('ownership_history_documents', {})
    require(not supplied or all(name not in documents or value == documents[name] for name, value in supplied.items()),
            'history overlay conflicts with immutable database')
    documents.update(supplied)
    return before, after, ledger, documents


def validate_auxiliary_bindings(after, ledger, entities, usages):
    bound = after.get('exam_usage_policy', {}).get('residual_auxiliary_usages', [])
    require(not bound or bound == ledger.get('render_context', {}).get('residual_auxiliary_usages'),
            'auxiliary snapshot/render ledger differ')
    for usage in bound:
        bare = {key: value for key, value in usage.items() if key != 'entity'}
        require(usages.get((usage['entity_id'], usage['book_id'], usage['occurrence_id'])) == bare and
                usage.get('entity') == entities[usage['entity_id']], 'source auxiliary binding/export differs')


def prepare(request_pin, *, adapter=None):
    request = read_json(request_pin)
    require(request.get('schema') == SCHEMA, 'unknown preview request')
    checkpoint = read_json(request['checkpoint'])
    require(checkpoint.get('schema') == 'residual-optimization-checkpoint.v1', 'committed residual checkpoint is required')
    require(isinstance(checkpoint.get('run_id'), str) and re.fullmatch(r'[a-z0-9_-]+', checkpoint['run_id']),
            'checkpoint run ID must be a safe immutable directory identifier')
    web_root = Path(request['web_root']).resolve(strict=True)
    output = Path(request['output']).resolve()
    artifact = (web_root / ARTIFACT).resolve()
    require(output.parent.is_relative_to(artifact) and not output.exists(), 'output must be a fresh owned candidate')
    require(all(re.fullmatch(r'[a-z0-9_-]+', part) for part in output.relative_to(artifact).parts),
            'candidate output directory names must be safe URL components')
    runtime = checked(request['runtime'])
    require(runtime.is_relative_to(web_root), 'shared runtime is outside the web root')
    parent, parent_stat = checked_database(checkpoint['parent_database'])
    candidate, candidate_stat = checked_database(checkpoint['database'])
    require(parent != candidate and parent_stat['ino'] != candidate_stat['ino'], 'candidate must be independent of baseline')
    cards = checkpoint.get('cards')
    require(isinstance(cards, list) and cards, 'checkpoint has no affected cards')
    keys = [(item['book_id'], item['card_id']) for item in cards]
    require(len(set(keys)) == len(keys) and all(_HEX.fullmatch(card) for _, card in keys), 'affected card identities must be unique hashes')
    books = {}
    for book in request['books']:
        require(book.get('book_id') in {'redbook', 'redbook2027'}, 'unsupported book path')
        require(book['book_id'] not in books, 'duplicate book')
        page, catalog = load_book(book, web_root, runtime)
        books[book['book_id']] = (book, page, catalog)
    require({book for book, _ in keys} <= set(books), 'affected card edition is absent')
    watched = {str(checked(value)): value['sha256'] for value in [request_pin, request['checkpoint'], request['runtime']]}
    variant_observation = {}
    variant_pin = native_variant_transport(request, watched, variant_observation)
    content_transport = pdf_transport = None
    if checkpoint.get('plan'):
        writer_plan = read_json(checkpoint['plan'])
        require(writer_plan.get('run_id') == checkpoint['run_id'], 'writer/checkpoint batch identity differs')
        watched[str(checked(checkpoint['plan']))] = checkpoint['plan']['sha256']
        content_transport = source_content_transport(request, writer_plan.get('source_files', {}), watched)
        pdf_transport = source_pdf_content_transport(request, writer_plan.get('source_files', {}), watched)
        registered = {row['original_source']['file'] for row in content_transport['rows']} if content_transport else set()
        if pdf_transport:
            registered.update(row['original_source']['file'] for row in pdf_transport['rows'])
        for path, checksum in writer_plan.get('source_files', {}).items():
            if path not in registered:
                watched[str(checked({'file': path, 'sha256': checksum}))] = checksum
        if content_transport:
            content_transport['writer_plan'] = deepcopy(checkpoint['plan'])
        if pdf_transport:
            pdf_transport['writer_plan'] = deepcopy(checkpoint['plan'])
    require(not request.get('source_content_snapshots') or content_transport is not None,
            'source snapshot transport requires an exact writer plan')
    require(not request.get('source_pdf_content_snapshots') or pdf_transport is not None,
            'PDF snapshot transport requires an exact writer plan')
    alias_transport = native_alias_content_transport(request, content_transport, watched)
    for book, _, _ in books.values():
        watched.update({str(checked(book[field])): book[field]['sha256'] for field in ('entry', 'catalog')})
    # Auxiliary exports are small; large physical payloads are never accumulated.
    entities = read_json(checkpoint['entities_file']) if checkpoint.get('entities_file') else []
    usages = read_json(checkpoint['entity_usages_file']) if checkpoint.get('entity_usages_file') else []
    require(isinstance(entities, list) and isinstance(usages, list), 'auxiliary exports must be arrays')
    require(request.get('fixture_only') is True or
            all(entity.get('canonical_identity_kind') == 'lexical_owner' for entity in entities),
            'new auxiliary owners need the common lexical identity contract')
    entity_index = {entity['entity_id']: entity for entity in entities}
    require(len(entity_index) == len(entities), 'duplicate auxiliary entity')
    usage_index = {}
    for usage in usages:
        require(usage['entity_id'] in entity_index, 'auxiliary usage entity is absent')
        validate_auxiliary(entity_index[usage['entity_id']], usage)
        key = usage['entity_id'], usage['book_id'], usage['occurrence_id']
        require(key not in usage_index, 'duplicate auxiliary physical owner')
        usage_index[key] = usage
    card_refs, source_pins = {}, {}
    native_history_checks = {'checked_cards': 0, 'checked_sides': 0, 'history_rows': 0,
        'histories': 0, 'verified_history_rows': 0, 'failures': []}
    reused_histories = reuse_native_history_preflight(request, checkpoint, watched)
    if reused_histories is not None:
        native_history_checks = reused_histories
    with closing(owned_readonly(parent)) as old_db, closing(owned_readonly(candidate)) as new_db:
        for item in cards:
            key = item['book_id'], item['card_id']
            before, after, ledger, documents = load_card_payloads(old_db, new_db, item)
            target_urls = {row['id']: row['previewUrl'] for row in books[key[0]][2]['cards']}
            if reused_histories is None:
                for side, prepared, db, supplied in (('before', before, old_db, None), ('current', after, new_db, documents)):
                    result = native_history_metadata(prepared, db, ledger, target_urls=target_urls,
                        variant_pin=variant_pin, documents=supplied)
                    native_history_checks['checked_sides'] += 1
                    for field in ('history_rows', 'histories', 'verified_history_rows'):
                        native_history_checks[field] += result[field]
                    native_history_checks['failures'].extend({'book_id': key[0], 'card_id': key[1], 'side': side,
                        **failure} for failure in result['failures'])
                native_history_checks['checked_cards'] += 1
            validate_auxiliary_bindings(after, ledger, entity_index, usage_index)
            for field in ('payload_file', 'ledger_file'):
                watched[str(checked(item[field]))] = item[field]['sha256']
            if item.get('before_payload_file'):
                watched[str(checked(item['before_payload_file']))] = item['before_payload_file']['sha256']
            catalog = books[key[0]][2]
            selected = [row for row in catalog['cards'] if row['id'] == key[1]]
            require(len(selected) == 1 and selected[0]['word'] == item['word'], 'affected card/catalog binding differs')
            source = local_url(selected[0]['previewUrl'], web_root)
            source_pin = pin(source)
            watched[source_pin['file']] = source_pin['sha256']
            source_pins[key] = source_pin
            card_refs[key] = deepcopy(item)
            del before, after, ledger, documents
    require(not native_history_checks['failures'], 'native history metadata preflight failed: ' +
        canonical(native_history_checks['failures']))
    if request.get('presentation_adapter'):
        watched[str(checked(request['presentation_adapter']))] = request['presentation_adapter']['sha256']
        adapter = adapter or load_adapter(request['presentation_adapter'])
    for field in ('entities_file', 'entity_usages_file'):
        if checkpoint.get(field):
            watched[str(checked(checkpoint[field]))] = checkpoint[field]['sha256']
    code_files = [Path(__file__), Path(sf.__file__), Path(preview.__file__), Path(owner.__file__),
        *[ROOT / 'anki_pipeline' / name for name in ('native_example_usage.py', 'sense_chunks.py',
          'sense_groups.py', 'sense_display.py', 'translation_alignment.py', 'packaging.py', 'ownership_history.py')],
        ROOT / 'scripts/prepare_sense_frequency_records.py', ROOT / 'anki_pipeline/templates/sense-frequency.css']
    code_pins = [pin(path) for path in code_files]
    watched.update({value['file']: value['sha256'] for value in code_pins})
    versions = {Path(value['file']).parent.parent for value in source_pins.values()}
    for version in sorted(versions):
        for asset in sorted((version / 'assets').glob('*.js')):
            value = pin(asset)
            watched[value['file']] = value['sha256']
    if request.get('native_source_aliases'):
        value = request['native_source_aliases']
        watched[str(checked(value))] = value['sha256']
    auxiliary_code = [ROOT / 'anki_pipeline/templates/card-chunks.js', ROOT / 'anki_pipeline/templates/sense-frequency.js',
        ROOT / 'output/exam-usage-policy-20261012/ownership-recovery-v5/library-inline-history-ui-v5/chunk-fine-only-runtime.js']
    if entities:
        for file in auxiliary_code:
            value = pin(file)
            watched[value['file']] = value['sha256']
    output_url = '/' + str(output.relative_to(web_root))
    runtime_raw, runtime_proof = runtime_overlay(runtime.read_bytes(), output_url)
    plan = {'schema': 'residual-optimization-preview-plan.v1', 'request': deepcopy(request_pin),
        'checkpoint': request['checkpoint'], 'output': str(output), 'run_id': checkpoint['run_id'],
        'affected': [{'book_id': book, 'card_id': card, 'source': source_pins[book, card],
                      'parent_snapshot_id': card_refs[book, card]['parent_snapshot_id'],
                      'snapshot_id': card_refs[book, card]['child_snapshot_id'],
                      'physical_updated': card_refs[book, card].get('physical_updated', True)} for book, card in keys],
        'books': [{'book_id': name, 'cards': len(value[2]['cards']), 'changed_cards': sum(book == name for book, _ in keys)} for name, value in books.items()],
        'code_pins': code_pins, 'watched_pins': [{'file': path, 'sha256': checksum} for path, checksum in sorted(watched.items())],
        'native_variant_transport': variant_observation or None, 'native_history_preflight': native_history_checks,
        'source_content_snapshots': content_transport, 'native_source_aliases_content_transport': alias_transport,
        'source_pdf_content_snapshots': pdf_transport,
        'runtime_overlay': {'sha256': hashlib.sha256(runtime_raw).hexdigest(), 'bytes': len(runtime_raw), **runtime_proof},
        'auxiliary': [{'entity_id': entity['entity_id'], 'learning_card': False,
            'physical_occurrences': len({usage['occurrence_id'] for usage in usages if usage['entity_id'] == entity['entity_id']})}
            for entity in entities],
        'database_guards': [{'file': str(parent), 'stat': parent_stat}, {'file': str(candidate), 'stat': candidate_stat}],
        'unchanged_card_policy': 'Keep complete existing catalog rows and preview URLs; render only checkpoint affected cards.',
        'runtime_policy': 'Reuse pinned shared all-card runtime, original media/reader/flip/etymology/chunk/history rules.',
        'database_reads': 'Only affected immutable snapshots and their referenced history documents; no full database hash.',
        'payload_lifetime': 'Stream one card and its ledger at a time; retain only checkpoint file references between cards.',
        'database_writes': 0, 'source_writes': 0, 'production_applied': False, 'browser_accepted': False}
    return plan, (request, checkpoint, books, card_refs, web_root, output, adapter, entities, usages)


def check_guards(plan):
    recheck_source_transports(plan)
    for value in plan['watched_pins']:
        checked(value)
    for value in plan['database_guards']:
        checked_database(value)  # Recheck sidecars as well as every original stat field.
    if plan.get('native_variant_transport'):
        native_variant_transport({'native_variant_addendum': plan['native_variant_transport']['pin']})
    if plan.get('native_history_preflight', {}).get('reused_cache'):
        request = read_json(plan['request'])
        checkpoint = read_json(request['checkpoint'])
        reuse_native_history_preflight(request, checkpoint, {})


def recheck_source_transports(plan):
    pdf = plan.get('source_pdf_content_snapshots')
    if pdf is not None:
        request = read_json(plan['request'])
        writer = read_json(pdf['writer_plan'])
        actual = source_pdf_content_transport(request, writer.get('source_files', {}))
        actual['writer_plan'] = pdf['writer_plan']
        require(actual == pdf, 'PDF snapshot plan transport changed')
    value = plan.get('source_content_snapshots')
    if value is None:
        require(not plan.get('native_source_aliases_content_transport'), 'alias locator bridge has no source proof')
        return
    request = read_json(plan['request'])
    writer = read_json(value['writer_plan'])
    actual = source_content_transport(request, writer.get('source_files', {}))
    actual['writer_plan'] = value['writer_plan']
    require(actual == value, 'source snapshot plan transport changed')
    require(native_alias_content_transport(request, actual) == plan.get('native_source_aliases_content_transport'),
            'alias content locator bridge changed')


def render_book_worker(request_pin, book_id, stage_path, plan):
    """One book, private readers/caches; only plain pinned data crosses spawn."""
    stage = Path(stage_path).resolve(strict=True)
    request = read_json(request_pin)
    checkpoint = read_json(request['checkpoint'])
    for value in plan['code_pins']:
        checked(value)
    book = next(item for item in request['books'] if item['book_id'] == book_id)
    web_root = Path(request['web_root']).resolve(strict=True)
    output = Path(request['output']).resolve()
    shell, catalog = load_book(book, web_root, checked(request['runtime']))
    card_refs = {(item['book_id'], item['card_id']): item for item in checkpoint['cards'] if item['book_id'] == book_id}
    source_pins = {item['card_id']: item['source'] for item in plan['affected'] if item['book_id'] == book_id}
    adapter = load_adapter(request['presentation_adapter']) if request.get('presentation_adapter') else None
    recheck_source_transports(plan)
    source_aliases = native_api.load_source_aliases(request['native_source_aliases']) if request.get('native_source_aliases') else None
    variant_pin = native_variant_transport(request)
    output_url = '/' + str(output.relative_to(web_root))
    auxiliary_urls = {item['entity_id']: output_url + '/auxiliary/' + item['entity_id'] + '.html'
        for item in read_json(checkpoint['entities_file'])} if checkpoint.get('entities_file') else {}
    files, aliases_cache = {}, {}
    proof_count, proof_bytes, proof_hash = 0, 0, hashlib.sha256()
    fragment = stage / book_id / '.worker-card-proofs.jsonl'
    started = time.monotonic()
    def write(name, raw):
        name = Path(name)
        require(not name.is_absolute() and name.parts and name.parts[0] == book_id and
            all(part not in {'..', '.'} for part in name.parts), 'book worker path escapes its prefix')
        destination = (stage / name).resolve()
        require(destination.is_relative_to(stage / book_id), 'book worker path overlaps another namespace')
        raw = raw.encode() if isinstance(raw, str) else raw
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open('xb') as handle:
            handle.write(raw)
        files[str(name)] = {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
    with closing(owned_readonly(checked_database(checkpoint['parent_database'])[0])) as old_db, \
            closing(owned_readonly(checked_database(checkpoint['database'])[0])) as new_db:
        revised_catalog = deepcopy(catalog)
        prefix = '/' + str((output / book_id).relative_to(web_root))
        urls = {row['id']: (prefix + '/web-preview/' + checkpoint['run_id'] + '/cards/' + row['id'] + '.html'
                if (book_id, row['id']) in card_refs else row['previewUrl']) for row in catalog['cards']}
        for index, row in enumerate(catalog['cards']):
            key = book_id, row['id']
            if key not in card_refs:
                continue
            before, after, ledger, documents = load_card_payloads(old_db, new_db, card_refs[key])
            if variant_pin is not None:
                require('__owner_recovery_native_variant_addendum__' not in documents or
                    documents['__owner_recovery_native_variant_addendum__'] == variant_pin,
                    'native variant transport conflicts with card documents')
                documents['__owner_recovery_native_variant_addendum__'] = deepcopy(variant_pin)
            for name, document in documents.items():
                if name.startswith(prefix + '/history/'):
                    filename = name[len(prefix + '/history/'):]
                    require(re.fullmatch(r'[a-f0-9]{64}\.html', filename), 'new history route is not a sealed hash filename')
                    require(document['reference']['file'] == name and sf._sha(document['document_html']) ==
                            document['reference']['sha256'], 'new history complete bytes/ref differ')
                    history_name = Path(book_id) / 'history' / filename
                    if str(history_name) not in files:
                        write(history_name, document['document_html'])
            source = checked(source_pins[row['id']])
            require(source == local_url(row['previewUrl'], web_root), 'worker source route/pin differs')
            version = source.parent.parent
            if version not in aliases_cache:
                aliases_cache[version] = class_aliases(version)
            try:
                content, frequency, breakdown, proof, additions = render_card(source.read_text(), before, after, ledger,
                    source_url=row['previewUrl'], target_url=urls[row['id']], target_urls=urls,
                    aliases=aliases_cache[version], source_aliases=source_aliases, documents=documents,
                    exam_base_url=request.get('exam_base_url'), adapter=adapter)
            except Exception as error:
                error.add_note('incremental preview card: book=' + book_id + ' card=' + row['id'])
                raise
            content, link_inverse = auxiliary_links(content, after, auxiliary_urls)
            proof['auxiliary_source_link_inverse'] = link_inverse
            proof['after_sha256'] = sf._sha(content)
            name = Path(book_id) / 'web-preview' / checkpoint['run_id'] / 'cards' / (row['id'] + '.html')
            write(name, content)
            for evidence, filename in additions.values():
                evidence_name = Path(book_id) / 'sources' / filename
                if str(evidence_name) not in files:
                    write(evidence_name, evidence)
            projected = {**row, 'previewUrl': urls[row['id']],
                'definition': preview._catalog_summary(row['definition'], frequency),
                'exam_frequency': frequency, 'exam_frequency_breakdown': breakdown,
                'residual_optimization': {'run_id': checkpoint['run_id'], 'parent_snapshot_id': before['snapshot_id'], 'snapshot_id': after['snapshot_id']}}
            if proof['native_stats']['native_examples'] or not row['exampleCount']:
                projected['exampleCount'] = proof['native_stats']['native_examples'] - proof['native_stats']['removed_examples'] - proof['auxiliary_removed_native_examples']
                require(projected['exampleCount'] >= 0, 'visible source examples count became negative')
            revised_catalog['cards'][index] = projected
            proof_raw = (canonical({'book_id': book_id, 'card_id': row['id'], **proof}) + '\n').encode()
            fragment.parent.mkdir(parents=True, exist_ok=True)
            with fragment.open('ab' if proof_count else 'xb') as handle:
                handle.write(proof_raw)
            proof_count += 1
            proof_bytes += len(proof_raw)
            proof_hash.update(proof_raw)
            if proof_count % 20 == 0:
                print('preview-worker book=' + book_id + ' cards=' + str(proof_count) + ' elapsed=' + format(time.monotonic() - started, '.1f') + 's', file=sys.stderr, flush=True)
            del before, after, ledger, documents, content, proof
            del proof_raw
        revised_catalog['counts']['examples'] = sum(row['exampleCount'] for row in revised_catalog['cards'])
        require(revised_catalog['decks'] == catalog['decks'] and len(revised_catalog['cards']) == len(catalog['cards']), 'catalog membership changed')
        require(all(new == old for old, new in zip(catalog['cards'], revised_catalog['cards']) if (book_id, old['id']) not in card_refs), 'unchanged catalog row changed')
        write(Path(book_id) / 'catalog.json', canonical(revised_catalog) + '\n')
        write(Path(book_id) / 'preview-library.html', rewrite_shell(shell, prefix + '/catalog.json',
            output_url + '/assets/library-preview.js'))

    for value in plan['code_pins']:
        checked(value)
    for field in ('parent_database', 'database'):
        checked_database(checkpoint[field])
    receipt = {'schema': 'residual-preview-book-worker.v1', 'status': 'PASS', 'book_id': book_id,
        'request': deepcopy(request_pin), 'files': files, 'proof_count': proof_count, 'proof_bytes': proof_bytes,
        'proof_sha256': proof_hash.hexdigest(), 'proof_fragment': str(fragment), 'elapsed_seconds': time.monotonic() - started}
    path = stage / book_id / '.worker-receipt.json'
    with path.open('x') as handle:
        handle.write(canonical(receipt) + '\n')
    return receipt


def _spawn_book_worker(connection, request_pin, book_id, stage_path, plan):
    try:
        receipt = render_book_worker(request_pin, book_id, stage_path, plan)
        connection.send({'status': 'PASS', 'book_id': book_id, 'receipt': receipt})
    except BaseException as error:
        failure = {'status': 'FAILED', 'book_id': book_id, 'error_type': type(error).__name__,
            'error': str(error), 'notes': list(getattr(error, '__notes__', [])), 'traceback': traceback.format_exc()}
        path = Path(stage_path) / book_id / '.worker-failure.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('x') as handle:
            handle.write(canonical(failure) + '\n')
        connection.send(failure)
        raise SystemExit(1)
    finally:
        connection.close()


def run_book_workers(request_pin, book_ids, stage, plan, *, parallel=True):
    if not parallel:
        return {book: render_book_worker(request_pin, book, stage, plan) for book in book_ids}
    context = multiprocessing.get_context('spawn')
    live, results = [], {}
    try:
        for book in book_ids:
            receiver, sender = context.Pipe(duplex=False)
            process = context.Process(target=_spawn_book_worker, args=(sender, request_pin, book, str(stage), plan),
                name='residual-preview-' + book)
            try:
                process.start()
            except BaseException:
                sender.close(); receiver.close()
                raise
            sender.close()
            live.append((book, process, receiver))
        pending = {receiver: (book, process) for book, process, receiver in live}
        while pending:
            for receiver in wait_connections(list(pending), timeout=1):
                book, process = pending.pop(receiver)
                message = receiver.recv()
                require(message.get('book_id') == book, 'book worker response identity differs')
                process.join(timeout=5)
                require(not process.is_alive(), 'book worker did not finish after its response')
                if message.get('status') != 'PASS' or process.exitcode != 0:
                    error = RuntimeError('book worker failed: ' + book + ': ' + message.get('error_type', 'process') + ': ' + message.get('error', ''))
                    error.add_note(message.get('traceback', 'worker process exit=' + str(process.exitcode)))
                    raise error
                require(book not in results, 'duplicate worker completion')
                results[book] = message['receipt']
            for receiver, (book, process) in list(pending.items()):
                require(process.is_alive() or receiver.poll(), 'book worker exited without a receipt: ' + book)
        return results
    finally:
        # Joining every child precedes any failure quarantine or final rename.
        for _, process, receiver in live:
            if process.is_alive():
                process.terminate()
            process.join()
            receiver.close()


def merge_book_worker_proofs(stage, book_ids, results, plan, files):
    """Merge in request/catalog order, independently of completion order."""
    stage = Path(stage).resolve(strict=True)
    require(set(results) == set(book_ids), 'book worker coverage differs')
    count, size, checksum = 0, 0, hashlib.sha256()
    destination = Path(stage) / 'card-proofs.jsonl'
    with destination.open('xb') as output:
        for book in book_ids:
            receipt = results[book]
            require(receipt.get('schema') == 'residual-preview-book-worker.v1' and receipt.get('status') == 'PASS' and
                receipt.get('book_id') == book and receipt.get('request') == plan['request'], 'book worker receipt differs')
            for name, value in receipt['files'].items():
                relative = Path(name)
                require(not relative.is_absolute() and relative.parts[0] == book and '..' not in relative.parts and name not in files,
                    'book worker file inventory overlaps another namespace')
                path = (Path(stage) / relative).resolve(strict=True)
                require(path.is_relative_to(Path(stage) / book) and path.stat().st_size == value['bytes'] and
                    preview.file_sha(path) == value['sha256'], 'book worker file bytes differ')
                files[name] = value
            source = Path(receipt['proof_fragment']).resolve(strict=True)
            require(source == (Path(stage) / book / '.worker-card-proofs.jsonl').resolve(), 'book proof fragment path differs')
            catalog = read_json({'file': str(Path(stage) / book / 'catalog.json'), 'sha256': receipt['files'][book + '/catalog.json']['sha256']})
            expected = [row['id'] for row in catalog['cards'] if any(item['book_id'] == book and item['card_id'] == row['id'] for item in plan['affected'])]
            actual_count, actual_size, actual_hash = 0, 0, hashlib.sha256()
            with source.open('rb') as fragment:
                for raw in fragment:
                    require(raw.endswith(b'\n'), 'book proof fragment has an incomplete record')
                    proof = json.loads(raw)
                    require(actual_count < len(expected) and proof.get('book_id') == book and proof.get('card_id') == expected[actual_count],
                        'book proof physical card/order differs')
                    binding = next(item for item in plan['affected'] if item['book_id'] == book and item['card_id'] == proof['card_id'])
                    require(proof.get('source_sha256') == binding['source']['sha256'] and
                        proof.get('parent_snapshot_id') == binding['parent_snapshot_id'] and proof.get('snapshot_id') == binding['snapshot_id'],
                        'book proof source/snapshot differs')
                    output.write(raw); checksum.update(raw); size += len(raw); count += 1
                    actual_hash.update(raw); actual_size += len(raw); actual_count += 1
            require(actual_count == receipt['proof_count'] == len(expected) and actual_size == receipt['proof_bytes'] and
                actual_hash.hexdigest() == receipt['proof_sha256'], 'book proof count/hash differs')
    require(count == len(plan['affected']), 'merged worker card coverage differs')
    for book in book_ids:
        (Path(stage) / book / '.worker-card-proofs.jsonl').unlink()
        (Path(stage) / book / '.worker-receipt.json').unlink()
    return count, size, checksum


def execute(request_pin, plan_sha256, *, adapter=None, _parallel=True):
    plan, state = prepare(request_pin, adapter=adapter)
    require(hashlib.sha256((canonical(plan) + '\n').encode()).hexdigest() == plan_sha256, 'exact reviewed plan SHA is required')
    request, checkpoint, books, card_refs, web_root, output, adapter, entities, usages = state
    recheck_source_transports(plan)
    source_aliases = None
    if request.get('native_source_aliases'):
        from anki_pipeline.native_example_usage import load_source_aliases
        source_aliases = load_source_aliases(request['native_source_aliases'])
    variant_pin = native_variant_transport(request)
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.residual-preview-', dir=output.parent))
    files, aliases_cache = {}, {}
    proof_count, proof_bytes, proof_hash = 0, 0, hashlib.sha256()
    readers = ExitStack()
    def write(name, raw):
        raw = raw.encode() if isinstance(raw, str) else raw
        destination = stage / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open('xb') as handle:
            handle.write(raw)
        files[str(name)] = {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
    try:
        output_url = '/' + str(output.relative_to(web_root))
        runtime_raw, runtime_proof = runtime_overlay(checked(request['runtime']).read_bytes(), output_url)
        require(hashlib.sha256(runtime_raw).hexdigest() == plan['runtime_overlay']['sha256'], 'runtime candidate drift')
        write('assets/library-preview.js', runtime_raw)
        auxiliary_urls = {entity['entity_id']: output_url + '/auxiliary/' + entity['entity_id'] + '.html' for entity in entities}
        auxiliary_proofs = []
        if entities:
            whole = ROOT / 'output/exam-usage-policy-20261012/ownership-recovery-v5/library-inline-history-ui-v5/chunk-fine-only-runtime.js'
            auxiliary_js = '\n'.join((ROOT / 'anki_pipeline/templates' / filename).read_text()
                for filename in ['card-chunks.js', 'sense-frequency.js']) + '\n' + whole.read_text() + '\n' + RESIDUAL_KEYBOARD + \
                '\nwindow.AnkiFineChunkRuntime.install(document);window.AnkiResidualReviewedChunkRuntime.install(document);\n'
            write('assets/auxiliary-chunks.js', auxiliary_js)
            for entity in entities:
                content, proof = render_auxiliary(entity, [usage for usage in usages if usage['entity_id'] == entity['entity_id']],
                    runtime_url=output_url + '/assets/auxiliary-chunks.js', exam_base_url=request.get('exam_base_url'))
                write(Path('auxiliary') / (entity['entity_id'] + '.html'), content)
                auxiliary_proofs.append(proof)
        results = run_book_workers(request_pin, list(books), stage, plan, parallel=_parallel)
        proof_count, proof_bytes, proof_hash = merge_book_worker_proofs(stage, list(books), results, plan, files)
        files['card-proofs.jsonl'] = {'sha256': proof_hash.hexdigest(), 'bytes': proof_bytes}
        check_guards(plan)
        manifest = {**plan, 'files': files, 'rendered_cards': proof_count, 'auxiliary_entries': auxiliary_proofs, 'actual_source_inverses_exact': True,
                    'candidate_generated': True, 'production_applied': False, 'browser_accepted': False}
        write('preview-manifest.json', canonical(manifest) + '\n')
        require(not output.exists(), 'candidate output appeared during render')
        os.rename(stage, output)
        return {'output': str(output), 'manifest': pin(output / 'preview-manifest.json'), 'rendered_cards': proof_count,
                'production_applied': False, 'browser_accepted': False}
    except BaseException as error:
        # Failed work is forensic evidence, never a resumable or published book.
        # A later run must prepare/check all guards and render fresh output.
        quarantine = stage.with_name('.FAILED-' + stage.name.lstrip('.'))
        try:
            require(not quarantine.exists(), 'failed preview quarantine already exists')
            formal = stage / 'preview-manifest.json'
            if formal.exists():
                formal.rename(stage / 'failed-unpublished-preview-manifest.json')
            worker_proofs = {}
            for fragment in stage.glob('*/.worker-card-proofs.jsonl'):
                lines = 0
                with fragment.open('rb') as handle:
                    while raw := handle.read(1024 * 1024):
                        lines += raw.count(b'\n')
                worker_proofs[fragment.parent.name] = {'complete_record_lines': lines,
                    'fragment_bytes': fragment.stat().st_size, 'independently_validated_for_reuse': False}
            journal = {'schema': 'failed-residual-preview-stage.v1', 'status': 'FAILED_DO_NOT_PUBLISH',
                'published': False, 'reusable': False, 'intended_output': str(output), 'request': deepcopy(request_pin),
                'plan_sha256': plan_sha256, 'code_pins': plan['code_pins'], 'completed_cards': proof_count,
                'completed_proof_bytes': proof_bytes, 'completed_proof_sha256': proof_hash.hexdigest(),
                'completed_files': files, 'error_type': type(error).__name__, 'error': str(error),
                'worker_proof_evidence': worker_proofs,
                'error_notes': list(getattr(error, '__notes__', [])),
                'policy': 'Forensic failed stage only. No partial publication or reuse; a new run uses a new exact plan and all code/input/database guards.'}
            with (stage / 'failed-journal.json').open('x') as handle:
                handle.write(canonical(journal) + '\n')
            os.rename(stage, quarantine)
            error.add_note('failed preview quarantined, not published or reusable: ' + str(quarantine))
        except Exception as retention_error:
            error.add_note('failed preview evidence retained at ' + str(stage) + '; quarantine journal error: ' + str(retention_error))
        raise
    finally:
        readers.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', required=True, type=Path)
    parser.add_argument('--sha256', required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--dry-run', action='store_true')
    mode.add_argument('--execute', action='store_true')
    parser.add_argument('--plan-sha256')
    args = parser.parse_args(argv)
    request_pin = {'file': str(args.request.resolve()), 'sha256': args.sha256}
    if args.dry_run:
        plan, _ = prepare(request_pin)
        check_guards(plan)
        print(canonical(plan))
    else:
        require(args.plan_sha256, 'execute requires the exact dry-run plan SHA256')
        print(canonical(execute(request_pin, args.plan_sha256)))


if __name__ == '__main__':
    main()
