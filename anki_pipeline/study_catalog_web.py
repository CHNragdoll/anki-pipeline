"""Small, subject-neutral navigation host for the common book projection.

The complete catalog remains an export artifact. The browser boots from a compact
navigation index and opens only the selected card; card contents and media are
never copied into the navigation index or modified here.
"""
from __future__ import annotations

import gzip
import hashlib
import html
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from urllib.parse import unquote, urlsplit


class _LabelText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored = 0

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style'}:
            self.ignored += 1
        elif tag in {'br', 'p', 'div', 'li'} and not self.ignored:
            self.parts.append(' ')

    def handle_endtag(self, tag):
        if tag in {'script', 'style'}:
            self.ignored = max(0, self.ignored - 1)
        elif tag in {'p', 'div', 'li'} and not self.ignored:
            self.parts.append(' ')

    def handle_data(self, value):
        if not self.ignored:
            self.parts.append(value)


def plain_label(value: str) -> str:
    """Present authored HTML as text without changing its stored source field."""
    parser = _LabelText()
    parser.feed(str(value))
    parser.close()
    return re.sub(r'\s+', ' ', ''.join(parser.parts)).strip()


def navigation_index(catalog: dict, metadata: dict | None = None) -> dict:
    """Keep native card order and index only compact current display metadata.

    ``member_ids`` is an explicit retained inventory, allowing a known package
    guide to have its own entry. Without that evidence every card stays listed:
    the legacy importer calls all notes without a Word field ``guide``, which
    also includes ordinary mathematics and other non-vocabulary study content.
    A future guide role must be explicit, never guessed from a title or field.
    """
    metadata = metadata or {}
    metadata_cards = metadata.get('cards', {})
    units: list[str] = []
    positions: dict[str, int] = {}
    rows = []
    membership = metadata.get('member_ids')
    if membership is not None:
        if not isinstance(membership, list) or any(not isinstance(identity, str) for identity in membership) or len(set(membership)) != len(membership):
            raise ValueError('navigation source membership must contain unique text identities')
        membership = set(membership)
        if not membership.issubset({str(card['id']) for card in catalog['cards']}):
            raise ValueError('navigation source membership references a missing card')
    elif metadata.get('provenance', {}).get('kind') == 'sealed-source-catalog':
        membership = set(metadata_cards)
    for card in catalog['cards']:
        details = metadata_cards.get(str(card['id']), {})
        unit = details.get('deck_name') or card['unit']
        if not isinstance(unit, str):
            raise ValueError('navigation grouping path must be text')
        example_count = details.get('example_count')
        if example_count is not None and (type(example_count) is not int or example_count < 0):
            raise ValueError('navigation example count must be nonnegative or unknown')
        if unit not in positions:
            positions[unit] = len(units)
            units.append(unit)
        rows.append([str(card['id']), plain_label(card['word']),
                     plain_label(card.get('label') or card['word']),
                     positions[unit], card['url'], plain_label(details.get('summary', '')),
                     example_count,
                     membership is None or str(card['id']) in membership])
    return {'schema': 'study-navigation.v2', 'units': units, 'cards': rows,
            'totals': {'cards': sum(row[7] for row in rows), 'groups': len({row[3] for row in rows if row[7]}),
                       'examples': sum(row[6] for row in rows if row[7] and row[6] is not None),
                       'unknown_example_cards': sum(row[7] and row[6] is None for row in rows)},
            'catalog_revision': catalog.get('catalog_revision'), 'metadata_provenance': metadata.get('provenance')}


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')


class _ShelfBrowseLinks(HTMLParser):
    """Locate attribute values without serializing the original bookshelf DOM."""
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.lines = [0]
        for line in source.splitlines(keepends=True):
            self.lines.append(self.lines[-1] + len(line))
        self.articles = []
        self.links = {}
        self.fragments = []
        self.feed(source)
        self.close()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'article':
            self.articles.append(attrs.get('data-study-book'))
        if tag != 'a':
            return
        identity = self.articles[-1] if self.articles else None
        browse = bool(identity and 'browse-book' in attrs.get('class', '').split())
        fragment = attrs.get('href', '').startswith('#')
        if not browse and not fragment:
            return
        if browse and identity in self.links:
            raise ValueError('source bookshelf has duplicate browse links for a book')
        matches = list(re.finditer(r'\bhref\s*=\s*([\"\'])(.*?)\1', self.get_starttag_text(), re.I | re.S))
        if len(matches) != 1:
            raise ValueError('source bookshelf browse link needs one quoted href')
        line, column = self.getpos()
        offset = self.lines[line - 1] + column
        positions = offset + matches[0].start(2), offset + matches[0].end(2)
        if fragment:
            self.fragments.append((*positions, attrs['href']))
        if browse:
            self.links[identity] = positions

    def handle_endtag(self, tag):
        if tag == 'article' and self.articles:
            self.articles.pop()


