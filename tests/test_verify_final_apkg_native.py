"""Pure guard tests; never import a package or touch an Anki profile."""
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json
import tempfile
import zipfile
from scripts import verify_final_apkg_native as verifier


class NativeVerifierGuards(unittest.TestCase):
    def test_identity_guard_preserves_existing_and_exactly_two_additions(self):
        before=[(1,'old',20),(2,'guide',21)]
        after=before+[(3,'new-a',20),(4,'new-b',20)]
        verifier.check_identities(before,after,{'new-a','new-b'})
        for bad in [[(1,'old',99),*after[1:]],after[:-1],after+[(5,'extra',20)]]:
            with self.assertRaises(ValueError):verifier.check_identities(before,bad,{'new-a','new-b'})

    def test_original_schedules_ignore_only_mod_and_usn(self):
        columns=['id','nid','mod','usn','queue','due','flags']
        before=verifier.project_card_states(columns,[(10,1,7,3,-1,11,0)])
        after=verifier.project_card_states(columns,[(10,1,99,-1,-1,11,0),(20,2,99,-1,-1,12,0)])
        verifier.check_original_states(before,after)
        changed=dict(after);changed[10]=(*changed[10][:-1],1)
        with self.assertRaisesRegex(ValueError,'original card schedule'):verifier.check_original_states(before,changed)

    def test_fields_nfc_and_runtime_byte_hash_are_separate_from_origin_hash(self):
        self.assertEqual(verifier.nfc('e\u0301'),verifier.nfc('\u00e9'))
        runtime={'js':'_af_runtime.js','css':'_af_runtime.css','js_sha256':verifier.sha(b'actual-js'),
            'css_sha256':verifier.sha(b'actual-css'),'helper_source_sha256':verifier.sha(b'origin-js')}
        verifier.check_runtime_bytes(runtime,b'actual-js',b'actual-css')
        with self.assertRaisesRegex(ValueError,'runtime JS'):verifier.check_runtime_bytes(runtime,b'origin-js',b'actual-css')

    def test_native_template_requires_actual_current_runtime_on_each_face(self):
        model={'flds':[{'name':'Word'}],'tmpls':[{'qfmt':'<script>AnkiFinalApkgDispose()</script>',
            'afmt':'<script src="_af_runtime.js"></script><script>AnkiFinalApkgHydrate()</script>'}],'css':'native-css'}
        runtime={'js':'_af_runtime.js'}
        verifier.check_runtime_model(model,deepcopy(model),runtime)
        bad=deepcopy(model);bad['tmpls'][0]['afmt']=bad['tmpls'][0]['afmt'].replace('_af_runtime.js','old.js')
        with self.assertRaises(ValueError):verifier.check_runtime_model(bad,model,runtime)

    def test_original_media_are_verified_by_filename_and_exact_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            old=Path(directory)/'old.apkg';new=Path(directory)/'new.apkg'
            with zipfile.ZipFile(old,'w') as archive:
                archive.writestr('media',json.dumps({'0':'voice.mp3'}))
                archive.writestr('0',b'untouched-audio')
            runtime={'js':'runtime.js','css':'runtime.css','js_sha256':verifier.sha(b'js'),'css_sha256':verifier.sha(b'css')}
            def package(audio):
                with zipfile.ZipFile(new,'w') as archive:
                    archive.writestr('media',json.dumps({'7':'voice.mp3','8':'runtime.js','9':'runtime.css'}))
                    for key,data in [('7',audio),('8',b'js'),('9',b'css')]:archive.writestr(key,data)
            package(b'untouched-audio')
            verifier._media_checks(old,new,runtime)
            package(b'changed-audio')
            with self.assertRaisesRegex(ValueError,'original media bytes changed'):verifier._media_checks(old,new,runtime)

    def test_qa_exports_actual_faces_css_and_all_non_audio_media(self):
        with tempfile.TemporaryDirectory() as directory:
            media=Path(directory)/'media';media.mkdir()
            (media/'runtime.js').write_bytes(b'js');(media/'image.png').write_bytes(b'png')
            (media/'voice.mp3').write_bytes(b'audio')
            candidates={word:{'guid':word,'nid':i,'mid':1} for i,word in enumerate(verifier.QA_WORDS,1)}
            collection=SimpleNamespace(
                media=SimpleNamespace(dir=lambda:str(media)),
                models=SimpleNamespace(get=lambda mid:{'css':'.card{color:blue}'}),
                db=SimpleNamespace(all=lambda sql,nid:[(nid+100,)]),
                get_card=lambda cid:SimpleNamespace(id=cid,question=lambda:'native-question',answer=lambda:'native-answer'))
            target=Path(directory)/'native-qa'
            result=verifier._export_qa(collection,candidates,{'0':'voice.mp3','1':'runtime.js','2':'image.png'},target)
            self.assertEqual(len(result['samples']),14)
            self.assertEqual({p.name for p in target.iterdir() if p.suffix not in ['.html']},{'runtime.js','image.png'})
            self.assertIn('native-answer',(target/'as-answer.html').read_text())
            self.assertIn('.card{color:blue}',(target/'as-question.html').read_text())
            with self.assertRaises(FileExistsError):verifier._export_qa(collection,candidates,{},target)


if __name__=='__main__':unittest.main()
