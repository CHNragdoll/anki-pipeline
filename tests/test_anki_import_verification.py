"""Test rendered-card acceptance without loading Anki or accessing a profile."""
from __future__ import annotations

import importlib.util
import hashlib
import html
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import zipfile


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_anki_import.py"
SPEC = importlib.util.spec_from_file_location("verify_anki_import", SCRIPT)
assert SPEC and SPEC.loader
verification = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verification)

FRONT = ('<h1 class="word">rate</h1><a class="dictionary-link" href="#">lookup</a>'
         '<script>var lookup="eudic://x-callback-url/searchword?word=";</script>')
JUMP = ('<a class="sentence-jump" href="http://localhost:8765/latex.htm?anki_word=rate#block-1" '
        'data-latex-url="http://localhost:8765/latex.htm?anki_word=rate#block-1" '
        'data-full-paper-url="http://localhost:8765/full-paper.htm?anki_word=rate#block-1" '
        'data-reader="latex" target="_blank" rel="noopener">jump</a>')
READER = ('<select class="source-reader"><option value="latex">LaTeX</option>'
          '<option value="full-paper">整卷</option></select>')
DICTIONARY_AUDIO = (
    '<select class="dictionary-audio-source"><option value="oxford">牛津</option>'
    '<option value="webster">韦氏</option></select>'
    '<audio hidden data-dictionary-source="oxford" src="oxford_rate.mp3"></audio>'
    '<audio hidden data-dictionary-source="webster" src="webster_rate.mp3"></audio>'
)
MIT_LICENSE = '''MIT License

Copyright (c) 2025 Linwei

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
'''


def ecdict_fields(license_text: str = MIT_LICENSE) -> list[str]:
    fields = [''] * len(verification.FIELD_NAMES)
    fields[0] = 'exsert'
    fields[2] = '<div class="dictionary-definition" data-dictionary="ecdict">v. 伸出</div>'
    fields[4] = ('<ul class="level-list" data-dictionary="ecdict"><li>考研</li></ul>'
                 '<div class="ecdict-license-notice" hidden aria-hidden="true">'
                 + html.escape(license_text) + '</div>')
    fields[6] = DICTIONARY_AUDIO
    return fields


class Card:
    def __init__(self, controls: str, front: str = FRONT) -> None:
        self.front = front
        self.back = (front + '<hr id="answer"><section class="primary-definition">释义</section>'
                     '<mark class="target-word">rate</mark>' + controls)

    def question(self) -> str:
        return self.front

    def answer(self) -> str:
        return self.back


class Collection:
    def __init__(self, card: Card) -> None:
        self.card = card

    def get_card(self, card_id: int) -> Card:
        return self.card


