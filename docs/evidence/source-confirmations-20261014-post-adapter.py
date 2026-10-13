"""Finite native-display and route derivation of the completed 180-card preview."""
from contextlib import closing
import html
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from anki_pipeline import source_confirmations as sc, sense_display as sd
from anki_pipeline.native_example_usage import _Offsets, _source_classes
from anki_pipeline.packaging import (_highlight_example, _chunk_translation,
    _example_chunk_ranges, _annotate_sentence_chunks, _source_jump)
from scripts import apply_source_confirmations as driver
from scripts import build_residual_optimization_preview as renderer
from scripts import update_exam_usage_preview as preview
from scripts import patch_exam_usage_preview as owner

OWNED = ROOT / 'output/source-confirmations-20261014/cards-own'
OUTPUT = OWNED / 'preview-v1'
PLAN = OWNED / 'prepared-v5-final-plan.json'
PLAN_SHA = 'be28346ed841773d2e1838146d83166bcdd7d2a786e1ee995bb8145612a995cb'
LAN = 'http://192.168.3.5:8765'
PREFIX = '/source-confirmations-20261014/cards-own/preview-v1'
MOVED_SID = 'kaoyan:2001-01:p:b-11-4:0'


def default_examples(page, aliases):
    result = []
    for node in _Offsets(page, aliases).root.walk():
        if node.tag != 'li' or 'example-card' not in node.classes or renderer._inside_history(node):
            continue
        parent = node.parent
        historical = False
        while parent:
            historical |= bool(parent.attrs.get('data-native-ownership-history')) or bool(parent.attrs.get('data-source-confirmation-history'))
            parent = parent.parent
        if not historical:
            values = sd._native_examples(page[node.start:node.end], aliases)
            sc.require(len(values) == 1, 'default native example is not unique')
            result.append((node, values[0]))
    return result


def native_markup(row, ordinal, aliases, *, history=True):
    example = {'text': row['english'], 'translation': row['translation'],
        'translation_source': 'codex', 'translation_alignment': row['alignment']}
    en_chunks, zh_chunks, _ = _example_chunk_ranges(example)
    en = _annotate_sentence_chunks(_highlight_example(row['english'], '', '', [],
        target_ranges=[row['target_range']], chunk_ranges=en_chunks, preserve_source=True), row['alignment'])
    zh = _annotate_sentence_chunks(_chunk_translation(row['translation'], zh_chunks), row['alignment'])
    explanation = ''
    if history:
        open_tag = '<article class="sf-example" data-sf-occurrence-id="' + row['occurrence_id'] + '">'
        marked, _ = driver.inline_history(open_tag + '</article>', {'occurrences': [row]}, {})
        explanation = marked[len(open_tag):-len('</article>')]
        sc.require('来源核验、原句与完整旧审查' in explanation, 'moved native example lacks complete inline history')
    markup = ('<li class="example-card" data-source-confirmation-native-occurrence="' + row['occurrence_id'] + '">'
        '<div class="example-heading"><span class="index-tag">' + str(ordinal) + '</span><span class="example-text">' + en + '</span>'
        + _source_jump(owner.original_paper_jump(row, row['target_range'], LAN)) + '</div>'
        '<span class="example-translation" data-translation-source="codex"><span class="translate-tag">翻译</span> ' + zh + '</span>'
        '<span class="example-source">' + html.escape(row['source']) + '</span><span class="sentence-status" role="status"></span>'
        + explanation + '</li>')
    return _source_classes(markup, aliases)


