"""Restore current disclosure bodies uniformly from sealed semantic sources."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
INPUT = ROOT / 'output/example-numbering-20261015'
BASELINE = ROOT / 'output/final-anki-20261015'
OWN = ROOT / 'output/inline-disclosures-20261015'
PINS = {'2026': 'a1d9615237e100f09247da0252baa78d6b40f6424d319ce29729f1c30492d750',
        '2027': '0d45380a4d9aaa2dbf1703f683034c43d15547e20c8795671f66e11e6a54bdb5'}
BASE_PINS = {'2026': '227399bbd6cfa2c8f268dda51034caa48bce957a9846b3c5306849cc3080d36b',
             '2027': '4a41e3e57ac9ea7563d3bb1223fa92474e92100484b2e98766c4a324a5ae4c46'}
FIELDS = ['Word','Phonetic','Definition','SimpleDefinition','Level','WordForms','Audio','Examples','Meta','Note']
SAMPLE_WORDS = frozenset({'abide', 'venture'})
REFS = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.-]*\.(?:js|css|png|jpe?g|gif|webp|svg|mp3|wav|ogg|m4a|woff2?|ttf)\b', re.I)
REGISTRY = re.compile(r'window\.AnkiSlimAssets=window\.AnkiSlimAssets\|\|\{\};window\.AnkiSlimAssets\["([a-f0-9]{64})"\]=(.*);', re.S)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def text_sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


class SampleMedia:
    """Follow actual media references, expanding packed data without execution."""
    def __init__(self, archive, mapping):
        self.archive = archive
        self.mapping = mapping
        self.keys = {name: key for key, name in mapping.items()}
        self.values = {}

    def literal(self, name, expected=None):
        raw = self.archive.read(self.keys[name]).decode('utf-8')
        match = REGISTRY.fullmatch(raw)
        if not match:
            raise ValueError('expected inert local registration: ' + name)
        value = json.loads(match[2])
        if not isinstance(value, str) or text_sha(value) != match[1] or expected and match[1] != expected:
            raise ValueError('local literal hash mismatch: ' + name)
        return value

    def logical(self, name):
        raw = self.archive.read(self.keys[name]).decode('utf-8')
        match = REGISTRY.fullmatch(raw)
        if not match:
            return raw, ()
        value = json.loads(match[2])
        dependencies = ()
        if isinstance(value, dict):
            if value.get('schema') != 'anki-slim-shared-strings.v1':
                raise ValueError('unknown packed schema')
            pin = value['dict']; dictionary = pin['src']
            bank = json.loads(self.literal(dictionary, pin['sha256']))
            if bank.get('schema') != 'anki-slim-shared-dictionary.v1':
                raise ValueError('invalid shared dictionary')
            from anki_pipeline.slim_shared_codec import expand
            value = expand(value['pieces'], bank['strings'])
            dependencies = (dictionary,)
        if not isinstance(value, str) or text_sha(value) != match[1]:
            raise ValueError('packed local string hash mismatch')
        # A dictionary is a decoding resource, not references from other cards.
        if value.startswith('{'):
            try:
                if json.loads(value).get('schema') == 'anki-slim-shared-dictionary.v1':
                    return '', dependencies
            except (ValueError, AttributeError):
                pass
        return value, dependencies

    def closure(self, roots):
        def references(raw):
            result = set()
            for name in REFS.findall(raw):
                # The shared transport deliberately maps logical _as names to
                # physical _ac files; include the preferred route and any old
                # literal fallback when both versions coexist.
                if re.fullmatch(r'_as_[a-f0-9]{24}\.js', name):
                    packed = name.replace('_as_', '_ac_', 1)
                    if packed in self.keys:
                        result.add(packed)
                if name in self.keys:
                    result.add(name)
            return result
        pending = set()
        for raw in roots:
            pending.update(references(raw))
        found = set()
        while pending:
            name = pending.pop()
            if name in found:
                continue
            found.add(name)
            if Path(name).suffix.lower() not in ('.js', '.css'):
                continue
            raw, dependencies = self.logical(name)
            pending.update(dependencies)
            pending.update(references(raw) - found)
        return {key: name for key, name in self.mapping.items() if name in found}


def write_package(archive, path, database, mapping):
    if path.exists():
        raise ValueError('never overwrite a generated package')
    with zipfile.ZipFile(path, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as target:
        target.write(database, 'collection.anki2')
        for key, name in mapping.items():
            info = copy.copy(archive.getinfo(key))
            with archive.open(key) as incoming, target.open(info, 'w') as outgoing:
                shutil.copyfileobj(incoming, outgoing, 1024 * 1024)
        target.writestr('media', json.dumps(mapping, ensure_ascii=False))


def build(year, sample=False):
    from anki_pipeline.inline_disclosures import restore_definition_disclosures
    started = time.monotonic()
    prior = json.loads((INPUT / year / 'build-report.json').read_text())
    source = Path(prior['output'])
    semantic = Path(prior['source'])
    assert sha(source) == prior['sha256'] == PINS[year]
    assert semantic.parent == BASELINE and sha(semantic) == BASE_PINS[year]
    folder = OWN / (year + '-sample' if sample else year)
    folder.mkdir(parents=True, exist_ok=False)
    pins = {str(path): sha(path) for path in (Path(__file__), ROOT / 'anki_pipeline/inline_disclosures.py',
                                           ROOT / 'anki_pipeline/slim_apkg_content.py')}
    with zipfile.ZipFile(source) as archive, zipfile.ZipFile(semantic) as original:
        for directory, packaged in ((INPUT, archive), (BASELINE, original)):
            with packaged.open('collection.anki2') as stream:
                assert hashlib.file_digest(stream, 'sha256').hexdigest() == sha(directory / year / 'collection.anki2')
        before = sqlite3.connect('file:' + str(INPUT / year / 'collection.anki2') + '?mode=ro', uri=True)
        baseline = sqlite3.connect('file:' + str(BASELINE / year / 'collection.anki2') + '?mode=ro', uri=True)
        after = sqlite3.connect(folder / 'collection.anki2'); before.backup(after)
        models = json.loads(before.execute('select models from col').fetchone()[0])
        baseline_models = json.loads(baseline.execute('select models from col').fetchone()[0])
        selected = []
        if sample:
            for nid, mid, fields in before.execute('select id,mid,flds from notes'):
                if [f['name'] for f in models[str(mid)]['flds']] == FIELDS and fields.split('\x1f')[0] in SAMPLE_WORDS:
                    selected.append(nid)
            assert len(selected) == 2
            marks = ','.join('?' for _ in selected)
            after.execute('delete from revlog where cid not in (select id from cards where nid in (' + marks + '))', selected)
            after.execute('delete from cards where nid not in (' + marks + ')', selected)
            after.execute('delete from notes where id not in (' + marks + ')', selected)
            after.execute('delete from graves')
            after.commit()
            source_sample = folder / 'source-sample.anki2'
            clone = sqlite3.connect(source_sample); after.backup(clone); clone.close()
        now = int(time.time()); proofs = []; vocabulary = 0; changed = 0; kinds = {}
        for nid, guid, mid, fields, mod in before.execute('select id,guid,mid,flds,mod from notes order by id'):
            if sample and nid not in selected:
                continue
            if [f['name'] for f in models[str(mid)]['flds']] != FIELDS:
                continue
            old = fields.split('\x1f'); new = list(old)
            semantic_row = baseline.execute('select mid,flds from notes where guid=?', (guid,)).fetchone()
            assert semantic_row and [f['name'] for f in baseline_models[str(semantic_row[0])]['flds']] == FIELDS
            result = restore_definition_disclosures(old[2], semantic_row[1].split('\x1f')[2])
            new[2] = result.html
            inverse = new[2]
            for region in reversed(result.regions):
                inverse = inverse[:region['revised_start']] + region['original'] + inverse[region['revised_end']:]
                kinds[region['kind']] = kinds.get(region['kind'], 0) + 1
            assert inverse == old[2] and old[:2] + old[3:] == new[:2] + new[3:]
            if new[2] != old[2]:
                changed += 1
                proofs.append({'nid': nid, 'guid': guid, 'field': 'Definition', 'before_sha256': text_sha(old[2]),
                               'after_sha256': text_sha(new[2]), 'regions': result.regions})
            # Every vocabulary note receives the same field policy on import.
            after.execute('update notes set flds=?,mod=?,usn=-1 where id=?', ('\x1f'.join(new), max(now, mod + 1), nid))
            vocabulary += 1
            if vocabulary % 500 == 0:
                print(json.dumps({'year': year, 'vocabulary': vocabulary, 'changed': changed, 'seconds': round(time.monotonic()-started, 1)}), flush=True)
        count = after.execute('select count(*) from notes').fetchone()[0]
        for table in ('cards', 'revlog'):
            if not sample:
                assert before.execute('select * from ' + table + ' order by 1').fetchall() == after.execute('select * from ' + table + ' order by 1').fetchall()
        if not sample:
            assert before.execute('select * from graves order by 1').fetchall() == after.execute('select * from graves order by 1').fetchall()
            assert before.execute('select id,guid,mid,tags from notes order by 1').fetchall() == after.execute('select id,guid,mid,tags from notes order by 1').fetchall()
        for model in models.values():
            if [f['name'] for f in model['flds']] == FIELDS:
                model['mod'] = max(now, model['mod'] + 1)
        after.execute('update col set models=?,mod=max(mod+1,?),usn=-1',
                      (json.dumps(models, ensure_ascii=False), now * 1000)); after.commit()
        assert after.execute('pragma integrity_check').fetchone()[0] == 'ok'
        mapping = json.loads(archive.read('media'))
        if sample:
            roots = [r[0] for r in after.execute('select flds from notes')]
            sample_before = sqlite3.connect(source_sample)
            roots += [r[0] for r in sample_before.execute('select flds from notes')]
            sample_before.close()
            for model in models.values():
                if [f['name'] for f in model['flds']] == FIELDS:
                    roots += [model['css']] + [t[face] for t in model['tmpls'] for face in ('qfmt', 'afmt')]
            mapping = SampleMedia(archive, mapping).closure(roots)
            write_package(archive, folder / 'source-sample.apkg', source_sample, mapping)
        before.close(); baseline.close(); after.close()
        label = '手机验证-abide-venture-展开正文内嵌' if sample else year + '红宝书完整版-统一内嵌展开正文'
        package = OWN / (label + '-20261015.apkg')
        write_package(archive, package, folder / 'collection.anki2', mapping)
    assert sha(source) == PINS[year] and sha(semantic) == BASE_PINS[year]
    assert all(sha(path) == pin for path, pin in pins.items())
    save(folder / 'inline-field-proofs.json', proofs)
    report = {'schema': 'inline-disclosures-apkg.v1', 'year': year, 'output': str(package), 'bytes': package.stat().st_size,
              'sha256': sha(package), 'source': str(semantic), 'source_sha256': BASE_PINS[year],
              'storage_source': str(source), 'storage_source_sha256': PINS[year], 'runtime': prior['runtime'],
              'cards': count, 'vocabulary_notes_updated': vocabulary, 'changed_definitions': changed, 'inline_regions': kinds,
              'all_current_disclosure_bodies_inline': True, 'only_definition_bodies_and_note_model_mod_changed': True,
              'field_byte_inverse_verified': True, 'all_original_media_preserved': not sample,
              'learning_tables_and_identities_preserved': not sample, 'sample': sample, 'sample_media_items': len(mapping) if sample else None,
              'source_code_pins': pins, 'phone_verified': False, 'elapsed_seconds': round(time.monotonic()-started, 2)}
    save(folder / 'build-report.json', report)
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--year', required=True, choices=('2026', '2027'))
    parser.add_argument('--sample', action='store_true')
    args = parser.parse_args()
    build(args.year, args.sample)
