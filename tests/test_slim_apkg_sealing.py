from pathlib import Path
import tempfile
import unittest
from anki_pipeline.slim_apkg_content import Store
from scripts.finalize_slim_apkg import check_literal,check_references
from scripts.build_slim_apkg import compiled_runtime


class SlimSealing(unittest.TestCase):
    def test_literal_corruption_and_executable_substitution_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(Path(directory));part=store.add('原文与译文');path=store.files[part['sha256']]
            self.assertEqual(check_literal(path),part['sha256'])
            original=path.read_text();path.write_text(original.replace('原文','改文'))
            with self.assertRaisesRegex(ValueError,'SHA'):check_literal(path)
            path.write_text(original+'window.bad=true;')
            with self.assertRaises(ValueError):check_literal(path)

    def test_compiled_helper_requires_and_includes_panel_and_observer_gates(self):
        raw="(function(){'use strict';var config={};document.querySelectorAll('a');document.querySelectorAll('b');document.querySelectorAll('c');})();\n"
        raw+='    observer.observe(a);\n    observer.observe(b);\n    observer.observe(c);\n'
        raw+="if (disposed) return; var natives = physicalNativeIndex(doc);\n"
        raw+="doc.querySelectorAll('.sf-sense > .sf-panel').forEach(function (panel) {\n});\n"
        compiled=compiled_runtime(raw)
        self.assertEqual(compiled.count('if (!window.__ankiSlimManualRefresh) observer.observe('),3)
        self.assertIn('if (window.AnkiSlimPanelReady && !window.AnkiSlimPanelReady(panel)) return;',compiled)
        self.assertIn('window.AnkiSlimDecode=function(root)',compiled)
        with self.assertRaisesRegex(ValueError,'readiness'):compiled_runtime(raw.replace(".sf-sense > .sf-panel","changed"))

    def test_missing_nested_local_asset_is_rejected(self):
        name='_as_'+('c'*24)+'.js'
        with self.assertRaisesRegex(ValueError,'missing a referenced'):check_references('<script data-as-src="'+name+'"></script>',set())
        check_references('<script data-as-src="'+name+'"></script>',{name})


if __name__=='__main__':unittest.main()