def append_moved_native(page, after, aliases):
    row = next(row for row in after['occurrences'] if row['sentence_id'] == MOVED_SID)
    examples = default_examples(page, aliases)
    sc.require(len(examples) == after['expected_occurrences'] - 1, 'destination default example count differs before insertion')
    sc.require(not any(value.get('jump', {}).get('sentence_id') == MOVED_SID for _, value in examples), 'moved native example already exists')
    parents = {node.parent.start: node.parent for node, _ in examples}
    sc.require(len(parents) == 1, 'destination native examples lack one exact list')
    parent = next(iter(parents.values()))
    sc.require(parent.tag in {'ol', 'ul'} and parent.closed is not None, 'destination native list has no complete insertion boundary')
    addition = native_markup(row, len(examples) + 1, aliases)
    revised, inverse = preview.apply_edits(page, [(parent.closed, parent.closed, addition)])
    current = default_examples(revised, aliases)
    sc.require(len(current) == after['expected_occurrences'], 'destination default native count differs after insertion')
    moved = [value for _, value in current if value.get('jump', {}).get('sentence_id') == MOVED_SID]
    sc.require(len(moved) == 1 and moved[0]['english'] == row['english'] and moved[0]['translation'] == row['translation']
        and moved[0]['target_ranges'] == [row['target_range']], 'moved default native bilingual text/owned target differs')
    jump = moved[0]['jump']
    sc.require(jump['english_hash'] == row['english_hash']
        and jump['reviewed_content_hash'] == row['source_provenance']['reviewedContentHash']
        and jump['target_ranges'] == [row['target_range']] and jump['native_jump'].startswith(LAN + '/'), 'moved default source jump differs')
    sc.require(preview.restore_edits(revised, inverse) == page, 'moved native insertion inverse differs')
    return revised, inverse


def option_role(page, after, aliases):
    ids = {row['occurrence_id'] for row in after['occurrences'] if row.get('usage', {}).get('source_role') == 'passage_option'}
    edits = []
    for node in _Offsets(page, aliases).root.walk():
        if node.tag == 'article' and node.attrs.get('data-sf-occurrence-id') in ids and not renderer._inside_history(node):
            label = '<span class="exam-usage-labels" style="font-size:12px;color:var(--muted,#63718a)">篇章选项（计入其他原文）</span>'
            edits.append((node.opened, node.opened, _source_classes(label, aliases)))
    sc.require(len(edits) == len(ids), 'actual passage-option classification lacks one exact visible row')
    return preview.apply_edits(page, edits)


def native_lan_links(page, aliases, after=None):
    edits = []
    for node, value in default_examples(page, aliases):
        for anchor in node.walk():
            if anchor.tag != 'a' or 'sentence-jump' not in anchor.classes:
                continue
            if anchor.attrs.get('data-rb-j'):
                sc.require(after is not None and after['word'] == 'juggle'
                    and set(anchor.attrs) == {'class', 'data-rb-j', 'aria-disabled'}
                    and anchor.attrs['aria-disabled'] == 'true'
                    and anchor.attrs['data-rb-j'].startswith('0|'), 'compact native anchor differs from observed juggle shape')
                jump = value['jump']
                rows = [row for row in after['occurrences'] if row['sentence_id'] == jump['sentence_id']
                    and row['english_hash'] == jump['english_hash']
                    and row['source_provenance'].get('reviewedContentHash') == jump['reviewed_content_hash']
                    and jump['target_ranges'] == [row['target_range']]]
                sc.require(len(rows) == 1, 'compact native anchor lacks one exact committed bilingual/source/target row')
                row = rows[0]
                view = row
                if (row['english'], row['translation']) != (value['english'], value['translation']):
                    sc.require(row.get('display'), 'compact native text has no sealed source-derived display')
                    view = sd.validate_display(row['display'], row, after['definition_provenance'])
                sc.require((view['english'], view['translation'], [view['target_range']])
                    == (value['english'], value['translation'], value['target_ranges']), 'compact native text differs from committed source/display')
                replacement = _source_classes(_source_jump(owner.original_paper_jump(rows[0], rows[0]['target_range'], LAN)), aliases)
                edits.append((anchor.start, anchor.end, replacement))
                continue
            for field in ('href', 'data-latex-url', 'data-full-paper-url'):
                sc.require(anchor.attrs.get(field), 'native source jump lacks both reader modes')
                url = urlsplit(anchor.attrs[field])
                sc.require(url.scheme == 'http' and url.hostname in {'localhost', '127.0.0.1', '192.168.3.5'} and url.port == 8765
                    and not url.username and not url.password and (re.fullmatch(r'/english-exams-reflow-latex/kaoyan/papers/\d{4}-\d{2}\.htm', url.path)
                    or url.path == '/exam-library/practice/full-paper.htm'), 'native source URL is outside exact original-paper routes')
                if url.hostname == '192.168.3.5':
                    continue
                opening = page[anchor.start:anchor.opened]
                matches = list(re.finditer(r'(?<![A-Za-z0-9_-])' + re.escape(field) + r'=(["\'])(.*?)\1', opening))
                sc.require(len(matches) == 1, 'native source link has no exact reader attribute boundary')
                match = matches[0]
                target = urlunsplit(('http', '192.168.3.5:8765', url.path, url.query, url.fragment))
                edits.append((anchor.start + match.start(2), anchor.start + match.end(2), html.escape(target, quote=True)))
    revised, inverse = preview.apply_edits(page, edits)
    for node, _ in default_examples(revised, aliases):
        for anchor in node.walk():
            if anchor.tag == 'a' and 'sentence-jump' in anchor.classes:
                sc.require(all(urlsplit(anchor.attrs[field]).netloc == '192.168.3.5:8765'
                    for field in ('href', 'data-latex-url', 'data-full-paper-url')), 'native two-mode source origins were not all migrated')
    return revised, inverse


