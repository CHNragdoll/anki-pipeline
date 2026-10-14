"""Native slim-package guard tests; never open a user Anki profile."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import zipfile

from scripts import verify_slim_apkg_native as verifier


class SlimVerifierGuards(unittest.TestCase):
    def test_default_output_and_baseline_roots_remain_compatible(self):
        package = verifier.OWN / "2026红宝书完整版-无损瘦身与加载优化-20261015.apkg"
        source = verifier.BASELINE / "2026红宝书完整版-最新释义校勘与chunk-20261015.apkg"
        self.assertEqual(verifier.resolve_scope("2026", {"output": str(package), "source": str(source)}),
                         (package.resolve(), source.resolve()))

    def test_custom_roots_accept_current_filename_and_reject_cross_scope_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            output_root = Path(directory) / "slim-v2"
            baseline_root = Path(directory) / "baseline"
            package = output_root / "2026红宝书完整版-深度无损瘦身-20261015.apkg"
            source = baseline_root / "2026红宝书完整版-最新释义校勘与chunk-20261015.apkg"
            report = {"output": str(package), "source": str(source)}
            self.assertEqual(verifier.resolve_scope("2026", report, output_root, baseline_root),
                             (package.resolve(), source.resolve()))
            for key, value in [("output", package.parent.parent / package.name),
                               ("output", output_root / "2027红宝书完整版-深度无损瘦身-20261015.apkg"),
                               ("output", package.with_suffix(".txt")),
                               ("source", baseline_root.parent / source.name)]:
                with self.assertRaises(ValueError):
                    verifier.resolve_scope("2026", {**report, key: str(value)}, output_root, baseline_root)

    def test_cli_root_options_are_optional(self):
        args = verifier.parse_arguments(["--year", "2026", "--qa"])
        self.assertIsNone(args.output_root)
        self.assertIsNone(args.baseline_root)
        self.assertTrue(args.qa)
        args = verifier.parse_arguments(["--year", "2027", "--output-root", "/tmp/slim-v2",
                                         "--baseline-root", "/tmp/baseline"])
        self.assertEqual(args.output_root, Path("/tmp/slim-v2"))
        self.assertEqual(args.baseline_root, Path("/tmp/baseline"))

    def test_update_preserves_every_native_note_identity_without_additions(self):
        before = [(1, "old", 20), (2, "guide", 21), (3, "supplemental", 20)]
        verifier.check_exact_identities(before, list(reversed(before)))
        for bad in [before[:-1], before + [(4, "extra", 20)],
                    [(99, "old", 20), *before[1:]],
                    [(1, "old", 22), *before[1:]],
                    [*before, before[0]]]:
            with self.assertRaises(ValueError):
                verifier.check_exact_identities(before, bad)

    def test_schedules_flags_and_card_ids_are_exact_ignoring_only_bookkeeping(self):
        columns = ["id", "nid", "mod", "usn", "queue", "due", "flags"]
        before = verifier.project_card_states(columns, [(10, 1, 7, 3, -1, 11, 3)])
        after = verifier.project_card_states(columns, [(10, 1, 99, -1, -1, 11, 3)])
        verifier.check_exact_states(before, after)
        for row in [(10, 1, 99, -1, -1, 12, 3),
                    (10, 1, 99, -1, -1, 11, 0),
                    (20, 1, 99, -1, -1, 11, 3)]:
            with self.assertRaises(ValueError):
                verifier.check_exact_states(before, verifier.project_card_states(columns, [row]))
        with self.assertRaises(ValueError):
            verifier.check_exact_states(before, {**after, 99: (99, 2, -1, 11, 3)})

    def test_first_native_import_can_renumber_but_not_change_guid_or_model(self):
        expected = [(2200000000000, "one", 20), (2200000000001, "two", 21)]
        actual = [(1, "one", 20), (2, "two", 21)]
        verifier.check_guid_models(expected, actual)
        with self.assertRaises(ValueError):
            verifier.check_guid_models(expected, [(1, "one", 22), actual[1]])
        with self.assertRaises(ValueError):
            verifier.check_exact_identities(expected, actual)

    def test_templates_are_exact_and_use_current_slim_runtime(self):
        runtime = {"js": "_slim.js", "css": "_slim.css",
                   "hydrate": "AnkiSlimApkgHydrate", "dispose": "AnkiSlimApkgDispose"}
        model = {"flds": [{"name": "Word"}], "css": "css",
                 "tmpls": [{"qfmt": '<script>AnkiSlimApkgDispose()</script>',
                             "afmt": '<script src="_slim.js"></script><script>AnkiSlimApkgHydrate()</script>'}]}
        verifier.check_slim_model(model, deepcopy(model), runtime)
        for face in ["qfmt", "afmt"]:
            changed = deepcopy(model)
            changed["tmpls"][0][face] = "old template"
            with self.assertRaises(ValueError):
                verifier.check_slim_model(changed, model, runtime)
        changed = deepcopy(model)
        changed["tmpls"][0]["afmt"] = changed["tmpls"][0]["afmt"].replace("_slim.js", "old.js")
        with self.assertRaises(ValueError):
            verifier.check_slim_model(changed, changed, runtime)

    def test_baseline_media_filename_and_every_byte_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            old, new = (Path(directory) / name for name in ["old.apkg", "new.apkg"])
            with zipfile.ZipFile(old, "w") as archive:
                archive.writestr("media", json.dumps({"0": "voice.mp3", "1": "old-runtime.js"}))
                archive.writestr("0", b"original audio")
                archive.writestr("1", b"original runtime")
            runtime = {"js": "_slim.js", "css": "_slim.css",
                       "js_sha256": verifier.sha(b"js"), "css_sha256": verifier.sha(b"css")}

            def create_package(audio):
                with zipfile.ZipFile(new, "w") as archive:
                    archive.writestr("media", json.dumps({"7": "voice.mp3", "8": "old-runtime.js",
                                                          "9": "_slim.js", "10": "_slim.css"}))
                    for key, value in [("7", audio), ("8", b"original runtime"), ("9", b"js"), ("10", b"css")]:
                        archive.writestr(key, value)

            create_package(b"original audio")
            verifier._media_checks(old, new, runtime)
            create_package(b"modified audio")
            with self.assertRaisesRegex(ValueError, "original media bytes changed"):
                verifier._media_checks(old, new, runtime)

    def test_qa_exports_all_eight_actual_native_faces_and_non_audio_media(self):
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "media"
            media.mkdir()
            (media / "_slim.js").write_bytes(b"js")
            (media / "voice.mp3").write_bytes(b"audio")
            candidates = {word: {"guid": word, "nid": i, "mid": 1}
                          for i, word in enumerate(verifier.QA_WORDS, 1)}
            collection = SimpleNamespace(
                media=SimpleNamespace(dir=lambda: str(media)),
                models=SimpleNamespace(get=lambda mid: {"css": ".card{color:blue}"}),
                db=SimpleNamespace(all=lambda sql, nid: [(nid + 100,)]),
                get_card=lambda cid: SimpleNamespace(id=cid, question=lambda: "native question", answer=lambda: "native answer"))
            result = verifier.export_qa(collection, candidates,
                                        {"0": "voice.mp3", "1": "_slim.js"}, Path(directory) / "qa")
            self.assertEqual(len(result["samples"]), 16)
            self.assertIn("native answer", (Path(directory) / "qa/the-answer.html").read_text())
            self.assertFalse((Path(directory) / "qa/voice.mp3").exists())
            self.assertEqual(set(verifier.QA_WORDS), {"the", "more", "training", "train", "oblige", "as", "teem", "deep-rooted"})
            with self.assertRaisesRegex(ValueError, "sample words"):
                verifier.export_qa(collection, {}, {}, Path(directory) / "missing")

    def test_native_media_checks_new_payloads_as_well_as_original_audio(self):
        with tempfile.TemporaryDirectory() as directory:
            media = Path(directory) / "media"
            media.mkdir()
            package = Path(directory) / "slim.apkg"
            media_map = {"0": "voice.mp3", "1": "_slim-payload.js"}
            with zipfile.ZipFile(package, "w") as archive:
                archive.writestr("0", b"audio")
                archive.writestr("1", b"payload")
            (media / "voice.mp3").write_bytes(b"audio")
            (media / "_slim-payload.js").write_bytes(b"payload")
            collection = SimpleNamespace(media=SimpleNamespace(dir=lambda: str(media)))
            self.assertEqual(verifier._check_native_media_bytes(collection, package, media_map), 2)
            (media / "_slim-payload.js").write_bytes(b"wrong payload")
            with self.assertRaisesRegex(ValueError, "native media bytes differ"):
                verifier._check_native_media_bytes(collection, package, media_map)


if __name__ == "__main__":
    unittest.main()
