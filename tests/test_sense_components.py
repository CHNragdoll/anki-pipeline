"""Composite dictionary insertion keeps each original component and identity."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

import unittest

from anki_pipeline import sense_frequency as sf
from anki_pipeline.sense_components import (
    inject_component_report, plan_components, remove_component_report,
)


def sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


def block(source, pos, text):
    return (f'<div class="_d" data-dictionary="{source}"><div class="_s">'
            f'<span class="_p">{pos}</span><span class="_t">{text}</span></div></div>')


ALIASES = {'_d': 'dictionary-definition', '_s': 'sense-row',
           '_p': 'sense-pos', '_t': 'sense-text'}


def page_and_components(*, duplicate=False, empty=False):
    first = block('oxford', 'n.', '第一义')
    second = first if duplicate else block('reviewed', 'v.', '第二义')
    parts = [first, second]
    if empty:
        parts.insert(0, '<div class="_d" data-dictionary="wordbook"><p>未收录</p></div>')
    names = ['缺项', 'a', 'an'] if empty else ['a', 'an']
    definitions = []
    cursor = 0
    for index, (name, original) in enumerate(zip(names, parts)):
        count = 0 if empty and index == 0 else 1
        definitions.append({'source': 'wordbook' if not count else ('oxford' if duplicate or index == int(empty) else 'reviewed'),
                            'component_index': index, 'sense_start': cursor,
                            'sense_count': count, 'html_sha256': sha(original), 'headword': name})
        cursor += count
    # An identical fragment on the question side must never be selected.
    page = ('<!doctype html><html><head><title>test</title></head><body>'
            f'<div id="preview-front">{first}</div><div id="preview-back">'
            + ''.join(f'<h3>{name}</h3><section class="frequency">原频次 {index}</section>{original}'
                      '<p class="source-notice">来源说明不能消失</p>'
                      for index, (name, original) in enumerate(zip(names, parts)))
            + '</div><footer>原跳转</footer></body></html>')
    return page, definitions


def occurrence(index, year=2022):
    return {'occurrence_id': f'token-{index}', 'year': year,
            'english': 'A test.', 'translation': '一个测试。', 'target_range': [0, 1],
            'translation_ranges': [[0, 2]], 'source': f'{year} 真题 · {index}',
            'reason': '上下文核验', 'alignment': None}


def report(components, *, duplicate=False, pending=True):
    rows = [occurrence(1), occurrence(2, 2021), occurrence(3, 2021)]
    waiting = [occurrence(4, 2020)] if pending else []
    return {'schema': sf.SCHEMA, 'snapshot_id': 'real-global-snapshot',
            'book_id': 'book', 'card_id': 'card', 'word': 'a/an',
            'definition_source': 'oxford' if duplicate else ('mixed'),
            'definition_provenance': {'components': deepcopy(components)},
            'total': 3 + len(waiting), 'pending': waiting, 'pending_count': len(waiting),
            'senses': [{'ordinal': 0, 'sense_id': 'sense-0', 'pos': 'n.', 'text': '第一义',
                        'count': 1, 'years': [{'year': 2022, 'count': 1}], 'occurrences': rows[:1]},
                       {'ordinal': 1, 'sense_id': 'sense-1', 'pos': 'n.' if duplicate else 'v.',
                        'text': '第一义' if duplicate else '第二义', 'count': 2,
                        'years': [{'year': 2021, 'count': 2}], 'occurrences': rows[1:]}]}


def test_noncontiguous_mixed_sources_keep_headwords_and_exact_inverse():
    page, components = page_and_components()
    plan = plan_components(page, components, ALIASES)
    revised = inject_component_report(page, plan, report(components))
    assert revised.count('<h3>a</h3>') == revised.count('<h3>an</h3>') == 1
    assert revised.count('来源说明不能消失') == 2
    assert revised.index('<h3>a</h3>') < revised.index('sense-component:start:0')
    assert revised.index('sense-component:end:0') < revised.index('<h3>an</h3>')
    assert revised.count('data-snapshot="real-global-snapshot"') == 2
    assert 'width:25.000%' in revised and 'width:50.000%' in revised
    assert revised.count('class="sf-pending"') == 1
    assert remove_component_report(revised, plan) == page


def test_identical_html_components_are_replaced_by_answer_offsets():
    page, components = page_and_components(duplicate=True)
    plan = plan_components(page, components, ALIASES)
    revised = inject_component_report(page, plan, report(components, duplicate=True))
    front = re.search(r'<div id="preview-front">(.*?)</div><div id="preview-back">', page)[1]
    assert f'<div id="preview-front">{front}</div>' in revised
    assert revised.count('class="sf-report"') == 2
    assert remove_component_report(revised, plan) == page


def test_stale_component_identity_order_and_hash_rejected():
    for key, value in [('headword', 'AN'), ('source', 'collins'), ('sense_start', 0),
                       ('sense_count', 2), ('component_index', 0), ('html_sha256', 'stale')]:
        page, components = page_and_components()
        components[1][key] = value
        with unittest.TestCase().assertRaises(ValueError, msg=key):
            plan_components(page, components, ALIASES)


def check_report_rejection(change):
    page, components = page_and_components()
    plan = plan_components(page, components, ALIASES)
    data = report(components)
    if change == 'sense_order':
        data['senses'].reverse()
    elif change == 'total':
        data['total'] += 1
    elif change == 'years':
        data['senses'][1]['years'][0]['count'] += 1
    elif change == 'source':
        data['definition_source'] = 'oxford'
    elif change == 'component_provenance':
        data['definition_provenance']['components'][1]['headword'] = 'other'
    else:
        data['pending'][0]['occurrence_id'] = 'token-1'
    with unittest.TestCase().assertRaises(ValueError, msg=change):
        inject_component_report(page, plan, data)


def test_report_must_reconcile_global_senses_physical_total_and_years():
    for change in ['sense_order', 'total', 'years', 'source', 'component_provenance', 'duplicate_token']:
        check_report_rejection(change)


def test_zero_sense_source_notice_stays_original_and_pending_once():
    page, components = page_and_components(empty=True)
    plan = plan_components(page, components, ALIASES)
    revised = inject_component_report(page, plan, report(components))
    assert '<h3>缺项</h3><section class="frequency">原频次 0</section>' + components_html(plan, 0) in revised
    assert revised.count('class="sf-report"') == 2
    assert revised.count('class="sf-pending"') == 1
    assert remove_component_report(revised, plan) == page


def components_html(plan, index):
    return plan.components[index].html


def test_source_or_revised_page_tampering_cannot_silently_restore():
    page, components = page_and_components()
    plan = plan_components(page, components, ALIASES)
    data = report(components)
    with unittest.TestCase().assertRaises(ValueError):
        inject_component_report(page.replace('原跳转', '已变化'), plan, data)
    revised = inject_component_report(page, plan, data)
    with unittest.TestCase().assertRaises(ValueError):
        remove_component_report(revised.replace('原跳转', '已变化'), plan)
    with unittest.TestCase().assertRaises(ValueError):
        inject_component_report(revised, plan, data)


def test_self_consistent_report_still_must_match_original_physical_total():
    page, components = page_and_components()
    page = page.replace('<section class="frequency">原频次 0</section>',
                        '<section class="frequency" data-occurrences="2">原频次 0</section>')
    page = page.replace('<section class="frequency">原频次 1</section>',
                        '<section class="frequency" data-occurrences="2">原频次 1</section>')
    plan = plan_components(page, components, ALIASES)
    revised = inject_component_report(page, plan, report(components))
    assert remove_component_report(revised, plan) == page
    # Three assigned rows and zero pending are internally consistent, but the
    # original two components declare four actual physical appearances.
    with unittest.TestCase().assertRaises(ValueError):
        inject_component_report(page, plan, report(components, pending=False))


def test_original_dictionary_shell_keeps_actual_refresh_definition_state():
    """Exercise the real shared script, including reviewed titles and sources.

    These are the two original reviewed headings used by okay/OK and a/an.
    Compressed source classes are expanded exactly as the page runtime does;
    nothing fabricates replacement dictionary metadata after injection.
    """
    root = Path(__file__).resolve().parents[1]
    node = shutil.which('node')
    assert node, 'The existing template checks require the Node runtime'
    payloads = []
    for reviewed_index, heading in [(0, '牛津释义（拼写／词形核对）'),
                                    (1, '本地剑桥在线完美版释义')]:
        definitions, sections, cursor = [], [], 0
        originals = []
        for index, (headword, pos, text) in enumerate([('okay' if reviewed_index == 0 else 'a', 'n.', '第一义'),
                                                    ('OK' if reviewed_index == 0 else 'an', 'v.', '第二义')]):
            source = 'reviewed' if index == reviewed_index else 'oxford'
            attrs = (f' data-definition-heading="{heading}"' if source == 'reviewed' else '')
            # An extra attribute with a quoted > catches unsafe tag splitting.
            original = block(source, pos, text).replace(
                f'data-dictionary="{source}">',
                f'data-dictionary="{source}"{attrs} data-original="literal > wrapper">', 1)
            original = original[:-6] + '</DIV >'
            originals.append(original)
            definitions.append({'source': source, 'component_index': index,
                                'sense_start': cursor, 'sense_count': 1,
                                'html_sha256': sha(original), 'headword': headword})
            cursor += 1
            sections.append(f'<h3>{headword}</h3><div class="meaning-section">'
                            '<section class="primary-definition"><h2 class="field-title">原标题</h2>'
                            + original + '</section><section class="secondary-definition">词表旧释义</section></div>')
        page = '<!doctype html><html><head></head><body><div id="preview-back">' + ''.join(sections) + '</div></body></html>'
        plan = plan_components(page, definitions, ALIASES)
        revised = inject_component_report(page, plan, report(definitions))
        for original in originals:
            # The literal opening tag and its original source survive without
            # reserializing attributes, entities, or original compressed class.
            opening = original[:original.index('<div class="_s">')]
            assert revised.count(opening) == 1
        assert revised.count('</DIV >') == len(originals)
        assert remove_component_report(revised, plan) == page
        payloads.append({'before': page, 'after': revised,
                         'titles': [heading if index == reviewed_index else '牛津释义' for index in range(2)],
                         'sources': ['reviewed' if index == reviewed_index else 'oxford' for index in range(2)]})
    runtime = r'''
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { JSDOM } = require('jsdom');
const { pages, aliases } = JSON.parse(fs.readFileSync(0, 'utf8'));
const script = fs.readFileSync('anki_pipeline/templates/script.js', 'utf8');
function refresh(html) {
  const dom = new JSDOM(html, { runScripts: 'outside-only', url: 'http://localhost/' });
  try {
    const document = dom.window.document;
    document.querySelectorAll('[class]').forEach(node => {
      node.setAttribute('class', node.getAttribute('class').split(/\s+/).map(name => aliases[name] || name).join(' '));
    });
    dom.window.eval(script);
    return Array.from(document.querySelectorAll('.primary-definition')).map(section => ({
      title: section.querySelector('.field-title').textContent,
      source: section.getAttribute('data-definition-source'),
      enriched: section.getAttribute('data-dictionary-definition'),
      hidden: section.closest('.meaning-section').querySelector('.secondary-definition').hidden,
      headings: section.querySelectorAll('.field-title').length,
      definitions: section.querySelectorAll('.dictionary-definition').length,
    }));
  } finally { dom.window.close(); }
}
for (const page of pages) {
  const before = refresh(page.before), after = refresh(page.after);
  assert.deepEqual(after, before, 'Actual refreshDefinitions must retain original definition state');
  for (let index = 0; index < after.length; index++) {
    assert.deepEqual(after[index], { title: page.titles[index], source: page.sources[index],
      enriched: 'oxford', hidden: true, headings: 1, definitions: 1 });
  }
}
process.stdout.write('shared refreshDefinitions: original titles, sources and secondary visibility retained\n');
'''
    checked = subprocess.run([node, '-e', runtime], cwd=root,
                             input=json.dumps({'pages': payloads, 'aliases': ALIASES}),
                             text=True, capture_output=True, timeout=60)
    assert checked.returncode == 0, checked.stderr
    assert 'original titles, sources and secondary visibility retained' in checked.stdout


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(unittest.FunctionTestCase(value) for name, value in globals().items()
                              if name.startswith('test_') and callable(value))


if __name__ == '__main__':
    unittest.main()
