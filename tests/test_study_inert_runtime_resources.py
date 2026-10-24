import hashlib
import json
import unittest
from unittest.mock import patch
from anki_pipeline import study_catalog_presentation as p


def registration(value):
    text = json.dumps(value)
    pin = hashlib.sha256(value.encode()).hexdigest() if isinstance(value, str) else 'a'*64
    return '_ac_'+pin[:24]+'.js', 'window.AnkiSlimAssets=window.AnkiSlimAssets||{};window.AnkiSlimAssets["'+pin+'"]='+text+';'


class InertRuntimeTests(unittest.TestCase):
    def test_only_exact_known_inert_json_is_eligible(self):
        name, text = registration('document.currentScript.src;')
        self.assertTrue(p._dynamic_reference(text))
        self.assertTrue(p._inert_registration(name, text))
        self.assertFalse(p._inert_registration(name, text+'alert(1);'))
        self.assertFalse(p._inert_registration('wrong.js', text))
        history = text.replace('AnkiSlimAssets','AnkiFinalHistoryEvidence')
        history_name = '_af_' + hashlib.sha256(history.encode()).hexdigest()[:24] + '.js'
        self.assertTrue(p._inert_registration(history_name, history))
        self.assertFalse(p._inert_registration('_af_'+('0'*24)+'.js', history))
        name, text = registration({'schema':'anki-slim-shared-strings.v1',
            'dict':{'src':'_as_'+('b'*24)+'.js','sha256':'b'*64,'literal':True},
            'pieces':['document.currentScript.src',0]})
        self.assertTrue(p._inert_registration(name, text))
        self.assertFalse(p._inert_registration(name, text.replace(', 0]', ', true]')))
        self.assertFalse(p._inert_registration(*registration({'arbitrary':'document.currentScript.src'})))

    def project(self, data, originals, current):
        class DB:
            def execute(self, query, args):
                return list(originals.items()) if 'resource_aliases' in query else list(current.items())
        with patch.object(p.c,'get_object',side_effect=lambda db,key:data[key].encode()):
            return p._runtime_projection(DB(), 'fixture', {'resources':{name:name for name in originals}})

    def test_unchanged_inert_payload_is_preserved_but_affected_inert_is_rejected(self):
        name, text = registration('document.currentScript.src')
        originals={name:'inert','x.js':'old'};current={name:'inert','x.js':'new'}
        result=self.project({'inert':text,'old':'old','new':'new'},originals,current)
        self.assertNotIn(name,result['aliases'])
        name2,text2=registration('document.currentScript; "x.js"')
        with self.assertRaisesRegex(ValueError,'inert registration cannot'):
            self.project({'inert':text2,'old':'old','new':'new'},
                {name2:'inert','x.js':'old'},{name2:'inert','x.js':'new'})

    def test_unknown_dynamic_code_and_changed_inert_are_still_rejected(self):
        with self.assertRaisesRegex(ValueError,'explicit dependency'):
            self.project({'code':'document.currentScript.src','old':'old','new':'new'},
                {'unknown.js':'code','x.js':'old'},{'unknown.js':'code','x.js':'new'})
        name, text=registration('document.currentScript.src')
        with self.assertRaisesRegex(ValueError,'explicit dependency'):
            self.project({'old':'original data','new':text},{name:'old'},{name:'new'})

    def test_preserved_legacy_is_exact_unchanged_and_outside_rewrite_closure(self):
        from anki_pipeline import study_native_examples_complete as completion
        name='legacy.js'; code='document.currentScript.src'
        pin=hashlib.sha256(code.encode()).hexdigest()
        with patch.object(completion,'_PRESERVED_LEGACY',{name:pin}):
            self.assertTrue(completion.preserved_legacy_runtime(name,code))
            self.assertFalse(completion.preserved_legacy_runtime(name,code+';'))
            result=self.project({'legacy':code,'old':'old','new':'new'},
                {name:'legacy','x.js':'old'},{name:'legacy','x.js':'new'})
            self.assertNotIn(name,result['aliases'])
            with self.assertRaisesRegex(ValueError,'explicit dependency'):
                self.project({'old':'previous','new':code},{name:'old'},{name:'new'})
        code='document.currentScript; "x.js"';pin=hashlib.sha256(code.encode()).hexdigest()
        with patch.object(completion,'_PRESERVED_LEGACY',{name:pin}):
            with self.assertRaisesRegex(ValueError,'preserved legacy runtime cannot'):
                self.project({'legacy':code,'old':'old','new':'new'},
                    {name:'legacy','x.js':'old'},{name:'legacy','x.js':'new'})
