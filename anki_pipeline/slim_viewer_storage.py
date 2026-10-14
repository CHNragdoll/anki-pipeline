"""Share exact original iframe code without rewriting its vocabulary document.

Only canonically escaped srcdoc and plain original script/style blocks qualify.
The replacement remains in its original parse order, using local media assets.
Every field has a byte-exact inverse; unsupported documents remain untouched.
"""
from collections import Counter
from hashlib import sha256
from html import escape, unescape
from pathlib import Path
import re

from anki_pipeline.slim_apkg_content import _ATTR, _NAME, _TAG, apply


def digest(raw):
    return sha256(raw.encode('utf-8')).hexdigest()


def frames(raw):
    for match in _TAG.finditer(raw):
        opening = match[0]
        if not re.match(r'<iframe\b', opening, re.I):
            continue
        attributes = list(_ATTR.finditer(opening, _NAME.match(opening).end()))
        source = next((a for a in attributes if a[1].lower() == 'srcdoc'), None)
        if source is None or source[2] is None or source[2][:1] not in ('"', "'"):
            continue
        encoded = source[2][1:-1]
        decoded = unescape(encoded)
        # Preserve alternate entities and attribute quoting exactly. A base
        # element would change resolution of newly shared local resources.
        if escape(decoded, quote=True) != encoded or re.search(r'<base\b', decoded, re.I):
            continue
        begin = match.start() + source.start(2) + 1
        yield begin, begin + len(encoded), decoded


def code_blocks(document):
    for match in _TAG.finditer(document):
        block = match[0]
        tag = 'style' if block.startswith('<style>') and block.endswith('</style>') else 'script' if block.startswith('<script>') and block.endswith('</script>') else None
        if tag is None or len(block.encode('utf-8')) < 128:
            continue
        if tag == 'script' and re.search(r'document\s*\.\s*(?:currentScript|write|writeln|getElementsByTagName)', block):
            continue
        yield match.start(), match.end(), tag, block


def collect_blocks(raws, min_repetitions=2):
    counts = Counter()
    for raw in raws:
        for _, _, document in frames(raw):
            counts.update(block for _, _, _, block in code_blocks(document))
    return {block for block, count in counts.items() if count >= min_repetitions}


class ViewerStore:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.files = {}
        self.originals = {}

    def add(self, tag, block):
        pin = digest(block)
        suffix = 'css' if tag == 'style' else 'js'
        name = '_as_viewer_' + pin[:24] + '.' + suffix
        body = block[len('<' + tag + '>'):-len('</' + tag + '>')]
        path = self.folder / name
        if path.exists() and path.read_bytes().decode('utf-8') != body:
            raise ValueError('viewer asset collision or changed source')
        if not path.exists():
            path.write_bytes(body.encode('utf-8'))
        if tag == 'style':
            replacement = '<link rel="stylesheet" href="' + name + '">'
        else:
            replacement = '<script src="' + name + '"></script>'
        self.files[pin] = path
        self.originals[replacement] = (pin, tag, block)
        return replacement

    def read(self, replacement):
        pin, tag, original = self.originals[replacement]
        body = self.files[pin].read_bytes().decode('utf-8')
        actual = '<' + tag + '>' + body + '</' + tag + '>'
        if actual != original or digest(actual) != pin:
            raise ValueError('original viewer bytes changed')
        return actual


def factor_frames(raw, store, selected):
    edits = []
    for begin, end, document in frames(raw):
        replacements = [(left, right, store.add(tag, block)) for left, right, tag, block in code_blocks(document) if block in selected]
        if replacements:
            revised = apply(document, replacements)
            edits.append((begin, end, escape(revised, quote=True)))
    return apply(raw, edits)


def restore_frames(raw, store):
    edits = []
    for begin, end, document in frames(raw):
        replacements = []
        for match in _TAG.finditer(document):
            replacement = match[0]
            if replacement in store.originals:
                replacements.append((match.start(), match.end(), store.read(replacement)))
        if replacements:
            edits.append((begin, end, escape(apply(document, replacements), quote=True)))
    return apply(raw, edits)
