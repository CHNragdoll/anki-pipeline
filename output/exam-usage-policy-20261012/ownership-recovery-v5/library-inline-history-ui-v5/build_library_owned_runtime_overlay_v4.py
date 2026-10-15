"""Prepare a reviewable additive two-shell/one-JS candidate, then ROOT-only apply.

All writes are exclusive new files inside this owned folder. Frozen helpers,
source shells/catalogs/cards/archives/DB are never opened for writing. The
combined JS changes only two lifecycle hooks in the accepted history candidate.
"""
from __future__ import annotations
import argparse
import difflib
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil

OWN = Path(__file__).resolve().parent
REPO = OWN.parents[3]
SOURCE = OWN.parent / 'owner-source-display-v5/final-overlay'
OUTPUT = OWN / 'runtime-candidate-overlay-v4'
URL = '/exam-usage-policy-20261012/ownership-recovery-v5/library-inline-history-ui-v5/runtime-candidate-overlay-v4/library-preview.js'
BASE_SHA = 'e8d394af2f5495c86c669f8f5eaeb647be5d388a4206fe1100d70e85b78b8a1e'
PINS = {
    OWN / 'library-preview-inline-history.js': BASE_SHA,
    OWN / 'chunk-fine-only-runtime.js': '3431f1db7de02878f82a64a7495fd971b4d6ad8c698ab39a6b804ab80f485c16',
    OWN / 'fine-display-projection-runtime-v3.js': '604054e469fca217c8eeef30134c77bcf34b068169ab9de640439ad95f652df0',
    OWN.parent / 'same-sense-group-own/same-sense-group-runtime.js': '65ccda70243f22c69326a9bb824c82fe1ad2eb9dd3cbe723569f0f632f426357',
    REPO / 'output/exam-usage-policy-20261012/shared-reading-bank-v5-own/shared-reading-bank-runtime-v5-v2.js': '8982bdec9d37dba2669d4738acd5cd69b9e1b6522084be094824df2a23238d6d',
    SOURCE / 'overlay-manifest.json': 'c069e7e23f96630fdc66908962ff046d853166bd1eb283c5bf3b4efe25acc734',
    SOURCE / 'redbook/preview-library.html': '0270d23cf5fe0067b1bb07011be26324157f000af8c89008c15f00a95eb80a99',
    SOURCE / 'redbook2027/preview-library.html': 'fe6cd9769b6c9c99873123344421461a8cd55c20d875516a42e1ff6df5d2b2b8',
    SOURCE / 'redbook/catalog.json': 'e6f29a52f155162b024ac03110b61ae7ea990833779b02eb7964313c93f90b30',
    SOURCE / 'redbook2027/catalog.json': '7a4bf232caedf722d89eb656f40496519087f4b0f518b69321dd77f5464591e8',
    REPO / 'output/exam-usage-policy-20261012/derived-chunk-display-projection/merge-own/candidate-v1/projection.json': 'de893f8518063d999c033854f33d1bde59ff2f6c20615ea61b89a753745af2c8',
    REPO / 'output/exam-usage-policy-20261012/shared-reading-bank-v5-own/shared-reading-bank-v5.json': 'af3e69641213564226f92b44c0192afc1e3bbf3cd30ac4d101885d06f6fefab5',
}

def require(value, message):
    if not value:
        raise ValueError(message)

def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode()).hexdigest()

def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)

def read(path, expected=None):
    path = Path(path).resolve(strict=True)
    require(path.suffix not in {'.sqlite3', '.db'}, 'database reads/hashes forbidden')
    raw = path.read_bytes()
    if expected is not None:
        require(sha(raw) == expected, f'input pin drift: {path}')
    return raw

def pin(path):
    return {'file': str(Path(path).resolve(strict=True)), 'sha256': sha(read(path))}

def write_new(path, raw):
    path = Path(path)
    require(path.parent.resolve().is_relative_to(OWN), 'only owned new files permitted')
    with path.open('xb') as stream:
        stream.write(raw)

def combined(base, extension, helpers):
    require(sha(base) == BASE_SHA, 'accepted history candidate drift')
    text = base.decode()
    edits = [
        ("    cardDocument.addEventListener('click', click);", "    cardDocument.addEventListener('click', click, true);"),
        ("      disposed = true; cardDocument.removeEventListener('click', click);", "      disposed = true; cardDocument.removeEventListener('click', click, true);"),
        ("    if (target && target.closest && target.closest('input, textarea, select, button, a[href], summary, audio, video, [contenteditable]:not([contenteditable=\"false\"])')) return;",
         "    if (target && target.closest && target.closest('[data-reviewed-chunk-projection]') && (event.key === ' ' || event.key === 'Spacebar' || event.key === 'Enter')) return;\n    if (target && target.closest && target.closest('input, textarea, select, button, a[href], summary, audio, video, [contenteditable]:not([contenteditable=\"false\"])')) return;"),
        ('  function constrainCardDocument(cardDocument) {', extension.decode() + '\n  function constrainCardDocument(cardDocument) {'),
        ('    if (old.historyCleanup) old.historyCleanup();', '    if (old.runtimeCleanup) old.runtimeCleanup();\n    if (old.historyCleanup) old.historyCleanup();'),
        ('        state.historyCleanup = installInlineHistory(cardDocument, cardsById, selectCard, function () { return frameIsCurrent(state); });',
         '        state.historyCleanup = installInlineHistory(cardDocument, cardsById, selectCard, function () { return frameIsCurrent(state); });\n        if (state.runtimeCleanup) state.runtimeCleanup();\n        state.runtimeCleanup = installOwnedCardRuntime(state, cardDocument);'),
    ]
    revised = text
    for old, new in edits:
        require(revised.count(old) == 1, 'lifecycle hook not unique')
        revised = revised.replace(old, new, 1)
    inverse = revised
    for old, new in reversed(edits):
        require(inverse.count(new) == 1, 'inverse hook not unique')
        inverse = inverse.replace(new, old, 1)
    require(inverse.encode() == base, 'accepted history JS inverse not exact')
    return b'\n'.join(helpers) + b'\n' + revised.encode(), revised.encode()

