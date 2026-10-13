"""Read-only current-source and effective-page audit of the completed preview."""
from contextlib import closing
import importlib.util
import json
from pathlib import Path
import time
from urllib.parse import parse_qs, unquote, urlsplit

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('post_adapter', HERE / 'post_preview_adapter.py')
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)
sc, driver, renderer, sd = adapter.sc, adapter.driver, adapter.renderer, adapter.sd


def historical(node):
    if renderer._inside_history(node):
        return True
    parent = node.parent
    while parent is not None:
        if parent.attrs.get('data-native-ownership-history') or parent.attrs.get('data-source-confirmation-history'):
            return True
        parent = parent.parent
    return False


def anchor_sid(anchor):
    if anchor.attrs.get('data-rb-j'):
        fields = anchor.attrs['data-rb-j'].split('|')
        sc.require(len(fields) in {6, 7}, 'compact source identity differs')
        return 'kaoyan:' + fields[1] + ':' + unquote(fields[2])
    value = anchor.attrs.get('href') or anchor.attrs.get('data-latex-url')
    if not value:
        return None
    values = parse_qs(urlsplit(value).query).get('anki-codex-sentence', [])
    sc.require(len(values) <= 1, 'native source carries duplicate sentence identity')
    return values[0] if values else None


def audit():
    started = time.monotonic()
    plan = driver.load_plan(adapter.PLAN, adapter.PLAN_SHA)
    manifest_path = adapter.OUTPUT / 'preview-manifest.json'
    manifest = json.loads(manifest_path.read_text())
    post_path = adapter.OUTPUT / 'post-adapter/receipt.json'
    post = json.loads(post_path.read_text())
    sc.require(manifest['run_id'] == post['run_id'] == plan['run_id'], 'effective output run differs')
    sc.require(driver.pin(adapter.__file__) == post['adapter'], 'applied post adapter changed')
    post_cards = {(c['book_id'], c['card_id']): c for c in post['cards']}
    effective, native_records = [], []
    for index, card in enumerate(plan['cards'], 1):
        file = adapter.OUTPUT / card['book_id'] / 'source-correction-cards' / (card['card_id'] + '.html')
        raw = file.read_bytes()
        checksum = sc.digest(raw)
        proof_file = adapter.OUTPUT / 'card-proofs' / card['book_id'] / (card['card_id'] + '.json')
        proof = json.loads(proof_file.read_text())
        identity = (card['book_id'], card['card_id'])
        derived = post_cards.get(identity)
        sc.require(proof['inverse_exact'] and checksum == (derived['after_sha256'] if derived else proof['after_sha256']),
            'effective page differs from frozen renderer/post-adapter pins')
        if derived:
            sc.require(derived['before_sha256'] == proof['after_sha256'], 'post-adapter inverse does not chain to frozen render')
        after = sc._payload(card)
        rows_by_sid = {}
        for row in after['occurrences']:
            if row['source_provenance'].get('source_confirmation'):
                rows_by_sid.setdefault(row['sentence_id'], []).append(row)
        page = raw.decode()
        aliases = renderer.source_class_aliases(page)
        count = 0
        for node in adapter._Offsets(page, aliases).root.walk():
            if node.tag != 'li' or 'example-card' not in node.classes or historical(node):
                continue
            anchors = [a for a in node.walk() if a.tag == 'a' and 'sentence-jump' in a.classes]
            if not anchors:
                continue
            sc.require(len(anchors) == 1, 'current native example has multiple source anchors')
            anchor = anchors[0]
            sid = anchor_sid(anchor)
            if sid not in rows_by_sid:
                continue
            rows = rows_by_sid[sid]
            sc.require(all((r['english'], r['translation'], r['alignment'], r['english_hash'],
                r['source_provenance']['reviewedContentHash']) == (rows[0]['english'], rows[0]['translation'],
                rows[0]['alignment'], rows[0]['english_hash'], rows[0]['source_provenance']['reviewedContentHash']) for r in rows),
                'current native source rows disagree')
            values = sd._native_examples(page[node.start:node.end], aliases)
            sc.require(len(values) == 1, 'current native source example is not unique')
            value, row = values[0], rows[0]
            owned = sorted({tuple(r['target_range']) for r in rows})
            sc.require((value['english'], value['translation']) == (row['english'], row['translation'])
                and sorted(map(tuple, value['target_ranges'])) == owned, 'current native bilingual text/owned marks differ')
            for field in ('href', 'data-latex-url', 'data-full-paper-url'):
                sc.require(anchor.attrs.get(field), 'current corrected native lacks a reader mode')
                url = urlsplit(anchor.attrs[field])
                sc.require(url.scheme == 'http' and url.netloc == '192.168.3.5:8765', 'current native source origin differs')
                query = parse_qs(url.query)
                for key, expected in [('anki-codex-sentence', sid), ('anki-codex-hash', row['english_hash']),
                    ('anki-codex-review', row['source_provenance']['reviewedContentHash'])]:
                    sc.require(query.get(key) == [expected], 'current native source hash/identity differs')
                sc.require(len(query.get('anki-codex-en', [])) == 1 and
                    sorted(map(tuple, json.loads(query['anki-codex-en'][0]))) == owned, 'current native source targets differ')
                stem = row['paper_id'].split(':')[1]
                if field == 'data-latex-url':
                    sc.require(url.path == '/english-exams-reflow-latex/kaoyan/papers/' + stem + '.htm', 'latex source route differs')
                elif field == 'data-full-paper-url' or url.path == '/exam-library/practice/full-paper.htm':
                    sc.require(url.path == '/exam-library/practice/full-paper.htm' and query.get('paper') == [row['paper_id']],
                        'full-paper source route differs')
            native_records.append({'book_id':card['book_id'], 'card_id':card['card_id'], 'sentence_id':sid,
                'english_hash':row['english_hash'], 'reviewed_content_hash':row['source_provenance']['reviewedContentHash'],
                'owned_target_ranges':[list(r) for r in owned], 'all_three_reader_attributes_lan':True})
            count += 1
        effective.append({'book_id':card['book_id'], 'card_id':card['card_id'], 'word':card['word'],
            'child_snapshot_id':card['child_snapshot_id'], 'file':str(file), 'effective_sha256':checksum,
            'frozen_render_sha256':proof['after_sha256'], 'post_adapter':bool(derived and derived['word']=='juggle'),
            'source_current_native_examples':count, 'inverse_chain_exact':True})
        if index % 20 == 0 or index == len(plan['cards']):
            print(json.dumps({'audited_cards':index,'total':len(plan['cards']),'native_current_sources':len(native_records),
                'elapsed_seconds':round(time.monotonic()-started,1)}), flush=True)
    source_rows = sum(c['source_current_native_examples'] for c in effective)
    expected_native = sum(json.loads((adapter.OUTPUT/'card-proofs'/c['book_id']/(c['card_id']+'.json')).read_text())['native']['updated_native_examples']
        for c in plan['cards']) + 2
    sc.require(source_rows == expected_native, 'complete native source coverage differs from frozen render plus two additions')
    result = {'schema':'source-confirmations-final-preview-audit.v1', 'run_id':plan['run_id'], 'database_writes':False,
        'preview_writes':False, 'plan':driver.pin(adapter.PLAN), 'frozen_render_manifest':driver.pin(manifest_path),
        'post_adapter_receipt':driver.pin(post_path), 'render_driver':driver.pin(driver.__file__), 'audit_driver':driver.pin(__file__),
        'cards':effective, 'source_native_examples':native_records, 'summary':{'cards':len(effective),
        'current_native_examples':source_rows,'all_current_reader_modes_lan':True,'all_effective_page_pins_exact':True,
        'all_inverse_chains_exact':True}, 'elapsed_seconds':round(time.monotonic()-started,1), 'root_browser_accepted':False}
    output = HERE / 'final-native-source-audit-v1.json'
    driver.atomic_write(output, sc.canonical(result))
    print(json.dumps({'audit':driver.pin(output),'summary':result['summary']}), flush=True)


if __name__ == '__main__':
    audit()
