'use strict';
// Reuse only the immutable actual-source fixture setup of the frozen V1 harness.
// Do not rerun its all-632-alias sweep for this one DOM guard change.
const _fs = require('node:fs'), _path = require('node:path'), _crypto = require('node:crypto');
const _base = _fs.readFileSync(_path.join(__dirname, 'test_shared_reading_bank_runtime_v5.js'), 'utf8');
if (_crypto.createHash('sha256').update(_base).digest('hex') !== 'aa6c8a5a41e0db69da0ffeeddf635caafa1af5e176812defa58b12f56c898945') throw new Error('immutable V1 fixture harness differs');
const _start = _base.indexOf("test('actual understand D native + SF");
if (_start < 0) throw new Error('immutable V1 fixture boundary missing');
const _prefix = _base.slice(0, _start).replace("'shared-reading-bank-runtime-v5.js'", "'shared-reading-bank-runtime-v5-v2.js'");
const _focused = String.raw`
const derivedKeys = ['reading_candidate', 'derivation_payload', 'option_context', 'reading_completion'];
const nonemptyPairs = [
  { name: 'camel null / nonempty snake', value: { questionId: null, question_id: 'kaoyan:2012-02:q-41-1' } },
  { name: 'snake null / nonempty camel', value: { question_id: null, questionId: 'kaoyan:2012-02:q-41-1' } },
  { name: 'nonempty conflicting keys', value: { questionId: 'kaoyan:2012-02:q-41-1', question_id: 'kaoyan:2012-02:q-42-1' } }
];
function validCandidate() {
  const value = { questionId: null, question_id: null };
  derivedKeys.forEach(key => { value[key] = { questionId: null, question_id: null }; });
  return value;
}
async function rejectActualDom(candidate, expectedReason) {
  const h = setup(realSf + realNative, { beforeInstall: d => {
    d.querySelectorAll('a.sentence-jump').forEach(anchor => anchor.setAttribute('data-reading-candidate', JSON.stringify(candidate)));
  } });
  await h.handle.ready; await settle();
  assert.equal(h.d.body.innerHTML, h.before, 'rejected actual native/SF candidate must not change a DOM byte');
  assert.equal(h.d.querySelector('[data-shared-reading-bank-group-id]'), null);
  assert.equal(h.handle.stats().rejected, 2);
  assert.equal(h.handle.stats().rejectionReasons[expectedReason], 2);
  h.handle.dispose(); assert.equal(h.d.body.innerHTML, h.before); h.dom.window.close();
}
for (const key of derivedKeys) for (const pair of nonemptyPairs) {
  test('actual native + SF DOM ' + key + ': ' + pair.name + ' rejects without null masking', async () => {
    const candidate = validCandidate(); candidate[key] = pair.value;
    await rejectActualDom(candidate, 'shared bank dual-key DOM derived source claims a question');
  });
}
for (const pair of nonemptyPairs) {
  test('actual native + SF DOM top-level: ' + pair.name + ' rejects', async () => {
    await rejectActualDom({ ...validCandidate(), ...pair.value }, 'shared bank dual-key DOM candidate claims a question');
  });
}
test('actual native + SF all four derived DOM candidates with both qid keys null keep correct group labels and raw bodies', async () => {
  const h = setup(realSf + realNative, { beforeInstall: d => {
    d.querySelectorAll('a.sentence-jump').forEach(anchor => anchor.setAttribute('data-reading-candidate', JSON.stringify(validCandidate())));
  } });
  const bodies = frozenBodies(h.d); await h.handle.ready; await settle();
  const labels = Array.from(h.d.querySelectorAll('[data-shared-reading-bank-evidence]'));
  assert.equal(labels.length, 2);
  labels.forEach(label => {
    const evidence = JSON.parse(label.dataset.sharedReadingBankEvidence);
    assert.equal(evidence.display_label, '错误选项 D · 41–45题共享干扰项');
    assert.equal(evidence.question_id, null); assert.deepEqual(evidence.matched_question_ids, []);
    assert.equal(evidence.counting_effect, 'none');
  });
  assert.deepEqual(frozenBodies(h.d), bodies);
  h.handle.dispose(); assert.equal(h.d.body.innerHTML, h.before); h.dom.window.close();
});
test('actual native + SF absent optional DOM candidates still bind', async () => {
  const h = setup(realSf + realNative), bodies = frozenBodies(h.d);
  await h.handle.ready;
  assert.equal(h.d.querySelectorAll('[data-shared-reading-bank-group-id]').length, 2);
  assert.deepEqual(frozenBodies(h.d), bodies);
  h.handle.dispose(); assert.equal(h.d.body.innerHTML, h.before); h.dom.window.close();
});
test('existing URL context strict four-branch guard remains enforced', async () => {
  for (const key of derivedKeys) await unchangedNegative(fixture(D), d => {
    const candidate = validCandidate(); candidate[key] = nonemptyPairs[0].value;
    d.querySelector('a').href = url(D, { 'anki-codex-context': JSON.stringify(candidate) });
  });
});
test('actual Q34 native + SF still keep complete source/usage/target/count DOM unchanged', async () => {
  const h = setup(realQ34.map(element => element.outerHTML).join(''));
  await h.handle.ready; await settle(); assert.equal(h.d.body.innerHTML, h.before);
  h.handle.dispose(); assert.equal(h.d.body.innerHTML, h.before); h.dom.window.close();
});
test('disposing before new runtime validation completes remains safe', async () => {
  const h = setup(realSf + realNative); h.handle.dispose(); await h.handle.ready; await settle();
  assert.equal(h.d.body.innerHTML, h.before); h.dom.window.close();
});
(async () => {
  for (const [name, callback] of tests) { await callback(); results.push({ name, pass: true }); console.log('PASS', name); }
  const receipt = { schema: 'shared-reading-bank-runtime-js-tests.v5-v2', status: 'pass', tests: results,
    change_scope: 'DOM data-reading-candidate four derived sources strict dual-key guard only',
    reused_v1_fixture_test_sha256: 'aa6c8a5a41e0db69da0ffeeddf635caafa1af5e176812defa58b12f56c898945',
    source_pin: locators.source_pin, actual_q34_source_pin: q34SourcePin,
    actual_inflater_sha256: crypto.createHash('sha256').update(inflater).digest('hex'),
    runtime_sha256: crypto.createHash('sha256').update(sourceText).digest('hex'),
    sidecar_sha256: crypto.createHash('sha256').update(sidecarBytes).digest('hex'),
    assertions: { derived_dom_nonempty_pair_cases: 12, actual_native_and_sf_rejected_per_case: 2,
      unchanged_DOM_on_rejection: true, all_four_null_positive_control: true, Q34_unchanged: true,
      group_id_retained_single_question_id_null: true, full_alias_inventory_rerun: false,
      final_browser_or_sqlite_acceptance: false } };
  fs.writeFileSync(path.join(own, 'runtime-js-test-receipt-v5-v2.json'), JSON.stringify(receipt, null, 2) + '\n');
  console.log(JSON.stringify({ tests: results.length, status: 'pass', runtime_sha256: receipt.runtime_sha256 }));
  sourceDoc.defaultView.close(); q34Doc.defaultView.close();
})().catch(error => { console.error(error); process.exitCode = 1; });
`;
new Function('require', '__dirname', _prefix + _focused)(require, __dirname);
