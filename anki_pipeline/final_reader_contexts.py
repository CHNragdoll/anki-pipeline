"""Persist corrected reading stems without rewriting physical occurrences.

The old certified display remains immutable. A separately replayed, explicitly
corrected context is sealed in the child policy, with its complete inverse.
"""
from __future__ import annotations
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
from urllib.parse import urlencode

from . import source_confirmations as sc, residual_optimization as ro
from . import final_source_corrections as fs, sense_frequency as sf
from . import reading_display_projection as rdp, sense_display as sd
from . import option_context as oc, option_translation as ot, codex_exam_index as ci
from .store import utc_now

ROOT = Path(__file__).resolve().parents[1]
OWNED = ROOT / 'output/eleven-resolution-20261014/context-apply-own'
BOOKS = ['redbook', 'redbook2027']
REQUEST = 'final-reader-contexts-request.v1'
SCOPE = 'final-reader-contexts-scope.v1'
PLAN = 'final-reader-contexts-plan.v1'
PROJECTION = 'final-reader-context-projection.v1'
RECEIPT = 'final-reader-contexts-receipt.v1'
QUESTIONS = {'kaoyan:2014-01:q-23-1':'prompted', 'kaoyan:2022-01:q-38-1':'be'}
OPTION_IDS = [qid+':'+label+':new:0' for qid in QUESTIONS for label in 'ABCD']
canonical, digest, require, stat_pin = sc.canonical, sc.digest, sc.require, sc.stat_pin
payload = fs.payload
_DDL = (
 'CREATE TABLE IF NOT EXISTS final_reader_context_runs(run_id TEXT PRIMARY KEY,plan_sha256 TEXT NOT NULL,state TEXT NOT NULL,created_at TEXT NOT NULL)',
 'CREATE TABLE IF NOT EXISTS final_reader_context_cards(run_id TEXT NOT NULL REFERENCES final_reader_context_runs(run_id),book_id TEXT NOT NULL,card_id TEXT NOT NULL,parent_snapshot_id TEXT NOT NULL REFERENCES snapshots(id),child_snapshot_id TEXT NOT NULL REFERENCES snapshots(id),inverse_sha256 TEXT NOT NULL,PRIMARY KEY(run_id,book_id,card_id))',
)
_REPLAYED = object()


def _fingerprint_value(value):
    if isinstance(value,dict):
        result={}
        for key,part in value.items():
            key=str(key) if isinstance(key,Path) else key
            require(key not in result, 'replay cache path-key collision')
            result[key]=_fingerprint_value(part)
        return result
    if isinstance(value,list):return [_fingerprint_value(part) for part in value]
    return str(value) if isinstance(value,Path) else value


class ContextInputs(dict):
    """Opaque replay result; caller edits or later source drift fail closed."""
    def __init__(self,token,value,extra_stats=None):
        require(token is _REPLAYED, 'context inputs must be independently replayed')
        super().__init__(value)
        self._content_sha256=digest(_fingerprint_value(value))
        self._stats={file:stat_pin(file) for file in value['source_files']}
        self._reader_databases=list(extra_stats or {})
        for file,pin in (extra_stats or {}).items():
            require(stat_pin(file)==pin, 'context replay extra source stat differs')
            self._stats[file]=dict(pin)

    def unchanged(self):
        require(digest(_fingerprint_value(self))==self._content_sha256, 'context replay cache was modified')
        for file in self._reader_databases:
            require(not any(Path(file+suffix).exists() for suffix in ('-wal','-shm','-journal')),
                'context live reader database acquired a SQLite sidecar')
        for file,pin in self._stats.items():
            require(stat_pin(file)==pin, 'context replay source changed: '+file)
        return self


def _boundary(request):
    require(request.get('schema')==REQUEST, 'context request schema differs')
    candidate=Path(request['candidate']['file']).resolve(strict=True)
    protected=Path(request['protected']['file']).resolve(strict=True)
    require(candidate!=protected and not candidate.samefile(protected), 'protected DB or inode alias rejected')
    require(stat_pin(protected)==request['protected']['stat'], 'protected database changed')
    require(sorted(request['expected_books'])==BOOKS, 'exact two books required')
    return candidate


