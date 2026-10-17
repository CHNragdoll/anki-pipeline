from pathlib import Path
import hashlib
import json
import os
import stat
import subprocess
import time

ROOT = Path('/Users/apple/Documents/PyCharm/Anki/anki_rebuild')
STAGE = Path('/tmp/study-largest-codec-once-sealed-20261017-8ztnwna5')
DEST = ROOT / 'output/study-catalog-20261015/compiled-authored-codec-largest-stopped-v1'
SEAL = 'f2a95972a1dd1733d5a8c62a4abda419205514d88c5132bca7db42950b7b0e04'


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def stats(value):
    return {key: str(number) for key, number in (
        ('dev', value.st_dev), ('ino', value.st_ino), ('size', value.st_size),
        ('mtimeNs', value.st_mtime_ns), ('ctimeNs', value.st_ctime_ns))}


def verify_external(label, row):
    path = Path(row['path'])
    resolved_before = str(path.resolve(strict=True))
    before = path.stat()
    assert resolved_before == row['resolved'], (label, 'alias changed')
    assert stats(before) == row['stat'], (label, 'source stat changed')
    hasher = hashlib.sha256()
    count = 0
    with path.open('rb') as handle:
        opened = os.fstat(handle.fileno())
        assert stat.S_ISREG(opened.st_mode), (label, 'nonregular source')
        assert stats(opened) == row['stat'], (label, 'opened source changed')
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b''):
            hasher.update(chunk)
            count += len(chunk)
        assert stats(os.fstat(handle.fileno())) == row['stat'], (label, 'source changed during hash')
    assert str(path.resolve(strict=True)) == resolved_before, (label, 'alias changed during hash')
    after = path.stat()
    assert stats(after) == row['stat'], (label, 'source replaced during hash')
    assert count == row['bytes'] and hasher.hexdigest() == row['sha256'], (label, 'source content changed')
    return {'label': label, **row, 'current_sha256': hasher.hexdigest(),
            'current_bytes': count, 'current_stat': stats(after),
            'alias_unchanged': True, 'source_stat_unchanged': True,
            'source_bytes_unchanged': True}


raw_seal = (STAGE / 'FROZEN.json').read_bytes()
assert digest(raw_seal) == SEAL
seal = json.loads(raw_seal)
sealed_files = []
for row in seal['files']:
    path = STAGE / row['path']
    assert path.parent == STAGE and not path.is_symlink()
    raw = path.read_bytes()
    assert len(raw) == row['bytes'] and digest(raw) == row['sha256'], row['path']
    sealed_files.append(row)

inputs = json.loads((STAGE / 'inputs.json').read_bytes())
source_rows = [(key, inputs[key]) for key in ('fixture_freeze', 'body', 'profile', 'packet', 'policy_source')]
source_rows += [('resource:' + key, value) for key, value in inputs['resources'].items()]
source_verification = [verify_external(label, row) for label, row in source_rows]

stdout_raw = (STAGE / 'stdout.log').read_bytes()
stderr_raw = (STAGE / 'stderr.log').read_bytes()
phases = [json.loads(line) for line in stdout_raw.decode().splitlines() if line]
assert [row['phase'] for row in phases] == ['sealed-input-verification', 'inert-DOM-parse-start']
assert b'JavaScript heap out of memory' in stderr_raw
assert b'FATAL ERROR:' in stderr_raw
ended = json.loads((STAGE / 'RUN-ENDED.json').read_bytes())
assert ended['pid'] == 77809 and ended['signal'] == 6
assert ended['attempt'] == 1 and not ended['timed_out'] and not ended['restarted']
assert ended['external_seal_sha256'] == SEAL
assert ended['argv'][1] == '--max-old-space-size=2048'

candidate_names = ('profile-with-authored-codec.json', 'candidate-frame.js', 'candidate-frame.html',
                   'candidate-assets.json', 'frame-assets-edits.json', 'result.json', 'failure.json')
candidate_absence = {name: not (STAGE / name).exists() for name in candidate_names}
assert all(candidate_absence.values())
allowed_names = {row['path'] for row in sealed_files} | {
    'FROZEN.json', 'RUNNING.json', 'RUN-ENDED.json', 'stdout.log', 'stderr.log'}
assert {path.name for path in STAGE.iterdir()} == allowed_names
worker = (STAGE / 'worker.cjs').read_text()
assert "runScripts:'outside-only'" in worker
assert worker.index("phase('inert-DOM-parse-start'") < worker.index('dom=new JSDOM')
assert worker.index('dom=new JSDOM') < worker.index("phase('inert-DOM-parse-complete')")
assert worker.index("phase('inert-DOM-parse-complete')") < worker.index('firstExecutions++;w.eval(FIRST)')
ps = subprocess.run(['/bin/ps', '-p', '77809', '-o', 'pid=,comm=,state='],
                    capture_output=True, text=True, timeout=3, check=False)
pid_absent = ps.returncode == 1 and not ps.stdout.strip()
assert pid_absent, 'Original PID unexpectedly present; do not infer ownership or signal it'