def runtime_routes(source):
    old_card = r'/\/web-preview\/[a-z0-9_-]+\/cards\/[a-f0-9]+\.html$/i.test(url.pathname)'
    prefix = re.escape(PREFIX).replace('/', r'\/')
    card = '^' + prefix + r'\/(redbook|redbook2027)\/source-correction-cards\/[a-f0-9]{64}\.html$'
    history = '^' + prefix + r'\/(redbook|redbook2027)\/history\/[a-f0-9]{64}\.html$'
    sc.require(source.count(old_card) == 1, 'cloned runtime card guard is not unique')
    parent = json.loads((driver.ACCEPTED / 'preview-manifest.json').read_text())
    old_history = parent['runtime_overlay']['new_guard']
    sc.require(source.count(old_history) == 1, 'cloned runtime historical route guard differs')
    result = source.replace(old_card, '(' + old_card + ' || /' + card + '/.test(url.pathname))')
    result = result.replace(old_history, old_history[:-2] + ' || /' + history + '/.test(url.pathname)),')
    script = "const card=new RegExp(" + json.dumps(card) + ");const history=new RegExp(" + json.dumps(history) + ");const id='a'.repeat(64);const base=" + json.dumps(PREFIX) + ";for(const book of ['redbook','redbook2027']){if(!card.test(base+'/'+book+'/source-correction-cards/'+id+'.html')||!history.test(base+'/'+book+'/history/'+id+'.html'))throw Error('positive');}for(const path of [base+'/other/source-correction-cards/'+id+'.html',base+'/redbook/source-correction-cards/'+id.slice(1)+'.html',base+'/redbook/source-correction-cards/%2e%2e/'+id+'.html','/other/redbook/source-correction-cards/'+id+'.html',base+'/redbook/source-correction-cards/'+id+'.html?x=1']){if(card.test(path)||history.test(path))throw Error('negative');}"
    subprocess.run(['node', '-e', script], check=True, capture_output=True)
    return result, {'card_pattern': card, 'history_pattern': history, 'positive_negative_node_tests': True,
        'unrelated_runtime_bytes_preserved': result.replace('(' + old_card + ' || /' + card + '/.test(url.pathname))', old_card)
            .replace(old_history[:-2] + ' || /' + history + '/.test(url.pathname)),', old_history) == source}