def write_shelf(root: Path, entries: list[dict], *, source: Path, service_origin: str,
                mount_path: str | None = None) -> dict:
    """Reuse the original bookshelf, adapting browse and local fragment URLs.

    The original DOM, covers, downloads, stable study IDs and progress scripts
    remain its sole UI and data path. A separate QA origin redirects to the same
    service before the original deferred scripts read progress; no second study
    service or browser storage namespace is created.
    """
    root, source = root.resolve(), source.resolve(strict=True)
    if source == root / 'index.html':
        raise ValueError('the original bookshelf cannot be overwritten')
    origin = urlsplit(service_origin)
    if (origin.scheme not in {'http', 'https'} or not origin.netloc or
            origin.path not in {'', '/'} or origin.query or origin.fragment or
            origin.username is not None or origin.password is not None or
            any(ord(char) < 32 for char in service_origin)):
        raise ValueError('bookshelf service requires a plain HTTP origin')
    service_origin = origin.scheme + '://' + origin.netloc
    if mount_path is None:
        mount_path = '/' + root.relative_to(source.parent).as_posix().strip('/') + '/'
    mount = urlsplit(mount_path)
    if (mount.scheme or mount.netloc or mount.query or mount.fragment or
            not mount.path.startswith('/') or '\\' in unquote(mount.path) or
            '..' in Path(unquote(mount.path)).parts or any(ord(char) < 32 for char in mount_path)):
        raise ValueError('bookshelf mount must be a local absolute URL path')
    mount_path = mount.path.rstrip('/') + '/'
    original_bytes = source.read_bytes()
    original = original_bytes.decode('utf-8')
    if re.search(r'<base\b', original, re.I):
        raise ValueError('source bookshelf already declares a resource base')
    source_links = _ShelfBrowseLinks(original)
    links = source_links.links
    # A service-root base retains existing assets and downloads. Fragment-only
    # links must name this mounted page so they do not jump to the old root.
    replacements = {(start, end): html.escape(mount_path + 'index.html' + fragment, quote=True)
                    for start, end, fragment in source_links.fragments}
    identities = set()
    for entry in entries:
        identity, href = entry['study_book_id'], entry['href']
        if not isinstance(identity, str) or not identity or identity in identities:
            raise ValueError('bookshelf stable study IDs must be unique text')
        identities.add(identity)
        if identity not in links:
            raise ValueError('book is missing from the original bookshelf configuration')
        if not isinstance(href, str):
            raise ValueError('shelf links must be relative text URLs')
        url = urlsplit(href)
        path = unquote(url.path)
        if (not path or url.scheme or url.netloc or url.query or url.fragment or
                path.startswith('/') or '\\' in path or '..' in Path(path).parts or
                any(ord(char) < 32 for char in href)):
            raise ValueError('shelf links must stay within the relative book directory')
        start, end = links[identity]
        replacements[(start, end)] = html.escape(mount_path + href, quote=True)
    page = original
    for (start, end), href in sorted(replacements.items(), reverse=True):
        page = page[:start] + href + page[end:]
    base = '<base href="' + html.escape(service_origin + '/', quote=True) + '">'
    redirect = ('<script>(function(){const target=new URL(' + _json(mount_path + 'index.html') + ',' +
                _json(service_origin) + ');if(location.origin!==target.origin){target.search=location.search;'
                'target.hash=location.hash;location.replace(target.href)}})();</script>')
    page, inserted = re.subn(r'<head(?:\s[^>]*)?>', lambda match: match[0] + base + redirect,
                             page, count=1, flags=re.I)
    if inserted != 1:
        raise ValueError('original bookshelf needs a head element')
    raw = page.encode('utf-8')
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=root, prefix='.shelf-', delete=False) as stream:
        staging = Path(stream.name)
        stream.write(raw)
    try:
        os.replace(staging, root / 'index.html')
    finally:
        staging.unlink(missing_ok=True)
    return {'schema': 'study-web-shelf.v2', 'books': len(entries), 'path': str(root / 'index.html'),
            'sha256': hashlib.sha256(raw).hexdigest(), 'source': str(source),
            'source_sha256': hashlib.sha256(original_bytes).hexdigest(),
            'stable_study_ids': sorted(identities), 'service_origin': service_origin,
            'mount_path': mount_path, 'progress_service': '/api/study/overview',
            'original_dom_preserved_except_browse_and_local_fragment_hrefs': True,
            'local_fragment_links': len(source_links.fragments)}


