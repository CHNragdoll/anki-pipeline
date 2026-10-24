"""Fresh-process modern APKG codecs, isolated from the caller's RSS high-water.

The worker accepts only two fixed codec operations and JSON data on stdin. It
never opens PostgreSQL or executes caller-provided code. Codec source/output
pins, publication rules and resource limits remain owned by the existing APIs.
"""
from __future__ import annotations

from contextlib import redirect_stdout
from dataclasses import asdict
import json
from pathlib import Path
import re
import subprocess
import sys
import traceback

from .study_modern_recompress import RecompressionLimits, _Budget

_SCHEMA = 'study-modern-codec-worker.v1'
_RESULT = 'study-modern-codec-result.v1'
_OPTIONS = {'convert': frozenset({'expected_source_bytes'}),
            'recompress': frozenset({'level', 'window_log', 'prefix', 'expected_prefix_sha256'})}


def _need(value, message):
    if not value:
        raise ValueError(message)


def _unique(pairs):
    value = {}
    for key, item in pairs:
        _need(key not in value, 'duplicate codec JSON key')
        value[key] = item
    return value


def _request(value):
    _need(type(value) is dict and set(value) == {'schema', 'operation', 'source', 'destination',
          'expected_source_sha256', 'limits', 'options'} and value['schema'] == _SCHEMA,
          'exact codec worker request required')
    operation = value['operation']
    _need(type(operation) is str and operation in _OPTIONS, 'unsupported codec operation')
    for key in ('source', 'destination'):
        _need(type(value[key]) is str and Path(value[key]).is_absolute(), 'absolute codec path required')
    _need(type(value['expected_source_sha256']) is str and
          re.fullmatch('[0-9a-f]{64}', value['expected_source_sha256']), 'source SHA256 pin required')
    _need(type(value['limits']) is dict and set(value['limits']) == set(asdict(RecompressionLimits())),
          'exact codec limits required')
    limits = RecompressionLimits(**value['limits'])
    # Construction validates the limits without consulting this parent's RSS.
    _Budget(limits, Path(value['destination']).parent)
    _need(type(value['options']) is dict and set(value['options']) <= _OPTIONS[operation],
          'unsupported codec options')
    return operation, limits


def _execute(value):
    operation, limits = _request(value)
    if operation == 'convert':
        from .study_modern_convert import convert_legacy_apkg
        function = convert_legacy_apkg
    else:
        from .study_modern_recompress import recompress_modern_apkg
        function = recompress_modern_apkg
    # Keep the single JSON stdout protocol separate from any library diagnostics.
    with redirect_stdout(sys.stderr):
        report = function(value['source'], value['destination'],
            expected_source_sha256=value['expected_source_sha256'], limits=limits, **value['options'])
    return {'schema': _RESULT, 'operation': operation, 'report': report}


def run_codec(operation, source, destination, *, expected_source_sha256, limits=None, **options):
    """Run one original codec API in a fresh interpreter with unchanged budgets.

    Source/destination are absolute before changing cwd. The child has no live
    catalog connection; the caller retains its original projection transaction.
    Failure/timeout retains all codec partials and cannot be reported as success.
    """
    limits = limits if limits is not None else RecompressionLimits()
    _need(isinstance(limits, RecompressionLimits), 'explicit RecompressionLimits required')
    value = {'schema': _SCHEMA, 'operation': operation, 'source': str(Path(source).absolute()),
             'destination': str(Path(destination).absolute()),
             'expected_source_sha256': expected_source_sha256, 'limits': asdict(limits), 'options': options}
    _, limits = _request(value)
    try:
        result = subprocess.run([sys.executable, '-B', '-m', 'anki_pipeline.study_modern_codec_worker'],
            input=json.dumps(value, ensure_ascii=False, allow_nan=False), text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=Path(__file__).resolve().parent.parent, timeout=limits.wall_seconds)
    except subprocess.TimeoutExpired as error:
        raise TimeoutError('modern '+operation+' worker exceeded wall budget; partials retained') from error
    if result.returncode:
        raise ValueError('modern '+operation+' worker failed (exit '+str(result.returncode)+'); partials retained: '+result.stderr[-8192:])
    try:
        response = json.loads(result.stdout, object_pairs_hook=_unique)
    except (ValueError, TypeError) as error:
        raise ValueError('modern '+operation+' worker returned invalid JSON; outputs retained') from error
    _need(type(response) is dict and set(response) == {'schema', 'operation', 'report'} and
          response['schema'] == _RESULT and response['operation'] == operation, 'codec worker response differs')
    report = response['report']
    _need(type(report) is dict and report.get('schema') ==
          ('study-modern-conversion.v1' if operation == 'convert' else 'study-modern-recompression.v1') and
          (operation != 'convert' or report.get('status') == 'COMPLETE'), 'codec worker did not complete')
    identity = report.get('source_identity_before')
    _need(report.get('source') == value['source'] and report.get('destination') == value['destination'] and
          report.get('source_sha256') == expected_source_sha256 and
          report.get('source_identity_sha256_unchanged') is True and
          type(identity) is list and len(identity) == 6 and all(type(n) is int for n in identity) and
          identity == report.get('source_identity_after') and report.get('source_bytes') == identity[3] and
          (options.get('expected_source_bytes') is None or report['source_bytes'] == options['expected_source_bytes']),
          'codec worker source/destination pins differ')
    _need(type(report.get('output_bytes')) is int and 0 < report['output_bytes'] <= limits.output_bytes and
          type(report.get('output_sha256')) is str and re.fullmatch('[0-9a-f]{64}', report['output_sha256']) and
          type(report.get('peak_rss_bytes')) is int and report['peak_rss_bytes'] <= limits.rss_bytes,
          'codec worker output pins/budget differ')
    return report


def main():
    try:
        raw = sys.stdin.buffer.read(65537)
        _need(len(raw) <= 65536, 'codec worker request exceeds 64KiB')
        value = json.loads(raw, object_pairs_hook=_unique)
        report = _execute(value)
        json.dump(report, sys.stdout, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
        sys.stdout.write('\n'); sys.stdout.flush()
    except Exception:
        traceback.print_exc(file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