def _historical(request, files):
    """Replay the historical CN acceptance, never claim it reviewed new English."""
    registry=ro.read_json(request['historical_registry'])
    require(registry.get('schema')=='reading-option-context-review.v1', 'historical registry schema differs')
    report={'manifest_sha256':registry['indexManifestHash'],
        'input_manifest_sha256':registry['inputManifestHash'],'source_files':{}}
    for context in registry['rows']:
        name=context['paperId'].split(':')[1]+'.json'
        for field,directory in (('indexFileHash','index'),('reviewedInputHash','inputs'),('reviewedTranslationHash','translations'),('reviewHash','reviews')):
            key=directory+'/'+name
            require(key not in report['source_files'] or report['source_files'][key]==context[field], 'historical source pins conflict')
            report['source_files'][key]=context[field]
    pin=request['historical_translations'];ro.read_pin(pin)
    translations,watched,_=ot.load_option_translations(Path(pin['file']),registry['rows'],report)
    require(request['historical_registry']['sha256']==registry.get('sourceRegistrySha256',request['historical_registry']['sha256']), 'historical registry identity differs')
    sidecar=ro.read_json(pin)
    require(sidecar['sourceRegistrySha256']==request['historical_registry']['sha256'], 'historical translation registry binding differs')
    files.update({str(path.resolve()):value for path,value in watched.items()})
    files[request['historical_registry']['file']]=request['historical_registry']['sha256']
    contexts={c['sentenceId']:c for c in registry['rows'] if c['questionId'] in QUESTIONS}
    require(set(contexts)==set(OPTION_IDS) and set(OPTION_IDS)<=set(translations), 'all eight approved old candidates required')
    return contexts,{sid:translations[sid] for sid in OPTION_IDS}


def _current_paper(request,paper_id,revisions,files):
    """Independent full-paper replay, with only pinned history extras allowed."""
    root=Path(request['replay']['exam_root']).resolve(strict=True)
    staging=Path(request['replay']['staging']).resolve(strict=True);watched={}
    manifest,msha=rdp.read_materialized(staging/'index/manifest.json',watched)
    inventory,isha=rdp.read_materialized(staging/'manifest.json',watched)
    require(manifest.get('schema')=='codex-exam-sentence-index-manifest.v1' and manifest.get('scope')=='full'
        and manifest.get('semanticReviewStatus')=='approved' and manifest['inputManifestHash']==isha
        and inventory.get('schema')=='codex-exam-translation-manifest.v1', 'complete current approved manifest differs')
    for document,keys in ((manifest,ci._COUNT_FIELDS),(inventory,ci._INPUT_COUNTS)):
        records=ci._rows(document['papers'],'complete paper inventory')
        require(len(records)==len(ci._PAPER_IDS) and {v['paperId'] for v in records}==ci._PAPER_IDS, 'complete paper identities differ')
        for row in records:ci._counts(row,keys,'complete inventory')
        totals={key:sum(row[key] for row in records) for key in keys}
        if document is manifest:totals['papers']=len(records)
        require(document['totals']==totals, 'complete inventory totals differ')
    entry=next(row for row in manifest['papers'] if row['paperId']==paper_id)
    native=next(row for row in inventory['papers'] if row['paperId']==paper_id)
    name=paper_id.split(':')[1]
    require(entry['indexFile']==name+'.json' and entry['semanticReviewStatus']=='approved'
        and native['file']=='inputs/'+name+'.json', 'approved paper path/approval differs')
    values,source_files={},{}
    for lane,field in (('inputs','inputHash'),('translations','translationHash'),('reviews','reviewHash'),('index','indexHash')):
        value,checksum=rdp.read_materialized(staging/lane/(name+'.json'),watched)
        require(checksum==entry[field], 'current approved paper bytes differ: '+lane)
        values[lane]=value;source_files[lane+'/'+name+'.json']=checksum
    review=values['reviews']
    require(native['sha256']==entry['inputHash'] and values['inputs']['paperId']==paper_id
        and review.get('schema')=='codex-exam-translation-review.v1' and review.get('approved') is True
        and review.get('issues')==[] and review.get('paperId')==paper_id
        and review['inputHash']==entry['inputHash'] and review['translationHash']==entry['translationHash']
        and bool(review.get('method')), 'current paper independent review differs')
    expected,answers,counts=ci._expected_sentences(values['inputs'],values['translations'])
    index=values['index']
    require(set(index)=={'schema','paperId','sentences'} and index['schema']=='codex-exam-sentence-index.v1'
        and index['paperId']==paper_id and len(expected)==len(index['sentences']), 'current full paper index shape differs')
    revised={pair['newRecord']['id']:pair['newRecord'] for meta in revisions.values()
        for pair in meta['paragraphAffectedRecords'] if meta['paperId']==paper_id}
    for actual,replayed in zip(index['sentences'],expected):
        extra=actual.get('sourceCorrectionHistory')
        require({k:v for k,v in actual.items() if k!='sourceCorrectionHistory'}==replayed,
            'current index differs from full independent expected_sentence replay')
        if extra is not None:
            require(actual['id'] in revised and actual==revised[actual['id']], 'unapproved source history extra in current index')
    require(all(entry[k]==counts[k] for k in counts) and all(native[k]==counts[k] for k in ('paragraphs','sentences','blocked'))
        and native['sourceParagraphs']==counts['paragraphs'] and type(review['reviewedSentences']) is int
        and type(review['reviewedAlignments']) is int and review['reviewedSentences']==counts['sentences']
        and review['reviewedAlignments']==counts['alignments'], 'full paper coverage counts differ')
    sentences=[{**row,'cloze_answers':answers[row['id']],'translation_alignment':{
        'schema':'codex-sentence-alignment.v1','englishHash':row['englishHash'],
        'translationHash':row['translationHash'],'alignments':deepcopy(row['alignments'])}} for row in index['sentences']]
    qid=next(q for q in QUESTIONS if q.startswith(paper_id+':'));meta=revisions[QUESTIONS[qid]]
    require(next(row for row in index['sentences'] if row['id']==meta['sentenceId'])==meta['newRecord'], 'live corrected stem differs from finalized reader')
    ids={pair['newRecord']['id'] for pair in meta['paragraphAffectedRecords']}
    selected=[row for row in sentences if row['id'] in ids or row['context'].get('questionId')==qid]
    require({row['id'] for row in selected if row['kind']=='answer_option'}=={sid for sid in OPTION_IDS if sid.startswith(qid+':')}, 'eight current option source identity closure differs')
    structured=root/'data/sources/exam-library/structured/papers/kaoyan'/(name+'.json')
    _,checksum=rdp.read_materialized(structured,watched)
    require(checksum==meta['newStructuredPaperHash'], 'live structured paper differs from correction')
    report={'manifest_sha256':msha,'input_manifest_sha256':isha,'source_files':source_files}
    options,option_watched,_,_=oc.prepare_option_contexts(root,selected,report,{})
    watched.update({str(path.resolve()):value for path,value in option_watched.items()})
    files.update(watched)
    return {'sentences':{row['id']:row for row in selected},'options':options,'completions':{},
        'watched':{Path(path):value for path,value in watched.items()}},counts