def card_shell(payload: str, base: str) -> str:
    """Mount exactly one authored side, with resources resolved before parsing.

    The JSON literal is the shared renderer's exact output, not a second field
    renderer. Refreshing an existing export passes that same literal through.
    """
    original_base = '<base href="' + html.escape(base, quote=True) + '">'
    return ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<style>html,body{margin:0;height:100%;background:#f5f7fc}#study-side{border:0;width:100%;height:100%}'
        '#study-flip{position:fixed;right:12px;top:10px;z-index:99999;border:1px solid #dbe3ef;border-radius:6px;'
        'padding:8px 12px;background:white;color:#215fbb;font:14px system-ui;cursor:pointer}</style></head><body>'
        '<button id="study-flip" type="button" aria-pressed="false">显示答案</button><iframe id="study-side" title="学习卡片正面"></iframe>'
        '<script>const absoluteBase=document.createElement("base");absoluteBase.href=new URL(' + _json(base) + ',location.href);'
        'const sides=' + payload + '.map(content=>content.replace(' + _json(original_base) + ',absoluteBase.outerHTML));'
        'let answer=false;const side=document.getElementById("study-side"),flip=document.getElementById("study-flip");'
        'function show(){side.srcdoc=sides[answer?1:0];side.title=answer?"学习卡片背面":"学习卡片正面";flip.textContent=answer?"返回正面":"显示答案";'
        'flip.setAttribute("aria-pressed",String(answer))}flip.onclick=()=>{answer=!answer;show()};'
        'function key(e){if(e.target.matches("input,select,textarea,button,summary,a,[contenteditable]"))return;'
        'if(e.code==="Space"){e.preventDefault();flip.click()}if(e.key==="ArrowLeft"||e.key==="ArrowRight")'
        '{e.preventDefault();parent.postMessage({type:"study-navigate",direction:e.key==="ArrowRight"?1:-1},location.origin)}}'
        'document.addEventListener("keydown",key);side.onload=()=>{side.contentDocument.addEventListener("keydown",key)};show();</script></body></html>')


def write_library(root: Path, catalog: dict, metadata: dict | None = None) -> dict:
    """Write a versioned navigation index and common host assets.

    Content addressed names let ordinary HTTP caches reuse the host without a
    service worker, cache invalidation rule, or a second content renderer.
    """
    navigation = navigation_index(catalog, metadata)
    payload = _json(navigation).encode()
    nav_name = '_study_navigation_' + hashlib.sha256(payload).hexdigest() + '.json'
    runtime = HOST_RUNTIME.encode()
    runtime_name = '_study_library_' + hashlib.sha256(runtime).hexdigest() + '.js'
    (root / nav_name).write_bytes(payload)
    compressed = gzip.compress(payload, compresslevel=9, mtime=0)
    (root / (nav_name + '.gz')).write_bytes(compressed)
    (root / runtime_name).write_bytes(runtime)
    initial = next((row for row in navigation['cards'] if row[7]), navigation['cards'][0] if navigation['cards'] else None)
    (root / 'index.html').write_text(library_html(catalog['title'], navigation_href=nav_name,
                                               navigation_gzip_href=nav_name + '.gz', initial=initial,
                                               total=navigation['totals']['cards'], totals=navigation['totals'],
                                               initial_path=navigation['units'][initial[3]] if initial else ''))
    return {'navigation_bytes': len(payload), 'navigation_cards': len(navigation['cards']),
            'runtime_bytes': len(runtime), 'navigation_gzip_bytes': len(compressed)}


def card_payload(page: bytes) -> bytes:
    """Read the JSON array boundary without mistaking quoted card text for JS."""
    prefix = b'<script>const sides='
    marker = page.find(prefix)
    if marker < 0:
        # This is the shared v2 shell, with its base prepared before the array.
        marker = page.find(b'<script>const absoluteBase=')
        if marker < 0:
            raise ValueError('source card has an unsupported browser wrapper')
        marker = page.find(b'const sides=', marker)
        if marker < 0:
            raise ValueError('source card is missing the common side payload')
        start = marker + len(b'const sides=')
        expected_suffix = '.map(content=>content.replace('
    else:
        start = marker + len(prefix)
        expected_suffix = ';let answer=false;const side='
    source = page[start:].decode('utf-8')
    try:
        sides, end = json.JSONDecoder().raw_decode(source)
    except json.JSONDecodeError as error:
        raise ValueError('source card has an invalid side payload') from error
    if not isinstance(sides, list) or len(sides) != 2 or not all(isinstance(side, str) for side in sides):
        raise ValueError('source card has an unsupported side payload')
    if not source[end:].startswith(expected_suffix):
        raise ValueError('source card is missing the common flip wrapper')
    # raw_decode locates the end by JSON syntax. This is the exact source
    # literal, not a serialization of the decoded sides.
    return source[:end].encode('utf-8')


