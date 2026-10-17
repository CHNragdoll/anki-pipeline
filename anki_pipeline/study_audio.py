"""Match each US word recording to its selected UK recording without rewriting either."""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit, unquote
import hashlib
import io
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import threading

from .preview_static_mounts import MountDenied, StaticMounts
from .study_catalog_web import card_payload


class AudioBalanceError(Exception):
    status = 400
    message = '录音必须来自当前词卡的同一组英美发音'


@dataclass(frozen=True)
class BalancedAudio:
    path: Path
    matched: bool


class _Recordings(HTMLParser):
    def __init__(self):
        super().__init__(); self.stack = []; self.groups = []; self.current = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'div':
            self.stack.append(self.current)
            if 'dictionary-word-audio' in attrs.get('class', '').split():
                self.current = []; self.groups.append(self.current)
        if tag == 'audio' and self.current is not None and attrs.get('data-dictionary-accent') in ('uk', 'us'):
            self.current.append((attrs['data-dictionary-accent'], attrs.get('src', '')))

    def handle_endtag(self, tag):
        if tag == 'div' and self.stack: self.current = self.stack.pop()


class _CardShell(HTMLParser):
    """Recognize actual common wrapper elements, never quoted HTML/JS text."""
    def __init__(self):
        super().__init__()
        self.common = False
        self.scripts = []
        self._script = None
        self._script_tag = None
        self._template_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag == 'template':
            self._template_depth += 1
            return
        if self._template_depth:
            return
        if tag == 'iframe' and dict(attrs).get('id') == 'study-side':
            self.common = True
        if tag == 'script':
            self._script = []
            self._script_tag = self.get_starttag_text()

    def handle_data(self, data):
        if not self._template_depth and self._script is not None:
            self._script.append(data)

    def handle_endtag(self, tag):
        if tag == 'template' and self._template_depth:
            self._template_depth -= 1
            return
        if self._template_depth:
            return
        if tag == 'script' and self._script is not None:
            script = ''.join(self._script)
            if script.startswith(('const sides=', 'const absoluteBase=')):
                self.common = True
                self.scripts.append(self._script_tag + script)
            self._script = None
            self._script_tag = None

    def handle_startendtag(self, tag, attrs):
        if tag == 'template':
            # HTML templates are non-void: a trailing slash does not close
            # their inert contents in the browser's live document tree.
            self.handle_starttag(tag, attrs)
        else:
            super().handle_startendtag(tag, attrs)


class _SideRecordings(_Recordings):
    """Each authored side owns its first base-with-href and recording groups."""
    def __init__(self):
        super().__init__()
        self.base = None
        self._template_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag == 'template':
            self._template_depth += 1
            return
        if self._template_depth:
            return
        values = dict(attrs)
        if tag == 'base' and self.base is None and 'href' in values:
            self.base = values['href'] or ''
        super().handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag == 'template' and self._template_depth:
            self._template_depth -= 1
        elif not self._template_depth:
            super().handle_endtag(tag)

    def handle_startendtag(self, tag, attrs):
        if tag == 'template':
            self.handle_starttag(tag, attrs)
        else:
            super().handle_startendtag(tag, attrs)


