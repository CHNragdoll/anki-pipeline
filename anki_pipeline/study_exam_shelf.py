"""Append a locally delivered non-vocabulary book to the existing shelf.

Only an explicit marked supplementary section changes. Existing vocabulary
cards, scheduler identities, scripts and resource links retain their bytes.
"""
import html
import re
from urllib.parse import urlsplit, unquote


def _url(value):
    parsed = urlsplit(value)
    if (not value.startswith('/') or parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or
            '\\' in value or any(part == '..' for part in unquote(parsed.path).split('/'))):
        raise ValueError('shelf entry requires a local confined URL')
    return html.escape(value, quote=True)


def append_entry(source, *, identity, title, subtitle, subject, stats, browse, papers, package):
    if not re.fullmatch('[a-z0-9-]+', identity):
        raise ValueError('invalid supplementary shelf identity')
    start = '<!-- study-extra:' + identity + ':start -->'
    end = '<!-- study-extra:' + identity + ':end -->'
    escaped = {key: html.escape(value) for key, value in {'title': title, 'subtitle': subtitle, 'subject': subject, 'stats': stats}.items()}
    block = (start + '<section class="extra-study-section" aria-label="' + escaped['subject'] + '"><div class="books-heading"><h2>' + escaped['subject'] + '</h2></div><div class="book-grid"><article class="book book-red" data-extra-book="' + identity + '"><div class="book-heading"><div class="book-spine" aria-hidden="true"><span>真题</span><strong>' + escaped['subject'] + '</strong><span>整卷 · 逐题</span></div><div><h2>' + escaped['title'] + '</h2><p class="subtitle">' + escaped['subtitle'] + '</p></div></div><p class="book-stats">' + escaped['stats'] + '</p><a class="start-book" href="' + _url(browse) + '">浏览题目与答案 <span aria-hidden="true">→</span></a><div class="book-secondary"><a class="browse-book" href="' + _url(papers) + '">按年份整卷阅读</a><a class="download" download href="' + _url(package) + '">下载完整 Anki 卡包</a></div></article></div></section>' + end)
    if start in source:
        if source.count(start) != 1 or source.count(end) != 1:
            raise ValueError('ambiguous supplementary shelf section')
        a, b = source.index(start), source.index(end) + len(end)
        return source[:a] + block + source[b:]
    marker = '<details id="home-help"'
    if source.count(marker) != 1:
        raise ValueError('original bookshelf insertion anchor is missing or ambiguous')
    return source.replace(marker, block + '\n' + marker, 1)