def load_inputs(request):
    _boundary(request);files={};fs._reader_guard(request,files)
    source=ro.read_json(request['source_revisions'])
    require(source.get('schema')=='confirmed-reader-source-revisions.v1', 'reader revisions schema differs')
    revisions={r['caseKey']:r for r in source['records']}
    require(set(revisions)==set(fs.CASES) and len(source['records'])==5, 'finalized exact source5 revisions required')
    files[request['source_revisions']['file']]=request['source_revisions']['sha256']
    for key in QUESTIONS.values():
        meta=revisions[key];old,new=meta['oldRecord'],meta['newRecord'];a,b,text=fs.CASES[key]['edit']
        require(meta['sentenceId']==old['id']==new['id']==fs.CASES[key]['sentence_id'] and
            new['english']==old['english'][:a]+text+old['english'][b:] and old['translationZh']==new['translationZh'], 'exact authorized stem correction differs')
        fs._index(old);fs._index(new)
        history=new['sourceCorrectionHistory']
        require(len(history)==1 and history[0]['originalRecord']==old and history[0]['correctedEnglish']==new['english']
            and history[0]['confirmation']['authority']=='direct_user_confirmation', 'full approved stem inverse missing')
        ro.read_pin({'file':history[0]['confirmationFile'],'sha256':history[0]['confirmationSha256']})
        files[history[0]['confirmationFile']]=history[0]['confirmationSha256']
    historical,translations=_historical(request,files)
    papers={};coverage={}
    for paper in sorted({qid.rsplit(':q-',1)[0] for qid in QUESTIONS}):
        papers[paper],coverage[paper]=_current_paper(request,paper,revisions,files)
    for sid,old in historical.items():
        qid=old['questionId'];meta=revisions[QUESTIONS[qid]];current=papers[old['paperId']]['options'][sid]
        require(old['questionEnglish']==meta['oldRecord']['english'] and current['questionEnglish']==meta['newRecord']['english']
            and old['originalQuestionChinese']==current['originalQuestionChinese'] and not old['hasQuestionBlank']
            and not current['hasQuestionBlank'], 'exact old/current stem grammar or Chinese differs')
        for field in ('optionText','optionTextHash','optionSentenceRefs','optionSentenceIds','optionParagraphId','candidateOptionLabel',
            'correctOptionLabel','isCorrectCandidate','answerSource','reviewedCompletionSentenceId'):
            require(old[field]==current[field], 'unchanged physical option/answer metadata differs: '+field)
        current['translationZh']=translations[sid];current['translationHash']=sf._sha(translations[sid])
        current['translationScope']='source_corrected_reuse_of_independently_reviewed_complete_candidate_translation'
        current['newTranslationAuthored']=False
        current['translation_alignment']=oc._context_chunks(current,papers[old['paperId']]['sentences'])
    review=ro.read_json(request['reader_binding']['review_inputs'])
    return ContextInputs(_REPLAYED,{'revisions':revisions,'historical':historical,'translations':translations,'papers':papers,
        'source_files':files,'full_paper_replay_counts':coverage},
        {review['database']['path']:request['reader_binding']['database_stat']})


