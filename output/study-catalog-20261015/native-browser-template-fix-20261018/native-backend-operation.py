#!/usr/bin/env python3.13
"""One-note native backend reproduction. No GUI, profile, package import or PG."""
from __future__ import annotations
import copy, hashlib, json, os, re, sqlite3, sys, traceback
from pathlib import Path
sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
SOURCE = Path('/Users/apple/Library/Application Support/AnkiStudyCatalog/service-runtime/native-authored-filter-v4-9o9w56zb/2026/collection.anki2')
PACKED = SOURCE.parent / 'PACKED.json'
SOURCE_SHA = '82a24ca77142a1c55295f8922d45d0d73ae10522f24fff4379e0ed11fa46cf56'
APP = Path('/Applications/Anki.app/Contents/Resources/app_packages')
ROOT = Path('/Users/apple/Documents/PyCharm/Anki/anki_rebuild')
APP_PINS = {
    'anki/buildinfo.pyc': '22800b3b2e14502779ea75a8383453490de0137f1fb687108ac26edc5a2fbef0',
    'anki/_rsbridge.so': '64db6db082deff445696471ea8939fb8bfc06635973f50779070ed638675cd6e',
}
MARKER = '[[study-native-delivery:v3:'
LIMIT = 5 * 1024 * 1024

def sha(p):
    with Path(p).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()

def save(name, value):
    data = value if isinstance(value, bytes) else value.encode('utf-8')
    with (HERE / name).open('xb') as f:
        f.write(data); f.flush(); os.fsync(f.fileno())

def json_save(name, value):
    save(name, json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')

def state(p):
    s = p.stat()
    return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)

def budget():
    files = {str(p.relative_to(HERE)): p.stat().st_size for p in HERE.rglob('*') if p.is_file()}
    assert sum(files.values()) <= LIMIT, files
    return files

def measure(text):
    return {'characters': len(text), 'utf8_bytes': len(text.encode('utf-8')),
            'sha256': digest(text), 'prefix_200_characters': text[:200], 'has_meta_token': MARKER in text}

