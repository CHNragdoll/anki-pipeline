"""Replace the cropped 2010 Q8 graph in the current 408 projections.

Stage first. The PostgreSQL source archive and the original scanned SVG remain
immutable; a new source manifest records the clean display derivative. Activate
only after the disposable native Anki import and staged Web checks pass.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import xml.etree.ElementTree as ET

from anki_pipeline import study_catalog as catalog
from anki_pipeline.study_catalog_anki import bump_content_mods
from anki_pipeline.study_catalog_export import export_book, project_book, project_note
from anki_pipeline.study_exam_refresh import _backup
from scripts.update_exam_visible_cleanup import finish


ROOT = Path(__file__).resolve().parents[1]
EXAM = ROOT.parent / 'exam-library'
ASSET = EXAM / 'data/sources/exam-library/assets/redrawn/cs408-2010-complete-p001-b012-clean.svg'
ORIGINAL = EXAM / 'data/sources/cs408-latex-2009-2017/assets/figures/2010-complete-p001-b012.svg'
REFLOW = EXAM / 'data/sources/cs408-latex-2009-2017/papers/2010-complete.htm'
STRUCTURED = EXAM / 'data/sources/exam-library/structured/papers/cs408/2010-complete.json'
QUESTION_DB = EXAM / 'data/question-bank.sqlite3'
DELIVERY = ROOT / 'output/cs408-q8-graph-clean-20261103'
ACTIVE = ROOT / 'output/cs408-display-clean-20261103'
LEGACY = ROOT / 'output/cs408-dual-20261102'
BACKUP = ROOT / 'backups/cs408-q8-graph-clean-20261103'
BOOK = 'cs408-exams'
NOTE_ID = 1793558734108
OLD_SHA = 'c59bb3b0e923f7b82c8dc9210983d63a6f00b3d383a2c41b62b3dc64a07a079d'
OLD_NAME = f'_exam_{OLD_SHA}.svg'
EXPECTED_TOPOLOGICAL = {'abced', 'abecd', 'aebcd'}
EDGES = {('a', 'e'), ('e', 'd'), ('a', 'b'), ('a', 'c'), ('b', 'c'), ('c', 'd')}


def sha(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def stable_rows(db, table: str, where: str = '') -> str:
    allowed = {'notes', 'note_fields', 'native_cards', 'resource_aliases'}
    if table not in allowed and not table.startswith('study_progress_'):
        raise ValueError('unregistered guard table')
    rows = db.execute('SELECT row_to_json(t)::text FROM ' + table + ' t ' + where).fetchall()
    return hashlib.sha256('\n'.join(sorted(row[0] for row in rows)).encode()).hexdigest()


def topological_orders():
    result = set()

    def visit(order, pending):
        if not pending:
            result.add(''.join(order))
            return
        available = sorted(v for v in pending if all(start in order for start, end in EDGES if end == v))
        for vertex in available:
            visit(order + [vertex], pending - {vertex})

    visit([], set('abcde'))
    return result


def preflight():
    if sha(ORIGINAL) != OLD_SHA:
        raise ValueError('original cropped SVG differs from the audited source')
    raw = ASSET.read_bytes()
    tree = ET.fromstring(raw)
    ns = {'svg': 'http://www.w3.org/2000/svg'}
    if [element.text for element in tree.findall('.//svg:text', ns)] != list('abcde'):
        raise ValueError('clean SVG must contain only the five source vertices')
    if len(tree.findall('.//svg:g[@marker-end]/svg:path', ns)) != len(EDGES):
        raise ValueError('clean SVG must draw exactly six directed edges')
    if tree.findall('.//svg:image', ns) or tree.findall('.//svg:use', ns) or tree.findall('.//svg:clipPath', ns):
        raise ValueError('clean SVG cannot embed the original crop')
    if topological_orders() != EXPECTED_TOPOLOGICAL:
        raise ValueError('directed edges change the printed answer')
    return hashlib.sha256(raw).hexdigest(), raw


def field_rows(db):
    rows = list(db.execute('SELECT f.ordinal,f.name,f.component_id,c.current_id FROM note_fields f '
                           'JOIN components c ON c.id=f.component_id '
                           'WHERE f.book_id=%s AND f.note_id=%s ORDER BY f.ordinal', (BOOK, NOTE_ID)))
    if len(rows) != 6:
        raise ValueError('2010 Q8 field schema changed')
    fields = {name: catalog.get_object(db, key).decode() for _, name, _, key in rows}
    if fields.get('Title') != '2010 · 单选题 · 第 8 题' or fields.get('Status') != 'available':
        raise ValueError('2010 Q8 identity or status changed')
    if fields['Question'].count(OLD_NAME) != 1 or '第 8 题有向图' not in fields['Question']:
        raise ValueError('2010 Q8 original graph reference changed')
    if 'abced，abecd，aebcd' not in fields['Answer'] or 'B' not in fields['Answer']:
        raise ValueError('2010 Q8 answer differs from source')
    return rows, fields


def stage():
    new_sha, raw = preflight()
    new_name = f'_exam_{new_sha}.svg'
    if DELIVERY.exists():
        raise FileExistsError('candidate delivery already exists')
    DELIVERY.mkdir(parents=True)
    BACKUP.mkdir(parents=True, exist_ok=True)
    target = catalog.Target(catalog.DEFAULT_DSN, 'study_catalog')
    with catalog.connect(target) as db, catalog.transaction(db):
        catalog.write_lock(db)
        source = db.execute('SELECT source_id,collection_id,col_payload_id FROM book_sources '
                            'WHERE book_id=%s FOR UPDATE', (BOOK,)).fetchone()
        if source is None:
            raise ValueError('408 book is not registered')
        book = project_book(db, BOOK)
        manifest = copy.deepcopy(book['manifest'])
        slots = [slot for slot, name in manifest['media'].items() if name == OLD_NAME]
        if len(slots) != 1:
            raise ValueError('old SVG has no unique native media slot')
        original_alias = db.execute('SELECT object_id,zip_info_id FROM resource_aliases '
                                    'WHERE book_id=%s AND name=%s FOR UPDATE', (BOOK, OLD_NAME)).fetchone()
        if original_alias is None or original_alias[0] != OLD_SHA:
            raise ValueError('old media alias is stale')
        if db.execute('SELECT 1 FROM resource_aliases WHERE book_id=%s AND name=%s', (BOOK, new_name)).fetchone():
            raise ValueError('clean graph alias already exists')
        rows, fields = field_rows(db)
        before_note = project_note(db, book, NOTE_ID, apply_runtime=False)
        old_identities = list(db.execute('SELECT note_id,guid,model_id FROM notes WHERE book_id=%s ORDER BY note_id', (BOOK,)))
        old_cards = list(db.execute('SELECT native_id,note_id,unit_id,payload_id FROM native_cards '
                                    'WHERE book_id=%s ORDER BY native_id', (BOOK,)))
        progress = [row[0] for row in db.execute("SELECT tablename FROM pg_tables WHERE schemaname=current_schema() "
                                                 "AND tablename LIKE 'study_progress%' ORDER BY tablename")]
        progress_before = {table: stable_rows(db, table) for table in progress}
        others_before = {table: stable_rows(db, table, "WHERE book_id<>'cs408-exams'")
                         for table in ('notes', 'note_fields', 'native_cards', 'resource_aliases')}
        backup_path, backup_sha = _backup(db, BOOK, BACKUP)

        key = catalog.put_object(db, raw)
        if key != new_sha:
            raise ValueError('new graph object digest differs')
        db.execute('INSERT INTO resource_aliases(book_id,name,object_id,zip_info_id) VALUES(%s,%s,%s,%s)',
                   (BOOK, new_name, key, original_alias[1]))
        # The old URL stays a compatibility alias, now serving clean bytes.
        if db.execute('UPDATE resource_aliases SET object_id=%s WHERE book_id=%s AND name=%s AND object_id=%s',
                      (key, BOOK, OLD_NAME, OLD_SHA)).rowcount != 1:
            raise ValueError('legacy media alias changed concurrently')
        question_row = next(row for row in rows if row[1] == 'Question')
        if db.execute('SELECT count(*) FROM note_fields WHERE component_id=%s', (question_row[2],)).fetchone()[0] != 1:
            raise ValueError('Q8 Question component is shared outside this note')
        new_question = fields['Question'].replace(OLD_NAME, new_name)
        field_key = catalog.put_object(db, new_question.encode())
        if db.execute('UPDATE components SET current_id=%s WHERE id=%s AND current_id=%s',
                      (field_key, question_row[2], question_row[3])).rowcount != 1:
            raise ValueError('Q8 Question component changed concurrently')
        db.execute('INSERT INTO component_revisions(component_id,before_id,after_id,reason,created_at) '
                   'VALUES(%s,%s,%s,%s,%s)',
                   (question_row[2], question_row[3], field_key, '2010 Q8 graph crop residue removed', catalog.now()))
        bump_content_mods(db, [(BOOK, NOTE_ID)])

        manifest['previous_source_id'] = source[0]
        manifest['media'][slots[0]] = new_name
        manifest['media_index_id'] = catalog.put_json(db, manifest['media'])
        manifest['display_graph_correction'] = {'question': 'cs408:2010-complete:q-8-1',
                                                'original_sha256': OLD_SHA, 'clean_sha256': new_sha}
        new_source = catalog.identity('exam-graph-correction.v1', BOOK, source[0], OLD_SHA, new_sha)
        db.execute('INSERT INTO sources(id,kind,label,manifest_id,status) VALUES(%s,%s,%s,%s,%s)',
                   (new_source, 'exam-graph-correction', BOOK, catalog.put_json(db, manifest), 'complete'))
        if db.execute('UPDATE book_sources SET source_id=%s WHERE book_id=%s AND source_id=%s',
                      (new_source, BOOK, source[0])).rowcount != 1:
            raise ValueError('408 source changed concurrently')
        catalog.event(db, 'clean-cs408-2010-q8-graph', {'book_id': BOOK, 'note_id': NOTE_ID,
                    'previous_source_id': source[0], 'source_id': new_source,
                    'old_alias': OLD_NAME, 'new_alias': new_name})

        final_book = project_book(db, BOOK)
        final_note = project_note(db, final_book, NOTE_ID, apply_runtime=False)
        if final_note['fields'][final_note['field_names'].index('Question')] != new_question:
            raise ValueError('Q8 field projection did not update')
        for name in fields:
            if name != 'Question' and final_note['fields'][final_note['field_names'].index(name)] != fields[name]:
                raise ValueError('unrelated Q8 field changed')
        if (before_note['guid'], before_note['note_id'], before_note['model_id']) != (
                final_note['guid'], final_note['note_id'], final_note['model_id']):
            raise ValueError('Q8 native identity changed')
        if old_identities != list(db.execute('SELECT note_id,guid,model_id FROM notes WHERE book_id=%s ORDER BY note_id', (BOOK,))):
            raise ValueError('408 note identities changed')
        if old_cards != list(db.execute('SELECT native_id,note_id,unit_id,payload_id FROM native_cards '
                                        'WHERE book_id=%s ORDER BY native_id', (BOOK,))):
            raise ValueError('408 card identities or source scheduling changed')
        if progress_before != {table: stable_rows(db, table) for table in progress}:
            raise ValueError('learning rows changed')
        if others_before != {table: stable_rows(db, table, "WHERE book_id<>'cs408-exams'") for table in others_before}:
            raise ValueError('other book rows changed')
        if db.execute('SELECT count(*) FROM resource_aliases WHERE book_id=%s', (BOOK,)).fetchone()[0] != 185:
            raise ValueError('unexpected 408 media alias count')
    receipt = {'book_id': BOOK, 'note_id': NOTE_ID, 'old_sha256': OLD_SHA, 'new_sha256': new_sha,
               'old_alias': OLD_NAME, 'new_alias': new_name, 'backup': backup_path,
               'backup_sha256': backup_sha, 'previous_source_id': source[0], 'source_id': new_source,
               'notes': len(old_identities), 'native_cards': len(old_cards),
               'learning_rows_exact': True, 'other_book_rows_exact': True,
               'only_q8_question_field_changed': True, 'source_record_unchanged': True,
               'original_svg_unchanged': sha(ORIGINAL) == OLD_SHA}
    (DELIVERY / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
    receipt['apkg'] = export_book(target, BOOK, DELIVERY / 'questions.apkg', format='apkg')
    receipt['web'] = export_book(target, BOOK, DELIVERY / 'web', format='web')
    finish(DELIVERY / 'questions.apkg', ACTIVE / 'CS408-Past-Exams-Full-20261103.apkg',
           DELIVERY / 'CS408-Past-Exams-Full-20261103.apkg')
    package = DELIVERY / 'CS408-Past-Exams-Full-20261103.apkg'
    receipt['package_sha256'] = sha(package)
    (DELIVERY / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
    subprocess.run([sys.executable, str(ROOT / 'scripts/verify_study_catalog_native.py'),
                    '--source', str(ACTIVE / 'CS408-Past-Exams-Full-20261103.apkg'),
                    '--candidate', str(package), '--report', str(DELIVERY / 'native-upgrade-report.json')],
                   check=True, cwd=ROOT)
    verify_staged(receipt)
    print(json.dumps({'stage': 'complete', 'package_sha256': receipt['package_sha256'],
                      'new_svg_sha256': new_sha}, ensure_ascii=False))


def verify_staged(receipt):
    new_name = receipt['new_alias']
    web = DELIVERY / 'web'
    catalog_doc = json.loads((web / 'catalog.json').read_text())
    cards = [row for row in catalog_doc['cards'] if row['label'] == '2010 · 单选题 · 第 8 题']
    if len(cards) != 1 or len(catalog_doc['cards']) != 799:
        raise ValueError('Q8 Web card or complete card count differs')
    card = (web / cards[0]['url']).read_text()
    if new_name not in card or OLD_NAME in card.split('<pre class="exam-selection-source', 1)[0]:
        raise ValueError('Q8 Web card still renders the cropped graph')
    if sha(web / 'media' / new_name) != receipt['new_sha256']:
        raise ValueError('clean Web media differs')
    year_pages = list((web / 'papers').glob('*.html'))
    if sum(new_name in path.read_text() for path in year_pages) != 1:
        raise ValueError('2010 whole-paper view did not use the clean graph exactly once')
    native = json.loads((DELIVERY / 'native-upgrade-report.json').read_text())
    if (native['notes'], native['cards']) != (800, 800) or not native['identity_schedule_flags_revlog_preserved']:
        raise ValueError('native Anki acceptance failed')
    return cards[0]['url']


def _replace_exact(path: Path, old: str, new: str, expected: int):
    before = path.read_text()
    if before.count(old) != expected:
        raise ValueError(f'source reference count changed: {path}')
    return before.replace(old, new)


def sync_database():
    """Refresh the live practice reader's one cached source block."""
    source_blocks = json.loads(STRUCTURED.read_text())['blocks']
    matching = [block for block in source_blocks if block['id'] == 'b-1-13']
    if len(matching) != 1 or matching[0]['questionId'] != 'q-8-1':
        raise ValueError('structured Q8 source block changed')
    candidate = matching[0]
    new_name = ASSET.name
    if candidate['contentHtml'].count(new_name) != 1 or candidate['images'] != [
            '../../exam-library/assets/redrawn/' + new_name]:
        raise ValueError('structured Q8 source is not activated')
    backup = BACKUP / 'question-bank-before.sqlite3'
    with sqlite3.connect(QUESTION_DB) as connection:
        row = connection.execute('SELECT content_html,images_json,raw_json FROM source_blocks '
                                 'WHERE id=? AND question_id=?',
                                 ('cs408:2010-complete:b-1-13', 'cs408:2010-complete:q-8-1')).fetchone()
        if row is None:
            raise ValueError('live Q8 block is missing')
        old = json.loads(row[2])
        if old == candidate:
            if not backup.is_file():
                raise ValueError('live Q8 block is updated without its recorded backup')
        else:
            expected = copy.deepcopy(candidate)
            expected['contentHtml'] = expected['contentHtml'].replace(
                '../../../../exam-library/assets/redrawn/' + new_name,
                '../../../../cs408-latex-2009-2017/assets/figures/2010-complete-p001-b012.svg')
            expected['images'] = ['../assets/figures/2010-complete-p001-b012.svg']
            if old != expected:
                raise ValueError('live Q8 block differs beyond the audited graph reference')
            if backup.exists():
                raise FileExistsError('live question bank backup already exists')
            with sqlite3.connect(backup) as backup_connection:
                connection.backup(backup_connection)
            connection.execute('BEGIN IMMEDIATE')
            changed = connection.execute(
                'UPDATE source_blocks SET content_html=?,images_json=?,raw_json=? '
                'WHERE id=? AND content_html=? AND images_json=? AND raw_json=?',
                (candidate['contentHtml'], json.dumps(candidate['images'], ensure_ascii=False, separators=(',', ':')),
                 json.dumps(candidate, ensure_ascii=False, separators=(',', ':')),
                 'cs408:2010-complete:b-1-13', *row))
            if changed.rowcount != 1 or connection.total_changes != 1:
                connection.rollback()
                raise ValueError('live Q8 source block changed concurrently')
            connection.commit()
        final = connection.execute('SELECT content_html,images_json,raw_json FROM source_blocks '
                                   'WHERE id=?', ('cs408:2010-complete:b-1-13',)).fetchone()
        if (final[0] != candidate['contentHtml'] or json.loads(final[1]) != candidate['images']
                or json.loads(final[2]) != candidate):
            raise ValueError('live Q8 block verification failed')
        if connection.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('live question bank integrity check failed')
    result = {'database': str(QUESTION_DB), 'backup': str(backup),
              'backup_sha256': sha(backup), 'source_block': 'cs408:2010-complete:b-1-13',
              'one_row_changed': True}
    (DELIVERY / 'sqlite-sync.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    activation = DELIVERY / 'activation.json'
    if activation.exists():
        receipt = json.loads(activation.read_text())
        receipt['sqlite_sync'] = result
        activation.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
    return result


def activate():
    receipt = json.loads((DELIVERY / 'receipt.json').read_text())
    if sha(ASSET) != receipt['new_sha256'] or sha(ORIGINAL) != OLD_SHA:
        raise ValueError('source art changed after stage')
    verify_staged(receipt)
    package = DELIVERY / 'CS408-Past-Exams-Full-20261103.apkg'
    if sha(package) != receipt['package_sha256']:
        raise ValueError('staged package changed')
    ref_old = '../assets/figures/2010-complete-p001-b012.svg'
    ref_new = '../../exam-library/assets/redrawn/cs408-2010-complete-p001-b012-clean.svg'
    reflow_new = _replace_exact(REFLOW, ref_old, ref_new, 1)
    structured = json.loads(STRUCTURED.read_text())
    blocks = [b for b in structured['blocks'] if b['id'] == 'b-1-13']
    if len(blocks) != 1 or blocks[0]['questionId'] != 'q-8-1':
        raise ValueError('structured Q8 figure identity changed')
    old_html = '../../../../cs408-latex-2009-2017/assets/figures/2010-complete-p001-b012.svg'
    new_html = '../../../../exam-library/assets/redrawn/cs408-2010-complete-p001-b012-clean.svg'
    if blocks[0]['contentHtml'].count(old_html) != 1 or blocks[0]['images'] != [ref_old]:
        raise ValueError('structured Q8 figure references changed')
    blocks[0]['contentHtml'] = blocks[0]['contentHtml'].replace(old_html, new_html)
    blocks[0]['images'] = [ref_new]
    structured_new = json.dumps(structured, ensure_ascii=False, separators=(',', ':'))
    if not ACTIVE.joinpath('web').is_dir() or not LEGACY.joinpath('web').is_symlink():
        raise ValueError('active 408 Web alias changed')
    BACKUP.mkdir(parents=True, exist_ok=True)
    old_web = BACKUP / 'web-before'
    if old_web.exists():
        raise FileExistsError('activation backup already exists')
    for source, name in [(REFLOW, 'reflow-before.htm'), (STRUCTURED, 'structured-before.json'),
                         (ACTIVE / 'CS408-Past-Exams-Full-20261103.apkg', 'full-before.apkg'),
                         (ACTIVE / 'questions.apkg', 'questions-before.apkg'),
                         (LEGACY / 'CS408-Past-Exams-Visual-Centered-20261102.apkg', 'legacy-before.apkg')]:
        destination = BACKUP / name
        if destination.exists():
            raise FileExistsError(f'activation backup already exists: {destination}')
        if source.suffix == '.apkg':
            os.link(source, destination)
        else:
            shutil.copy2(source, destination)
    os.replace(ACTIVE / 'web', old_web)
    os.replace(DELIVERY / 'web', ACTIVE / 'web')
    for source, destination in [(package, ACTIVE / package.name),
                                (DELIVERY / 'questions.apkg', ACTIVE / 'questions.apkg')]:
        temp = destination.with_name('.' + destination.name + '.new')
        os.link(source, temp)
        os.replace(temp, destination)
    legacy_names = sorted(LEGACY.glob('CS408-Past-Exams-*.apkg'))
    if len(legacy_names) != 8:
        raise ValueError('legacy APKG alias set changed')
    for destination in legacy_names:
        temp = destination.with_name('.' + destination.name + '.new')
        os.link(package, temp)
        os.replace(temp, destination)
    for destination, content in [(REFLOW, reflow_new), (STRUCTURED, structured_new)]:
        temp = destination.with_name('.' + destination.name + '.new')
        temp.write_text(content)
        os.replace(temp, destination)
    sync_database()
    if sha(ACTIVE / package.name) != receipt['package_sha256'] or sha(LEGACY / legacy_names[0].name) != receipt['package_sha256']:
        raise ValueError('active APKG alias did not switch')
    if sha(ACTIVE / 'web/media' / receipt['new_alias']) != receipt['new_sha256']:
        raise ValueError('active Web media differs')
    (DELIVERY / 'activation.json').write_text(json.dumps({
        'active_package': str(ACTIVE / package.name), 'package_sha256': receipt['package_sha256'],
        'active_web': str(ACTIVE / 'web'), 'legacy_apkg_aliases': [str(path) for path in legacy_names],
        'reflow_2010_q8_clean': True, 'structured_2010_q8_clean': True,
        'original_page_and_original_cropped_svg_unchanged': True,
    }, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'activation': 'complete', 'package_sha256': receipt['package_sha256']}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=('preflight', 'stage', 'activate', 'sync-db'))
    args = parser.parse_args()
    if args.phase == 'preflight':
        digest, _ = preflight()
        print(json.dumps({'clean_svg_sha256': digest, 'topological_orders': sorted(topological_orders())}))
    elif args.phase == 'stage':
        stage()
    elif args.phase == 'activate':
        activate()
    else:
        print(json.dumps(sync_database(), ensure_ascii=False))


if __name__ == '__main__':
    main()
