"""Serve explicitly mounted web exports without allowing arbitrary symlinks.

The bookshelf's document root remains unchanged. Each URL prefix has its own
canonical export root and exact cards/media/catalog delegates. A sibling export
or another Application Support directory is never implicitly authorized.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
from urllib.parse import unquote, urlsplit


class MountDenied(PermissionError):
    pass


def request_path(target: str) -> str:
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith('/') or parsed.fragment:
        raise MountDenied('Only local URL paths are supported')
    path = parsed.path
    for _ in range(5):
        decoded = unquote(path, errors='strict')
        if decoded == path:
            break
        path = decoded
    if ('%' in path or '\\' in path or '\x00' in path
            or any(part.startswith('.') for part in path.split('/') if part)):
        raise MountDenied('Invalid static export path')
    return path


class Resource:
    def __init__(self, path: Path, root: Path):
        self.path, self.root = path, root

    def open(self):
        """Walk from the approved root without following substituted symlinks."""
        parts = self.path.relative_to(self.root).parts
        if not parts:
            raise IsADirectoryError(self.path)
        # Opening only the final root component would still follow a replaced
        # ancestor (approved-book -> outside/cards). Walk the complete canonical
        # root from a stable filesystem-root descriptor instead.
        directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        descriptor = os.open(self.root.anchor, directory_flags)
        try:
            for part in self.root.parts[1:]:
                child = os.open(part, directory_flags, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
            for index, part in enumerate(parts):
                flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
                if index < len(parts) - 1:
                    flags |= os.O_DIRECTORY
                child = os.open(part, flags, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode):
                raise MountDenied('Only regular export files may be served')
            stream = os.fdopen(descriptor, 'rb')
            descriptor = None
            return stream, info
        finally:
            if descriptor is not None:
                os.close(descriptor)


class LimitedReader:
    def __init__(self, stream, length: int):
        self.stream, self.remaining = stream, length

    def read(self, size: int = -1) -> bytes:
        size = self.remaining if size < 0 else min(size, self.remaining)
        value = self.stream.read(size)
        self.remaining -= len(value)
        return value

    def close(self):
        self.stream.close()


class StaticMounts:
    def __init__(self, entries: list[dict]):
        if not isinstance(entries, list) or not entries:
            raise ValueError('An explicit static export manifest is required')
        self.mounts = {}
        for row in entries:
            if set(row) != {'url_mount', 'export', 'cards', 'media', 'catalog'}:
                raise ValueError('Unexpected static mount fields')
            prefix = row['url_mount']
            if (not isinstance(prefix, str) or request_path(prefix) != prefix
                    or not re.fullmatch(r'/study-catalog-\d{8}/master-[a-z0-9_-]+-web-v\d+/', prefix)
                    or prefix in self.mounts):
                raise ValueError('Invalid or duplicate static export URL')
            paths = {key: Path(row[key]).resolve(strict=True)
                     for key in ('export', 'cards', 'media', 'catalog')}
            if (paths['export'].name != prefix.rstrip('/').rsplit('/', 1)[1]
                    or any(not paths[key].is_dir() for key in ('export', 'cards', 'media'))
                    or paths['cards'].name != 'cards' or paths['media'].name != 'media'
                    or paths['catalog'].name != 'catalog.json'
                    or not paths['catalog'].is_file()):
                raise ValueError('Static export roots do not match the approved manifest')
            # Validate actual aliases now and again for each relevant request.
            for alias, key in (('cards', 'cards'), ('media', 'media'), ('catalog.json', 'catalog')):
                if (paths['export'] / alias).resolve(strict=True) != paths[key]:
                    raise ValueError('Static export alias target changed')
            self.mounts[prefix] = paths

    @classmethod
    def load(cls, config: str | Path):
        value = json.loads(Path(config).read_text(encoding='utf-8'))
        if value.get('schema') != 'preview.static-mounts.v1':
            raise ValueError('Unexpected static mount configuration')
        return cls(value['mounts'])

    def resolve(self, target: str) -> Resource | None:
        path = request_path(target)
        prefix = next((key for key in self.mounts if path.startswith(key)), None)
        if prefix is None:
            return None
        roots = self.mounts[prefix]
        relative = path[len(prefix):] or 'index.html'
        parts = relative.split('/')
        if (any(not part or part.startswith('.') for part in parts)
                or Path(relative).suffix.lower() in {'.py', '.pyc', '.db', '.sqlite', '.sqlite3',
                                                    '.apkg', '.colpkg', '.bak', '.toml', '.key', '.pem'}):
            raise MountDenied('Private files and directories are not export resources')
        if parts[0] in {'cards', 'media'}:
            kind = parts[0]
            if (roots['export'] / kind).resolve(strict=True) != roots[kind]:
                raise MountDenied('Static export alias was retargeted')
            root = roots[kind]
            candidate = root.joinpath(*parts[1:]).resolve()
        elif parts[0] == 'catalog.json':
            if len(parts) != 1 or (roots['export'] / 'catalog.json').resolve(strict=True) != roots['catalog']:
                raise MountDenied('Static catalog alias was retargeted')
            candidate, root = roots['catalog'], roots['catalog'].parent
        else:
            root = roots['export']
            candidate = root.joinpath(*parts).resolve()
        if not candidate.is_relative_to(root):
            raise MountDenied('Static file escapes its exact approved root')
        return Resource(candidate, root)

    def send_head(self, handler, resource: Resource):
        try:
            stream, info = resource.open()
        except FileNotFoundError:
            handler.send_error(404)
            return None
        except (OSError, MountDenied):
            handler.send_error(403)
            return None
        size, start, end = info.st_size, 0, info.st_size - 1
        requested = handler.headers.get('Range') if not handler.headers.get('If-Range') else None
        if requested:
            match = re.fullmatch(r'bytes=(\d*)-(\d*)', requested)
            valid = bool(match and any(match.groups()) and all(len(value) <= 20 for value in match.groups()))
            if valid:
                if match[1]:
                    start = int(match[1])
                    end = min(int(match[2]), end) if match[2] else end
                else:
                    valid = int(match[2]) > 0
                    start = max(0, size - int(match[2]))
                valid = valid and start <= end and start < size
            if not valid:
                stream.close()
                handler.send_response(416)
                handler.send_header('Content-Range', f'bytes */{size}')
                handler.send_header('Content-Length', '0')
                handler.end_headers()
                return None
        length = end - start + 1
        stream.seek(start)
        handler.send_response(206 if requested else 200)
        handler.send_header('Content-Type', handler.guess_type(str(resource.path)))
        handler.send_header('Content-Length', str(length))
        handler.send_header('Last-Modified', handler.date_time_string(info.st_mtime))
        handler.send_header('Cache-Control', 'no-cache')
        handler.send_header('Accept-Ranges', 'bytes')
        handler.send_header('X-Content-Type-Options', 'nosniff')
        if requested:
            handler.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        handler.end_headers()
        return LimitedReader(stream, length)
