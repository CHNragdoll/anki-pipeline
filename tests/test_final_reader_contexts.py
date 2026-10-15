"""Context corrections must leave all physical and dictionary data unchanged."""
from copy import deepcopy
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from anki_pipeline import final_reader_contexts as fc
from anki_pipeline import source_confirmations as sc, residual_optimization as ro
from anki_pipeline import sense_frequency as sf, sense_display as sd, option_context as oc


def index(sid,text,chinese,span):
    chunks=[{'en':span,'zh':[[0,len(chinese)]],'relation':'equivalent'}]
    return {'id':sid,'paperId':':'.join(sid.split(':')[:2]),'paragraphId':sid.split(':new:')[0],
        'english':text,'englishHash':sf._sha(text),'translationZh':chinese,'translationHash':sf._sha(chinese),
        'sourceEnglish':text,'filledEnglish':text,'start':0,'end':len(text),'sourceHash':sf._sha(text),
        'reviewedContentHash':sf._sha(chinese+'\0'+json.dumps(chunks,ensure_ascii=False,separators=(',',':'))),
        'alignments':chunks,'sourceBlockIds':[sid.split(':new:')[0]]}


class Fixture:
    def __init__(self,root):
        self.root=Path(root);self.database=self.root/'candidate.sqlite3';self.protected=self.root/'protected.sqlite3'
        self.protected.write_bytes(b'untouched recovery source')
        fixture=json.loads((Path(__file__).parent/'fixtures/reading-display-projection-q30.json').read_text())
        self.parents=[];self.inputs={'revisions':{},'historical':{},'translations':{},'papers':{},'source_files':{},'full_paper_replay_counts':{}}
        for qid,key in fc.QUESTIONS.items():
            paper=qid.rsplit(':q-',1)[0];sid=qid+':A:new:0';spec=fc.fs.CASES[key]
            original=('What promoted the chancellor to develop his scheme?' if key=='prompted' else
                'Which of the following measures would be the Productivity Commission support?')
            a,b,text=spec['edit'];corrected=original[:a]+text+original[b:]
            oldstem=index(spec['sentence_id'],original,'原题干译文',[a,b] if key=='prompted' else [41,68])
            newstem=index(spec['sentence_id'],corrected,'原题干译文',[a,a+len(text)] if key=='prompted' else [38,65])
            rawtext='A desire to secure a better life for all.' if key=='prompted' else 'Enforcing employment protection laws.'
            span=[12,18] if key=='prompted' else [0,9];raw=index(sid,rawtext,'原选项译文',span)
            context={'sentenceId':sid,'paperId':paper,'questionId':qid,'answerNumber':'23' if key=='prompted' else '38',
                'candidateOptionLabel':'A','correctOptionLabel':'D','isCorrectCandidate':False,'answerSource':None,
                'optionSentenceIds':[sid],'optionParagraphId':raw['paragraphId'],'optionText':rawtext,'optionTextHash':raw['englishHash'],
                'stemSentenceRefs':oc._refs([oldstem]),'optionSentenceRefs':oc._refs([raw]),
                'structuredPaperHash':'a'*64,'originalQuestionEnglish':original,'questionEnglish':original,
                'originalQuestionChinese':oldstem['translationZh'],'hasQuestionBlank':False,
                'completedEnglish':original+'\n\n'+rawtext,'translationZh':'原题干译文。原选项译文。',
                'insertedRange':[len(original)+2,len(original)+2+len(rawtext.rstrip('.!?'))],
                'reviewedCompletionSentenceId':None,'indexFileHash':'b'*64,'reviewedInputHash':'b'*64,
                'reviewedTranslationHash':'b'*64,'reviewHash':'b'*64,'translationScope':'historical','newTranslationAuthored':True}
            context.update(englishHash=sf._sha(context['completedEnglish']),translationHash=sf._sha(context['translationZh']))
            self.inputs['historical'][sid]=deepcopy(context);self.inputs['translations'][sid]=context['translationZh']
            newcontext=deepcopy(context);newcontext.update(structuredPaperHash='c'*64,originalQuestionEnglish=corrected,
                questionEnglish=corrected,stemSentenceRefs=oc._refs([newstem]),completedEnglish=corrected+'\n\n'+rawtext,
                insertedRange=[len(corrected)+2,len(corrected)+2+len(rawtext.rstrip('.!?'))])
            oldsources=self.sources(raw,oldstem,context)
            self.inputs['papers'][paper]=self.sources(raw,newstem,newcontext)
            self.inputs['revisions'][key]={'caseKey':key,'paperId':paper,'sentenceId':oldstem['id'],
                'oldRecord':oldstem,'newRecord':newstem,'newStructuredPaperHash':'c'*64}
            for book in fc.BOOKS:
                row=deepcopy(fixture['entry']['row']);row.pop('display',None)
                row.update(paper_id=paper,year=int(paper.split(':')[1][:4]),sentence_id=sid,physical_source=[sid],
                    english=rawtext,english_hash=raw['englishHash'],translation=raw['translationZh'],translation_hash=raw['translationHash'],
                    target_range=span,translation_ranges=[[0,len(raw['translationZh'])]],alignment=raw['translation_alignment'],
                    alignment_evidence=[],reviewed_sense_id=None,assignment_context_hash=None,sense_index=0,
                    source='Reading Comprehension ➫ 选项A',source_provenance={'paragraphId':raw['paragraphId'],
                        'sourceHash':raw['sourceHash'],'reviewedContentHash':raw['reviewedContentHash'],
                        'sourcePathEvidence':{'kind':'answer_option','sourcePath':'Reading Comprehension',
                            'questionId':qid,'structuredPaperHash':'a'*64}},status='reviewed')
                row['occurrence_id']=fc.digest([paper,[sid],span])
                record={'book_id':book,'card_id':book+'-'+key,'word':'secure' if key=='prompted' else 'enforce',
                    'definition_source':'fixture','definition_provenance':deepcopy(fixture['entry']['definition_provenance']),
                    'senses':[{'pos':'v.','text':'原词典完整义项'}],'expected_occurrences':1}
                data=sf._definition(record);normal=sf._occurrence(row,data,require_binding=False)
                normal['display']=sd._display(normal,raw,[],oldsources,data['definition_provenance']['page_sha256'])
                sd.validate_display(normal['display'],normal,data['definition_provenance'])
                data['occurrences']=[normal];data['snapshot_id']=fc.digest(data);sc._identity(data)
                self.parents.append(data)
        with closing(sqlite3.connect(self.database)) as db:
            db.executescript(sf._SQL+'\nPRAGMA user_version=2;')
            for parent in self.parents:
                ro._insert(db,parent);db.execute('INSERT INTO active_snapshots VALUES(?,?,?)',
                    (parent['book_id'],parent['card_id'],parent['snapshot_id']))
            db.commit()
        rows=[{'book_id':p['book_id'],'card_id':p['card_id'],'snapshot_id':p['snapshot_id'],
            'word':p['word'],'occurrence_id':p['occurrences'][0]['occurrence_id'],'row_sha256':fc.digest(p['occurrences'][0])} for p in self.parents]
        counts={book:{sid:sum(p['book_id']==book and p['occurrences'][0]['sentence_id']==sid for p in self.parents)
            for sid in fc.OPTION_IDS} for book in fc.BOOKS}
        self.request={'schema':fc.REQUEST,'candidate':{'file':str(self.database),'stat':fc.stat_pin(self.database)},
            'protected':{'file':str(self.protected),'stat':fc.stat_pin(self.protected)},'expected_books':fc.BOOKS,
            'expected_cards':4,'expected_rows':4,'expected_option_rows_by_book':counts,
            'dependency_census':self.pin('census.json',{'rows':rows,'reading_display_projection_count':0})}
        self.inputs=fc.ContextInputs(fc._REPLAYED,self.inputs)

    def pin(self,name,value):
        return sc._write_json(self.root/name,value)

    @staticmethod
    def sources(raw,stem,context):
        for row in (raw,stem):
            row['translation_alignment']={'schema':'codex-sentence-alignment.v1','englishHash':row['englishHash'],
                'translationHash':row['translationHash'],'alignments':deepcopy(row['alignments'])};row['cloze_answers']=[]
        return {'sentences':{r['id']:deepcopy(r) for r in (raw,stem)},'options':{raw['id']:deepcopy(context)},
            'completions':{},'watched':{}}

    def prepare(self):
        self.request['scope']=self.pin('scope.json',fc.inspect_scope(self.request))
        return fc.prepare(self.request,artifact_root=self.root/'prepared')