def _display_dependency(row):
    display=row.get('display')
    return display is not None and display.get('derivation_payload',{}).get('questionId') in QUESTIONS


def inspect_scope(request):
    candidate=_boundary(request);inputs=load_inputs(request)
    if request['candidate'].get('stat'):require(stat_pin(candidate)==request['candidate']['stat'], 'candidate changed before census')
    with closing(sc._connect(candidate)) as db:
        graph=sc._graph(db)
        query=('SELECT x.book_id,x.card_id,x.snapshot_id,s.word,o.occurrence_id,o.sentence_id FROM active_snapshots x '
            'CROSS JOIN occurrences o INDEXED BY sqlite_autoindex_occurrences_1 ON o.snapshot_id=x.snapshot_id '
            'JOIN snapshots s ON s.id=x.snapshot_id WHERE x.book_id IN (?,?) AND o.sentence_id IN ('+
            ','.join('?' for _ in OPTION_IDS)+') ORDER BY x.book_id,x.card_id,o.occurrence_id')
        dependencies=[];cards={};matches={}
        for item in db.execute(query,[*BOOKS,*OPTION_IDS]):
            matches.setdefault((item['book_id'],item['card_id'],item['snapshot_id']),[]).append(dict(item))
        for (book,card,snapshot),items in matches.items():
            saved=db.execute('SELECT payload FROM snapshots WHERE id=?',(snapshot,)).fetchone()
            rows={r['occurrence_id']:r for r in json.loads(saved[0])['occurrences']}
            for item in items:
                row=rows[item['occurrence_id']]
                if not _display_dependency(row):continue
                key=book,card;cards[key]={k:item[k] for k in ('book_id','card_id','snapshot_id','word')}
                display=row['display'];sid=row['sentence_id'];historical=inputs['historical'][sid]
                require(display['provenance']['derivation']=='option_context' and display['derivation_payload']['questionEnglish']==historical['questionEnglish'], 'current parent is not exact old stem display')
                dependencies.append({k:item[k] for k in ('book_id','card_id','snapshot_id','word','occurrence_id','sentence_id')} |
                    {'row_sha256':digest(row),'original_display_sha256':digest(display),'question_id':historical['questionId']})
    require(len(dependencies)==request['expected_rows'] and len(cards)==request['expected_cards'], 'finite context dependency count differs')
    counts={book:{sid:sum(r['book_id']==book and r['sentence_id']==sid for r in dependencies) for sid in OPTION_IDS} for book in BOOKS}
    require(counts==request['expected_option_rows_by_book'], 'all eight candidate dependency counts differ')
    census=ro.read_json(request['dependency_census'])
    actual={(r['book_id'],r['card_id'],r['occurrence_id'],r['snapshot_id'],r['row_sha256']) for r in dependencies}
    require(actual=={(r['book_id'],r['card_id'],r['occurrence_id'],r['snapshot_id'],r['row_sha256']) for r in census['rows']}, 'independent all active display census differs')
    require(census['reading_display_projection_count']==0, 'additional policy-only dependency must be included explicitly')
    result={'schema':SCOPE,'candidate':str(candidate),'candidate_stat':stat_pin(candidate),'active_graph_sha256':digest(graph),
        'cards':sorted(cards.values(),key=lambda r:(r['book_id'],r['card_id'])),'rows':dependencies,
        'expected_option_rows_by_book':counts,'expected_cards':len(cards),'expected_rows':len(dependencies),
        'physical_count_delta_by_book':{book:0 for book in BOOKS},'full_paper_replay_counts':inputs['full_paper_replay_counts']}
    result['scope_sha256']=digest(result);return result