def upgrade_card_base(page: bytes) -> bytes:
    """Absolutize the common wrapper base while keeping its payload byte exact.

    Chromium's speculative loader can request srcdoc resources against the
    parent card URL before resolving a relative base. An absolute srcdoc base
    avoids the failed first request. This adapter changes only the enclosing
    wrapper; it neither parses nor serializes the authored front/back payload.
    """
    if b'<script>const absoluteBase=' in page:
        card_payload(page)
        return page
    payload = card_payload(page)
    # Both refreshes and new PostgreSQL exports use this exact host generator.
    result = card_shell(payload.decode('utf-8'), '../media/').encode()
    if payload not in result:
        raise AssertionError('card refresh changed the authored side payload')
    return result


def refresh_library(source: Path, destination: Path, *, expected_revision: int | None = None,
                    upgrade_card_bases: bool = False, metadata: dict | None = None, callback=None) -> dict:
    """Publish the new common host around a complete, immutable web export.

    Cards, media and the complete catalog stay in their original export. Only
    small navigation/host files are generated; relative directory symlinks do
    not duplicate thousands of media files or revise source card fields. The
    original export must be retained alongside this local host refresh.
    """
    source = Path(source).resolve(strict=True)
    destination = Path(destination)
    # macOS /var and /tmp can be symlinked parents. Compute link paths against
    # the actual parent so they still resolve after staging publication.
    destination = destination.parent.resolve() / destination.name
    if destination.exists() or destination.is_symlink():
        raise FileExistsError('refreshed web destination already exists')
    if destination.is_relative_to(source):
        raise ValueError('refreshed host must not be written inside its source export')
    marker_raw = (source / 'COMPLETE.json').read_bytes()
    marker = json.loads(marker_raw)
    catalog_raw = (source / 'catalog.json').read_bytes()
    catalog = json.loads(catalog_raw)
    if marker.get('format') != 'web' or catalog.get('schema') != 'shared-book-web.v1':
        raise ValueError('source is not a complete common web export')
    if marker.get('cards') != len(catalog['cards']):
        raise ValueError('source completion marker has a different card count')
    if expected_revision is not None and catalog.get('catalog_revision') != expected_revision:
        raise ValueError('source catalog revision differs from the approved source')
    for name in ('cards', 'media'):
        if not (source / name).is_dir():
            raise ValueError('source export is missing its ' + name + ' directory')
    ids = set()
    for card in catalog['cards']:
        path = (source / card['url']).resolve()
        if not path.is_relative_to((source / 'cards').resolve()) or not path.is_file():
            raise ValueError('source catalog has an unsafe or missing card')
        if card['id'] in ids:
            raise ValueError('source catalog repeats a native card identity')
        ids.add(card['id'])
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.study-host-', dir=destination.parent) as staging:
        staging = Path(staging)
        for name in ('media', 'catalog.json', *(() if upgrade_card_bases else ('cards',))):
            # Staging and destination have equal depth under the same parent.
            (staging / name).symlink_to(os.path.relpath(source / name, destination),
                                      target_is_directory=name != 'catalog.json')
        upgraded = 0
        if upgrade_card_bases:
            (staging / 'cards').mkdir()
            for number, card in enumerate(catalog['cards'], 1):
                raw = (source / card['url']).read_bytes()
                revised = upgrade_card_base(raw)
                target = staging / card['url']
                # Card URLs have already been bounded to the source cards
                # directory above. They must also stay in the new directory.
                if not target.resolve().is_relative_to((staging / 'cards').resolve()):
                    raise ValueError('source card URL cannot be reused in refreshed export')
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(revised)
                upgraded += revised != raw
                if callback and number % 500 == 0:
                    callback({'stage': 'refresh-card-host', 'completed': number,
                              'cards': len(catalog['cards'])})
        navigation = write_library(staging, catalog, metadata)
        report = {**marker, **navigation, 'schema': 'study-web-host-refresh.v1',
                  'host_version': 'study-web-host.v3',
                  'host_runtime_sha256': hashlib.sha256(HOST_RUNTIME.encode()).hexdigest(),
                  'source_export': os.path.relpath(source, destination),
                  'source_catalog_revision': catalog.get('catalog_revision'),
                  'source_catalog_sha256': hashlib.sha256(catalog_raw).hexdigest(),
                  'source_complete_sha256': hashlib.sha256(marker_raw).hexdigest(),
                  'reused_cards_and_media': 'exact-payload-new-card-hosts' if upgrade_card_bases else 'relative-symlink',
                  'upgraded_card_bases': upgraded,
                  'generator': 'anki_pipeline.study_catalog_web.refresh_library'}
        destination.mkdir()
        for child in staging.iterdir():
            shutil.move(str(child), destination / child.name)
        # No successful-looking marker is visible for a partially moved host.
        (destination / 'COMPLETE.json').write_text(_json(report))
    return {**report, 'output': str(destination)}


