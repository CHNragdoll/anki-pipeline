"""Real HTTP replay against a frozen legacy oracle; no ignored runtime imports.

The small loopback transport is a test adapter for StudyStore.dispatch, not a
replacement for the live server or its host/CSRF/static-file boundary.
The oracle retains object insertion order: action hashes and restored scheduler
JSON text are part of the legacy state, not values to sort or normalize away.
"""
from contextlib import contextmanager
from datetime import datetime
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.metadata import version
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
import uuid

from anki_pipeline import study_progress
from anki_pipeline.study_progress_snapshot import canonical_rows


FIXTURE = Path(__file__).parent / 'fixtures' / 'study-progress-legacy-v1.json'


@contextmanager
def serve(store):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def _route(self, method):
            parsed = urlsplit(self.path)
            query = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
            body = (json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                    if method == 'POST' else None)
            try:
                status, result = 200, store.dispatch(method, parsed.path, query, body or {})
            except Exception as error:
                status = getattr(error, 'status', 500)
                result = {'error': getattr(error, 'message', '操作失败，进度未保存，请重试。')}
            raw = json.dumps(result, ensure_ascii=False, allow_nan=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            self._route('GET')

        def do_POST(self):
            self._route('POST')

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()
        if thread.is_alive():
            raise RuntimeError('test HTTP server did not stop')


def request(port, method, path, body=None):
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
    try:
        raw = (json.dumps(body, ensure_ascii=False, allow_nan=False).encode('utf-8')
               if body is not None else None)
        connection.request(method, path, body=raw, headers={'Content-Type': 'application/json'})
        response = connection.getresponse()
        payload = response.read()
        headers = {name: response.getheader(name) for name in (
            'Content-Type', 'Content-Length', 'Cache-Control', 'X-Content-Type-Options')}
        return response.status, headers, payload
    finally:
        connection.close()


def state(path):
    rows = list(canonical_rows(path))
    return hashlib.sha256(b''.join(rows)).hexdigest(), [json.loads(row) for row in rows]


class ProgressHTTPReplayTests(unittest.TestCase):
    def test_runtime_matches_the_legacy_pinned_scheduler(self):
        self.assertEqual(version('fsrs'), '6.3.2')
        self.assertEqual(version('typing-extensions'), '4.16.0')

    def test_http_responses_and_every_table_match_frozen_legacy_sequence(self):
        fixture = json.loads(FIXTURE.read_text(encoding='utf-8'))
        self.assertEqual(fixture['schema'], 'study-progress-legacy-http.v1')
        self.assertEqual(fixture['provenance']['backend_sha256'],
                         '782963ec45a9a6f708c28497fedadea8c284830d5ccde4491a6946677fa609b7')
        clock = [datetime.fromisoformat(fixture['clock_start'])]
        fixed_uuid = uuid.UUID(fixture['uuid4'])
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'progress.sqlite3'
            store = study_progress.StudyStore(path, fixture['catalog'], now=lambda: clock[0])
            self.assertEqual(state(path)[0], fixture['initial_state_sha256'])
            with patch.object(study_progress.uuid, 'uuid4', return_value=fixed_uuid), serve(store) as port:
                for step in fixture['requests']:
                    with self.subTest(request=step['name']):
                        clock[0] = datetime.fromisoformat(step['at'])
                        status, headers, payload = request(port, step['method'], step['path'], step['body'])
                        self.assertEqual(status, step['status'])
                        self.assertEqual(headers, step['headers'])
                        self.assertEqual(payload.decode('utf-8'), step['response_text'])
                        self.assertEqual(state(path)[0], step['state_sha256'],
                                         'cards/history/revisions/sequence/dedupe/settings/controls drifted')
                        if step['backup_before_sha256'] is not None:
                            backup = path.parent / 'backups' / json.loads(payload)['automaticBackup']
                            self.assertEqual(state(backup)[0], step['backup_before_sha256'])
            self.assertEqual(state(path)[1], fixture['final_state'])


if __name__ == '__main__':
    unittest.main()