def apply_adapter():
    plan = driver.load_plan(PLAN, PLAN_SHA)
    manifest_file = OUTPUT / 'preview-manifest.json'
    frozen_manifest = json.loads(manifest_file.read_text())
    sc.require(frozen_manifest['run_id'] == plan['run_id'] and frozen_manifest['rendered_cards'] == 180
        and frozen_manifest['source_inverses_exact'], 'complete frozen render manifest required')
    evidence = OUTPUT / 'post-adapter'
    sc.require(not evidence.exists(), 'fresh post-adapter evidence directory required')
    evidence.mkdir()
    prepared = []
    with closing(sc._connect(plan['candidate'])) as db:
        for card in [card for card in plan['cards'] if card['word'] in {'jug', 'juggle'}]:
            after = sc._payload(card)
            sc.require(sc._read_parent(db, card['book_id'], card['card_id'], card['child_snapshot_id']) == after,
                'post-adapter committed snapshot differs')
            active = db.execute('SELECT snapshot_id FROM active_snapshots WHERE book_id=? AND card_id=?', (card['book_id'], card['card_id'])).fetchone()
            sc.require(active[0] == after['snapshot_id'], 'post-adapter active child differs')
            path = OUTPUT / card['book_id'] / 'source-correction-cards' / (card['card_id'] + '.html')
            original = path.read_text();aliases = renderer.source_class_aliases(original)
            old_default = default_examples(original, aliases)
            if card['word'] == 'jug':
                sc.require(after['expected_occurrences'] == 0 and not any(value.get('jump', {}).get('sentence_id') == MOVED_SID for _, value in old_default),
                    'source jug still has moved sentence as active default native')
                prepared.append({'book_id':card['book_id'],'card_id':card['card_id'],'word':'jug','default_moved_sentence_absent':True,
                    'native_count':len(old_default),'file':str(path),'before_sha256':sc.digest(original.encode()),'after_sha256':sc.digest(original.encode())})
                continue
            changed, native_inverse = append_moved_native(original, after, aliases)
            changed, role_inverse = option_role(changed, after, aliases)
            changed, links_inverse = native_lan_links(changed, aliases, after)
            restored = preview.restore_edits(preview.restore_edits(preview.restore_edits(changed, links_inverse), role_inverse), native_inverse)
            sc.require(restored == original, 'complete post-adapter card inverse differs')
            prepared.append({'book_id':card['book_id'],'card_id':card['card_id'],'word':'juggle','file':str(path),
                'before_sha256':sc.digest(original.encode()),'after_sha256':sc.digest(changed.encode()),
                'native_before':len(old_default),'native_after':len(default_examples(changed,aliases)),
                'native_inverse':native_inverse,'role_inverse':role_inverse,'links_inverse':links_inverse,'inverse_exact':True,
                'before_content':original,'content':changed})
    runtime = OUTPUT / 'assets/library-preview.js'
    runtime_before = runtime.read_text();runtime_after, routes = runtime_routes(runtime_before)
    sc.require(routes['unrelated_runtime_bytes_preserved'], 'runtime route transport changed unrelated code')
    route_inverse = [{'before':runtime_before,'before_sha256':sc.digest(runtime_before.encode()),'after_sha256':sc.digest(runtime_after.encode())}]
    driver.atomic_write(evidence / 'runtime-before.js', runtime_before)
    for item in prepared:
        if 'before_content' in item:
            backup = evidence / (item['book_id'] + '-' + item['card_id'] + '-before.html')
            driver.atomic_write(backup, item.pop('before_content'))
            item['before_file'] = driver.pin(backup)
            sc.require(item['before_file']['sha256'] == item['before_sha256'], 'frozen card backup differs before mutation')
    for item in prepared:
        if 'content' in item:
            driver.atomic_write(Path(item['file']), item.pop('content'))
    driver.atomic_write(runtime, runtime_after)
    catalog_checks = []
    for book in plan['request']['expected_books']:
        catalog_path=OUTPUT/book/'catalog.json';catalog=json.loads(catalog_path.read_text())
        for item in [item for item in prepared if item['book_id']==book]:
            row=next(row for row in catalog['cards'] if row['id']==item['card_id'])
            expected=5 if item['word']=='juggle' else 0
            sc.require(row['exampleCount']==expected, 'affected catalog default example count does not match final native list')
        sc.require(catalog['counts']['examples']==sum(row['exampleCount'] for row in catalog['cards']), 'book example total differs')
        catalog_checks.append({'book_id':book,'counts':catalog['counts'],'catalog_unchanged':True})
    receipt={'schema':'source-confirmations-post-preview-adapter.v1','run_id':plan['run_id'],'database_writes':False,
        'frozen_render_manifest':{'file':str(manifest_file),'sha256':sc.digest(manifest_file.read_bytes())},
        'adapter':driver.pin(__file__),'cards':prepared,'catalogs':catalog_checks,'routes':routes,
        'runtime_before':driver.pin(evidence/'runtime-before.js'),'runtime_after':driver.pin(runtime),'route_inverse':route_inverse,
        'original_driver_unchanged':driver.pin(driver.__file__),'root_browser_accepted':False}
    driver.atomic_write(evidence/'receipt.json',sc.canonical(receipt))
    print(json.dumps({'receipt':driver.pin(evidence/'receipt.json'),'cards':len(prepared),'runtime':receipt['runtime_after'],'node_tests':True}))


if __name__=='__main__':
    apply_adapter()
