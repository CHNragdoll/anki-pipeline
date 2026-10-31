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


def broaden_header(source):
    """Rename only the old subject-specific shell copy, preserving its layout."""
    replacements = {
        '<title>词汇书架 · 学习与查阅</title>': '<title>学习书架 · 学习与查阅</title>',
        '<a class="brand" href="/">词汇书架</a>': '<a class="brand" href="/">学习书架</a>',
        '<span class="header-note">考研英语 · 真题例句</span>': '<span class="header-note">词书 · 整卷真题</span>',
        '<h1>今天，从一个词开始。</h1>': '<h1>今天，继续你的学习。</h1>',
        '<p>选书学习，或浏览全书查词。你的学习进度会自动保存。</p>': '<p>按科目选择内容：计划复习、整卷阅读或逐题翻面。</p>',
        '<h2>我的词书</h2>': '<h2>英语词书</h2>',
    }
    for original, revised in replacements.items():
        source = source.replace(original, revised, 1)
    return source
