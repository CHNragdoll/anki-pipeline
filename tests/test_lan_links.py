"""Exercise sealed nested cards through the unsealed LAN shell companion."""
import base64
import hashlib
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import ipaddress
import json
from pathlib import Path
import shutil
import subprocess
import threading
import unittest
from unittest.mock import MagicMock, patch

from scripts import serve_preview_lan as lan

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/lan_links.js"
SCRIPT_URL = "/_preview_lan_links.js"
AUXILIARY_PATH = '/residual-optimization-20261013/engineering/preview-own/root-full-preview-v1/assets/auxiliary-chunks.js'
SEALED = b'<head></head><a class="sentence-jump" href="http://localhost:8765/exam-library/practice/full-paper.htm?paper=kaoyan%3A2025-01&amp;word=offline#sentence">source</a>'
AUXILIARY_SEALED = SEALED.replace(b'class="sentence-jump" ', b'').replace(
    b'<a ', b'<section class="sf-report" data-residual-auxiliary-entry="fixture"><article class="sf-example"><p><a ').replace(
    b'</a>', b'</a></p></article></section>')

HARNESS = r"""
const {JSDOM} = require('jsdom'), fs = require('node:fs'), assert = require('node:assert/strict');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const dom = new JSDOM(input.shell, {url: input.url || 'http://192.168.3.5:8771/preview-library.html', runScripts:'outside-only'});
const win=dom.window, doc=win.document;
const latex='http://localhost:8765/english-exams-reflow-latex/kaoyan/papers/2025-01.htm?sentence=one%3Atwo&word=off%2Dline#exact';
const full='http://127.0.0.1:8765/exam-library/practice/full-paper.htm?paper=kaoyan%3A2025-01#exact';
function link(document, url=latex) {
  const a=document.createElement('a'); a.className='sentence-jump'; a.href=url;
  a.setAttribute('data-latex-url',latex); a.setAttribute('data-full-paper-url',full);
  a.setAttribute('data-reader','latex'); document.body.append(a); return a;
}
function frame(document) {const f=document.createElement('iframe');document.body.append(f);return f;}
const outer=frame(doc), card=outer.contentDocument, anchor=link(card);
const nested=frame(card), history=nested.contentDocument, historical=link(history, full);
if (input.directAux) win.eval(input.asset);
if (doc.querySelector('script[src="/_preview_lan_links.js"]') && fs.existsSync(input.script)) win.eval(fs.readFileSync(input.script,'utf8'));
const tick=()=>new Promise(resolve=>win.setTimeout(resolve,0));
(async()=>{ __BODY__ })().then(()=>{dom.window.close();process.stdout.write('PASS\n');}).catch(e=>{dom.window.close();console.error(e);process.exitCode=1;});
"""