def derive_projection(row,parent,inputs):
    require(isinstance(inputs,ContextInputs), 'opaque independently replayed context inputs required')
    inputs.unchanged()
    require(parent['book_id'] in BOOKS and row['sentence_id'] in OPTION_IDS, 'foreign book or source in context projection')
    display=row['display'];sd.validate_display(display,row,parent['definition_provenance'])
    sid=row['sentence_id'];old=inputs['historical'][sid];key=QUESTIONS[old['questionId']];meta=inputs['revisions'][key]
    require(display['provenance']['derivation']=='option_context' and
        all(display['derivation_payload'].get(k)==old[k] for k in ot._SOURCE_FIELDS), 'old display grammar/source certificate differs from accepted historical registry')
    require(display['translation']==inputs['translations'][sid] and display['derivation_payload']['translationZh']==inputs['translations'][sid], 'accepted composite CN was changed')
    sources=inputs['papers'][row['paper_id']]
    ephemeral=deepcopy(row);ephemeral['source_provenance']['sourcePathEvidence']['structuredPaperHash']=meta['newStructuredPaperHash']
    source=sd._source_row(ephemeral,sources)
    new=sd._display(ephemeral,source,[],sources,parent['definition_provenance']['page_sha256'])
    sd.validate_display(new,ephemeral,parent['definition_provenance'])
    a,b,text=fs.CASES[key]['edit']
    require(new['english']==display['english'][:a]+text+display['english'][b:] and new['translation']==display['translation'], 'regenerated composite exceeds authorized stem-only edit')
    delta=len(text)-(b-a)
    require(new['target_range']==[v+delta for v in display['target_range']] and
        new['english'][slice(*new['target_range'])]==row['english'][slice(*row['target_range'])], 'new display target no longer exact raw option token')
    stem=meta['newRecord'];params={'anki-codex-sentence':stem['id'],'anki-codex-hash':stem['englishHash'],
        'anki-codex-review':stem['reviewedContentHash'],'anki-codex-en':canonical([[0,len(stem['english'])]])}
    context_jump='http://localhost:8765/english-exams-reflow-latex/kaoyan/papers/'+row['paper_id'].split(':')[1]+'.htm?'+urlencode(params)
    result={'schema':PROJECTION,'book_id':parent['book_id'],'card_id':parent['card_id'],'word':parent['word'],
        'occurrence_id':row['occurrence_id'],'parent_snapshot_id':parent['snapshot_id'],
        'label':'用户已确认题干校正；展示派生于现行已核阅读器，原印题干与旧合成证书完整保留。',
        'original_row':deepcopy(row),'original_row_sha256':digest(row),'original_display':deepcopy(display),
        'original_display_sha256':digest(display),'physical_row_sha256':rdp.physical_row_sha256(row),
        'current_source_revision':deepcopy(meta),'current_source_files':deepcopy(inputs['source_files']),
        'ephemeral_authority_row':ephemeral,'ephemeral_authority_delta':{'source_provenance.sourcePathEvidence.structuredPaperHash':meta['newStructuredPaperHash']},
        'historical_translation_acceptance':{'registry_context':deepcopy(old),'translation':inputs['translations'][sid],
            'scope':'old English independently reviewed; unchanged Chinese reused for exact owner-confirmed stem correction'},
        'new_display':new,'new_view':deepcopy(new),'context_source_jump':context_jump,
        'raw_option_source_jump':deepcopy(display['provenance'].get('native_jump')),
        'builder_proof':{'method':'current full expected_sentences + option_context.prepare_option_contexts + sense_display._display/validate_display',
            'full_paper_replay_counts':deepcopy(inputs['full_paper_replay_counts']),
            'old_english':display['english'],'new_english':new['english'],'stem_edit':[a,b,text],
            'fine_chunks':'current reviewed stem and unchanged option sources; exact codepoint projection',
            'raw_occurrence_and_dictionary_changed':False,'physical_count_delta':0}}
    result['projection_sha256']=digest(result);return result


def validate_projection(projection,row,parent,request,inputs=None):
    require(projection.get('schema')==PROJECTION and projection.get('projection_sha256')==digest({k:v for k,v in projection.items() if k!='projection_sha256'}), 'context projection seal differs')
    inputs=inputs or load_inputs(request)
    require(projection==derive_projection(row,parent,inputs), 'context projection differs from independent current reader replay')
    return deepcopy(projection['new_display'])


