"""Escaped display markup for dictionary fields; never rewrite source data."""

import html
import re

_PARTS = re.compile(r"\s*[|\n]\s*")
_POS = re.compile(r"^(vt\.|vi\.|adj\.|adv\.|prep\.|pron\.|conj\.|interj\.|aux\.|num\.|det\.|abbr\.|n\.|v\.)\s*", re.I)


def _parts(text: str) -> list[str]:
    return [part.strip() for part in _PARTS.split(text) if part.strip()]


def render_senses(text: str) -> str:
    rows = []
    for part in _parts(text):
        match = _POS.match(part)
        if match and part[match.end():].strip():
            pos = html.escape(match.group(1), quote=True)
            meaning = html.escape(part[match.end():].strip(), quote=True)
            rows.append(f'<div class="sense-row"><span class="sense-pos">{pos}</span>'
                        f'<span class="sense-text">{meaning}</span></div>')
        else:
            rows.append('<div class="sense-row sense-unlabelled">'
                        + html.escape(part, quote=True) + '</div>')
    return ''.join(rows)


def render_levels(text: str) -> str:
    items = _parts(text)
    if not items:
        return ''
    return '<ul class="level-list" aria-label="考试等级">' + ''.join(
        '<li>' + html.escape(item, quote=True) + '</li>' for item in items
    ) + '</ul>'


def render_forms(text: str) -> str:
    rows = []
    for part in _parts(text):
        pair = re.split(r'[：:]', part, maxsplit=1)
        if len(pair) == 2 and all(value.strip() for value in pair):
            label, value = (html.escape(value.strip(), quote=True) for value in pair)
            rows.append(f'<dl class="form-row"><dt>{label}</dt><dd>{value}</dd></dl>')
        else:
            rows.append('<div class="form-unlabelled">' + html.escape(part, quote=True) + '</div>')
    return '<div class="forms-list">' + ''.join(rows) + '</div>' if rows else ''