class LanLinkRuntimeTests(unittest.TestCase):
    def node(self, body, url=None, direct_aux=False):
        shell = (AUXILIARY_SEALED if direct_aux else
                 lan.bootstrap_hash_runtime(b'<html><head></head><body></body></html>', '/preview-library.html'))
        asset = getattr(lan, 'bootstrap_auxiliary_links', lambda raw, path: raw)(b'window.savedNativePrefix=true;', AUXILIARY_PATH)
        result = subprocess.run([shutil.which('node'), '-e', HARNESS.replace('__BODY__', body)],
            input=json.dumps({'shell': shell.decode(), 'script': str(SCRIPT), 'url': url,
                             'directAux': direct_aux, 'asset': asset.decode()}),
            text=True, capture_output=True, cwd=ROOT, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), 'PASS')

    def test_sealed_nested_iframe_source_and_reader_links_reach_lan(self):
        self.node(r"""
await tick();
assert.equal(anchor.href, latex.replace('localhost','192.168.3.5'));
assert.equal(anchor.dataset.latexUrl, latex.replace('localhost','192.168.3.5'));
assert.equal(anchor.dataset.fullPaperUrl, full.replace('127.0.0.1','192.168.3.5'));
assert.equal(historical.href, full.replace('127.0.0.1','192.168.3.5'));
const ipv6=link(card,'http://[::1]:8771/exam-library/practice/full-paper.htm?paper=one#two');
await tick(); assert.equal(ipv6.href,'http://192.168.3.5:8771/exam-library/practice/full-paper.htm?paper=one#two');
""")

    def test_new_frames_reader_changes_and_href_changes_are_repaired_before_click(self):
        self.node(r"""
const added=frame(card), late=link(added.contentDocument); added.dispatchEvent(new win.Event('load'));
await tick(); assert.equal(late.href,latex.replace('localhost','192.168.3.5'));
anchor.setAttribute('href',full); anchor.setAttribute('data-full-paper-url',full);
anchor.setAttribute('data-reader','full-paper'); card.dispatchEvent(new win.Event('change',{bubbles:true}));
await tick(); assert.equal(anchor.href,full.replace('127.0.0.1','192.168.3.5'));
anchor.href=latex; anchor.addEventListener('click',e=>e.preventDefault());
anchor.dispatchEvent(new win.MouseEvent('click',{bubbles:true,cancelable:true}));
assert.equal(anchor.href,latex.replace('localhost','192.168.3.5'));
win.eval(fs.readFileSync(input.script,'utf8')); await tick();
assert.equal(anchor.href,latex.replace('localhost','192.168.3.5'));
""")

    def test_external_origins_ports_api_and_unrelated_links_are_unchanged(self):
        self.node(r"""
const cases=['https://localhost:8765/exam-library/practice/full-paper.htm',
 'http://localhost:87650/exam-library/practice/full-paper.htm',
 'http://localhost.evil:8765/exam-library/practice/full-paper.htm',
 'http://evil.example:8765/exam-library/practice/full-paper.htm',
 'http://user@localhost:8765/exam-library/practice/full-paper.htm',
 'http://localhost:8765/api/study/import','eudic://searchword?word=offline',
 'http://localhost:8765/exam-library/practice/full-paper.htm/extra'];
const checks=cases.map(value=>{const a=link(card,value);return [a,a.getAttribute('href')];});
const unrelated=card.createElement('a'); unrelated.href=latex;card.body.append(unrelated);checks.push([unrelated,unrelated.getAttribute('href')]);
const foreign=frame(card); const foreignDom=new JSDOM('<a class="sentence-jump" href="'+latex+'">x</a>',{url:'https://evil.example/'});
Object.defineProperty(foreign,'contentDocument',{get:()=>foreignDom.window.document});
foreign.dispatchEvent(new win.Event('load')); await tick();
for(const [a,value] of checks)assert.equal(a.getAttribute('href'),value);
assert.equal(foreignDom.window.document.querySelector('a').href,latex);foreignDom.window.close();
""")

    def test_loopback_shell_is_not_changed_by_lan_companion(self):
        self.node("await tick();assert.equal(anchor.href,latex);assert.equal(historical.href,full);",
            'http://localhost:8771/preview-library.html')

    def test_direct_sealed_auxiliary_page_bootstraps_from_its_existing_asset(self):
        self.node(r"""
await tick(); assert.equal(win.savedNativePrefix,true);
const script=doc.querySelector('script[src="/_preview_lan_links.js"]');
assert.ok(script,'the existing unsealed auxiliary asset must load the companion');
const expected=require('node:crypto').createHash('sha256').update(fs.readFileSync(input.script)).digest('base64');
assert.equal(script.integrity,'sha256-'+expected);assert.equal(script.crossOrigin,'anonymous');
assert.equal(doc.querySelector('[data-residual-auxiliary-entry] .sf-example a').href,'http://192.168.3.5:8765/exam-library/practice/full-paper.htm?paper=kaoyan%3A2025-01&word=offline#sentence');
""", direct_aux=True)

    def test_shell_companion_is_sri_pinned_and_sealed_bytes_remain_exact(self):
        shell = b'<html><head><script src="original.js"></script></head></html>'
        changed = lan.bootstrap_hash_runtime(shell, '/preview-library.html')
        self.assertIn(SCRIPT_URL.encode(), changed)
        integrity = base64.b64encode(hashlib.sha256(SCRIPT.read_bytes()).digest())
        self.assertIn(b'integrity="sha256-' + integrity + b'"', changed)
        self.assertEqual(lan.bootstrap_hash_runtime(changed, '/preview-library.html'), changed)
        for path in ('/book/cards/a.html', '/book/history/a.html', '/book/sources/a.html', '/book/evidence/a.html'):
            self.assertEqual(lan.rewrite_text(SEALED, '192.168.3.5', 8771, path), SEALED)
            self.assertEqual(lan.bootstrap_hash_runtime(SEALED, path), SEALED)


class LanLinkHttpTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), lan.LanPreviewHandler)
        self.server.lan_ip = '127.0.0.1'; self.server.lan_network = ipaddress.ip_network('127.0.0.0/8')
        self.server.backend_port = 8771
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()

    def fetch(self, path, method='GET'):
        conn = HTTPConnection('127.0.0.1', self.server.server_port);conn.request(method,path)
        response=conn.getresponse();value=(response.status,response.getheader('Content-Length'),response.read());conn.close();return value

    def test_companion_get_head_are_pinned_and_drift_fails_closed(self):
        raw=SCRIPT.read_bytes()
        with patch('scripts.serve_preview_lan.HTTPConnection') as upstream:
            self.assertEqual(self.fetch(SCRIPT_URL),(200,str(len(raw)),raw))
            self.assertEqual(self.fetch(SCRIPT_URL,'HEAD'),(200,str(len(raw)),b''))
            with patch('scripts.serve_preview_lan.LAN_LINK_SHA','0'*64):
                self.assertEqual(self.fetch(SCRIPT_URL)[0],503)
            upstream.assert_not_called()

    def test_signed_card_http_bytes_and_hash_remain_exact(self):
        response=MagicMock();response.status=200;response.reason='OK'
        response.getheader.side_effect=lambda key,default=None: 'text/html' if key=='Content-Type' else str(len(SEALED)) if key=='Content-Length' else default
        response.getheaders.return_value=[('Content-Type','text/html')];response.read.return_value=SEALED
        with patch('scripts.serve_preview_lan.HTTPConnection') as upstream:
            upstream.return_value.getresponse.return_value=response
            status,length,raw=self.fetch('/book/cards/a.html')
        self.assertEqual((status,length,raw),(200,str(len(SEALED)),SEALED))
        self.assertEqual(hashlib.sha256(raw).digest(),hashlib.sha256(SEALED).digest())

    def test_only_the_approved_auxiliary_asset_gets_a_pinned_suffix_with_exact_prefix(self):
        original=b'window.nativeOriginal="http://localhost:8765";'
        response=MagicMock();response.status=200;response.reason='OK'
        response.getheader.side_effect=lambda key,default=None: 'application/javascript' if key=='Content-Type' else str(len(original)) if key=='Content-Length' else default
        response.getheaders.return_value=[('Content-Type','application/javascript')];response.read.return_value=original
        with patch('scripts.serve_preview_lan.HTTPConnection') as upstream:
            upstream.return_value.getresponse.return_value=response
            status,length,raw=self.fetch(AUXILIARY_PATH)
        self.assertEqual(status,200);self.assertEqual(length,str(len(raw)))
        self.assertTrue(raw.startswith(original));self.assertIn(SCRIPT_URL.encode(),raw)
        self.assertIn(base64.b64encode(hashlib.sha256(SCRIPT.read_bytes()).digest()),raw)
        other=getattr(lan,'bootstrap_auxiliary_links',lambda raw,path:raw)(original,AUXILIARY_PATH.replace('v1','v2'))
        self.assertEqual(other,original)


if __name__ == '__main__': unittest.main()
