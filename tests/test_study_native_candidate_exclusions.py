"""Certified native exclusions preserve source text and exact inverse bytes."""
from copy import deepcopy
from collections import Counter
import base64
import hashlib
import json
from pathlib import Path
import tempfile
import re
import unittest
from unittest.mock import patch

from anki_pipeline import sense_candidate_scope as cs
from anki_pipeline import sense_display as sd
from anki_pipeline import study_native_candidate_exclusions as ce
from tests.test_sense_display import source, occurrence, native_example


def seal(value):
    value = deepcopy(value)
    value.pop('snapshot_id', None)
    value['snapshot_id'] = sd._sha(sd._json(value))
    return value


def write_json(path, value):
    raw = (sd._json(value)+'\n').encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def fixture(directory, english='As soon as a plan works.', spans=((0,2),(8,10),(11,12)), excluded=(0,1)):
    directory = Path(directory)
    item = source('kaoyan:2022-01:p:fixture:0',english,'原译文完整保留。')
    rows = []
    for span in spans:
        row = occurrence(item,list(span))
        row.update(paper_id='kaoyan:2022-01',status='unmatched',sense_index=None,
                   method='audited-test',review_version='v1',reason='source candidate')
        rows.append(row)
    record = {'book_id':'independent-book','card_id':'article-card','word':'a/an',
        'definition_source':'oxford','definition_provenance':{'headword':'a/an','page_sha256':'a'*64},
        'senses':[{'pos':'article','text':'一个'}],'matching_evidence':[],
        'expected_occurrences':len(rows),'occurrences':rows}
    inventory = directory/'full-inventory-v2';inventory.mkdir()
    raw = (sd._json(record)+'\n').encode();(inventory/'records.jsonl').write_bytes(raw)
    manifest = write_json(inventory/'inventory.json',{'records':1})
    evidence=[]
    for index in excluded:
        row=rows[index]
        evidence.append({'global_index':index,'work_id':'audited-work','physical_id':cs._physical(row),
            'raw_english_hash':row['english_hash'],'actual_token':english[slice(*row['target_range'])],
            'english':english,'translation':row['translation'],'source':row['source'],
            'source_provenance':row['source_provenance'],'context_proof_ref':item['id'],
            'canonical_sentence_exact_match':True,'classification':'different_lemma_as',
            'same_original_article_headword':False,'a_noun_plural':False,'reason':'已审为另一个 lemma。'})
    retained=[i for i in range(len(rows)) if i not in excluded]
    audit={'schema':'codex-a-an-form-audit.v1','book_id':record['book_id'],'card_id':record['card_id'],
        'work_id':'audited-work','summary':{'raw_physical_total':len(rows),'pending_as':0,
            'confirmed_same_original_article_headword_as':0,'confirmed_letter_or_grade_a_noun_plural_as':0,
            'safe_to_exclude_all_as_from_article_candidate_denominator':True,
            'non_as_candidate_count_is_not_certified_article_total':True,
            'non_as_candidate_count_after_overlay':len(retained),'excluded_as_indices':list(excluded),
            'raw_casefold_counts':dict(Counter(english[slice(*r['target_range'])].casefold() for r in rows))},
        'pending':[],'same_headword_as_records':[],'confirmed_exclusions':evidence,
        'non_as_retained_candidate_indices':retained,
        'original_book_intent':{'definition_provenance':record['definition_provenance']},
        'word_form_origin':{'formal_page_forms_raw':'','formal_page_form_raw_character_range':[0,0]},
        'source_snapshot':{'inventory_record_byte_locator':{'book_id':record['book_id'],
            'card_id':record['card_id'],'word':record['word'],'byte_offset':0,'byte_length':len(raw),
            'occurrences':len(rows),'senses':1},'inventory_record_sha256':hashlib.sha256(raw).hexdigest(),
            'inventory_manifest_sha256':manifest,'official_page':'unused-original.html',
            'official_page_sha256':'a'*64}}
    path=directory/'audit.json';pin=write_json(path,audit)
    current=seal({**record,'occurrences':[rows[i] for i in retained],'expected_occurrences':len(retained)})
    page='<!--外围保持--><ol class="examples">'+native_example(item,english,item['translationZh'],
        [list(span) for span in spans])+'</ol><!--尾部原字节-->'
    return page,current,path,pin,item,audit


class CandidateExclusionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def issue(self,page,current,path,pin,**kwargs):
        return ce.issue_exclusions(page,current,audit_path=path,expected_audit_sha256=pin,**kwargs)

    def apply(self,page,current,cap):
        before=deepcopy(current)
        result=ce.apply_exclusions(page,current,cap)
        self.assertEqual(current,before)
        self.assertEqual(ce.restore_original(result['page'],result['inverse']).encode(),page.encode())
        return result

    def test_mixed_two_as_and_a_preserves_every_other_markup_byte(self):
        page,current,path,pin,item,_=fixture(self.temp.name)
        page=page.replace('>As</mark>','><span class="card-chunk" data-chunk-id="77">As</span></mark>')
        page=page.replace('</li>','<details class="sf-catalog-revision"><summary>旧审核</summary><p>全文</p></details><audio src="original.mp3"></audio></li>')
        original=page
        # The current semantic rows alone have no authority to remove the old
        # native as marks: this is the actual old presentation defect.
        from anki_pipeline.native_example_usage import update_native_examples
        baseline=update_native_examples(page,current,current)
        self.assertEqual(sd._native_examples(baseline['page'],{})[0]['target_ranges'],
                         [[0,2],[8,10],[11,12]])
        cap=self.issue(page,current,path,pin)
        result=self.apply(page,current,cap)
        expected=page.replace('<mark class="target-word"><span class="card-chunk" data-chunk-id="77">As</span></mark>',
                              '<span class="card-chunk" data-chunk-id="77">As</span>').replace('<mark class="target-word">as</mark>','as')
        self.assertEqual(result['page'],expected)
        visible=sd._native_examples(result['page'],{})[0]
        self.assertEqual(visible['target_ranges'],[[11,12]])
        self.assertEqual(visible['english'],item['english'])
        self.assertEqual(visible['translation'],item['translationZh'])
        self.assertEqual(result['stats']['removed_target_marks'],2)
        self.assertEqual(result['stats']['removed_examples'],0)
        self.assertEqual(page,original)

    def test_pure_as_removes_only_certified_line_and_inverse_retains_all(self):
        page,current,path,pin,item,_=fixture(self.temp.name,'As promised.',((0,2),),(0,))
        other=source('kaoyan:2022-01:p:other:0',item['english'],item['translationZh'])
        untouched=native_example(other,item['english'],item['translationZh'],[[0,2]])
        page=page.replace('</ol>',untouched+'</ol>')
        result=self.apply(page,current,self.issue(page,current,path,pin))
        self.assertEqual(result['page'],'<!--外围保持--><ol class="examples">'+untouched+'</ol><!--尾部原字节-->')
        self.assertEqual(result['stats']['removed_examples'],1)

    def test_unbound_target_prevents_whole_line_removal(self):
        page,current,path,pin,item,_=fixture(self.temp.name,'As a rule.',((0,2),),(0,))
        page=page.replace('As</mark> a rule.','As</mark> <mark class="target-word">a</mark> rule.')
        result=self.apply(page,current,self.issue(page,current,path,pin))
        self.assertEqual(sd._native_examples(result['page'],{})[0]['target_ranges'],[[3,4]])
        self.assertEqual(result['stats']['removed_examples'],0)
        self.assertGreaterEqual(result['stats']['unbound_targets'],1)

    def test_unbound_other_source_is_unchanged(self):
        page,current,path,pin,_,_=fixture(self.temp.name)
        page=page.replace('p%3Afixture%3A0','p%3Aunbound%3A0')
        result=self.apply(page,current,self.issue(page,current,path,pin))
        self.assertEqual(result['page'],page)
        self.assertEqual(result['stats']['removed_target_marks'],0)

    def test_wrong_audit_source_range_and_token_are_rejected_even_with_new_pin(self):
        for field in ('range','source','token','classification'):
            with self.subTest(field=field),tempfile.TemporaryDirectory() as directory:
                page,current,path,pin,_,audit=fixture(directory)
                proof=audit['confirmed_exclusions'][0]
                if field=='range':proof['physical_id']['target_range']=[8,10]
                elif field=='source':proof['source_provenance']['reviewedContentHash']='0'*64
                elif field=='token':proof['actual_token']='a'
                else:proof['classification']='guess'
                with self.assertRaises(ValueError):self.issue(page,current,path,write_json(path,audit))

    def test_wrong_pin_plain_json_cap_current_seal_and_page_drift_reject(self):
        page,current,path,pin,_,_=fixture(self.temp.name)
        with self.assertRaises(ValueError):self.issue(page,current,path,'0'*64)
        cap=self.issue(page,current,path,pin)
        for false_cap in (cap.verification(),deepcopy(cap),None):
            with self.assertRaises(ValueError):ce.apply_exclusions(page,current,false_cap)
        for changed in (page+' ',page.replace('anki-codex-hash','wrong-hash')):
            with self.assertRaises(ValueError):ce.apply_exclusions(changed,current,cap)
        changed=deepcopy(current);changed['word']='elsewhere';changed=seal(changed)
        with self.assertRaises(ValueError):ce.apply_exclusions(page,changed,cap)
        changed=deepcopy(current);changed['occurrences'][0]['english_hash']='0'*64
        with self.assertRaises(ValueError):self.issue(page,seal(changed),path,pin)

    def test_source_jump_hash_and_unsupported_wrapper_fail_closed(self):
        page,current,path,pin,_,_=fixture(self.temp.name)
        bad=page.replace('anki-codex-hash=','anki-codex-hash=0')
        result=self.apply(bad,current,self.issue(bad,current,path,pin))
        self.assertEqual(result['page'],bad)
        self.assertEqual(result['stats']['unbound_native_sources'],1)
        bad=page.replace('<mark class="target-word">As','<mark class="target-word" style="color:red">As')
        with self.assertRaises(ValueError):self.apply(bad,current,self.issue(bad,current,path,pin))
        bad=page.replace('<mark class="target-word">As','<mark class="foreign" class="target-word">As')
        with self.assertRaises(ValueError):self.apply(bad,current,self.issue(bad,current,path,pin))

    def test_inverse_tamper_is_rejected(self):
        page,current,path,pin,_,_=fixture(self.temp.name)
        result=self.apply(page,current,self.issue(page,current,path,pin))
        with self.assertRaises(ValueError):ce.restore_original(result['page']+'x',result['inverse'])
        inverse=deepcopy(result['inverse']);inverse['spans'][0]['original']='changed'
        with self.assertRaises(ValueError):ce.restore_original(result['page'],inverse)

    def test_supplement_uses_independent_physical_mapping_not_primary_indices(self):
        from tests.test_sense_candidate_scope import candidate_fixture, supplement_fixture
        record,page,_,audit_path,_=candidate_fixture(self.temp.name)
        mapped,_,audit_pin,supplement,supplement_pin=supplement_fixture(
            self.temp.name,record,page,audit_path)
        # Supplement raw order reverses the primary indices: excluded 0/2,
        # retained 1/3. The current record may further filter other candidates.
        current=seal({**mapped,'occurrences':[mapped['occurrences'][3]],'expected_occurrences':1})
        pieces=[]
        for row in mapped['occurrences']:
            item=source(row['sentence_id'],row['english'],row['translation'])
            item['reviewedContentHash']=row['source_provenance']['reviewedContentHash']
            pieces.append(native_example(item,row['english'],row['translation'],[row['target_range']]))
        examples='<ol class="examples">'+''.join(pieces)+'</ol>'
        with self.assertRaises(ValueError):self.issue(examples,current,audit_path,audit_pin)
        cap=self.issue(examples,current,audit_path,audit_pin,supplement_path=supplement,
                       expected_supplement_sha256=supplement_pin)
        result=self.apply(examples,current,cap)
        self.assertEqual(result['page'],'<ol class="examples">'+pieces[1]+pieces[3]+'</ol>')
        self.assertEqual(result['stats']['removed_examples'],2)
        proof=json.loads(supplement.read_text())
        proof['physical_evidence_map'][0]['global_index_2027']=0
        with self.assertRaises(ValueError):
            self.issue(examples,current,audit_path,audit_pin,supplement_path=supplement,
                       expected_supplement_sha256=write_json(supplement,proof))

    def test_compressed_aliases_are_snapshotted_and_untouched_rows_stay_exact(self):
        page,current,path,pin,item,_=fixture(self.temp.name)
        aliases={'ec':'example-card','et':'example-text','ez':'example-translation',
                 'es':'example-source','sj':'sentence-jump','tt':'translate-tag','tw':'target-word'}
        for compact,canonical in aliases.items():
            page=page.replace('class="'+canonical+'"','class="'+compact+'"')
        cap=self.issue(page,current,path,pin,aliases=aliases)
        aliases['tw']='foreign'
        result=self.apply(page,current,cap)
        self.assertEqual(result['page'].count('class="tw"'),1)
        self.assertEqual(sd._native_examples(result['page'],cap.verification()['aliases'])[0]['target_ranges'],[[11,12]])

    def test_inventory_drift_and_other_card_cannot_issue_authority(self):
        page,current,path,pin,_,_=fixture(self.temp.name)
        wrong=seal({**current,'card_id':'other-card'})
        with self.assertRaises(ValueError):self.issue(page,wrong,path,pin)
        inventory=Path(self.temp.name)/'full-inventory-v2/records.jsonl'
        inventory.write_bytes(inventory.read_bytes().replace(b'As soon',b'AS soon'))
        with self.assertRaises(ValueError):self.issue(page,current,path,pin)

    def test_unrelated_retained_display_does_not_authorize_or_block_as_proof(self):
        page,current,path,pin,item,_=fixture(self.temp.name)
        excluded=native_example(item,item['english'],item['translationZh'],[[0,2],[8,10]])
        retained=native_example(item,item['english'],item['translationZh'],[[11,12]])
        def packed(markup,targets):
            hashes=[base64.urlsafe_b64encode(bytes.fromhex(item[key])).decode().rstrip('=')
                    for key in ('englishHash','reviewedContentHash')]
            jump='|'.join(['1','2022-01','p%3Afixture%3A0',*hashes,
                           ';'.join(str(a)+','+str(b) for a,b in targets)])
            return re.sub(r'href="[^"]+"','data-rb-j="'+jump+'"',markup)
        excluded=packed(excluded,[[0,2],[8,10]])
        retained=packed(retained,[[11,12]])
        page='<ol class="examples">'+excluded+retained+'</ol>'
        record=deepcopy(current);record.pop('snapshot_id')
        record['definition_provenance']['page_sha256']=sd._sha(page)
        sources={'sentences':{item['id']:item},'completions':{},'options':{},'watched':{}}
        with patch.object(sd,'_load_sources',return_value=sources):
            record=sd.attach_source_displays([record],{record['card_id']:page},{})[0]
        current=seal(record)
        # This retained row pins the second LI. Processing the first LI alone
        # loses that exact counterpart and correctly fails the common guard.
        from anki_pipeline import native_example_usage as native
        with self.assertRaisesRegex(ValueError,'owner counterpart'):
            cap=self.issue(page,current,path,pin)
            proof=cap.verification()
            native.update_native_examples(excluded,
                seal({'book_id':current['book_id'],'card_id':current['card_id'],
                      'occurrences':current['occurrences']+proof['excluded']}),
                seal({'book_id':current['book_id'],'card_id':current['card_id'],
                      'occurrences':current['occurrences']}))
        result=self.apply(page,current,cap)
        self.assertEqual(result['page'],'<ol class="examples">'+retained+'</ol>')

    def formal_bridge_fixture(self):
        page,current,path,pin,item,_=fixture(self.temp.name,'A ______ as a rule.',((9,11),(12,13)),(0,))
        english='A longer answer as a rule.'
        actual=native_example(item,english,item['translationZh'],[[16,18],[19,20]],
                              source_ranges=[[9,11],[12,13]],answer=[2,15],answer_number=29)
        formal_page=native_example(item,english,item['translationZh'],[[16,18]],
                                  source_ranges=[[9,11]],answer=[2,15],answer_number=29)
        raw=json.loads((Path(self.temp.name)/'full-inventory-v2/records.jsonl').read_text())
        formal={**raw,'card_id':'formal-as-card','word':'as','expected_occurrences':1,
                'occurrences':[raw['occurrences'][0]],'definition_provenance':{
                    'headword':'as','page_sha256':sd._sha(formal_page)}}
        completion={'sentenceId':item['id'],'originalEnglish':item['english'],'completedEnglish':english,
                    'translationZh':item['translationZh'],'blankRange':[2,8],'insertedRange':[2,15],
                    'answerNumber':'29','questionId':'kaoyan:2022-01:q-29-1'}
        source_path=Path(self.temp.name)/'reading-completions-v1.json'
        source_pin=write_json(source_path,{'completion':completion})
        sources={'sentences':{item['id']:item},'completions':{item['id']:completion},'options':{},
                 'watched':{source_path:source_pin}}
        with patch.object(sd,'_load_sources',return_value=sources):
            formal=sd.attach_source_displays([formal],{formal['card_id']:formal_page},{})[0]
        formal=seal(formal);formal_path=Path(self.temp.name)/'formal-record.json'
        formal_pin=write_json(formal_path,formal)
        return actual,current,path,pin,formal_path,formal_pin,formal,source_path

    def test_formal_display_bridge_preserves_a_and_uses_original_provenance(self):
        page,current,path,pin,formal_path,formal_pin,formal,_=self.formal_bridge_fixture()
        plain=self.apply(page,current,self.issue(page,current,path,pin))
        self.assertEqual(plain['page'],page)
        cap=self.issue(page,current,path,pin,source_display_records=[{'file':str(formal_path),'sha256':formal_pin}])
        result=self.apply(page,current,cap)
        self.assertEqual(result['page'],page.replace('<mark class="target-word">as</mark>','as'))
        self.assertEqual(sd._native_examples(result['page'],{})[0]['target_ranges'],[[19,20]])
        bridge=next(iter(cap.verification()['source_display_bridges'].values()))
        self.assertEqual(bridge['display'],formal['occurrences'][0]['display'])
        self.assertEqual(result['stats']['removed_target_marks'],1)

    def test_formal_bridge_wrong_source_pin_range_and_sidecar_are_rejected(self):
        page,current,path,pin,formal_path,formal_pin,formal,source_path=self.formal_bridge_fixture()
        with self.assertRaises(ValueError):
            self.issue(page,current,path,pin,source_display_records=[{'file':str(formal_path),'sha256':'0'*64}])
        bad=deepcopy(formal);bad['occurrences'][0]['display']['target_range']=[19,20]
        from tests.test_sense_display import reseal
        reseal(bad['occurrences'][0]['display']);bad=seal(bad)
        with self.assertRaises(ValueError):
            self.issue(page,current,path,pin,source_display_records=[{'file':str(formal_path),
                       'sha256':write_json(formal_path,bad)}])
        write_json(formal_path,formal);source_path.write_bytes(b'{"changed":true}')
        with self.assertRaises(ValueError):
            self.issue(page,current,path,pin,source_display_records=[{'file':str(formal_path),'sha256':formal_pin}])

    def test_formal_bridge_cannot_consume_a_only_target(self):
        page,current,path,pin,formal_path,formal_pin,_,_=self.formal_bridge_fixture()
        page=page.replace('<mark class="target-word">as</mark>','as')
        cap=self.issue(page,current,path,pin,source_display_records=[{'file':str(formal_path),'sha256':formal_pin}])
        result=self.apply(page,current,cap)
        self.assertEqual(result['page'],page)
        self.assertEqual(result['stats']['removed_target_marks'],0)

    def lexical_rule(self):
        return {'schema':'study-native-lexical-presentation-exclusions.v1',
                'denied_forms':['as'],'retained_forms':['a','an'],
                'reason':'Explicitly approved article-list presentation correction.'}

    def test_explicit_lexical_rule_handles_unmapped_view_without_physical_claim(self):
        page,current,path,pin,_,_=fixture(self.temp.name)
        # A different legitimate assembled view has no physical range mapping.
        page=page.replace('As soon as a plan works.', 'As soon as a plan works.')
        page=page.replace('p%3Afixture%3A0','p%3Aassembled%3A0')
        page=page.replace('>As</mark>','><span class="card-chunk" data-chunk-id="7">&#65;s</span></mark>')
        page=page.replace('</li>','<details class="sf-catalog-revision"><summary>原审核</summary>'
                          '<mark class="target-word">as</mark></details><audio src="kept.mp3"></audio></li>')
        baseline=self.apply(page,current,self.issue(page,current,path,pin))
        self.assertEqual(baseline['page'],page)
        rule=self.lexical_rule()
        cap=self.issue(page,current,path,pin,lexical_presentation_rule=rule)
        rule['denied_forms'].append('a')  # Capability must own its snapshot.
        result=self.apply(page,current,cap)
        expected=page.replace('<mark class="target-word"><span class="card-chunk" data-chunk-id="7">&#65;s</span></mark>',
                              '<span class="card-chunk" data-chunk-id="7">&#65;s</span>')
        expected=expected.replace('<mark class="target-word">as</mark> soon','as soon')
        # Replace only the current plain second as; the nested audit is exact.
        expected=expected.replace('soon <mark class="target-word">as</mark>','soon as')
        self.assertEqual(result['page'],expected)
        self.assertEqual(sd._native_examples(result['page'],{})[0]['target_ranges'],[[11,12]])
        self.assertEqual(result['stats']['lexical_removed_target_marks'],2)
        self.assertEqual(result['stats']['consumed_exclusions'],0)
        self.assertIn('<mark class="target-word">as</mark></details>',result['page'])

    def test_lexical_rule_pure_row_removal_keeps_nonexact_forms(self):
        page,current,path,pin,item,_=fixture(self.temp.name)
        other=source('kaoyan:2022-01:p:unbound:0','as a asx.','原句译文')
        pure=native_example(other,other['english'],other['translationZh'],[[0,2]])
        mixed=native_example(other,other['english'],other['translationZh'],[[0,2],[3,4],[5,8]])
        spaced=native_example(other,' as ',other['translationZh'],[[0,4]])
        page='<ol class="examples">'+pure+mixed+spaced+'</ol>'
        result=self.apply(page,current,self.issue(page,current,path,pin,
                          lexical_presentation_rule=self.lexical_rule()))
        self.assertEqual(result['page'],'<ol class="examples">'+
                         mixed.replace('<mark class="target-word">as</mark>','as')+spaced+'</ol>')
        self.assertEqual(result['stats']['lexical_removed_examples'],1)
        self.assertEqual(result['stats']['lexical_removed_target_marks'],2)
        self.assertEqual(result['stats']['consumed_exclusions'],0)

    def test_lexical_rule_rejects_unapproved_forms_and_bad_retained_record(self):
        page,current,path,pin,_,_=fixture(self.temp.name)
        for change in ({'denied_forms':['a']},{'denied_forms':[' as ']},
                       {'retained_forms':['an']},{'reason':''},{'schema':'unknown'}):
            rule={**self.lexical_rule(),**change}
            with self.assertRaises(ValueError):
                self.issue(page,current,path,pin,lexical_presentation_rule=rule)
        # A sealed current record retaining as must not gain lexical authority.
        row=deepcopy(current['occurrences'][0]);row['target_range']=[0,2]
        bad=seal({**current,'occurrences':[row]})
        with self.assertRaises(ValueError):
            self.issue(page,bad,path,pin,lexical_presentation_rule=self.lexical_rule())


if __name__=='__main__':
    unittest.main()