def redirect_library_entry(source: Path, destination: Path) -> dict:
    """Retain an existing URL after an immutable common-host refresh.

    The old index is recoverable by its SHA. Catalog, cards, media and completion
    markers remain untouched; query parameters and card/deck hashes pass through.
    """
    source, destination = source.resolve(strict=True), destination.resolve(strict=True)
    if source == destination:
        raise ValueError('entry redirect requires a different complete host')
    marker = json.loads((destination / 'COMPLETE.json').read_bytes())
    if marker.get('format') != 'web' or marker.get('host_version') != 'study-web-host.v3':
        raise ValueError('entry destination is not a complete current common host')
    for name in ('cards', 'media'):
        if (source / name).resolve(strict=True) != (destination / name).resolve(strict=True):
            raise ValueError('entry redirect must retain the original cards and media')
    if (source / 'catalog.json').read_bytes() != (destination / 'catalog.json').read_bytes():
        raise ValueError('entry redirect must retain the exact original catalog')
    page = source / 'index.html'
    original = page.read_bytes()
    digest = hashlib.sha256(original).hexdigest()
    backup = source / ('index.before-host-v3.' + digest + '.html')
    if backup.exists():
        if backup.read_bytes() != original:
            raise ValueError('entry backup differs from the original index')
    else:
        with backup.open('xb') as stream:
            stream.write(original)
    href = Path(os.path.relpath(destination / 'index.html', source)).as_posix()
    body = ('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>正在打开学习目录</title><p><a href="' + html.escape(href, quote=True) + '">打开学习目录</a></p>'
            '<script>const target=new URL(' + _json(href) + ',location.href);'
            'target.search=location.search;target.hash=location.hash;location.replace(target.href);</script></html>').encode()
    with tempfile.NamedTemporaryFile(dir=source, prefix='.index-redirect-', delete=False) as stream:
        staging = Path(stream.name)
        stream.write(body)
    try:
        if page.read_bytes() != original:
            raise ValueError('entry changed during redirect preparation; original was retained')
        os.replace(staging, page)
    finally:
        staging.unlink(missing_ok=True)
    return {'source': str(source), 'destination': str(destination), 'backup': str(backup),
            'original_index_sha256': digest, 'redirect_index_sha256': hashlib.sha256(body).hexdigest(),
            'relative_target': href, 'preserves_query_and_hash': True}


def library_html(title: str, *, navigation_href: str = 'navigation.json',
                 runtime_href: str | None = None, navigation_gzip_href: str | None = None,
                 initial: list | None = None, total: int = 0, totals: dict | None = None,
                 initial_path: str = '') -> str:
    """Use the original three-column/drawer layout with bounded live rows."""
    config = _json({'navigation': navigation_href, 'navigationGzip': navigation_gzip_href,
                    'initial': initial, 'total': total, 'totals': totals, 'initialPath': initial_path})
    stylesheet = (Path(__file__).parent / 'templates' / 'library-preview.css').read_text()
    stylesheet = stylesheet.replace('#card-frame', '#frame')
    stylesheet += '.word-list .virtual-spacer{padding:0;margin:0;border:0;pointer-events:none}.word-list{overflow-anchor:none}#frame{border:0}#status:empty{display:none}'
    runtime = ('<script defer src="' + html.escape(runtime_href, quote=True) + '"></script>'
               if runtime_href else '<script>' + HOST_RUNTIME + '</script>')
    return '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>' + html.escape(title) + '</title><style>' + stylesheet + '</style></head><body>' + '''
<header class="library-header"><button id="browse-toggle" class="small-button browse-toggle" aria-controls="browse-panel" aria-expanded="false">目录</button><div class="library-heading"><h1 id="library-name">''' + html.escape(title) + '''</h1><p id="library-summary" role="status">正在加载目录…</p></div><div class="card-toolbar" aria-label="卡片导航"><button id="guide-card" class="small-button" hidden>说明</button><span id="card-position" class="card-position" aria-live="polite"></span><button id="previous-card" class="small-button" aria-label="上一张卡片" title="上一张（←）" disabled>上一张</button><button id="next-card" class="small-button" aria-label="下一张卡片" title="下一张（→）" disabled>下一张</button><button id="flip-card" class="small-button primary-button" aria-pressed="false" title="翻面（空格）" disabled>显示答案</button></div></header>
<div class="catalog-failure" id="catalog-failure" hidden><p id="status" role="status"></p><button id="retry" class="small-button" hidden>重新读取目录</button></div>
<main class="library-workspace"><div id="browse-backdrop" class="browse-backdrop" hidden></div><aside id="browse-panel" class="browse-panel" aria-label="卡组和单词目录"><nav class="deck-panel" aria-labelledby="decks-heading"><div class="panel-heading"><h2 id="decks-heading">卡组</h2><button id="browse-close" class="small-button browse-close" aria-label="关闭目录">关闭</button></div><div id="deck-tree" class="deck-tree"></div></nav><section class="word-panel" aria-labelledby="words-heading"><div class="word-search-panel"><div class="panel-heading"><h2 id="words-heading">单词</h2><span id="word-count" class="muted"></span></div><label class="visually-hidden" for="word-search">在当前卡组中搜索单词或释义</label><div class="search-field"><input id="word-search" type="search" placeholder="搜索单词或释义" aria-label="在当前卡组中搜索单词或释义" autocomplete="off" spellcheck="false" disabled><button id="clear-search" aria-label="清空搜索" hidden>清空</button></div></div><p id="word-empty" class="word-empty" role="status" hidden>没有匹配的单词。清空搜索或选择其他卡组。</p><ul id="word-list" class="word-list" aria-label="单词列表"></ul></section></aside><section id="card-stage" class="card-stage" tabindex="-1" aria-labelledby="deck-path"><div class="reader-heading"><p id="deck-path">全部卡组</p><span class="shortcut-hint">← → 切卡 · 空格翻面</span></div><div class="frame-area"><div id="frame-host" class="frame-host"><iframe id="frame" title="学习卡片"></iframe></div><p id="empty" class="card-status" role="status" hidden>没有匹配的内容</p></div></section></main>
<script id="study-library-config" type="application/json">''' + config + '''</script><script>(function(){const c=JSON.parse(document.getElementById('study-library-config').textContent),wanted=new URLSearchParams(location.hash.slice(1)).get('card');if(c.initial&&(!wanted||wanted===c.initial[0])){const f=document.getElementById('frame');f.src=c.initial[4];f.dataset.studyCardId=c.initial[0];document.getElementById('card-position').textContent='1 / '+c.total;document.getElementById('deck-path').textContent=c.initialPath}})();</script>''' + runtime + '</body></html>'


