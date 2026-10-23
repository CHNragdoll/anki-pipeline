"""Separate the reviewed consumer addition from earlier whole-FRAME seals.

Two fixed readiness edits and nine consumer edits invert only this reviewed
API/callback/teardown increment to 10bd7c5. Older tests exercise original algorithms and original
checkpoint hashes. Consumer behavior has separate actual HOST/FRAME contracts.
This is frozen evidence, not an automatic diff-based baseline refresh.
The accepted compiled path has a separate seven-edit fixed inverse to the
same consumer base. Only its exact default HTML loses the new empty data tag.
"""
import hashlib
import json
from pathlib import Path


_FIXTURE_SHA256 = '10004942673d2cbe53424d14c0f90e3c4cf5f8a6109f3bb93ac665e7e9d3e06e'
_BASELINE_SHA256 = 'c7e422abe9758f1fd58bf8e083016d430a24c092aa67e0c7596da82043269a02'
_CONSUMER_SHA256 = '0ec19f2101b4da49258f7e20027c127350fb975b15a94a2691da3f201f06703f'
_COMMITTED_READY_SHA256 = '3fb080901abf1bd1b2bcd57d42347bdf4f331a18e70de1e1684c602f12c18d66'
_COMPILED_SHA256 = '8a938d35b1d76eee0681dd652cfbbf3998afae8fd4fab88abad0c42babea075d'
_COMPILED_FIXTURE_SHA256 = '9ee8a3eeaed6f71072af542c3aa9168c6701a3081397e28c9e93e42c5ebbe17d'
_COMPILED_DEFAULT_HTML_SHA256 = 'b1510d852c94f7bdd98fd90fa3853ed006e1b90345f194819e4900e0a0e99b8a'
_NUMBERING_FIXTURE_SHA256 = '9020f4355b28cefdd60aa2e22f536573ccc335fd2073d15e4ab3c3927d8faf7f'
_MODULE_COHORT_FIXTURE_SHA256 = '68be30a038aeb84710086b5d611983256ad7a2711cb1b1af6730e78042071313'
_READY_EDITS = (
    ('ready=!working&&owned&&view.consumerRevision===consumerRevision&&currentPreparation(view)',
     'ready=!working&&view===committedView&&owned&&consumerCurrent(consumer)&&view.consumerRevision===consumerRevision'),
    ('function fail(error,packet,token){if(current!==packet||token!==accepted)return;working=false;',
     "function fail(error,packet,token){if(current!==packet||token!==accepted)return;if(typeof committedView!=='undefined')committedView=null;working=false;"),
)


