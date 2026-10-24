"""Small persistent-worker protocol checks; no semantic DOM producer or real cards."""
import hashlib
import importlib.util
import json
from pathlib import Path
import select
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / 'anki_pipeline/compiled/build-worker.cjs'
NODE = shutil.which('node')


def profile_fixture_source():
    """Reuse the existing tiny, authenticated emitter input; run no tests."""
    location = ROOT / 'tests/test_study_compiled_profiles.py'
    spec = importlib.util.spec_from_file_location('worker_profile_fixture', location)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.FIXTURE_JS


@unittest.skipUnless(NODE, 'Node.js is unavailable')
class CompiledWorkerTests(unittest.TestCase):
    def make_profiles(self, directory, count=1):
        directories = [str(Path(directory) / str(n)) for n in range(count)]
        program = profile_fixture_source() + r"""
const directories=JSON.parse(fs.readFileSync(0,'utf8'));
console.log(JSON.stringify(directories.map(directory=>{
 fs.mkdirSync(directory);return fixture(directory).requestFile;
})));
"""
        result = subprocess.run([NODE, '-e', program], cwd=ROOT,
                                input=json.dumps(directories), capture_output=True,
                                text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def command(self, request, output, ident='task-1', operation='profile'):
        return {'id': ident, 'operation': operation,
                'request': str(request), 'output': str(output)}

    def run_lines(self, lines):
        result = subprocess.run([NODE, str(WORKER)], cwd=ROOT,
                                input=b''.join(lines), capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
        self.assertEqual(result.stderr, b'')
        return [json.loads(line) for line in result.stdout.splitlines()]

    def assert_response_shape(self, response):
        self.assertLess(len(json.dumps(response).encode()), 6000)
        self.assertEqual(set(response), {'id', 'ok', 'report' if response['ok'] else 'error'})
        if response['ok']:
            self.assertEqual(set(response['report']), {'path', 'sha256', 'bytes'})
        else:
            self.assertEqual(set(response['error']), {'name', 'message'})
            self.assertLessEqual(len(response['error']['message']), 512)

    def read_response(self, process):
        ready, _, _ = select.select([process.stdout], [], [], 10)
        self.assertTrue(ready, 'worker did not return a bounded response')
        line = process.stdout.readline()
        self.assertTrue(line, 'worker exited without a command response')
        response = json.loads(line)
        self.assert_response_shape(response)
        return response

    def test_two_real_tiny_profiles_use_same_live_process_and_report_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            requests = self.make_profiles(directory, 2)
            process = subprocess.Popen([NODE, str(WORKER)], cwd=ROOT,
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE)
            pid = process.pid
            try:
                for n, request in enumerate(requests):
                    command = self.command(request, Path(directory) / ('output-' + str(n)), 'profile-' + str(n))
                    process.stdin.write(json.dumps(command).encode() + b'\n')
                    process.stdin.flush()
                    response = self.read_response(process)
                    self.assertTrue(response['ok'], response)
                    self.assertEqual(response['id'], command['id'])
                    self.assertEqual(process.pid, pid)
                    self.assertIsNone(process.poll())
                    descriptor = response['report']
                    report = Path(descriptor['path']).read_bytes()
                    self.assertEqual(Path(descriptor['path']), Path(command['output']) / 'report.json')
                    self.assertEqual(hashlib.sha256(report).hexdigest(), descriptor['sha256'])
                    self.assertEqual(len(report), descriptor['bytes'])
                    self.assertEqual(json.loads(report)['schema'], 'study-compiled-profile-result.v1')
                process.stdin.close()
                self.assertEqual(process.wait(timeout=10), 0)
                self.assertEqual(process.stdout.read(), b'')
                self.assertEqual(process.stderr.read(), b'')
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                for stream in (process.stdin, process.stdout, process.stderr):
                    stream.close()

    def test_bad_json_utf8_and_command_fields_reject_then_valid_command_continues(self):
        with tempfile.TemporaryDirectory() as directory:
            request = self.make_profiles(directory)[0]
            output = Path(directory) / 'output'
            valid = self.command(request, output)
            bad = [b'{bad json}\n', b'\xff\n', b'[]\n']
            for edit in [dict(operation='unknown'), dict(extra=True), dict(id='x' * 129),
                         dict(request='relative.json'), dict(output=str(Path(directory) / '..' / 'escape')),
                         dict(request='/' + 'x' * 4096)]:
                bad.append(json.dumps(valid | edit).encode() + b'\n')
            responses = self.run_lines(bad + [json.dumps(valid).encode() + b'\n'])
            self.assertEqual(len(responses), len(bad) + 1)
            self.assertTrue(all(not response['ok'] for response in responses[:-1]))
            self.assertTrue(responses[-1]['ok'], responses[-1])
            for response in responses:
                self.assert_response_shape(response)

    def test_oversized_line_is_discarded_once_and_next_command_survives(self):
        with tempfile.TemporaryDirectory() as directory:
            request = Path(directory) / 'bad-request.json'
            request.write_text('{}')
            valid = self.command(request, Path(directory) / 'not-created', 'after-large', 'semantic')
            responses = self.run_lines([b'x' * (200 * 1024) + b'\n', json.dumps(valid).encode() + b'\n'])
            self.assertEqual(len(responses), 2)
            self.assertFalse(responses[0]['ok'])
            self.assertIsNone(responses[0]['id'])
            self.assertIn('line', responses[0]['error']['message'])
            self.assertFalse(responses[1]['ok'])
            self.assertEqual(responses[1]['id'], 'after-large')
            self.assertIn('semantic request', responses[1]['error']['message'])

    def test_semantic_failure_and_existing_output_leave_next_profile_usable(self):
        with tempfile.TemporaryDirectory() as directory:
            request = self.make_profiles(directory)[0]
            invalid = Path(directory) / 'invalid.json'
            invalid.write_text('{}')
            existing = Path(directory) / 'existing'
            existing.mkdir()
            sentinel = existing / 'keep.txt'
            sentinel.write_text('unrelated')
            commands = [self.command(invalid, Path(directory) / 'invalid-out', 'bad-semantic', 'semantic'),
                        self.command(request, existing, 'existing'),
                        self.command(request, Path(directory) / 'good', 'good')]
            responses = self.run_lines([json.dumps(command).encode() + b'\n' for command in commands])
            self.assertEqual([response['ok'] for response in responses], [False, False, True])
            self.assertEqual(sentinel.read_text(), 'unrelated')
            self.assertEqual([response['id'] for response in responses], [command['id'] for command in commands])

    def test_empty_stdin_and_unterminated_last_command_exit_normally(self):
        self.assertEqual(self.run_lines([]), [])
        with tempfile.TemporaryDirectory() as directory:
            request = Path(directory) / 'bad.json'
            request.write_text('{}')
            command = self.command(request, Path(directory) / 'new', operation='semantic')
            responses = self.run_lines([json.dumps(command).encode()])
            self.assertEqual(len(responses), 1)
            self.assertFalse(responses[0]['ok'])

    def test_transport_failure_rejects_without_fabricating_a_success(self):
        program = r"""
(async()=>{const assert=require('node:assert/strict'),{Writable}=require('node:stream');
const worker=require('./anki_pipeline/compiled/build-worker.cjs');let text='';
const output=new Writable({write(chunk,encoding,callback){text+=chunk.toString();callback();}});
async function* broken(){throw Error('input transport failed');}
await assert.rejects(worker.runWorker(broken(),output),/input transport failed/);
assert.equal(text,'');
})().catch(error=>{console.error(error);process.exitCode=1});
"""
        result = subprocess.run([NODE, '-e', program], cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_optional_gc_only_runs_above_threshold_after_response(self):
        program = r"""
(async()=>{const assert=require('node:assert/strict'),{Writable}=require('node:stream');
const worker=require('./anki_pipeline/compiled/build-worker.cjs'),trace=[];
const memory=process.memoryUsage,oldGc=global.gc;let heapUsed=worker.LIMITS.idleGcHeapBytes;
process.memoryUsage=()=>({heapUsed});global.gc=()=>trace.push('gc');
try{
 const output=new Writable({write(chunk,encoding,callback){trace.push('response');callback();}});
 async function* lines(){yield Buffer.from('{}\n');heapUsed++;yield Buffer.from('{}\n');}
 await worker.runWorker(lines(),output);
 assert.deepEqual(trace,['response','response','gc']);
}finally{process.memoryUsage=memory;if(oldGc===undefined)delete global.gc;else global.gc=oldGc;}
})().catch(error=>{console.error(error);process.exitCode=1});
"""
        result = subprocess.run([NODE, '-e', program], cwd=ROOT, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
