"""Disposable waveforms and exact approved mounts, never personal recordings."""
import ast
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import wave

from anki_pipeline import study_audio as audio
from anki_pipeline import study_http as web
from anki_pipeline.preview_static_mounts import StaticMounts
from tests.test_study_http import mount_fixture, request, serving


def sound(path, amplitude):
    samples = [int(32767 * amplitude * math.sin(2 * math.pi * 440 * i / 24000)) for i in range(24000)]
    with wave.open(str(path), 'wb') as output:
        output.setparams((1, 2, 24000, 0, 'NONE', ''))
        output.writeframes(struct.pack('<' + 'h' * len(samples), *samples))


def levels(path):
    with wave.open(str(path), 'rb') as source:
        data = source.readframes(source.getnframes())
        values = struct.unpack('<' + 'h' * (len(data) // 2), data)
        rms = math.sqrt(sum((value / 32768) ** 2 for value in values) / len(values))
        return 20 * math.log10(rms), max(abs(value / 32768) for value in values), len(values) / source.getframerate()


class AudioTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='study-audio-', dir='/tmp')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.public = self.root / 'public'; self.public.mkdir()
        self.card = self.public / 'card.html'
        self.card.write_text('<div class="dictionary-word-audio"><audio data-dictionary-accent="uk" src="uk.wav"></audio><audio data-dictionary-accent="us" src="us.wav"></audio></div>')
        sound(self.public / 'uk.wav', .23); sound(self.public / 'us.wav', .07)
        self.balancer = audio.AudioBalancer(self.public, self.root / 'cache', {'/card.html'})

    def get(self, **changes):
        return self.balancer.get(**{**dict(card='/card.html', source='/us.wav', reference='/uk.wav'), **changes})

    def require_ffmpeg(self):
        if not self.balancer.ffmpeg:
            self.skipTest('requires local ffmpeg for numerical waveform contract')

    def mounted(self):
        mounts, prefix, export = mount_fixture(self.root)
        card = prefix + 'cards/word.html'
        (export / 'cards' / 'word.html').write_text('<div class="dictionary-word-audio"><audio data-dictionary-accent="uk" src="../media/uk.wav"></audio><audio data-dictionary-accent="us" src="../media/us.wav"></audio></div>')
        sound(export / 'media' / 'uk.wav', .23); sound(export / 'media' / 'us.wav', .07)
        balancer = audio.AudioBalancer(self.public, self.root / 'mounted-cache', {card}, static_mounts=mounts)
        values = dict(card=card, source=prefix + 'media/us.wav', reference=prefix + 'media/uk.wav')
        return balancer, values, mounts, prefix, export

    def test_legacy_quiet_us_matches_uk_and_originals_and_cache_stay_unchanged(self):
        self.require_ffmpeg()
        before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.public.glob('*.wav')}
        result = self.get(); expected = levels(self.public / 'uk.wav'); actual = levels(result.path)
        self.assertTrue(result.matched)
        self.assertLess(abs(actual[0] - expected[0]), .5)
        self.assertLessEqual(actual[1], 10 ** (-1 / 20) + .0001)
        self.assertAlmostEqual(actual[2], 1, places=2)
        self.assertEqual(before, {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.public.glob('*.wav')})
        self.assertEqual(self.get().path, result.path)

    def test_legacy_loud_us_is_reduced_and_changed_reference_uses_new_cache(self):
        self.require_ffmpeg()
        sound(self.public / 'us.wav', .8)
        first = self.get()
        self.assertLess(abs(levels(first.path)[0] - levels(self.public / 'uk.wav')[0]), .5)
        sound(self.public / 'uk.wav', .12)
        changed = self.get()
        self.assertNotEqual(changed.path, first.path)
        self.assertLess(abs(levels(changed.path)[0] - levels(self.public / 'uk.wav')[0]), .5)

    def test_legacy_pair_boundaries_url_validation_and_unregistered_card(self):
        sound(self.public / 'other.wav', .1)
        for values in ({'source': '/other.wav'}, {'reference': 'https://example.com/x.wav'},
                       {'card': '/other.html'}, {'source': '/../private.wav'},
                       {'source': '/us.wav?query=1'}, {'source': '//example.com/us.wav'},
                       {'source': '/us.wav#fragment'}, {'source': '/us\x00.wav'}):
            with self.subTest(values=values), self.assertRaises(audio.AudioBalanceError):
                self.get(**values)
        self.card.write_text('<div class="dictionary-word-audio"><audio data-dictionary-accent="uk" src="uk.wav"></audio></div><div class="dictionary-word-audio"><audio data-dictionary-accent="us" src="us.wav"></audio></div>')
        with self.assertRaises(audio.AudioBalanceError):
            self.get()

    def test_legacy_missing_tool_keeps_exact_original_path(self):
        self.balancer.ffmpeg = None
        result = self.get()
        self.assertFalse(result.matched)
        self.assertEqual(result.path, self.public / 'us.wav')
        self.assertFalse(self.balancer.cache.exists())

    def test_legacy_silence_and_concurrent_pair_keep_old_fallback_and_lock(self):
        self.require_ffmpeg()
        with ThreadPoolExecutor(max_workers=3) as pool:
            values = list(pool.map(lambda _: self.get(), range(3)))
        self.assertEqual(len({value.path for value in values}), 1)
        sound(self.public / 'uk.wav', 0)
        result = self.get()
        self.assertFalse(result.matched)
        self.assertEqual(result.path, self.public / 'us.wav')

    def test_mounted_missing_tool_returns_exact_bytes_from_private_cache(self):
        balancer, values, _, _, export = self.mounted()
        balancer.ffmpeg = None
        before = (export / 'media' / 'us.wav').read_bytes()
        result = balancer.get(**values)
        self.assertFalse(result.matched)
        self.assertTrue(result.path.is_relative_to(balancer.cache))
        self.assertEqual(result.path.read_bytes(), before)
        self.assertEqual(result.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual((export / 'media' / 'us.wav').read_bytes(), before)
        self.assertEqual(balancer.get(**values).path, result.path)

    def test_mounted_ffmpeg_uses_guarded_fds_and_preserves_numerical_contract(self):
        balancer, values, _, _, export = self.mounted()
        if not balancer.ffmpeg:
            self.skipTest('requires local ffmpeg for approved-fd decoding')
        original = audio.subprocess.run
        invoked = []
        def inspect(args, **options):
            position = args.index('-i') + 1
            if Path(args[position]).is_relative_to(balancer.cache):
                # Measuring our private completed output keeps its old Path.
                self.assertFalse(options['pass_fds'])
            else:
                self.assertTrue(args[position].startswith('/dev/fd/'))
                self.assertTrue(options['pass_fds'])
            for descriptor in options['pass_fds']:
                self.assertGreater(os.fstat(descriptor).st_size, 0)
            invoked.append(args[position])
            return original(args, **options)
        with patch.object(audio.subprocess, 'run', side_effect=inspect):
            result = balancer.get(**values)
        self.assertTrue(result.matched)
        self.assertTrue(invoked)
        self.assertLess(abs(levels(result.path)[0] - levels(export / 'media' / 'uk.wav')[0]), .5)

    def test_mounted_escape_retarget_and_unpublished_audio_are_rejected(self):
        balancer, values, _, prefix, export = self.mounted()
        secret = self.root / 'secret.wav'; secret.write_bytes(b'outside secret bytes')
        (export / 'media' / 'escape.wav').symlink_to(secret)
        for url in (prefix + 'media/escape.wav', prefix + 'media/../../secret.wav', prefix + 'media/%252e%252e/secret.wav'):
            with self.assertRaises(audio.AudioBalanceError):
                balancer._file(url)
        source, _ = balancer._validate(**values)
        # Replace an already-approved ancestor after resolve: all later reads
        # must use Resource.open(), including the ffmpeg input, never raw Path.
        approved = export.parent
        preserved = approved.with_name('preserved-external')
        approved.rename(preserved)
        outside = self.root / 'outside'; outside.mkdir()
        approved.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(audio.AudioBalanceError):
            balancer._read_bytes(source)
        with self.assertRaises(audio.AudioBalanceError):
            balancer._run(['-i', str(source)])

    def test_public_cache_or_unapproved_resolver_is_never_accepted(self):
        with self.assertRaises(ValueError):
            audio.AudioBalancer(self.public, self.public / 'cache', set())
        _, _, mounts, _, export = self.mounted()
        with self.assertRaises(ValueError):
            audio.AudioBalancer(self.public, export / 'media' / 'cache', set(), static_mounts=mounts)
        with self.assertRaises(TypeError):
            audio.AudioBalancer(self.public, self.root / 'bad-cache', set(), static_mounts=lambda _: None)

    def test_mounted_audio_through_unchanged_http_keeps_original_range_bytes(self):
        balancer, values, mounts, _, export = self.mounted()
        balancer.ffmpeg = None
        with patch.object(web.StudyHandler, 'log_message', return_value=None), \
                serving(None, self.public, static_mounts=mounts, audio_balancer=balancer) as server:
            from urllib.parse import urlencode
            status, headers, data = request(server, 'GET', '/api/study/audio-balanced?' + urlencode(values),
                                            headers={'Range': 'bytes=0-43'})
        self.assertEqual(status, 206)
        self.assertEqual(headers['X-Study-Audio-Balanced'], '0')
        self.assertEqual(data, (export / 'media' / 'us.wav').read_bytes()[:44])

    def test_import_does_not_read_a_catalog_config_or_user_path(self):
        with patch.object(Path, 'read_text', side_effect=AssertionError('implicit text read')), \
                patch.object(Path, 'resolve', side_effect=AssertionError('implicit path resolve')):
            importlib.reload(audio)


def ast_shape(value):
    if isinstance(value, ast.AST):
        return [type(value).__name__, {key: ast_shape(item) for key, item in ast.iter_fields(value)
                                      if key != 'type_params' or item}]
    if isinstance(value, list):
        return [ast_shape(item) for item in value]
    if isinstance(value, bytes):
        return {'$bytes': base64.b64encode(value).decode()}
    return value


def ast_digest(node):
    return hashlib.sha256(json.dumps(ast_shape(node), ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


class GuardAdapter(ast.NodeTransformer):
    """Remove only the explicit new mounted-I/O adapters for source comparison."""
    def visit_Call(self, node):
        node = self.generic_visit(node)
        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == 'self':
            if node.func.attr in ('_stat', '_read_text', '_read_bytes') and len(node.args) == 1:
                return ast.Call(func=ast.Attribute(value=node.args[0], attr=node.func.attr[1:], ctx=ast.Load()),
                                args=[], keywords=[])
            if node.func.attr == '_fallback' and len(node.args) == 1:
                return ast.Call(func=ast.Name(id='BalancedAudio', ctx=ast.Load()),
                                args=[node.args[0], ast.Constant(value=False)], keywords=[])
        return node


class LegacySourceParityTests(unittest.TestCase):
    def test_http_wire_methods_and_audio_algorithm_match_frozen_live_source(self):
        fixture = json.loads((Path(__file__).parent / 'fixtures/study-http-audio-legacy-v1.json').read_text())
        parsed = {}
        for name, module in (('http', web), ('audio', audio)):
            tree = ast.parse(Path(module.__file__).read_text())
            parsed[name] = {}
            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    parsed[name][node.name] = node
                    for child in node.body:
                        if isinstance(child, ast.FunctionDef):
                            parsed[name][node.name + '.' + child.name] = child
        unchanged = ['StudyHandler.' + name for name in ('_json', '_allowed_host', '_same_origin', '_route',
                     'do_GET', 'do_HEAD', '_audio', 'do_POST', 'do_OPTIONS', 'end_headers')]
        for name in unchanged + ['PreviewThreadingHTTPServer', 'IPv6Server']:
            with self.subTest(name=name):
                self.assertEqual(ast_digest(parsed['http'][name]), fixture['sources']['http']['ast_sha256'][name])
        for name in ('AudioBalanceError', 'BalancedAudio', '_Recordings', 'AudioBalancer._levels'):
            with self.subTest(name=name):
                self.assertEqual(ast_digest(parsed['audio'][name]), fixture['sources']['audio']['ast_sha256'][name])
        for name in ('AudioBalancer._validate', 'AudioBalancer.get'):
            with self.subTest(name=name):
                normalized = GuardAdapter().visit(parsed['audio'][name])
                self.assertEqual(ast_digest(normalized), fixture['sources']['audio']['ast_sha256'][name],
                                 'Only approved I/O adapters may differ; pairing/gain/limits/cache algorithm must match')


if __name__ == '__main__':
    unittest.main()