report = {
    'schema': 'study-largest-authored-codec-stopped-review.v1',
    'status': 'stopped-inert-dom-parse-oom-no-candidate',
    'observed_unix': time.time(),
    'stage': str(STAGE), 'external_preflight_seal_sha256': SEAL,
    'preflight_seal_is_historical_not_executed_flag': True,
    'execution': ended,
    'root_controller_session': 15480,
    'controller_exit_code_from_root': 1,
    'observed_stdout_phases': phases,
    'fatal_stderr': 'FATAL ERROR: Ineffective mark-compacts near heap limit Allocation failed - JavaScript heap out of memory',
    'original_pid_absent': pid_absent,
    'sealed_local_file_count': len(sealed_files),
    'sealed_local_files_unchanged': True,
    'external_source_count': len(source_verification),
    'external_source_total_bytes_stream_verified': sum(row['current_bytes'] for row in source_verification),
    'external_sources': source_verification,
    'candidate_output_absent': candidate_absence,
    'stage_contains_only_frozen_inputs_and_execution_receipts': True,
    'proof_boundaries': {
        'first_execution_reached': False,
        'first_execution_evidence': 'Sealed worker performs synchronous outside-only JSDOM construction and emits parse-complete before its only FIRST evaluation; stdout ended at parse-start and native fatal OOM aborted before parse-complete.',
        'automatic_authored_execution_disabled': True,
        'inert_dom_parse_completed': False,
        'full_dom_zero_effect_proved': False,
        'runtime_14_cohort_dom_ledger_proved': False,
        'tiny_profile_certificate_created': False,
        'tiny_profile_inverse_proved': False,
        'original_binder_validation_performed': False,
        'maximum_candidate_ready_for_browser': False,
        'performance_or_paint_claim': False,
        'new_execution_or_retry_performed_by_archiver': False,
        'large_body_profile_packet_copied_to_archive': False,
    },
}

DEST.mkdir(mode=0o700, parents=True, exist_ok=False)
(DEST / 'preflight').mkdir(mode=0o700)
(DEST / 'execution').mkdir(mode=0o700)


def write(relative, raw):
    with (DEST / relative).open('xb') as handle:
        handle.write(raw)


for row in sealed_files:
    write('preflight/' + row['path'], (STAGE / row['path']).read_bytes())
write('preflight/FROZEN.json', raw_seal)
for name in ('RUNNING.json', 'RUN-ENDED.json', 'stdout.log', 'stderr.log'):
    write('execution/' + name, (STAGE / name).read_bytes())
write('post-verification.json', (json.dumps(report, ensure_ascii=False, indent=2) + '\n').encode())
write('archive-evidence.py', Path(__file__).read_bytes())
readme = '''# Maximum authored-codec attempt stopped

The single root-owned Node attempt (PID 77809, root exec session 15480) aborted with
signal 6 after 23.544 s during construction of the 49,390,544-byte inert JSDOM.
The original stderr reports JavaScript heap out of memory with a 2,048 MB heap
limit. It did not reach the first original codec evaluation. No retry or heap
increase was performed.

No new profile, FRAME, asset descriptor, or success result was produced. The
small-candidate-frame files under preflight are unchanged sealed INPUTS, not a
maximum-card output. The copied preflight FROZEN not_executed flag describes its
historical pre-run seal; execution/RUN-ENDED.json is the terminal run receipt.
Do not execute the archived run.py or worker.cjs.

post-verification.json contains stream SHA/length and before/open/after stat and
alias checks for all 13 external inputs. These checks all matched their original
pins after termination. Large HTML/profile/packet content is referenced by path
and pins only, not copied here. All 13 local preflight files matched their seal.

Uncompleted: inert DOM completion, original FIRST zero-DOM-effect proof, actual
DOM 14-position ledger, tiny certificate insertion/inverse, original binder
validation, maximum candidate and maximum browser acceptance. This is failure
evidence, not a performance result or a weakened acceptance gate.
'''
write('README.md', readme.encode())
files = []
for path in sorted(DEST.rglob('*')):
    if path.is_file():
        raw = path.read_bytes()
        files.append({'path': str(path.relative_to(DEST)), 'bytes': len(raw), 'sha256': digest(raw)})
archive_seal = {'schema': 'study-largest-authored-codec-stopped-evidence.v1',
                'status': report['status'], 'original_preflight_sha256': SEAL,
                'files': files, 'does_not_authorize_execution': True}
write('FROZEN.json', (json.dumps(archive_seal, indent=2) + '\n').encode())
archive_raw = (DEST / 'FROZEN.json').read_bytes()
print(json.dumps({'path': str(DEST), 'files': len(files) + 1,
                  'total_bytes': sum(row['bytes'] for row in files) + len(archive_raw),
                  'external_seal_sha256': digest(archive_raw),
                  'report_sha256': digest((DEST / 'post-verification.json').read_bytes()),
                  'input_count': len(source_verification), 'all_input_pins_match': True,
                  'status': report['status']}))