class AnkiImportMarkupTests(unittest.TestCase):
    def accept(self, controls: str = JUMP + READER, front: str = FRONT) -> int:
        return verification.card_rendering_sample(Collection(Card(controls, front)), {17})

    def test_source_jump_and_reader_replace_playback(self) -> None:
        self.assertEqual(self.accept(), 17)
        with self.assertRaisesRegex(RuntimeError, "source jump"):
            self.accept('<button class="sentence-play">play</button>')
        with self.assertRaisesRegex(RuntimeError, "source jump"):
            self.accept(JUMP + READER + '<button class="sentence-play">play</button>')

    def test_actual_elements_are_required(self) -> None:
        for controls in (JUMP, READER, '<script>var example="a.sentence-jump select.source-reader";</script>'):
            with self.subTest(controls=controls), self.assertRaises(RuntimeError):
                self.accept(controls)

    def test_front_excludes_jump_and_reader(self) -> None:
        for extra in (JUMP, READER, '<hr id="answer">', '<mark class="target-word">rate</mark>'):
            with self.subTest(extra=extra), self.assertRaises(RuntimeError):
                self.accept(front=FRONT + extra)

    def test_source_urls_require_http_and_no_credentials(self) -> None:
        for value in ("javascript:alert(1)", "file:///tmp/exam.htm", "/latex.htm", "//host/latex.htm",
                      "http://user:secret@host/latex.htm", "http://host:99999/latex.htm", "https://host/\nunsafe"):
            with self.subTest(value=value):
                self.assertFalse(verification.safe_source_url(value))
                controls = JUMP.replace("http://localhost:8765/latex.htm?anki_word=rate#block-1", value) + READER
                with self.assertRaises(RuntimeError):
                    self.accept(controls)

    def test_reader_choices_and_external_link_attributes_are_required(self) -> None:
        for controls in (JUMP + READER.replace('value="full-paper"', 'value="unknown"'),
                         JUMP + '<select class="source-reader"></select>' + READER.replace('class="source-reader"', 'class="other"'),
                         JUMP.replace('rel="noopener"', 'rel=""') + READER,
                         JUMP.replace('target="_blank"', 'target="_self"') + READER,
                         JUMP.replace('data-reader="latex"', 'data-reader="unknown"') + READER):
            with self.subTest(controls=controls), self.assertRaises(RuntimeError):
                self.accept(controls)

    def test_selected_href_matches_the_reader(self) -> None:
        with self.assertRaises(RuntimeError):
            self.accept(JUMP.replace('data-reader="latex"', 'data-reader="full-paper"') + READER)
        full_paper = JUMP.replace('href="http://localhost:8765/latex.htm',
                                 'href="http://localhost:8765/full-paper.htm', 1)
        self.assertEqual(self.accept(full_paper.replace('data-reader="latex"', 'data-reader="full-paper"') + READER), 17)

    def test_dictionary_recordings_require_real_audio_elements(self) -> None:
        self.assertEqual(verification.dictionary_audio_references(
            verification.card_markup(DICTIONARY_AUDIO)), {
                'oxford': {'oxford_rate.mp3'}, 'webster': {'webster_rate.mp3'},
            })
        self.assertEqual(verification.dictionary_audio_references(
            verification.card_markup('<script>var x="data-dictionary-source src=example.mp3";</script>')), {})
        for value in ('http://localhost:8770/rate.mp3', 'https://host/rate.mp3',
                      'data:audio/mpeg;base64,AAAA', '../rate.mp3', '/rate.mp3'):
            with self.subTest(value=value), self.assertRaisesRegex(RuntimeError, 'local media'):
                verification.dictionary_audio_references(verification.card_markup(
                    DICTIONARY_AUDIO.replace('oxford_rate.mp3', value)))

    def test_dictionary_sample_requires_oxford_definition_and_global_source_choices(self) -> None:
        controls = JUMP + READER + '<div class="dictionary-definition" data-dictionary="oxford">中文</div>'
        self.assertEqual(self.accept(controls, front=FRONT + DICTIONARY_AUDIO), 17)
        for malformed in (
            controls.replace('data-dictionary="oxford"', 'data-dictionary="webster"'),
            controls + '<section class="secondary-definition">旧释义</section>',
        ):
            with self.subTest(markup=malformed), self.assertRaisesRegex(RuntimeError, 'dictionary'):
                self.accept(malformed, front=FRONT + DICTIONARY_AUDIO)
        with self.assertRaisesRegex(RuntimeError, 'dictionary'):
            self.accept(controls, front=FRONT + DICTIONARY_AUDIO.replace(
                'value="webster"', 'value="unknown"'))


class PackageMediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        verification.OUTPUT.mkdir(parents=True, exist_ok=True)

    def package(self, folder: str, name: str, files: dict[str, bytes]) -> Path:
        package = Path(folder) / name
        with zipfile.ZipFile(package, 'w') as archive:
            names = {str(index): name for index, name in enumerate(files)}
            archive.writestr('media', json.dumps(names))
            for index, content in enumerate(files.values()):
                archive.writestr(str(index), content)
        return package

    def test_expected_media_is_old_and_new_union_with_exact_hashes(self) -> None:
        with tempfile.TemporaryDirectory(prefix='anki-media-unit-', dir=verification.OUTPUT) as folder:
            old = self.package(folder, 'old.apkg', {'legacy.mp3': b'old', 'shared.mp3': b'same'})
            new = self.package(folder, 'new.apkg', {'oxford.mp3': b'oxford', 'webster.mp3': b'webster',
                                                  'shared.mp3': b'same'})
            merged = verification.merge_package_media(
                verification.package_media_hashes(old), verification.package_media_hashes(new))
            self.assertEqual(set(merged), {'legacy.mp3', 'shared.mp3', 'oxford.mp3', 'webster.mp3'})
            self.assertEqual(merged['webster.mp3'], hashlib.sha256(b'webster').hexdigest())
            with self.assertRaisesRegex(RuntimeError, 'conflicting'):
                verification.merge_package_media({'shared.mp3': 'old'}, {'shared.mp3': 'new'})

    def test_package_mapping_rejects_unsafe_duplicate_and_missing_media(self) -> None:
        with tempfile.TemporaryDirectory(prefix='anki-media-unit-', dir=verification.OUTPUT) as folder:
            for mapping, members in (
                ({'0': '../unsafe.mp3'}, {'0': b'audio'}),
                ({'0': 'same.mp3', '1': 'same.mp3'}, {'0': b'a', '1': b'b'}),
                ({'0': 'missing.mp3'}, {}),
            ):
                package = Path(folder) / 'invalid.apkg'
                with zipfile.ZipFile(package, 'w') as archive:
                    archive.writestr('media', json.dumps(mapping))
                    for name, content in members.items():
                        archive.writestr(name, content)
                with self.subTest(mapping=mapping), self.assertRaises(RuntimeError):
                    verification.package_media_hashes(package)

    def test_imported_media_must_match_all_expected_contents(self) -> None:
        with tempfile.TemporaryDirectory(prefix='anki-media-unit-', dir=verification.OUTPUT) as folder:
            root = Path(folder)
            media = root / 'oxford.mp3'
            media.write_bytes(b'audio')
            expected = {'oxford.mp3': hashlib.sha256(b'audio').hexdigest()}
            verification.verify_imported_media(root, expected)
            media.write_bytes(b'changed')
            with self.assertRaisesRegex(RuntimeError, 'hash'):
                verification.verify_imported_media(root, expected)
            media.unlink()
            with self.assertRaisesRegex(RuntimeError, 'missing'):
                verification.verify_imported_media(root, expected)