def _numbering_inverse():
    raw = (Path(__file__).parent/'fixtures/study-section-numbering-inverse.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == _NUMBERING_FIXTURE_SHA256, 'numbering inverse evidence changed'
    proof = json.loads(raw)
    assert proof['schema'] == 'study-section-numbering-inverse.v1'
    assert len(proof['edits']) == 5 and len(proof['variants']) == 4
    return proof


def _module_cohort_inverse():
    raw = (Path(__file__).parent/'fixtures/study-example-module-cohorts-inverse.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == _MODULE_COHORT_FIXTURE_SHA256, 'module cohort inverse evidence changed'
    proof = json.loads(raw)
    assert proof['schema'] == 'study-example-module-cohorts-inverse.v1'
    assert len(proof['module_pairs']) == 2 and len(proof['variants']) == 14
    return proof


def without_example_module_cohorts(value):
    """Reverse fixed pin admissions only; retain every historical algorithm."""
    pin = hashlib.sha256(value.encode()).hexdigest()
    variants = [row for row in _module_cohort_inverse()['variants']
                if pin in (row['before_sha256'], row['after_sha256'])]
    assert len(variants) == 1, 'module cohort source differs'
    variant = variants[0]
    if pin == variant['before_sha256']:
        return value
    lines = value.splitlines(keepends=True)
    last = len(lines)
    for edit in reversed(variant['edits']):
        start, length = edit['after_line'], edit['after_lines']
        assert 0 <= start <= start+length <= last, 'module cohort edits overlap'
        assert ''.join(lines[start:start+length]) == edit['after'], 'module cohort edit differs'
        lines[start:start+length] = edit['before'].splitlines(keepends=True)
        last = start
    value = ''.join(lines)
    assert hashlib.sha256(value.encode()).hexdigest() == variant['before_sha256'], 'noncohort code changed'
    return value


def without_section_numbering(runtime):
    """Invert only the fixed section-numbering delta before older checkpoints."""
    if hashlib.sha256(runtime.encode()).hexdigest() in {
            row['after_sha256'] for row in _module_cohort_inverse()['variants']}:
        runtime = without_example_module_cohorts(runtime)
    proof = _numbering_inverse()
    pin = hashlib.sha256(runtime.encode()).hexdigest()
    variants = [row for row in proof['variants'] if pin in (row['before_sha256'], row['after_sha256'])]
    assert len(variants) == 1, 'section numbering runtime differs'
    variant = variants[0]
    if pin == variant['before_sha256']:
        return runtime
    for index in reversed(variant['edits']):
        edit = proof['edits'][index]
        assert runtime.count(edit['after']) == 1, 'section numbering edit differs'
        runtime = runtime.replace(edit['after'], edit['before'], 1)
    assert hashlib.sha256(runtime.encode()).hexdigest() == variant['before_sha256'], 'nonnumbering code changed'
    return runtime


def authored_module_loop(runtime):
    """Current verified loop for IIFE fixtures without the compiled hydrate.

    The complete compiled owner chain has a separate full-module contract.
    These original-algorithm fixtures reverse its exact outer wrapper only;
    resource verification, cancellation, checker scope and once-per-realm
    execution remain the production slice. No diagnostic phase is active.
    """
    without_section_numbering(runtime)  # Require an exact admitted runtime.
    start = runtime.index(' for(const item of scripts){const module=')
    end = runtime.index('\n if(!compiled)win.AnkiSlimDecode', start)
    loop = runtime[start:end]
    fine = ('adaptNativeFineWholeProbe(adaptSharedReadingBankWarm(adaptNativeGroupCoarseBuckets('
            'adaptNativeGroupRanges(adaptNativeGroupTranslationText(adaptNativeProjectionTask('
            'adaptNativeProjectionLookup(code,item.pin),item.pin),item.pin),item.pin),item.pin),item.pin),item.pin)')
    owner = 'adaptCompiledHistorySlotsOwner(' + fine + ',item.pin)'
    assert loop.count(owner) == 1, 'compiled owner wrapper differs'
    return 'const phase=null;' + loop.replace(owner, fine, 1)


def _compiled_inverse():
    raw = (Path(__file__).parent/'fixtures/study-compiled-consumer-inverse.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == _COMPILED_FIXTURE_SHA256, 'compiled inverse evidence changed'
    proof = json.loads(raw)
    assert proof['schema'] == 'study-compiled-consumer-inverse.v1'
    assert proof['before_sha256'] == _COMMITTED_READY_SHA256 and proof['after_sha256'] == _COMPILED_SHA256
    assert proof['default_html_sha256'] == _COMPILED_DEFAULT_HTML_SHA256
    assert len(proof['edits']) == 7
    return proof


def without_consumer_runtime(runtime):
    if hashlib.sha256(runtime.encode()).hexdigest() in {
            row['after_sha256'] for row in _module_cohort_inverse()['variants']}:
        runtime = without_example_module_cohorts(runtime)
    if hashlib.sha256(runtime.encode()).hexdigest() == _numbering_inverse()['variants'][1]['after_sha256']:
        runtime = without_section_numbering(runtime)
    if hashlib.sha256(runtime.encode()).hexdigest() == _COMPILED_SHA256:
        for edit in reversed(_compiled_inverse()['edits']):
            assert runtime.count(edit['after']) == 1, 'compiled edit differs'
            runtime = runtime.replace(edit['after'], edit['before'], 1)
    # Independently reviewed readiness semantics: retain a completed commit
    # through legal layout interactions; fail clears it immediately. No actual
    # prepare/show/promote/refresh gate changes. Reverse these two exact edits
    # before the original fixed nine-edit consumer inverse below.
    assert hashlib.sha256(runtime.encode()).hexdigest() == _COMMITTED_READY_SHA256
    for before, after in reversed(_READY_EDITS):
        assert runtime.count(after) == 1, 'committed-ready edit differs'
        runtime = runtime.replace(after, before)
    raw = (Path(__file__).parent/'fixtures/study-book-embed-inverse.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == _FIXTURE_SHA256, 'consumer inverse evidence changed'
    proof = json.loads(raw)
    assert proof['before_sha256'] == _BASELINE_SHA256 and proof['after_sha256'] == _CONSUMER_SHA256
    assert hashlib.sha256(runtime.encode()).hexdigest() == _CONSUMER_SHA256, 'consumer runtime differs'
    assert len(proof['edits']) == 9
    lines = runtime.splitlines(keepends=True)
    last = len(lines)
    for edit in reversed(proof['edits']):
        start, length = edit['after_line'], edit['after_lines']
        assert 0 <= start <= start+length <= last, 'consumer edits overlap'
        assert ''.join(lines[start:start+length]) == edit['after'], 'consumer edit differs'
        assert runtime.count(edit['after']) == 1, 'consumer edit is not unique'
        lines[start:start+length] = edit['before'].splitlines(keepends=True)
        last = start
    result = ''.join(lines)
    assert hashlib.sha256(result.encode()).hexdigest() == _BASELINE_SHA256, 'nonconsumer code changed'
    return result


def without_consumer_frame_html(html, runtime):
    assert html.count(runtime) == 1, 'FRAME must contain its exact runtime once'
    cohort = _module_cohort_inverse()
    if hashlib.sha256(runtime.encode()).hexdigest() == next(
            row['after_sha256'] for row in cohort['variants'] if row['name'] == 'compiled'):
        assert hashlib.sha256(html.encode()).hexdigest() == cohort['after_default_html_sha256'], 'module cohort default HTML differs'
        previous_runtime = without_example_module_cohorts(runtime)
        html = html.replace(runtime, previous_runtime, 1)
        runtime = previous_runtime
        assert hashlib.sha256(html.encode()).hexdigest() == cohort['before_default_html_sha256'], 'noncohort HTML changed'
    numbering = _numbering_inverse()
    if hashlib.sha256(runtime.encode()).hexdigest() == numbering['variants'][1]['after_sha256']:
        assert hashlib.sha256(html.encode()).hexdigest() == numbering['after_default_html_sha256'], 'section numbering default HTML differs'
        previous_runtime = without_section_numbering(runtime)
        html = html.replace(runtime, previous_runtime, 1)
        runtime = previous_runtime
        assert hashlib.sha256(html.encode()).hexdigest() == numbering['before_default_html_sha256'], 'nonnumbering HTML changed'
    if hashlib.sha256(runtime.encode()).hexdigest() == _COMPILED_SHA256:
        assert hashlib.sha256(html.encode()).hexdigest() == _COMPILED_DEFAULT_HTML_SHA256, 'compiled default HTML differs'
        proof = _compiled_inverse()
        assert html.count(proof['empty_configuration']) == 1, 'compiled empty configuration differs'
        html = html.replace(proof['empty_configuration'], '', 1)
        original_runtime = runtime
        for edit in reversed(proof['edits']):
            assert original_runtime.count(edit['after']) == 1, 'compiled HTML runtime edit differs'
            original_runtime = original_runtime.replace(edit['after'], edit['before'], 1)
        assert hashlib.sha256(html.replace(runtime, original_runtime, 1).encode()).hexdigest() == proof['consumer_html_sha256'], 'consumer HTML differs'
    return html.replace(runtime, without_consumer_runtime(runtime))