HOST_RUNTIME = r'''(function(){
'use strict';
const $=id=>document.getElementById(id),frame=$('frame'),list=$('word-list'),query=$('word-search'),panel=$('browse-panel');
const config=JSON.parse($('study-library-config').textContent),lower=value=>value.toLocaleLowerCase(),count=value=>Number(value).toLocaleString();
let all=[],entries=[],visible=[],units=[],byId=new Map(),byUnit=new Map(),selected=null,selectedIndex=-1,selectedDeck='',loaded=false,loading=false,browseOpen=false;
let offsets=[0],heights=new Map(),renderStart=-1,renderEnd=-1,scrollScheduled=false,measuring=false;
const rowEstimate=91,interactive='input,select,textarea,button,summary,a,[contenteditable]',media=window.matchMedia?window.matchMedia('(max-width: 900px)'):null;
const narrow=()=>media?media.matches:window.innerWidth<=900,requested=()=>new URLSearchParams(location.hash.slice(1)).get('card');
function node(tag,cls,text){const el=document.createElement(tag);if(cls)el.className=cls;if(text!==undefined)el.textContent=text;return el}
function safeURL(value){const url=new URL(value,location.href);if(url.origin!==location.origin||url.protocol!==location.protocol)throw Error('目录中的卡片地址无效');return url.href}
function drawer(open){browseOpen=Boolean(open)&&narrow();panel.hidden=narrow()&&!browseOpen;$('browse-backdrop').hidden=!browseOpen;$('browse-toggle').setAttribute('aria-expanded',String(browseOpen))}
$('browse-toggle').onclick=()=>drawer(!browseOpen);$('browse-close').onclick=()=>drawer(false);$('browse-backdrop').onclick=()=>drawer(false);media?.addEventListener('change',()=>drawer(false));drawer(false);
function updateHash(id){const params=new URLSearchParams({card:id});if(selectedDeck!=='')params.set('deck',selectedDeck);const hash=params.toString();if(location.hash.slice(1)!==hash)location.hash=hash}
function controls(){selectedIndex=visible.findIndex(card=>card.id===selected);$('card-position').textContent=count(selectedIndex+1)+' / '+count(visible.length);$('previous-card').disabled=selectedIndex<=0;$('next-card').disabled=selectedIndex<0||selectedIndex>=visible.length-1;$('word-count').textContent=count(visible.length);$('flip-card').disabled=!selected;}
function empty(){selected=null;selectedIndex=-1;frame.hidden=true;frame.removeAttribute('src');delete frame.dataset.studyCardId;$('empty').hidden=false;$('word-empty').hidden=false;$('flip-card').textContent='显示答案';$('flip-card').setAttribute('aria-pressed','false');controls()}
function offsetsForRows(){offsets=[0];for(const card of visible)offsets.push(offsets[offsets.length-1]+(heights.get(card.id)||rowEstimate))}
function indexAt(y){let low=0,high=visible.length;while(low<high){const mid=(low+high)>>1;if(offsets[mid+1]<=y)low=mid+1;else high=mid}return low}
function renderRows(force=false,target=null){const at=indexAt(target??list.scrollTop),start=Math.max(0,at-15),end=Math.min(visible.length,start+90);if(!force&&start===renderStart&&end===renderEnd)return;renderStart=start;renderEnd=end;const fragment=document.createDocumentFragment();
function spacer(height){const el=node('li','virtual-spacer');el.style.height=height+'px';el.setAttribute('aria-hidden','true');return el}fragment.append(spacer(offsets[start]||0));
for(let i=start;i<end;i++){const card=visible[i],li=node('li'),b=node('button','word-entry');b.type='button';b.dataset.cardId=card.id;b.setAttribute('aria-current',String(card.id===selected));b.append(node('span','word-entry-name',card.label),node('span','word-entry-definition',card.summary),node('span','word-entry-meta',card.examples===null?'例句数未确认':count(card.examples)+' 例句'));b.onclick=()=>open(card,{close:true});li.append(b);fragment.append(li)}fragment.append(spacer((offsets[visible.length]||0)-(offsets[end]||0)));list.replaceChildren(fragment);if(target!==null)list.scrollTop=target;
if(!measuring){measuring=true;requestAnimationFrame(()=>{measuring=false;const anchor=indexAt(list.scrollTop),old=offsets[anchor]||0;let changed=false;for(const b of list.querySelectorAll('.word-entry')){const height=b.parentElement.getBoundingClientRect().height;if(height>0&&Math.abs(height-(heights.get(b.dataset.cardId)||rowEstimate))>.5){heights.set(b.dataset.cardId,height);changed=true}}if(changed){offsetsForRows();list.scrollTop+=(offsets[anchor]||0)-old;renderRows(true)}})}}
list.addEventListener('scroll',()=>{if(!scrollScheduled){scrollScheduled=true;requestAnimationFrame(()=>{scrollScheduled=false;renderRows()})}},{passive:true});
function draw({rebuild=false,ensure=false}={}){controls();let target=rebuild?0:null;if(rebuild){offsetsForRows();renderStart=-1;renderEnd=-1}if(ensure&&selectedIndex>=0){const top=offsets[selectedIndex],bottom=offsets[selectedIndex+1],height=list.clientHeight||400,current=target??list.scrollTop;if(top<current||bottom>current+height)target=Math.max(0,top-30)}renderRows(true,target);for(const b of $('deck-tree').querySelectorAll('.deck-entry'))b.setAttribute('aria-current',b.dataset.deckKey===selectedDeck?'page':'false')}
function open(card,{hash=true,close=false,rebuild=false}={}){if(!card){empty();draw({rebuild});return}selected=card.id;frame.hidden=false;$('empty').hidden=true;$('word-empty').hidden=true;$('deck-path').textContent=units[card.unit];if(frame.dataset.studyCardId!==card.id){frame.dataset.studyCardId=card.id;frame.src=safeURL(card.url);$('flip-card').textContent='显示答案';$('flip-card').setAttribute('aria-pressed','false')}if(hash)updateHash(card.id);draw({rebuild,ensure:true});if(close)drawer(false)}
function filter({deckChanged=false}={}){const q=lower(query.value.trim()),source=selectedDeck===''?all:(byUnit.get(Number(selectedDeck))||[]);visible=q?source.filter(card=>card.search.includes(q)):source;$('clear-search').hidden=!q;if(!visible.some(card=>card.id===selected))open(visible.find(card=>lower(card.word)===q)||visible[0],{rebuild:true});else draw({rebuild:true,ensure:deckChanged})}
function chooseDeck(key){selectedDeck=key;filter({deckChanged:true});if(selected)updateHash(selected)}
function decks(){const fragment=document.createDocumentFragment(),groups=new Map();function button(key,label,total){const b=node('button','deck-entry');b.type='button';b.dataset.deckKey=key;b.append(node('span','',label),node('span','entry-count',count(total)));b.onclick=()=>chooseDeck(key);return b}fragment.append(button('','全部卡组',all.length));units.forEach((path,index)=>{if(!byUnit.has(index))return;const parts=path.split('::').slice(1),label=parts.pop()||path,group=parts.join(' / ')||'未分组';if(!groups.has(group))groups.set(group,[]);groups.get(group).push({index,label,count:(byUnit.get(index)||[]).length})});for(const[group,entries]of groups){const details=node('details','unit-group');details.open=true;const summary=node('summary','',group);summary.append(node('span','entry-count',count(entries.reduce((total,x)=>total+x.count,0))));const lessons=node('ul','lesson-list');for(const entry of entries){const li=node('li');li.append(button(String(entry.index),entry.label,entry.count));lessons.append(li)}details.append(summary,lessons);fragment.append(details)}$('deck-tree').replaceChildren(fragment)}
function navigate(direction){if(!loaded)return;const card=visible[selectedIndex+direction];if(card)open(card)}
function flip(){if(frame.hidden)return;frame.contentDocument?.getElementById('study-flip')?.click();syncFlip()}
function syncFlip(){const b=frame.contentDocument?.getElementById('study-flip'),answer=b?.getAttribute('aria-pressed')==='true';$('flip-card').textContent=answer?'返回正面':'显示答案';$('flip-card').setAttribute('aria-pressed',String(answer))}
frame.addEventListener('load',()=>{const b=frame.contentDocument?.getElementById('study-flip');if(b){b.style.display='none';b.addEventListener('click',syncFlip)}syncFlip()});
query.addEventListener('input',()=>filter());$('clear-search').onclick=()=>{query.value='';filter();query.focus()};$('previous-card').onclick=()=>navigate(-1);$('next-card').onclick=()=>navigate(1);$('flip-card').onclick=flip;
document.addEventListener('keydown',e=>{if(e.key==='Escape'){drawer(false);return}if(e.target.closest(interactive))return;if(e.key==='ArrowRight'||e.key==='ArrowLeft'){e.preventDefault();navigate(e.key==='ArrowRight'?1:-1)}if(e.code==='Space'&&!frame.hidden){e.preventDefault();flip()}});
window.addEventListener('message',e=>{if(e.source!==frame.contentWindow||e.origin!==location.origin||e.data?.type!=='study-navigate')return;if(e.data.direction===1||e.data.direction===-1)navigate(e.data.direction)});
window.addEventListener('hashchange',()=>{if(!loaded)return;const id=requested(),card=byId.get(id),deck=new URLSearchParams(location.hash.slice(1)).get('deck');if(!card)return;const desired=deck!==null&&card.listed?String(card.unit):'';if(id===selected&&desired===selectedDeck)return;query.value='';selectedDeck=desired;visible=!card.listed?[card]:(desired===''?all:byUnit.get(card.unit));offsetsForRows();open(card,{hash:false,rebuild:true})});
async function readNavigation(){if(config.navigationGzip&&typeof DecompressionStream==='function'){try{const r=await fetch(config.navigationGzip);if(!r.ok)throw Error('HTTP '+r.status);return await(r.headers.get('Content-Encoding')==='gzip'?r:new Response(r.body.pipeThrough(new DecompressionStream('gzip')))).json()}catch(error){console.warn('Study library compressed navigation unavailable:',error)}}const r=await fetch(config.navigation);if(!r.ok)throw Error('HTTP '+r.status);return r.json()}
async function load(){if(loading)return;loading=true;$('retry').hidden=true;$('status').textContent='正在读取目录…';try{const data=await readNavigation();if(data.schema!=='study-navigation.v2'||!Array.isArray(data.cards)||!Array.isArray(data.units))throw Error('目录格式无效');units=data.units;entries=data.cards.map(row=>{if(!Array.isArray(row)||row.length!==8||typeof row[0]!=='string'||typeof row[1]!=='string'||typeof row[2]!=='string'||!Number.isInteger(row[3])||row[3]<0||row[3]>=units.length||typeof row[4]!=='string'||typeof row[5]!=='string'||(row[6]!==null&&(!Number.isInteger(row[6])||row[6]<0))||typeof row[7]!=='boolean')throw Error('目录条目无效');safeURL(row[4]);return{id:row[0],word:row[1],label:row[2],unit:row[3],url:row[4],summary:row[5],examples:row[6],listed:row[7],search:lower(row[1]+' '+row[5])}});all=entries.filter(card=>card.listed);byId=new Map();byUnit=new Map();for(const card of entries){if(byId.has(card.id))throw Error('目录卡片重复');byId.set(card.id,card);if(!card.listed)continue;if(!byUnit.has(card.unit))byUnit.set(card.unit,[]);byUnit.get(card.unit).push(card)}decks();loaded=true;visible=all;query.disabled=false;$('catalog-failure').hidden=true;$('library-summary').textContent=count(all.length)+' 张卡 · '+count(data.totals?.groups??byUnit.size)+' 个卡组 · '+count(data.totals?.examples||0)+(data.totals?.unknown_example_cards?' 条已索引例句':' 条例句');const guides=entries.filter(card=>!card.listed);if(guides.length){$('guide-card').hidden=false;$('guide-card').onclick=()=>{visible=guides;selectedDeck='';open(guides[0],{rebuild:true})}}const first=byId.get(requested())||all[0],deck=new URLSearchParams(location.hash.slice(1)).get('deck');if(first&&!first.listed)visible=[first];if(first&&deck!==null&&first.listed){selectedDeck=String(first.unit);visible=byUnit.get(first.unit)}open(first,{rebuild:true})}catch(error){$('catalog-failure').hidden=false;$('status').textContent='目录暂时无法读取，请重试。';$('retry').hidden=false;console.error('Study library navigation:',error)}finally{loading=false}}
$('retry').onclick=load;load();
})();'''