def build_child(parent,projections):
    require('final_reader_contexts' not in parent.get('exam_usage_policy',{}), 'context lane already present')
    child=dict(parent);child['exam_usage_policy']=dict(parent.get('exam_usage_policy',{}))
    child['exam_usage_policy']['final_reader_contexts']={'schema':'final-reader-context-card.v1',
        'parent_snapshot_id':parent['snapshot_id'],'projections':deepcopy(projections),
        'physical_occurrences_unchanged':True,'dictionary_and_counts_unchanged':True}
    child['snapshot_id']=digest({k:v for k,v in child.items() if k!='snapshot_id'})
    return child


def prepare(request,*,artifact_root,progress=None):
    candidate=_boundary(request);inputs=load_inputs(request);scope=ro.read_json(request['scope'])
    require(scope==inspect_scope(request), 'pinned context scope differs')
    output=Path(artifact_root).resolve();require(not output.exists(), 'fresh context preparation directory required');output.mkdir(parents=True)
    files=dict(inputs['source_files']);files[request['scope']['file']]=request['scope']['sha256']
    files[request['dependency_census']['file']]=request['dependency_census']['sha256']
    cards=[];operations=[]
    with closing(sc._connect(candidate)) as db:
        graph=sc._graph(db)
        for n,ref in enumerate(scope['cards'],1):
            parent=sc._read_parent(db,ref['book_id'],ref['card_id'],ref['snapshot_id'])
            selected={r['occurrence_id']:r for r in scope['rows'] if (r['book_id'],r['card_id'])==(ref['book_id'],ref['card_id'])}
            projections={}
            for row in parent['occurrences']:
                if row['occurrence_id'] not in selected:continue
                require(digest(row)==selected[row['occurrence_id']]['row_sha256'], 'complete parent dependency differs')
                projections[row['occurrence_id']]=derive_projection(row,parent,inputs)
            require(set(projections)==set(selected), 'complete dependent row coverage differs')
            child=build_child(parent,projections);sc._identity(child)
            card={k:ref[k] for k in ('book_id','card_id','word')}
            card.update(created=False,parent_snapshot_id=parent['snapshot_id'],child_snapshot_id=child['snapshot_id'],
                before_payload_sha256=digest(parent),payload_sha256=digest(child),before_payload=parent,payload=child,
                original_count=parent['expected_occurrences'],new_count=child['expected_occurrences'],display_projections=projections,new_definitions=[])
            fs._export_card(card,output,files);cards.append(card)
            operations.extend({'book_id':ref['book_id'],'card_id':ref['card_id'],'occurrence_id':oid,
                'question_id':p['original_display']['derivation_payload']['questionId'],'action':'persist_corrected_reader_context',
                'old_display_sha256':p['original_display_sha256'],'new_display_sha256':p['new_display']['display_hash']} for oid,p in projections.items())
            if progress:progress({'stage':'complete_parent_export','completed':n,'total':len(scope['cards'])})
    child_ids={(c['book_id'],c['card_id']):c['child_snapshot_id'] for c in cards}
    child_graph=[[book,card,child_ids.get((book,card),sid)] for book,card,sid in graph]
    for module in (__file__,sc.__file__,fs.__file__,ro.__file__,sf.__file__,rdp.__file__,sd.__file__,oc.__file__,ot.__file__,ci.__file__):
        files[str(Path(module).resolve())]=digest(Path(module).read_bytes())
    require(stat_pin(candidate)==scope['candidate_stat'], 'candidate changed during context prepare')
    plan={'schema':PLAN,'request':deepcopy(request),'candidate':str(candidate),'candidate_stat':scope['candidate_stat'],
        'protected':deepcopy(request['protected']),'active_graph_sha256':digest(graph),'child_graph_sha256':digest(child_graph),
        'cards':cards,'source_files':files,'summary':{'cards':len(cards),'created_cards':0,'context_rows':len(operations),
            'physical_count_delta_by_book':{b:0 for b in BOOKS},'raw_occurrences_unchanged':True,'definitions_unchanged':True,
            'reader_files_modified':False,'operations':operations}}
    plan['run_id']=digest(plan);return plan


