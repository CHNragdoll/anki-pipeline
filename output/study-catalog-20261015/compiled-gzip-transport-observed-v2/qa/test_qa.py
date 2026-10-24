"""Small pure/temp contracts: never bind, execute JS/DOM, read PG or serve."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True

def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

server = load('snapshot_qa_server_under_test', 'snapshot_server.py')
parent = load('snapshot_qa_parent_under_test', 'prepare_parent.py')


def put(path, raw):
    path.write_bytes(raw)
    path.chmod(0o600)
    return server.digest(raw)


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='transport-qa-fixture-', dir='/private/tmp')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        self.root.chmod(0o700)
        self.source = self.root / 'source.html'
        self.original = b'<html>same original byte snapshot</html>'
        self.pin = put(self.source, self.original)
        self.row = {'route': 'A/source.html', 'path': str(self.source), 'resolved': str(self.source),
                    'bytes': len(self.original), 'sha256': self.pin, 'mime': 'text/html'}
        self.manifest = self.root / 'manifest.json'
        self.value = {'schema': server.SCHEMA, 'source_roots': [str(self.root)],
                      'routes': [self.row, dict(self.row, route='B/source.html')]}
        self.manifest_pin = put(self.manifest, json.dumps(self.value).encode())

    def test_default_check_reads_small_manifest_only_and_does_not_bind(self):
        real = server.read_pinned
        with patch.object(server, 'read_pinned', wraps=real) as reads, \
                patch.object(server, 'serve', side_effect=AssertionError('NO SERVER')) as serve, \
                patch.object(server, 'ThreadingHTTPServer', side_effect=AssertionError('NO BIND')):
            with patch.object(sys, 'argv', ['server.py', '--manifest', str(self.manifest), '--manifest-sha256', self.manifest_pin]), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                server.main()
        serve.assert_not_called()
        self.assertEqual([Path(call.args[0]) for call in reads.call_args_list], [self.manifest])
        value = json.loads(output.getvalue())
        self.assertFalse(value['socket_bound'])
        self.assertFalse(value['resource_bytes_hashed'])

    def test_shared_routes_are_authenticated_once_and_snapshot_bytes_remain_fixed(self):
        _, routes, total = server.inspect_manifest(self.manifest, self.manifest_pin)
        self.assertEqual(total, len(self.original))
        with patch.object(server, 'read_pinned', wraps=server.read_pinned) as reads:
            responses = server.make_snapshot(routes)
        self.assertEqual(reads.call_count, 1)
        self.assertIs(responses['A/source.html'], responses['B/source.html'])
        self.assertEqual(responses['A/source.html'].raw, self.original)
        self.assertTrue(server.check_used_sources(routes, responses, {'A/source.html'})[0]['source_unchanged'])
        put(self.source, b'changed source')
        self.assertEqual(responses['A/source.html'].raw, self.original)
        self.assertFalse(server.check_used_sources(routes, responses, {'A/source.html'})[0]['source_unchanged'])

    def test_source_alias_and_ancestor_replacement_are_rejected(self):
        directory = self.root / 'approved'; directory.mkdir()
        source = directory / 'source.html'; put(source, self.original)
        outside = self.root / 'outside'; outside.mkdir(); put(outside / 'source.html', b'foreign bytes')
        directory.rename(self.root / 'backup')
        directory.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(OSError): server.read_pinned(source, self.pin, len(self.original))
        alias = self.root / 'alias.html'; alias.symlink_to(self.source)
        row = dict(self.row, path=str(alias))
        snapshot = server.make_snapshot({'A/source.html': row})
        alias.unlink(); alias.symlink_to(outside / 'source.html')
        self.assertFalse(server.check_used_sources({'A/source.html': row}, snapshot, {'A/source.html'})[0]['source_unchanged'])

    def test_unknown_paths_hosts_query_and_encoded_traversal_have_no_directory_fallback(self):
        for target in ('/missing.html', '/A/../source.html', '/A/%2e%2e/source.html',
                       '/A/%252e%252e/source.html', '/A/source.html?x=1', '/A//source.html',
                       'http://localhost:1/A/source.html', 'http://[', '//other/A/source.html', '/A\\source.html'):
            with self.subTest(target=target): self.assertEqual(server.selected_route(target, '127.0.0.1:1234', 1234, {'A/source.html'}), (404,None))
        self.assertEqual(server.selected_route('/A/source.html', 'evil:1234', 1234, {'A/source.html'}), (403,None))
        self.assertEqual(server.selected_route('/A/source.html', '127.0.0.1:1234', 1234, {'A/source.html'}), (200,'A/source.html'))

    def test_original_range_semantics_and_gzip_carrier_bytes(self):
        self.assertEqual(server.byte_range(None,5),(200,0,5))
        for header,expected in [('bytes=0-0',(206,0,1)),('bytes=1-',(206,1,5)),('bytes=-2',(206,3,5)),('bytes=0-999',(206,0,5))]:
            self.assertEqual(server.byte_range(header,5),expected)
        for header in ('bytes=-0','bytes=5-','bytes=3-1','bytes=0-1,3-4','invalid'):
            with self.assertRaises(ValueError):server.byte_range(header,5)
        gzip_file=self.root/'encoded.html.gz';encoded=b'\x1f\x8b\x08raw-carrier'
        row=dict(self.row,route='A/body.html.gz',path=str(gzip_file),resolved=str(gzip_file),mime='application/gzip',
                 bytes=len(encoded),sha256=put(gzip_file,encoded))
        value=dict(self.value,routes=[row]);pin=put(self.manifest,json.dumps(value).encode())
        _,routes,_=server.inspect_manifest(self.manifest,pin)
        self.assertEqual(routes['A/body.html.gz']['mime'],'application/gzip')
        self.assertEqual(server.make_snapshot(routes)['A/body.html.gz'].raw,encoded)
        value['routes'][0]['mime']='text/html';pin=put(self.manifest,json.dumps(value).encode())
        with self.assertRaisesRegex(ValueError,'Gzip carrier'):server.inspect_manifest(self.manifest,pin)

    def test_fake_only_http_preserves_encoded_bytes_range_headers_and_flag_drain(self):
        # FakeServer never creates a socket. Its one fake request turn invokes
        # the captured signal callback, then verifies normal finally/drain.
        import signal
        encoded=b'\x1f\x8b\x08same-encoded-carrier'
        source=self.root/'carrier.gz';pin=put(source,encoded)
        row=dict(self.row,route='A/carrier.gz',path=str(source),resolved=str(source),
                 bytes=len(encoded),sha256=pin,mime='application/gzip')
        value=dict(self.value,routes=[row]);manifest_pin=put(self.manifest,json.dumps(value).encode())
        callbacks={};events=[];deliveries=[]
        class FakeServer:
            server_port=34567
            def __init__(self,address,handler):
                self.handler=handler;self.assert_address=address;events.append(('constructor-no-socket',address))
            def handle_request(self):
                for method,header,target,host in (('GET',None,'/A/carrier.gz','127.0.0.1:34567'),
                        ('HEAD',None,'/A/carrier.gz','127.0.0.1:34567'),
                        ('GET','bytes=1-3','/A/carrier.gz','127.0.0.1:34567'),
                        ('GET',None,'/missing.css?private-do-not-record','127.0.0.1:34567'),
                        ('GET',None,'/A/carrier.gz','evil:34567'),
                        ('GET','bytes=900-','/A/carrier.gz','127.0.0.1:34567')):
                    h=object.__new__(self.handler);h.server=self;h.command=method;h.path=target
                    h.headers={'Host':host}
                    if header:h.headers['Range']=header
                    h.wfile=io.BytesIO();headers={};status=[]
                    h.send_response=lambda code:status.append(code)
                    h.send_header=lambda key,value:headers.__setitem__(key,value)
                    h.end_headers=lambda:None
                    h.send_error=lambda code:status.append(code)
                    h.deliver(method=='GET');deliveries.append((method,status[0],headers,h.wfile.getvalue()))
                events.append('requests-returned');callbacks[signal.SIGTERM](signal.SIGTERM,None)
            def server_close(self):events.append('drained-without-listener')
        with patch.object(server,'ThreadingHTTPServer',FakeServer), \
                patch.object(server.signal,'getsignal',return_value=None), \
                patch.object(server.signal,'signal',side_effect=lambda sig,callback:callbacks.__setitem__(sig,callback)), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            server.serve(self.manifest,manifest_pin)
        self.assertEqual(events,[('constructor-no-socket',('127.0.0.1',0)),'requests-returned','drained-without-listener'])
        for method,status,headers,raw in deliveries[:3]:
            self.assertEqual(headers['Content-Type'],'application/gzip')
            self.assertEqual(headers['Cache-Control'],'no-store')
            self.assertNotIn('Content-Encoding',headers)
            self.assertEqual(raw,b'' if method=='HEAD' else encoded[1:4] if status==206 else encoded)
        self.assertEqual(deliveries[2][2]['Content-Range'],f'bytes 1-3/{len(encoded)}')
        closed=json.loads(list(self.root.glob('closed-*.json'))[0].read_bytes())
        self.assertTrue(closed['drained']);self.assertTrue(closed['used_sources_unchanged'])
        self.assertEqual(closed['request_count'],6)
        ledger_raw=list(self.root.glob('requests-*.json'))[0].read_bytes();ledger=json.loads(ledger_raw)
        self.assertEqual([row['status'] for row in ledger],[200,200,206,404,403,416])
        self.assertEqual(ledger[3]['path'],'/missing.css')
        self.assertIsNone(ledger[3]['sha256']);self.assertEqual(ledger[3]['bytes'],0)
        self.assertNotIn(b'private-do-not-record',ledger_raw)

    def test_pin_drift_scope_and_memory_cap_fail_closed(self):
        put(self.source,b'changed with same source identity')
        with self.assertRaises(ValueError):server.make_snapshot({'A/source.html':self.row})
        put(self.source,self.original)
        wrong=dict(self.value,source_roots=[str(self.root/'not-an-approved-root')])
        (self.root/'not-an-approved-root').mkdir()
        pin=put(self.manifest,json.dumps(wrong).encode())
        with self.assertRaisesRegex(ValueError,'outside'):server.inspect_manifest(self.manifest,pin)
        pin=put(self.manifest,json.dumps(self.value).encode())
        with patch.object(server,'MAX_SNAPSHOT',1),self.assertRaisesRegex(ValueError,'300 MiB'):
            server.inspect_manifest(self.manifest,pin)


class ParentTests(unittest.TestCase):
    def test_full_parent_changes_only_frame_and_collector_metadata_and_is_invertible(self):
        old_frame=b'<html><head>original frame</head></html>'
        new_frame=b'<html><head>gzip transport frame</head></html>'
        config=parent.literal({'navigation':'same.json','sharedFrame':{'html':old_frame.decode(),'policy':{'external':{'x':'pin'}}}})
        collector=b"(function(){\n const metadata={\"case_id\":\"fixture\"};\nconst flips='ORIGINAL-FLIP';\n})();"
        block=b'<script id="study-compiled-profile-qa-clock">\n'+collector+b'\n</script>\n'
        original=b'<head></head><main>ORIGINAL-FULL-HOST-fetchCard-source-prepared</main>'+config+block+b'<footer>unchanged</footer>'
        output,new_collector=parent.render_parent(original,config,collector,old_frame,new_frame,variant='B',frame_pin='b'*64)
        self.assertIn(b'ORIGINAL-FULL-HOST-fetchCard-source-prepared',output)
        self.assertIn(b"const flips='ORIGINAL-FLIP'",new_collector)
        self.assertIn(b'"transport_variant":"B"',new_collector)
        self.assertIn(b'"navigation":"same.json"',output)
        self.assertEqual(output.count(new_frame),0)  # frame stays safely JSON escaped
        with self.assertRaises(ValueError):parent.render_parent(original+config,config,collector,old_frame,new_frame,variant='B',frame_pin='b'*64)
        with self.assertRaises(ValueError):parent.render_parent(original,config,collector,old_frame,new_frame,variant='unknown',frame_pin='b'*64)


if __name__=='__main__':
    unittest.main()
