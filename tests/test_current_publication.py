import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from anki_pipeline.preview_static_mounts import StaticMounts
from scripts.stage_current_publication import stage


class CurrentPublicationTests(unittest.TestCase):
    def test_historical_urls_use_current_bytes_and_collisions_stay_distinct(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            document = root / 'output'
            document.mkdir()
            rows = []
            for book in ('one', 'two'):
                for version in (1, 2, 3):
                    name = f'master-{book}-web-v{version}'
                    export = root / 'old' / name
                    (export / 'cards').mkdir(parents=True)
                    (export / 'media').mkdir()
                    (export / 'index.html').write_text('current entry' if version == 3 else 'obsolete')
                    (export / 'cards/a.html').write_text(f'{book} v{version}')
                    (export / 'media/shared.mp3').write_bytes(b'same audio')
                    (export / 'media/collision.js').write_text(book)
                    (export / 'catalog.json').write_text(json.dumps({'book': book, 'version': version}))
                    rows.append(dict(url_mount=f'/study-catalog-20261015/{name}/', export=str(export),
                        cards=str(export / 'cards'), media=str(export / 'media'), catalog=str(export / 'catalog.json')))
            mounts = root / 'mounts.json'
            mounts.write_text(json.dumps({'schema': 'preview.static-mounts.v1', 'mounts': rows}))
            registry = root / 'registry.json'
            registry.write_text(json.dumps({'books': [{'projection': {'url_mount':
                f'/study-catalog-20261015/master-{book}-web-v3/'}} for book in ('one', 'two')]}))
            config = root / 'service.json'
            config.write_text(json.dumps(dict(document_root=str(document), static_mounts_path=str(mounts),
                registry_path=str(registry), port=8771)))
            destination = root / 'published'
            with contextlib.redirect_stdout(io.StringIO()):
                counts = stage(config, destination)
            resolver = StaticMounts.load(destination / 'settings/mounts.json')
            for book in ('one', 'two'):
                for version in (1, 2, 3):
                    resource = resolver.resolve(f'/study-catalog-20261015/master-{book}-web-v{version}/cards/a.html')
                    stream, _ = resource.open()
                    with stream:
                        self.assertEqual(stream.read(), f'{book} v3'.encode())
                self.assertEqual((destination / f'books/master-{book}-web-v3/media/collision.js').read_text(), book)
            a = destination / 'books/master-one-web-v3/media/shared.mp3'
            b = destination / 'books/master-two-web-v3/media/shared.mp3'
            self.assertEqual(a.stat().st_ino, b.stat().st_ino)
            self.assertGreater(counts['duplicate_files'], 0)
            self.assertEqual((root / 'old/master-one-web-v1/cards/a.html').read_text(), 'one v1')
            # Existing destinations are refused rather than overwriting a prior publication.
            with self.assertRaises(FileExistsError):
                stage(config, destination)
            redirected=root/'public-alias'
            redirected.symlink_to(document,target_is_directory=True)
            with self.assertRaises(ValueError):
                stage(config,redirected/'private-settings')
            self.assertFalse((document/'private-settings').exists())


if __name__ == '__main__':
    unittest.main()