class Shell(HTMLParser):
    def __init__(self, text):
        super().__init__(); self.scripts=[]; self.bases=[]; self.catalogs=[]; self.feed(text)
    def handle_starttag(self, tag, attrs):
        require(len(dict(attrs)) == len(attrs), 'duplicate shell attributes')
        attrs = dict(attrs)
        if tag == 'script' and attrs.get('src', '').endswith('/library-preview.js'): self.scripts.append(attrs['src'])
        if tag == 'base': self.bases.append(attrs.get('href'))
        if tag == 'body': self.catalogs.append(attrs.get('data-catalog-url'))

def shell(raw):
    text = raw.decode(); parsed = Shell(text)
    require(len(parsed.scripts) == len(parsed.bases) == len(parsed.catalogs) == 1, 'exact source3 script/base/catalog required')
    require(re.fullmatch(r'composition/[a-f0-9]{64}/assets/library-preview\.js', parsed.scripts[0]), 'source3 JS asset route differs')
    old = 'src="' + parsed.scripts[0] + '"'; new = 'src="' + URL + '"'
    require(text.count(old) == 1, 'script src replacement not unique')
    revised = text.replace(old, new, 1)
    require(revised.replace(new, old, 1).encode() == raw, 'shell inverse differs')
    result = Shell(revised)
    require(result.bases == parsed.bases and result.catalogs == parsed.catalogs, 'base/catalog route changed')
    return revised.encode(), {'original_script': parsed.scripts[0], 'new_script': URL, 'base': parsed.bases[0], 'catalog': parsed.catalogs[0], 'inverse_exact': True}

def prepare():
    for path, expected in PINS.items(): read(path, expected)
    extension = read(OWN / 'library-owned-runtime-extension-v4.js')
    helpers = [read(path, PINS[path]) for path in [OWN/'chunk-fine-only-runtime.js', OWN/'fine-display-projection-runtime-v3.js', REPO/'output/exam-usage-policy-20261012/shared-reading-bank-v5-own/shared-reading-bank-runtime-v5-v2.js', OWN.parent/'same-sense-group-own/same-sense-group-runtime.js']]
    js, revised = combined(read(OWN/'library-preview-inline-history.js', BASE_SHA), extension, helpers)
    files = {'library-preview.js': js}; proofs = []
    for book in ['redbook', 'redbook2027']:
        source = SOURCE/book/'preview-library.html'; raw = read(source, PINS[source]); content, proof = shell(raw)
        files[book+'/preview-library.html'] = content; proofs.append(dict(proof, book=book, source=pin(source), result_sha256=sha(content)))
    manifest = {'schema':'library-owned-runtime-overlay-plan.v1', 'output':str(OUTPUT), 'code':pin(Path(__file__)), 'extension':pin(OWN/'library-owned-runtime-extension-v4.js'),
        'inputs':[{'file':str(path),'sha256':expected} for path,expected in PINS.items()], 'proofs':proofs, 'files':[{'file':name,'sha256':sha(raw),'bytes':len(raw)} for name,raw in sorted(files.items())],
        'accepted_history_inverse_exact':True,'cards_written':0,'catalogs_written':0,'archives_written':0,'database_reads':0,'database_writes':0,'rollback':'Stop using this new overlay URL. All original source3 shell bytes and routes remain unchanged.',
        'browser_accepted':False,'production_applied':False}
    diff = ''.join(difflib.unified_diff(read(OWN/'library-preview-inline-history.js').decode().splitlines(True), revised.decode().splitlines(True), fromfile='accepted-e8d-library-preview-inline-history.js',tofile='owned-combined-private-library-hooks.js'))
    return manifest, files, diff.encode()

def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--prepare',action='store_true'); parser.add_argument('--execute',action='store_true'); parser.add_argument('--plan-sha256'); args=parser.parse_args()
    require(args.prepare != args.execute, 'choose prepare or ROOT execute')
    manifest, files, diff = prepare(); raw=(canonical(manifest)+'\n').encode()
    if args.prepare:
        write_new(OWN/'library-preview-owned-runtime-v4.js',files['library-preview.js']); write_new(OWN/'owned-runtime-integration-v4.diff',diff); write_new(OWN/'owned-runtime-overlay-plan-v4.json',raw)
        print(canonical({'plan':pin(OWN/'owned-runtime-overlay-plan-v4.json'),'combined_js':pin(OWN/'library-preview-owned-runtime-v4.js'),'diff':pin(OWN/'owned-runtime-integration-v4.diff')})); return
    require(args.plan_sha256 == sha(raw), 'exact reviewed current plan SHA required')
    require(not OUTPUT.exists(), 'fresh owned overlay required')
    created=False
    try:
        OUTPUT.mkdir();created=True
        for name,content in files.items():
            dest=OUTPUT/name;dest.parent.mkdir(exist_ok=True);write_new(dest,content)
        for path,expected in PINS.items():read(path,expected)
        write_new(OUTPUT/'overlay-manifest.json',raw)
    except BaseException:
        if created:shutil.rmtree(OUTPUT)
        raise
    print(canonical({'output':str(OUTPUT),'manifest':pin(OUTPUT/'overlay-manifest.json'),'files':manifest['files']}))

if __name__ == '__main__': main()