def _validate(plan):
    require(plan.get('schema')==PLAN and plan['run_id']==digest({k:v for k,v in plan.items() if k!='run_id'}), 'context plan seal differs')
    candidate=_boundary(plan['request']);require(str(candidate)==plan['candidate'] and plan['protected']==plan['request']['protected'], 'plan boundary differs')
    require(all(c['book_id'] in BOOKS and c['created'] is False for c in plan['cards']), 'foreign book or new card in context lane')
    leafs={c[field]['file'] for c in plan['cards'] for field in ('payload_file','before_payload_file')}
    for file,sha in plan['source_files'].items():
        if file not in leafs:ro.read_pin({'file':file,'sha256':sha})
    inputs=load_inputs(plan['request']);scope=ro.read_json(plan['request']['scope'])
    require(scope.get('schema')==SCOPE and scope.get('scope_sha256')==digest({k:v for k,v in scope.items() if k!='scope_sha256'}), 'context scope content seal differs')
    require(scope['expected_cards']==plan['request']['expected_cards'] and scope['expected_rows']==plan['request']['expected_rows']
        and scope['expected_option_rows_by_book']==plan['request']['expected_option_rows_by_book'], 'request/scope exact dependency partition differs')
    require(len(scope['rows'])==scope['expected_rows'] and len(scope['cards'])==scope['expected_cards']
        and len({(r['book_id'],r['card_id'],r['occurrence_id']) for r in scope['rows']})==len(scope['rows']), 'scope repeats or lacks a dependency')
    counts={book:{sid:sum(r['book_id']==book and r['sentence_id']==sid for r in scope['rows']) for sid in OPTION_IDS} for book in BOOKS}
    require(counts==scope['expected_option_rows_by_book'] and all(r['book_id'] in BOOKS for r in scope['rows']), 'scope option/book partition differs')
    census=ro.read_json(plan['request']['dependency_census'])
    require(census['reading_display_projection_count']==0 and
        {(r['book_id'],r['card_id'],r['occurrence_id'],r['snapshot_id'],r['row_sha256']) for r in scope['rows']}==
        {(r['book_id'],r['card_id'],r['occurrence_id'],r['snapshot_id'],r['row_sha256']) for r in census['rows']}, 'scope differs from independent complete active display census')
    require(len(plan['cards'])==scope['expected_cards'] and len(plan['cards'])==plan['summary']['cards'], 'complete context card scope differs')
    require({(c['book_id'],c['card_id'],c['parent_snapshot_id']) for c in plan['cards']}==
        {(c['book_id'],c['card_id'],c['snapshot_id']) for c in scope['cards']}, 'exact parent identity scope differs')
    seen=set()
    for card in plan['cards']:
        require('payload' not in card and 'before_payload' not in card, 'context plan requires only file-backed complete payloads')
        require(card['before_payload_file']['sha256']==card['before_payload_sha256'] and
            card['payload_file']['sha256']==card['payload_sha256'], 'full context backup leaf pin differs')
        # payload() verifies every complete export byte hash. Parent identity
        # plus exact build_child equality below cover both snapshot seals.
        before,after=payload(card,True),payload(card);sc._identity(before)
        require((before['book_id'],before['card_id'],before['snapshot_id'])==(card['book_id'],card['card_id'],card['parent_snapshot_id'])
            and after['snapshot_id']==card['child_snapshot_id'], 'context child/parent identity differs')
        for field in ('payload_file','before_payload_file'):
            require(plan['source_files'].get(card[field]['file'])==card[field]['sha256'], 'full export source pin omitted')
        originals={r['occurrence_id']:r for r in before['occurrences']}
        selected={r['occurrence_id']:r for r in scope['rows'] if (r['book_id'],r['card_id'])==(card['book_id'],card['card_id'])}
        complete={oid for oid,row in originals.items() if row['sentence_id'] in OPTION_IDS and _display_dependency(row)}
        require(complete==set(selected), 'exported full parent dependency census differs')
        require(set(card['display_projections'])==set(selected), 'complete context row scope differs')
        for oid,projection in card['display_projections'].items():
            require(digest(originals[oid])==selected[oid]['row_sha256'], 'complete old context row differs')
            validate_projection(projection,originals[oid],before,plan['request'],inputs)
            seen.add((card['book_id'],card['card_id'],oid))
        require(after==build_child(before,card['display_projections']), 'context snapshot changed beyond new policy')
        require(card['original_count']==card['new_count']==before['expected_occurrences']==after['expected_occurrences'], 'physical counts changed')
    require(len(seen)==scope['expected_rows']==plan['summary']['context_rows'] and
        plan['summary']['physical_count_delta_by_book']=={b:0 for b in BOOKS}, 'zero delta or complete dependency closure differs')
    return candidate