def main():
    if (HERE / 'collection.anki2').exists():
        raise FileExistsError('fresh exclusive scratch collection required')
    before = state(SOURCE)
    assert sha(SOURCE) == SOURCE_SHA
    packed = json.loads(PACKED.read_text())
    assert packed['collection']['sha256'] == SOURCE_SHA
    assert packed['collection']['path'] == str(SOURCE)
    app_pins = {name: sha(APP / name) for name in APP_PINS}
    assert app_pins == APP_PINS
    raw = sqlite3.connect(SOURCE.as_uri() + '?mode=ro&immutable=1', uri=True)
    try:
        row = raw.execute('select id,guid,mid,flds,mod from notes where id=?', (1791119707352,)).fetchone()
        assert row is not None
        nid, guid, mid, flds, source_mod = row
        model = json.loads(raw.execute('select models from col').fetchone()[0])[str(mid)]
    finally:
        raw.close()
    fields = flds.split('\x1f')
    assert len(fields) == len(model['flds']) == 10 and fields[0] == 'abide'
    assert all(t.get('bqfmt') == t.get('bafmt') == '' for t in model['tmpls'])
    json_save('source-one-note.json', {'source_nid': nid, 'guid': guid, 'model': model, 'fields': fields})
    sys.path.insert(0, str(ROOT))
    from anki_pipeline.study_compiled_native import bind_native_delivery, split_native_delivery_meta
    original_fields = fields[:]
    original_fields[8], descriptor = split_native_delivery_meta(fields[8])
    bootstrap, = re.findall(r'_study_native_bootstrap_[a-f0-9]{64}\.js', model['tmpls'][0]['qfmt'])
    source_note = {'id': descriptor['id'], 'fields': original_fields,
                   'field_names': [field['name'] for field in model['flds']],
                   'model': copy.deepcopy(model), 'payload': {'mod': source_mod}, 'content_mod': source_mod}
    projected = bind_native_delivery(source_note, descriptor, bootstrap_name=bootstrap,
                                     model_mod=model['mod'], note_mod=source_mod)
    assert projected['fields'] == fields
    fallback = projected['model']['tmpls'][0]
    for before_template, after_template in zip(model['tmpls'], projected['model']['tmpls']):
        assert {k:v for k,v in before_template.items() if k not in ('bqfmt','bafmt')} == {
            k:v for k,v in after_template.items() if k not in ('bqfmt','bafmt')}
    assert fallback['bqfmt'] == '{{text:Word}}' and fallback['bafmt'] == '条目：{{text:Word}}'
    code_paths = ('anki_pipeline/study_compiled_native.py', 'scripts/verify_study_compiled_apkg.py',
                  'tests/test_study_compiled_native.py', 'tests/test_study_compiled_apkg_parity.py')
    code_pins = {name: sha(ROOT / name) for name in code_paths}
    sys.path.insert(0, str(APP))
    from anki.collection import Collection
    col = Collection(str(HERE / 'collection.anki2'))
    results = []
    try:
        scratch_model = copy.deepcopy(model)
        scratch_model['id'] = 0  # add_dict requires a fresh id; source remains sealed.
        added = col.models.add_dict(scratch_model)
        added_model = col.models.get(added.id)
        assert added_model is not None
        note = col.new_note(added_model)
        note.guid = guid
        note.fields = list(fields)
        col.add_note(note, 1)
        assert col.get_note(note.id).fields == fields
        cid = col.db.scalar('select id from cards where nid=?', note.id)
        assert cid and col.note_count() == col.card_count() == 1
        col._backend.set_active_browser_columns(['question', 'answer'])
        card = col.get_card(cid)
        normal_before = (card.question(reload=True), card.answer())
        baseline_templates = copy.deepcopy(added_model['tmpls'])
        normal_body_before = (card.render_output().question_text, card.render_output().answer_text)
        variants = [('empty-browser-formats', '', ''),
                    ('normal-adapter-fallback', fallback['bqfmt'], fallback['bafmt'])]
        for label, bqfmt, bafmt in variants:
            updated = col.models.get(added.id)
            assert updated is not None
            for template in updated['tmpls']:
                template['bqfmt'], template['bafmt'] = bqfmt, bafmt
            col.models.update_dict(updated)
            col.models._clear_cache()
            card = col.get_card(cid)
            browser = (card.question(reload=True, browser=True), card.answer())
            table_row = col._backend.browser_row_for_id(cid)
            cells = [cell.text for cell in table_row.cells]
            assert len(cells) == 2
            # Exactly Previewer._render_scheduled's normal call sequence.
            normal_after = (card.question(reload=True), card.answer())
            assert normal_after == normal_before
            assert (card.render_output().question_text, card.render_output().answer_text) == normal_body_before
            assert col.get_note(note.id).fields == fields
            current_templates = col.models.get(added.id)['tmpls']
            for old, current in zip(baseline_templates, current_templates):
                assert old['qfmt'] == current['qfmt'] and old['afmt'] == current['afmt']
            if not bqfmt:
                assert all(MARKER in value for value in browser)
                assert MARKER in cells[0]
            else:
                assert cells == ['abide', '条目：abide']
                assert all(MARKER not in value for value in browser + tuple(cells))
            for side, text in zip(('question', 'answer'), browser):
                save(label + '-browser-' + side + '.html', text)
            results.append({'variant': label, 'bqfmt': bqfmt, 'bafmt': bafmt,
                            'browser_render': dict(zip(('question', 'answer'), map(measure, browser))),
                            'actual_browser_table': dict(zip(('question', 'answer'), map(measure, cells))),
                            'normal_preview_byte_exact': True, 'normal_preview_body_byte_exact': True,
                            'ten_source_fields_byte_exact': True})
            budget()
        for side, text in zip(('question', 'answer'), normal_before):
            save('normal-preview-' + side + '.html', text)
    finally:
        col.close()
    assert state(SOURCE) == before and sha(SOURCE) == SOURCE_SHA
    assert {name: sha(APP / name) for name in APP_PINS} == APP_PINS
    files = budget()
    result = {'status': 'PASS', 'schema': 'native-browser-format-micro.v1',
              'scope': 'one-note private backend only; no media loaded, JS, GUI, PG or QA access',
              'source': {'path': str(SOURCE), 'sha256': SOURCE_SHA, 'pre_post_identity_and_hash_equal': True},
              'source_packed_sha256': sha(PACKED), 'script_sha256': sha(__file__),
              'app_pins': app_pins, 'production_code_pins': code_pins, 'source_identity': {'nid': nid, 'guid': guid, 'mid': mid},
              'scratch_identity': {'nid': note.id, 'cid': cid, 'mid': added.id, 'model_id_remapped_for_new_collection': True}, 'results': results,
              'normal_preview': dict(zip(('question', 'answer'), map(measure, normal_before))),
              'normal_preview_body': dict(zip(('question', 'answer'), map(measure, normal_body_before))),
              'files_before_report': files, 'bytes_before_report': sum(files.values()),
              'limitations': ['backend string/table rendering only', 'not a GUI or AX crash reproduction',
                              'no claim that browser formats fix editor iframe loads']}
    json_save('REPORT.json', result)
    files = budget()
    json_save('SHA256.json', {str(p.relative_to(HERE)): sha(p) for p in HERE.rglob('*') if p.is_file()})
    budget()
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    try:
        main()
    except BaseException:
        save('FAILURE.txt', traceback.format_exc())
        raise