class ContextTransactions(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.fx=Fixture(self.temp.name)
        self.mock=patch.object(fc,'load_inputs',return_value=self.fx.inputs);self.mock.start();self.addCleanup(self.mock.stop)

    @staticmethod
    def reseal(plan):
        plan['run_id']=fc.digest({k:v for k,v in plan.items() if k!='run_id'})

    def test_true_builder_exact_edit_chunks_and_target_shift(self):
        for parent in self.fx.parents:
            row=parent['occurrences'][0];projection=fc.derive_projection(row,parent,self.fx.inputs)
            view=fc.validate_projection(projection,row,parent,self.fx.request,self.fx.inputs)
            self.assertEqual(view['translation'],row['display']['translation'])
            self.assertNotIn('What promoted',view['english']);self.assertNotIn('would be the',view['english'])
            shift=0 if parent['word']=='secure' else -3
            self.assertEqual(view['target_range'],[v+shift for v in row['display']['target_range']])
            self.assertEqual(view['english'][slice(*view['target_range'])],row['english'][slice(*row['target_range'])])
            self.assertEqual(projection['original_row'],row)
            self.assertIn('anki-codex-review=',projection['context_source_jump'])

    def test_resealed_unapproved_projection_and_cn_change_rejected(self):
        parent=self.fx.parents[0];row=parent['occurrences'][0];projection=fc.derive_projection(row,parent,self.fx.inputs)
        projection['new_display']['english']+=' extra';projection['projection_sha256']=fc.digest({k:v for k,v in projection.items() if k!='projection_sha256'})
        with self.assertRaisesRegex(ValueError,'independent current reader replay'):
            fc.validate_projection(projection,row,parent,self.fx.request,self.fx.inputs)
        forged=deepcopy(row);forged['display']['translation']='篡改译文'
        with self.assertRaises(ValueError):fc.derive_projection(forged,parent,self.fx.inputs)

    def test_plain_or_mutated_replay_cache_rejected(self):
        parent=self.fx.parents[0];row=parent['occurrences'][0]
        with self.assertRaisesRegex(ValueError,'opaque independently replayed'):
            fc.derive_projection(row,parent,dict(self.fx.inputs))
        self.fx.inputs['papers'][row['paper_id']]['sentences'][row['sentence_id']]['alignments'].clear()
        with self.assertRaisesRegex(ValueError,'replay cache was modified'):
            fc.derive_projection(row,parent,self.fx.inputs)

    def test_real_failure_apply_idempotence_and_complete_rollback(self):
        plan=self.fx.prepare();before=self.fx.protected.read_bytes()
        with self.assertRaisesRegex(RuntimeError,'injected'):
            fc.apply(plan,root_write_approved=True,fail_after_cards=2)
        with closing(sc._connect(self.fx.database)) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM snapshots').fetchone()[0],4)
            self.assertEqual(fc.digest(sc._graph(db)),plan['active_graph_sha256'])
        plan['candidate_stat']=fc.stat_pin(self.fx.database);self.reseal(plan)
        fc.apply(plan,root_write_approved=True);self.assertTrue(fc.apply(plan,root_write_approved=True)['already_applied'])
        for card in plan['cards']:
            self.assertEqual(fc.payload(card)['occurrences'],fc.payload(card,True)['occurrences'])
        fc.rollback(plan,root_write_approved=True);self.assertTrue(fc.rollback(plan,root_write_approved=True)['already_rolled_back'])
        self.assertEqual(self.fx.protected.read_bytes(),before)
        with closing(sc._connect(self.fx.database)) as db:
            self.assertEqual(fc.digest(sc._graph(db)),plan['active_graph_sha256'])
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_third_book_ignored_in_census_and_rejected_by_validator(self):
        foreign=deepcopy(self.fx.parents[0]);foreign['book_id']='foreign';foreign['card_id']='foreign'
        foreign['snapshot_id']=fc.digest({k:v for k,v in foreign.items() if k!='snapshot_id'})
        with closing(sqlite3.connect(self.fx.database)) as db:
            ro._insert(db,foreign);db.execute('INSERT INTO active_snapshots VALUES(?,?,?)',('foreign','foreign',foreign['snapshot_id']));db.commit()
        self.fx.request['candidate']['stat']=fc.stat_pin(self.fx.database)
        scope=fc.inspect_scope(self.fx.request);self.assertEqual(len(scope['cards']),4)
        plan=self.fx.prepare();plan['cards'][0]['book_id']='foreign';self.reseal(plan)
        with self.assertRaisesRegex(ValueError,'foreign book'):fc._validate(plan)

    def test_scope_omission_resealed_and_raw_child_change_rejected(self):
        plan=self.fx.prepare();bad=deepcopy(plan);scope=ro.read_json(bad['request']['scope']);scope['rows'].pop()
        scope['scope_sha256']=fc.digest({k:v for k,v in scope.items() if k!='scope_sha256'})
        bad['request']['scope']=self.fx.pin('omitted-scope.json',scope);self.reseal(bad)
        with self.assertRaisesRegex(ValueError,'scope repeats or lacks'):fc._validate(bad)
        bad=deepcopy(plan);card=bad['cards'][0];after=fc.payload(card);after['occurrences'][0]['reason']+=' unauthorized'
        after['snapshot_id']=fc.digest({k:v for k,v in after.items() if k!='snapshot_id'})
        card['payload_file']=self.fx.pin('forged-after.json',after);card['payload_sha256']=fc.digest(after);card['child_snapshot_id']=after['snapshot_id']
        bad['source_files'][card['payload_file']['file']]=card['payload_file']['sha256'];self.reseal(bad)
        with self.assertRaisesRegex(ValueError,'beyond new policy'):fc._validate(bad)

    def test_inline_payload_cannot_shadow_verified_export(self):
        plan=self.fx.prepare();plan['cards'][0]['payload']=fc.payload(plan['cards'][0])
        self.reseal(plan)
        with self.assertRaisesRegex(ValueError,'only file-backed complete payloads'):fc._validate(plan)

    def test_later_snapshot_prevents_rollback(self):
        plan=self.fx.prepare();fc.apply(plan,root_write_approved=True)
        with closing(sqlite3.connect(self.fx.database)) as db:
            card=plan['cards'][0];child=fc.payload(card);child['exam_usage_policy']['later']='actual successor'
            child['snapshot_id']=fc.digest({k:v for k,v in child.items() if k!='snapshot_id'})
            ro._insert(db,child);db.execute('UPDATE active_snapshots SET snapshot_id=? WHERE book_id=? AND card_id=?',
                (child['snapshot_id'],card['book_id'],card['card_id']));db.commit()
        with self.assertRaisesRegex(ValueError,'overwrite later graph'):fc.rollback(plan,root_write_approved=True)


class ReaderContextGuards(unittest.TestCase):
    def test_current_question_scope_is_exact(self):
        self.assertEqual(set(fc.QUESTIONS), {'kaoyan:2014-01:q-23-1', 'kaoyan:2022-01:q-38-1'})
        self.assertEqual(len(fc.OPTION_IDS), 8)

    def test_path_key_cache_fingerprint_and_collision_guard(self):
        value={'source_files':{},'papers':{'watched':{Path('/fixture/path'):'hash'}}}
        cache=fc.ContextInputs(fc._REPLAYED,value);self.assertEqual(cache.unchanged(),value)
        cache['papers']['watched'][Path('/fixture/path')]='forged'
        with self.assertRaisesRegex(ValueError,'cache was modified'):cache.unchanged()
        with self.assertRaisesRegex(ValueError,'path-key collision'):
            fc.ContextInputs(fc._REPLAYED,{'source_files':{},'watched':{Path('/p'):'a','/p':'b'}})

    def test_reader_sidecar_rejected_even_when_main_database_stat_unchanged(self):
        with tempfile.TemporaryDirectory() as root:
            database=Path(root)/'reader.sqlite3';database.write_bytes(b'fixture database')
            before=fc.stat_pin(database)
            cache=fc.ContextInputs(fc._REPLAYED,{'source_files':{}},{str(database):before})
            for suffix in ('-wal','-shm','-journal'):
                sidecar=Path(str(database)+suffix);sidecar.write_bytes(b'')
                self.assertEqual(fc.stat_pin(database),before)
                with self.assertRaisesRegex(ValueError,'SQLite sidecar'):cache.unchanged()
                sidecar.unlink()
            cache.unchanged()

    def test_child_only_changes_context_policy_and_identity(self):
        parent = {'book_id':'redbook','card_id':'fixture','snapshot_id':'parent',
                  'occurrences':[{'occurrence_id':'o','display':{'english':'old'}}],
                  'senses':[{'text':'native'}], 'expected_occurrences':1,
                  'exam_usage_policy':{'earlier':{'full':'history'}}}
        projection = {'o':{'schema':fc.PROJECTION, 'projection_sha256':'fixture'}}
        before = deepcopy(parent)
        child = fc.build_child(parent, projection)
        self.assertEqual(parent, before)
        self.assertEqual(child['occurrences'], parent['occurrences'])
        self.assertEqual(child['senses'], parent['senses'])
        self.assertEqual(child['expected_occurrences'], parent['expected_occurrences'])
        self.assertEqual(child['exam_usage_policy']['earlier'], parent['exam_usage_policy']['earlier'])
        self.assertEqual(child['exam_usage_policy']['final_reader_contexts']['projections'], projection)
        self.assertEqual(child['snapshot_id'], sc.digest({k:v for k,v in child.items() if k!='snapshot_id'}))


if __name__ == '__main__':
    unittest.main()