class AudioBalancer:
    VERSION = 'rms-limit-v2'

    def __init__(self, document_root, cache_root, card_paths, *, static_mounts=None):
        if static_mounts is not None and not isinstance(static_mounts, StaticMounts):
            raise TypeError('static_mounts must be an approved StaticMounts instance')
        self.root = Path(document_root).resolve(); self.cache = Path(cache_root).resolve()
        if self.cache.is_relative_to(self.root): raise ValueError('Audio cache must be private')
        if static_mounts is not None and any(self.cache.is_relative_to(paths[key])
                for paths in static_mounts.mounts.values() for key in ('export', 'cards', 'media')):
            raise ValueError('Audio cache must remain outside approved public export roots')
        self.static_mounts = static_mounts
        self._resources = {}
        self.card_paths = frozenset(card_paths)
        self.ffmpeg = shutil.which('ffmpeg')
        self._lock = threading.RLock(); self._jobs = {}; self._pairs = {}
        self._slots = threading.BoundedSemaphore(2)

    def _file(self, url):
        if not isinstance(url, str) or len(url) > 2048 or re.search(r'[\x00-\x20\x7f]', url): raise AudioBalanceError()
        parsed = urlsplit(url)
        if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or not parsed.path.startswith('/'): raise AudioBalanceError()
        if self.static_mounts is not None:
            try:
                resource = self.static_mounts.resolve(url)
                if resource is not None:
                    stream, _ = resource.open()
                    stream.close()
                    with self._lock:
                        self._resources[resource.path] = resource
                    return resource.path
            except (OSError, ValueError, RuntimeError, MountDenied) as error:
                raise AudioBalanceError() from error
        path = (self.root / unquote(parsed.path).lstrip('/')).resolve()
        if not path.is_relative_to(self.root) or not path.is_file(): raise AudioBalanceError()
        return path

    def _resource_open(self, path):
        try:
            return self._resources[path].open()
        except (OSError, ValueError, RuntimeError, MountDenied) as error:
            raise AudioBalanceError() from error

    def _stat(self, path):
        if path not in self._resources:
            return path.stat()
        stream, info = self._resource_open(path)
        stream.close()
        return info

    def _read_bytes(self, path):
        if path not in self._resources:
            return path.read_bytes()
        stream, _ = self._resource_open(path)
        with stream:
            return stream.read()

    def _read_text(self, path):
        if path not in self._resources:
            return path.read_text()
        stream, _ = self._resource_open(path)
        with io.TextIOWrapper(stream) as text:
            return text.read()

    def _recordings(self, card, path):
        try:
            source = self._read_text(path)
            shell = _CardShell(); shell.feed(source); shell.close()
            parser = _Recordings()
            if not shell.common:
                # Unknown ordinary authored HTML retains the original pairing
                # semantics, including its card-relative resource resolution.
                parser.feed(source)
                return parser
            if len(shell.scripts) != 1:
                raise ValueError('Missing or ambiguous common side payload')
            # Restrict the shared exact parser to the actual wrapper script.
            # Escaped examples elsewhere in the HTML cannot supply its marker.
            literal = card_payload(shell.scripts[0].encode('utf-8'))
            for content in json.loads(literal):
                side = _SideRecordings(); side.feed(content); side.close()
                base = urljoin(card, side.base) if side.base is not None else card
                parser.groups.extend([[(accent, urljoin(base, url)) for accent, url in group]
                                      for group in side.groups])
            return parser
        except (ValueError, UnicodeError, RecursionError) as error:
            # A malformed common shell must never authorize visible fallback
            # audio that the browser would not render as one of its sides.
            raise AudioBalanceError() from error

    def _fallback(self, original):
        if original not in self._resources:
            return BalancedAudio(original, False)
        # Keep the original HTTP result contract without returning an external
        # path that the handler would reopen after the mount's fd guard. This
        # cache is an exact byte copy, never a transcoded or balanced recording.
        data = self._read_bytes(original)
        output = self.cache / ('original-' + hashlib.sha256(data).hexdigest() + original.suffix)
        with self._lock:
            if output.is_file() and output.read_bytes() == data:
                return BalancedAudio(output, False)
            self.cache.mkdir(parents=True, exist_ok=True, mode=0o700)
            temporary = None
            identity = None
            try:
                with tempfile.NamedTemporaryFile(dir=self.cache, delete=False) as handle:
                    temporary = Path(handle.name)
                    info = os.fstat(handle.fileno()); identity = (info.st_dev, info.st_ino)
                    handle.write(data); handle.flush()
                info = temporary.lstat()
                if (info.st_dev, info.st_ino) != identity:
                    raise AudioBalanceError()
                os.replace(temporary, output); temporary = None
            finally:
                if temporary is not None:
                    try:
                        info = temporary.lstat()
                        if (info.st_dev, info.st_ino) == identity:
                            temporary.unlink()
                    except FileNotFoundError:
                        pass
        return BalancedAudio(output, False)

    def _validate(self, card, source, reference):
        if card not in self.card_paths: raise AudioBalanceError()
        path = self._file(card)
        if path.suffix != '.html': raise AudioBalanceError()
        stamp = (self._stat(path).st_mtime_ns, self._stat(path).st_size)
        with self._lock:
            cached = self._pairs.get(card)
            if not cached or cached[0] != stamp:
                parser = self._recordings(card, path)
                pairs = set()
                for group in parser.groups:
                    uk = [urljoin(card, url) for accent, url in group if accent == 'uk']
                    us = [urljoin(card, url) for accent, url in group if accent == 'us']
                    pairs.update((s, r) for s in us for r in uk)
                self._pairs[card] = (stamp, pairs)
            if (source, reference) not in self._pairs[card][1]: raise AudioBalanceError()
        source_file, reference_file = self._file(source), self._file(reference)
        for media in (source_file, reference_file):
            if media.suffix.lower() not in ('.mp3', '.wav', '.ogg', '.m4a') or self._stat(media).st_size > 2 * 1024 * 1024:
                raise AudioBalanceError()
        return source_file, reference_file

    def _run(self, args):
        if self.static_mounts is not None:
            return self._run_with_resources(args)
        return subprocess.run([self.ffmpeg, '-hide_banner', '-nostats', '-nostdin', *args],
                              check=True, capture_output=True, text=True, timeout=8)

    def _run_with_resources(self, args):
        arguments = list(args)
        descriptors = []
        with ExitStack() as files:
            for index, value in enumerate(arguments):
                if index and arguments[index - 1] == '-i' and Path(value) in self._resources:
                    stream, _ = self._resource_open(Path(value))
                    files.enter_context(stream)
                    descriptors.append(stream.fileno())
                    arguments[index] = f'/dev/fd/{stream.fileno()}'
            return subprocess.run([self.ffmpeg, '-hide_banner', '-nostats', '-nostdin', *arguments],
                                  check=True, capture_output=True, text=True, timeout=8,
                                  pass_fds=tuple(descriptors))

    def _levels(self, path):
        result = self._run(['-protocol_whitelist', 'file,pipe', '-i', str(path), '-t', '12',
                            '-af', 'volumedetect', '-f', 'null', '-'])
        duration = re.search(r'Duration: (\d+):(\d+):(\d+\.\d+)', result.stderr)
        if not duration or sum(float(duration[i]) * scale for i, scale in ((1, 3600), (2, 60), (3, 1))) > 12:
            raise ValueError('Only short word recordings are balanced')
        values = []
        for key in ('mean_volume', 'max_volume'):
            match = re.search(key + r': ([-\d.]+) dB', result.stderr)
            if not match: raise ValueError('No valid audio levels')
            values.append(float(match[1]))
        if not all(math.isfinite(v) for v in values): raise ValueError('Invalid audio levels')
        return values

    def get(self, *, card, source, reference):
        original, target_file = self._validate(card, source, reference)
        if not self.ffmpeg: return self._fallback(original)
        fingerprint = hashlib.sha256(self.VERSION.encode() + self._read_bytes(original) + self._read_bytes(target_file)).hexdigest()
        output = self.cache / (fingerprint + '.wav')
        with self._lock: lock = self._jobs.setdefault(fingerprint, threading.Lock())
        with lock:
            if output.is_file(): return BalancedAudio(output, True)
            temp = None
            try:
                with self._slots:
                    source_mean, source_peak = self._levels(original)
                    target_mean, _ = self._levels(target_file)
                    # Avoid magnifying silence/noise. Very hot reference files are capped.
                    if source_mean < -45 or target_mean < -40: return self._fallback(original)
                    target_mean = min(target_mean, -9)
                    gain = max(-18, min(12, target_mean - source_mean))
                    self.cache.mkdir(parents=True, exist_ok=True, mode=0o700)
                    with tempfile.NamedTemporaryFile(dir=self.cache, suffix='.wav', delete=False) as handle: temp = Path(handle.name)
                    for attempt in range(4):
                        self._run(['-y', '-protocol_whitelist', 'file,pipe', '-i', str(original), '-t', '12',
                                   '-vn', '-af', f'volume={gain:.3f}dB,alimiter=limit=0.891250938:level=false:latency=true:release=5',
                                   '-c:a', 'pcm_s16le', str(temp)])
                        actual_mean, actual_peak = self._levels(temp)
                        delta = target_mean - actual_mean
                        if abs(delta) <= .4 or gain >= 12 or attempt == 3: break
                        gain = max(-18, min(12, gain + delta))
                    if actual_peak > -.9: raise ValueError('Peak protection failed')
                    metadata = {'sourceMeanDb': source_mean, 'sourcePeakDb': source_peak,
                                'targetMeanDb': target_mean, 'outputMeanDb': actual_mean,
                                'outputPeakDb': actual_peak, 'gainDb': round(gain, 3), 'version': self.VERSION}
                    os.replace(temp, output); temp = None
                    (self.cache / (fingerprint + '.json')).write_text(json.dumps(metadata, indent=2))
                    return BalancedAudio(output, True)
            except (OSError, ValueError, subprocess.SubprocessError):
                # A missing tool or unprocessable recording must not remove usable speech.
                return self._fallback(original)
            finally:
                if temp is not None: temp.unlink(missing_ok=True)