class DictionaryMediaScannerTests(unittest.TestCase):
    def collection(self, *, scanned: set[str] | None = None,
                   missing: list[str] | None = None, unused: list[str] | None = None,
                   extra: str = ''):
        note = SimpleNamespace(fields=[DICTIONARY_AUDIO, extra], note_type=lambda: {'id': 7})
        media = SimpleNamespace(
            files_in_str=lambda model_id, field: (
                {'oxford_rate.mp3', 'webster_rate.mp3'} if scanned is None else scanned),
            check=lambda: SimpleNamespace(missing=missing or [], unused=unused or []),
        )
        card = Card(JUMP + READER + '<div class="dictionary-definition" data-dictionary="oxford">中文</div>',
                    front=FRONT + DICTIONARY_AUDIO)
        return SimpleNamespace(media=media, get_note=lambda note_id: note, get_card=lambda card_id: card)

    def verify(self, collection, packaged: set[str] | None = None, **kwargs) -> dict:
        return verification.verify_dictionary_media(
            collection, {19}, {17}, {'oxford_rate.mp3', 'webster_rate.mp3'} if packaged is None else packaged,
            **kwargs)

    def ecdict_collection(self, fields: list[str]):
        collection = self.collection()
        collection.get_note = lambda note_id: SimpleNamespace(fields=fields, note_type=lambda: {'id': 7})
        card = Card(JUMP + READER + fields[2] + fields[4], front=FRONT + DICTIONARY_AUDIO)
        card.nid = 19
        collection.get_card = lambda card_id: card
        return collection

    def test_both_sources_scanned_and_unused_old_recordings_allowed(self) -> None:
        result = self.verify(self.collection(unused=['legacy.mp3']))
        self.assertEqual(result['dictionary_audio_references_by_source'], {'oxford': 1, 'webster': 1})
        self.assertEqual(result['dictionary_audio_note_count'], 1)
        self.assertEqual(result['unused_old_media_count'], 1)

    def test_scanner_missing_new_unused_and_unpackaged_media_fail(self) -> None:
        for collection, message in (
            (self.collection(scanned={'oxford_rate.mp3'}), 'scanner misses'),
            (self.collection(missing=['webster_rate.mp3']), 'missing media'),
            (self.collection(unused=['webster_rate.mp3']), 'unused'),
        ):
            with self.subTest(message=message), self.assertRaisesRegex(RuntimeError, message):
                self.verify(collection)
        with self.assertRaisesRegex(RuntimeError, 'absent from new APKG'):
            self.verify(self.collection(), {'oxford_rate.mp3'})

    def test_dictionary_notes_must_not_depend_on_running_api(self) -> None:
        with self.assertRaisesRegex(RuntimeError, 'localhost API'):
            self.verify(self.collection(extra='<a href="http://localhost:8770/api/combined?word=rate">词典</a>'))

    def test_unreferenced_reserved_media_is_not_hidden_by_anki_unused_rules(self) -> None:
        with self.assertRaisesRegex(RuntimeError, 'not referenced in Anki fields'):
            self.verify(self.collection(), {'oxford_rate.mp3', 'webster_rate.mp3', '_orphan.mp3'})

    def test_labeled_wordbook_fallback_is_reported_without_accepting_unmarked_definitions(self) -> None:
        collection = self.collection()
        marker = '<div class="dictionary-definition" data-dictionary="wordbook">词表释义</div>'
        collection.get_note = lambda note_id: SimpleNamespace(
            fields=['exsert', marker, DICTIONARY_AUDIO], note_type=lambda: {'id': 7})
        card = Card(JUMP + READER + marker, front=FRONT + DICTIONARY_AUDIO)
        card.nid = 19
        collection.get_card = lambda card_id: card
        result = self.verify(collection)
        self.assertEqual(result['dictionary_wordbook_definition_fallback_words'], ['exsert'])
        card.back = card.back.replace('data-dictionary="wordbook"', 'data-dictionary="unknown"')
        with self.assertRaisesRegex(RuntimeError, 'definition marker'):
            self.verify(collection)

    def test_ecdict_fallback_requires_verified_tags_and_hidden_complete_source_license(self) -> None:
        result = self.verify(self.ecdict_collection(ecdict_fields()), expected_ecdict_license=MIT_LICENSE)
        self.assertEqual(result['dictionary_ecdict_definition_fallback_words'], ['exsert'])
        self.assertEqual(result['ecdict_exam_tag_source_note_count'], 1)
        self.assertEqual(result['ecdict_hidden_complete_mit_notice_count'], 1)

    def test_ecdict_rejects_truncated_visible_and_wrong_source_licenses(self) -> None:
        for license_text, change in (
            (MIT_LICENSE[:80], None),
            (MIT_LICENSE, 'visible'),
            (MIT_LICENSE.replace('2025 Linwei', '2017 someone else'), None),
        ):
            fields = ecdict_fields(license_text)
            if change == 'visible':
                fields[4] = fields[4].replace(' hidden aria-hidden="true"', '')
            with self.subTest(change=change, text=license_text[:50]), self.assertRaisesRegex(RuntimeError, 'license'):
                self.verify(self.ecdict_collection(fields), expected_ecdict_license=MIT_LICENSE)
        with self.assertRaisesRegex(RuntimeError, 'source LICENSE'):
            self.verify(self.ecdict_collection(ecdict_fields()))

    def test_ecdict_tag_sources_and_empty_tag_rows_are_explicit(self) -> None:
        fields = ecdict_fields()
        fields[4] = fields[4].replace('data-dictionary="ecdict"', 'data-dictionary="legacy"')
        with self.assertRaisesRegex(RuntimeError, 'tag source'):
            self.verify(self.ecdict_collection(fields), expected_ecdict_license=MIT_LICENSE)
        fields = ecdict_fields()
        fields[4] = fields[4].replace(
            '<ul class="level-list" data-dictionary="ecdict"><li>考研</li></ul>',
            '<small class="dictionary-missing" data-dictionary="ecdict">ECDICT 未标注考试标签</small>')
        result = self.verify(self.ecdict_collection(fields), expected_ecdict_license=MIT_LICENSE)
        self.assertEqual(result['ecdict_exam_tag_source_note_count'], 1)

    def test_ecdict_license_preserves_escaped_text_and_the_complete_mit_terms(self) -> None:
        license_text = MIT_LICENSE.replace('2025 Linwei', '2025 <owner> & "co"')
        result = self.verify(self.ecdict_collection(ecdict_fields(license_text)),
                             expected_ecdict_license=license_text)
        self.assertEqual(result['ecdict_hidden_complete_mit_notice_count'], 1)
        truncated = MIT_LICENSE.split('THE SOFTWARE IS PROVIDED')[0]
        with self.assertRaisesRegex(RuntimeError, 'complete MIT'):
            self.verify(self.ecdict_collection(ecdict_fields(truncated)), expected_ecdict_license=truncated)

    def test_legacy_fields_still_pass_without_dictionary_audio(self) -> None:
        collection = self.collection()
        collection.get_note = lambda note_id: SimpleNamespace(
            fields=['[sound:legacy.mp3]'], note_type=lambda: {'id': 7})
        collection.get_card = lambda card_id: Card(JUMP + READER)
        collection.media.files_in_str = lambda model_id, field: ['legacy.mp3']
        result = self.verify(collection, {'legacy.mp3'})
        self.assertFalse(result['anki_media_scanner_recognizes_dictionary_audio'])
        self.assertEqual(result['dictionary_audio_references_by_source'], {})


class NoteFieldChangeTests(unittest.TestCase):
    def test_changed_fields_are_reported_without_rejecting_intended_display_changes(self) -> None:
        old = {1: tuple(['rate'] + [''] * 9)}
        updated = list(old[1])
        updated[2] = 'new definition'
        updated[4] = 'ECDICT exam tags'
        updated[7] = 'newly matched examples'
        result = verification.note_field_changes(old, {1: tuple(updated)})
        self.assertEqual(set(result['note_fields_changed']), {'Definition', 'Level', 'Examples'})
        self.assertEqual(result['note_fields_changed']['Examples'], {'notes': 1, 'sample_words': ['rate']})
        self.assertIn('Word', result['note_fields_unchanged'])


if __name__ == "__main__":
    unittest.main()