def _receipt(plan,*,already=False,rollback=False):
    return {'schema':RECEIPT,'run_id':plan['run_id'],'database':{'file':plan['candidate'],'stat':stat_pin(plan['candidate'])},
        'state':'rolled_back' if rollback else 'applied','already_applied':already and not rollback,
        'already_rolled_back':already and rollback,'summary':plan['summary']}


def apply(plan,*,root_write_approved=False,fail_after_cards=None):
    require(root_write_approved is True, 'explicit ROOT context write approval required');candidate=_validate(plan)
    with closing(sc._connect(candidate,write=True)) as db:
        db.execute('BEGIN IMMEDIATE')
        try:
            for ddl in _DDL:db.execute(ddl)
            previous=db.execute('SELECT plan_sha256,state FROM final_reader_context_runs WHERE run_id=?',(plan['run_id'],)).fetchone()
            if previous:
                require(tuple(previous)==(digest(plan),'applied') and digest(sc._graph(db))==plan['child_graph_sha256'], 'existing context run or graph differs')
                for card in plan['cards']:ro._reconcile(db,payload(card))
                db.rollback();return _receipt(plan,already=True)
            require(stat_pin(candidate)==plan['candidate_stat'] and digest(sc._graph(db))==plan['active_graph_sha256'], 'current complete parent graph/stat changed')
            db.execute('INSERT INTO final_reader_context_runs VALUES(?,?,?,?)',(plan['run_id'],digest(plan),'applied',utc_now()))
            for n,card in enumerate(plan['cards'],1):
                identity=card['book_id'],card['card_id']
                current=db.execute('SELECT snapshot_id FROM active_snapshots WHERE book_id=? AND card_id=?',identity).fetchone()
                require(current is not None and current[0]==card['parent_snapshot_id'] and
                    sc._read_parent(db,*identity,card['parent_snapshot_id'])==payload(card,True), 'complete current context parent differs')
                child=payload(card);ro._insert(db,child);ro._reconcile(db,child)
                db.execute('UPDATE active_snapshots SET snapshot_id=? WHERE book_id=? AND card_id=? AND snapshot_id=?',
                    (card['child_snapshot_id'],*identity,card['parent_snapshot_id']))
                require(db.execute('SELECT changes()').fetchone()[0]==1, 'guarded context activation differs')
                db.execute('INSERT INTO final_reader_context_cards VALUES(?,?,?,?,?,?)',
                    (plan['run_id'],*identity,card['parent_snapshot_id'],card['child_snapshot_id'],card['before_payload_sha256']))
                if fail_after_cards==n:raise RuntimeError('injected final reader context failure')
            require(digest(sc._graph(db))==plan['child_graph_sha256'], 'unrelated active graph changed')
            require(stat_pin(plan['protected']['file'])==plan['protected']['stat'], 'protected changed during context write');db.commit()
        except BaseException:db.rollback();raise
    return _receipt(plan)


def rollback(plan,*,root_write_approved=False):
    require(root_write_approved is True, 'explicit ROOT context rollback approval required');candidate=_validate(plan)
    with closing(sc._connect(candidate,write=True)) as db:
        db.execute('BEGIN IMMEDIATE')
        try:
            previous=db.execute('SELECT plan_sha256,state FROM final_reader_context_runs WHERE run_id=?',(plan['run_id'],)).fetchone()
            require(previous is not None and previous[0]==digest(plan) and previous[1] in {'applied','rolled_back'}, 'exact context applied run required')
            already=previous[1]=='rolled_back'
            require(digest(sc._graph(db))==(plan['active_graph_sha256'] if already else plan['child_graph_sha256']), 'rollback would overwrite later graph')
            for card in plan['cards']:
                identity=card['book_id'],card['card_id']
                require(sc._read_parent(db,*identity,card['parent_snapshot_id'])==payload(card,True), 'complete immutable context inverse differs')
                if not already:db.execute('UPDATE active_snapshots SET snapshot_id=? WHERE book_id=? AND card_id=?',
                    (card['parent_snapshot_id'],*identity))
            db.execute('UPDATE final_reader_context_runs SET state=? WHERE run_id=?',('rolled_back',plan['run_id']))
            require(digest(sc._graph(db))==plan['active_graph_sha256'], 'complete context inverse graph differs');db.commit()
        except BaseException:db.rollback();raise
    return _receipt(plan,already=already,rollback=True)
