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
_READY_EDITS = (
    ('ready=!working&&owned&&view.consumerRevision===consumerRevision&&currentPreparation(view)',
     'ready=!working&&view===committedView&&owned&&consumerCurrent(consumer)&&view.consumerRevision===consumerRevision'),
    ('function fail(error,packet,token){if(current!==packet||token!==accepted)return;working=false;',
     "function fail(error,packet,token){if(current!==packet||token!==accepted)return;if(typeof committedView!=='undefined')committedView=null;working=false;"),
)


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
