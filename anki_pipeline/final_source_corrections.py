"""Owner-confirmed final five corrections, with immutable parents and inverses.

Only affected snapshots are appended. The spurious be is removed and the two
deep/root components become one complete compound: each book loses two counts.
Source PDFs, historical snapshots, dictionary text and study state stay intact.
"""
from __future__ import annotations
from contextlib import closing
from copy import deepcopy
import json
import html
import hashlib
from pathlib import Path
import re

from . import source_confirmations as sc, residual_optimization as ro, sense_frequency as sf
from .store import utc_now
from .translation_alignment import validate_translation_alignment

REQUEST = 'final-source-corrections-request.v1'
SCOPE = 'final-source-corrections-scope.v1'
PLAN = 'final-source-corrections-plan.v1'
RECEIPT = 'final-source-corrections-receipt.v1'
ROOT = Path(__file__).resolve().parents[1]
OWNED = ROOT / 'output/eleven-resolution-20261014/source-apply-own'
BOOKS = ['redbook', 'redbook2027']
CASES = {
 'be': {'word':'be','sentence_id':'kaoyan:2022-01:p:b-10-6:new:1','occurrence_id':'075b12d32c86ce97f2200a6c46134ad14eb6ec53398a7a7a7902e2d08be34fd8','edit':[38,41,''],'target':None},
 'prompted': {'word':'promote','sentence_id':'kaoyan:2014-01:p:b-4-5:new:1','occurrence_id':'5c58d684be1565472f9c71b2e19f600aa40b19f07647bed6b382b41e34ee5e80','edit':[5,13,'prompted'],'target':'prompt'},
 'data': {'word':'date','sentence_id':'kaoyan:2018-02:p:b-7-5:0','occurrence_id':'b4783841550f61c9e01a4d39627a7a62924eb557abe386226cbfea8c5ec6a36d','edit':[77,81,'data'],'target':'data'},
 'deep-rooted': {'word':'root','sentence_id':'kaoyan:2021-01:q-34-1:A:new:0','occurrence_id':'383edf41d6a6aa09d6a0533e1a6c8473b6e647ae500fe9da48437eb2be721f83','edit':[11,11,'ed'],'target':'deep-rooted'},
 'teeming': {'word':'team','sentence_id':'kaoyan:2024-01:p:b-9-6:1','occurrence_id':'cda58d71363c04e226f764a35067419521af8ba98221a75eecd75ae00cbe4157','edit':[182,189,'teeming'],'target':'teem'},
}
DEEP_COMPONENT_ID = '52956ebe7d8c94e9a3f97a391b988ee8ca36755f469cb49216ab6fc7ece65881'
_DDL = (
 'CREATE TABLE IF NOT EXISTS final_source_correction_runs(run_id TEXT PRIMARY KEY,plan_sha256 TEXT NOT NULL,state TEXT NOT NULL,created_at TEXT NOT NULL)',
 'CREATE TABLE IF NOT EXISTS final_source_correction_cards(run_id TEXT NOT NULL REFERENCES final_source_correction_runs(run_id),book_id TEXT NOT NULL,card_id TEXT NOT NULL,parent_snapshot_id TEXT REFERENCES snapshots(id),child_snapshot_id TEXT NOT NULL REFERENCES snapshots(id),inverse_sha256 TEXT NOT NULL,created INTEGER NOT NULL CHECK(created IN(0,1)),PRIMARY KEY(run_id,book_id,card_id))',
 'CREATE TABLE IF NOT EXISTS final_source_correction_lexemes(run_id TEXT NOT NULL REFERENCES final_source_correction_runs(run_id),book_id TEXT NOT NULL,card_id TEXT NOT NULL,snapshot_id TEXT NOT NULL REFERENCES snapshots(id),payload TEXT NOT NULL,PRIMARY KEY(run_id,book_id,card_id))',
)
canonical, digest, require, stat_pin = sc.canonical, sc.digest, sc.require, sc.stat_pin


def _boundary(request):
    require(request.get('schema') == REQUEST, 'final source request schema required')
    candidate = Path(request['candidate']['file']).resolve(strict=True)
    protected = Path(request['protected']['file']).resolve(strict=True)
    require(candidate != protected and not candidate.samefile(protected), 'protected database or inode alias rejected')
    require(stat_pin(protected) == request['protected']['stat'], 'protected database changed')
    require(sorted(request['expected_books']) == BOOKS, 'both complete books required')
    return candidate


def _index(row):
    require(row['englishHash'] == sf._sha(row['english']) and row['translationHash'] == sf._sha(row['translationZh']), 'reader text hash differs')
    alignment = {'schema':'codex-sentence-alignment.v1','englishHash':row['englishHash'], 'translationHash':row['translationHash'],'alignments':row['alignments']}
    validate_translation_alignment(row['english'], row['translationZh'], alignment)
    require(row['reviewedContentHash'] == sf._sha(row['translationZh']+'\0'+json.dumps(row['alignments'],ensure_ascii=False,separators=(',',':'))), 'reader review hash differs')
    if 'sourceEnglish' in row:
        require(row['sourceHash']==sf._sha(row['sourceEnglish']) and row['sourceEnglish'][row['start']:row['end']]==row['english'], 'reader paragraph range/hash differs')
    for name in ('englishHash','translationHash','reviewedContentHash','sourceHash'):
        require(re.fullmatch('[a-f0-9]{64}',row[name]) is not None, 'invalid reader hash')
    return alignment


def _file_sha(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):value.update(chunk)
    return value.hexdigest()


def _reader_guard(request,files):
    """Bind actual current reader bytes and its separately owned small DB."""
    binding=request['reader_binding']
    review=ro.read_json(binding['review_inputs']);complete=ro.read_json(binding['completion_receipt'])
    require(review.get('schema')=='confirmed-reader-freeze.v1' and complete.get('schema')=='confirmed-reader-completion.v1', 'reader freeze/receipt schema differs')
    require(complete['allAppliedFileHashesVerified'] is True and complete['regeneratedJsonAndTexExactlyMatchLive'] is True, 'reader source validation incomplete')
    require(complete['receipts']['review-inputs.json']['sha256']==binding['review_inputs']['sha256'] and
        review['receipts']['source-revisions.json']['sha256']==complete['receipts']['source-revisions.json']['sha256']==request['source_revisions']['sha256'], 'reader receipt lineage differs')
    require(type(request['expected_reader_files']) is int and request['expected_reader_files']>0 and len(review['files'])==request['expected_reader_files'], 'reader finite file scope differs')
    for entry in review['files']:
        pin={'file':entry['absolutePath'],'sha256':entry['afterSha256']}
        ro.read_pin(pin);files[pin['file']]=pin['sha256']
    database=Path(review['database']['path']).resolve(strict=True)
    require(stat_pin(database)==binding['database_stat'], 'live reader database stat differs')
    require(not Path(str(database)+'-wal').exists() or Path(str(database)+'-wal').stat().st_size==0, 'live reader WAL not checkpointed')
    require(_file_sha(database)==review['database']['afterSha256']==complete['databaseAfterSha256'] and stat_pin(database)==binding['database_stat'], 'live reader database bytes differ')
    for pin in (binding['review_inputs'],binding['completion_receipt']):files[pin['file']]=pin['sha256']


def _inputs(request):
    _boundary(request)
    require(set(request['confirmations'])==set(CASES), 'exact five human confirmations required')
    confirmations,files={},{}
    _reader_guard(request,files)
    for key,pin in request['confirmations'].items():
        value=ro.read_json(pin)
        require((value.get('authority') or value.get('human_normalization_approval',{}).get('authority'))=='direct_user_confirmation','direct human confirmation absent')
        require(value['sentence_id']==CASES[key]['sentence_id'] and value['original_occurrence_id']==CASES[key]['occurrence_id'],'confirmation finite identity differs')
        confirmations[key]=value;files[pin['file']]=pin['sha256']
    source=ro.read_json(request['source_revisions'])
    require(source.get('schema')=='confirmed-reader-source-revisions.v1' and {r['caseKey'] for r in source['records']}==set(CASES) and len(source['records'])==5, 'exact five reader revisions required')
    sentences={}
    for meta in source['records']:
        key,old,new=meta['caseKey'],meta['oldRecord'],meta['newRecord'];value=confirmations[key]
        require(meta['sentenceId']==old['id']==new['id']==CASES[key]['sentence_id'],'reader main sentence differs')
        approved=value.get('user_confirmed_corrected_text') or value['human_normalization_approval']['approved_corrected_text']
        a,b,text=CASES[key]['edit']
        require(old['english']==value['observed_local_source'] and new['english']==approved==old['english'][:a]+text+old['english'][b:],'finite approved English edit differs')
        require(any(p['oldRecord']==old and p['newRecord']==new for p in meta['paragraphAffectedRecords']),'main source omitted')
        require(re.fullmatch('[a-f0-9]{64}',meta['newStructuredPaperHash']) is not None,'new paper hash missing')
        for pair in meta['paragraphAffectedRecords']:
            before,after=pair['oldRecord'],pair['newRecord']
            require(before['id']==after['id'] and before['paragraphId']==after['paragraphId']==meta['paragraphId'] and before['translationZh']==after['translationZh'],'reader paragraph identity/Chinese changed')
            _index(before);_index(after)
            if before['id']!=old['id']:
                require(before['english']==after['english'] and before['alignments']==after['alignments'],'unrelated paragraph text/chunks changed')
            require(before['id'] not in sentences,'duplicate source revision')
            sentences[before['id']]={'key':key,'meta':meta,'old':before,'new':after}
    document=ro.read_json(request['targets'])
    require(document.get('schema')=='final-source-targets.v1','native target schema differs')
    targets={}
    for target in document['targets']:
        if target['case_key']=='be':
            require(target['word']=='be' and target['target_range'] is None and target['sense_ordinal'] is None,
                    'spurious be cannot have a destination')
            continue
        identity=target['case_key'],target['book_id']
        require(identity not in targets and identity[0] in CASES and identity[0]!='be' and identity[1] in BOOKS,'duplicate/out of scope target')
        require(target['word']==CASES[identity[0]]['target'] and target['kind'] in {'existing','supplemental'},'target lexeme differs')
        native=target['native_sense']
        require(native.get('original_english') and native.get('original_chinese') and target.get('evidence_pins'),'full bilingual native definition/evidence required')
        captures=[]
        for pin in target['evidence_pins']:
            raw=ro.read_pin(pin);files[pin['file']]=pin['sha256']
            try:captures.append(' '.join(html.unescape(re.sub('<[^>]*>','',raw.decode('utf-8'))).split()))
            except UnicodeDecodeError:pass
        for name in ('original_english','original_chinese'):
            require(any(' '.join(native[name].split()) in raw for raw in captures),'native original definition absent from actual capture')
        require(type(target['sense_ordinal']) is int and target['sense_ordinal']>=0,'native ordinal required')
        targets[identity]=target
    require(set(targets)=={(k,b) for k in CASES if k!='be' for b in BOOKS},'both books/four transfers required')
    for pin in (request['source_revisions'],request['targets']):files[pin['file']]=pin['sha256']
    return sentences,targets,files


def inspect_scope(request):
    """Read-only complete affected parent/row census, to be pinned explicitly."""
    candidate=_boundary(request);sentences,targets,_=_inputs(request)
    if request['candidate'].get('stat'):
        require(stat_pin(candidate)==request['candidate']['stat'], 'candidate changed before scope census')
    with closing(sc._connect(candidate)) as db:
        graph=sc._graph(db)
        query=('SELECT x.book_id,x.card_id,x.snapshot_id,s.word,o.occurrence_id,o.sentence_id FROM active_snapshots x '
            'CROSS JOIN occurrences o INDEXED BY sqlite_autoindex_occurrences_1 ON o.snapshot_id=x.snapshot_id '
            'JOIN snapshots s ON s.id=x.snapshot_id WHERE x.book_id IN (?,?) AND o.sentence_id IN ('+','.join('?' for _ in sentences)+') ORDER BY x.book_id,x.card_id,o.occurrence_id')
        rows=[dict(row) for row in db.execute(query,[*BOOKS,*sentences])]
        cards={(r['book_id'],r['card_id']):{k:r[k] for k in ('book_id','card_id','snapshot_id','word')} for r in rows}
        for target in targets.values():
            identity=target['book_id'],target['card_id']
            actual=db.execute('SELECT a.snapshot_id,s.word FROM active_snapshots a JOIN snapshots s ON s.id=a.snapshot_id WHERE a.book_id=? AND a.card_id=?',identity).fetchone()
            if target['kind']=='existing':
                require(actual is not None and tuple(actual)==(target['snapshot_id'],target['word']),'existing target parent differs')
                cards[identity]={'book_id':identity[0],'card_id':identity[1],'snapshot_id':actual[0],'word':actual[1]}
            else:
                require(actual is None and not db.execute('SELECT 1 FROM snapshots WHERE book_id=? AND card_id=?',identity).fetchone(),'supplemental target identity exists')
        for book in BOOKS:
            for key,case in CASES.items():
                require(len([r for r in rows if r['book_id']==book and r['word']==case['word'] and r['occurrence_id']==case['occurrence_id']])==1,'one exact source occurrence required: '+book+'/'+key)
            require(len([r for r in rows if r['book_id']==book and r['word']=='deep' and r['occurrence_id']==DEEP_COMPONENT_ID])==1,'exact deep component required')
    created=sorted([{'book_id':t['book_id'],'card_id':t['card_id'],'word':t['word']} for t in targets.values() if t['kind']=='supplemental'],key=lambda x:(x['book_id'],x['card_id']))
    result={'schema':SCOPE,'candidate':str(candidate),'candidate_stat':stat_pin(candidate),'active_graph_sha256':digest(graph),
        'cards':sorted(cards.values(),key=lambda x:(x['book_id'],x['card_id'])),'rows':rows,'created_cards':created,
        'expected_physical_count_delta_by_book':{book:-2 for book in BOOKS},'expected_changed_rows':len(rows),
        'expected_cards':len(cards)+len(created),'original_sources_modified':False}
    result['scope_sha256']=digest(result)
    return result


def remap_range(span,key):
    a,b,text=CASES[key]['edit'];start,end=span;delta=len(text)-(b-a)
    if a==b:return [start+(delta if start>=a else 0),end+(delta if end>=a else 0)]
    if start>=a and end<=b:return None if not text else [a,a+len(text)]
    require(not (start<a<end<b or a<start<b<end),'partial edit overlap is not an exact span')
    return [start+(delta if start>=b else 0),end+(delta if end>=b else 0)]


def _origin(parent,row):
    return {'book_id':parent['book_id'],'card_id':parent['card_id'],'word':parent['word'],
        'parent_snapshot_id':parent['snapshot_id'],'original_row':deepcopy(row),'original_row_sha256':digest(row)}


def _correct(row,parent,revision,request,*,target=None):
    key,old,new=revision['key'],revision['old'],revision['new']
    require(row['english']==old['english'] and row['english_hash']==old['englishHash'] and row['translation']==old['translationZh'] and row['translation_hash']==old['translationHash'],'current bilingual parent differs')
    require(row.get('alignment') is not None and row['alignment']['alignments']==old['alignments'],'current original chunks differ')
    require(row['source_provenance']['sourceHash']==old['sourceHash'] and
            row['source_provenance']['reviewedContentHash']==old['reviewedContentHash'], 'current original source/review seal differs')
    main=row['sentence_id']==CASES[key]['sentence_id']
    span=target['target_range'] if target else remap_range(row['target_range'],key) if main else row['target_range']
    require(span is not None,'deleted token cannot remain current')
    result=deepcopy(row)
    for field in ('display','matching_proposal','ownership_history'):result.pop(field,None)
    result.update(english=new['english'],english_hash=new['englishHash'],target_range=deepcopy(span),alignment=_index(new))
    if target:
        result['translation_ranges']=deepcopy(target.get('translation_ranges',[]))
        if not result['translation_ranges']:
            matches=[a for a in new['alignments'] if a['en'][0]<=span[0]<span[1]<=a['en'][1] and a['relation']=='equivalent']
            require(matches,'native target has no reviewed Chinese chunk')
            result['translation_ranges']=deepcopy(min(matches,key=lambda a:a['en'][1]-a['en'][0])['zh'])
    result['alignment_evidence']=[]
    for evidence in row['alignment_evidence']:
        en=remap_range(evidence['english_range'],key) if main else evidence['english_range']
        match=next((p for p in new['alignments'] if p['en']==en and p['zh']==evidence['translation_ranges'] and p['relation']==evidence.get('relation','equivalent')),None)
        if match:result['alignment_evidence'].append({'english_range':match['en'],'translation_ranges':match['zh'],'relation':match['relation']})
    source=result['source_provenance'];source.update(reviewedContentHash=new['reviewedContentHash'],sourceHash=new['sourceHash'],paragraphRange=[new['start'],new['end']])
    path=source.get('sourcePathEvidence',{})
    if path:
        path['structuredPaperHash']=revision['meta']['newStructuredPaperHash']
        for item in path.get('evidence',[]):
            if 'reviewedContentHash' in item:item['reviewedContentHash']=new['reviewedContentHash']
    history={'schema':'final-source-confirmation-row.v1','key':key,'authority':'direct_user_confirmation',
        'original_row':deepcopy(row),'original_row_sha256':digest(row),'original_occurrence_id':row['occurrence_id'],
        'original_card_id':parent['card_id'],'original_parent_snapshot_id':parent['snapshot_id'],'original_book_id':parent['book_id'],
        'evidence':deepcopy(request['confirmations'][key]),'metadata_only':not main,
        'note':'用户确认源文校正；同段落来源哈希同步；原印字样、原句原译与完整审查保留。',
        'source_revision':{'sentence_id':new['id'],'english_hash':new['englishHash'],'reviewed_content_hash':new['reviewedContentHash'],
            'source_hash':new['sourceHash'],'structured_paper_hash':revision['meta']['newStructuredPaperHash'],'published_record':deepcopy(new)}}
    history['history_sha256']=digest(history);source['source_confirmation']=history
    result['occurrence_id']=digest([result['paper_id'],result['physical_source'],result['target_range']])
    if main:result['semantic_review']={'occurrence_id':result['occurrence_id'],'action':'source_confirmed_correction','original_semantic_review':deepcopy(row.get('semantic_review')),'source_confirmation':request['confirmations'][key]}
    if target:
        result.update(status='reviewed',sense_index=target['sense_ordinal'],reason='用户确认源文校正后，归入已核原生词条 '+target['word']+'；同一原位置仅计一次。',method='final-source-confirmed-native-review.v1',review_version='20261014')
        for field in ('pending_category','broad_match','common_sense_match'):result.pop(field,None)
    result['assignment_context_hash']=None
    if result['status']=='reviewed':result['reviewed_sense_id']=None
    return result


def _template(target):
    require(target['kind']=='supplemental' and target['word'] in {'deep-rooted','teem'},'only two declared supplemental lexemes allowed')
    record={key:deepcopy(target[key]) for key in ('book_id','card_id','word','definition_source','definition_provenance','senses')}
    require(target['native_sense']['original_chinese']==record['senses'][target['sense_ordinal']]['text'],'supplemental Chinese must be exact native text')
    record.update(expected_occurrences=0,occurrences=[])
    data=sf.prepare_record(record)
    if target.get('definition_snapshot_id'):
        require(data['definition_snapshot_id']==target['definition_snapshot_id'] and
                data['senses'][target['sense_ordinal']]['sense_id']==target['target_sense_id'], 'declared native definition identity differs')
    return data


def prepare(request,*,progress=None,artifact_root=None):
    """Prepare/export complete affected parents and children without DB writes."""
    candidate=_boundary(request);sentences,targets,files=_inputs(request)
    scope=ro.read_json(request['scope']);require(scope==inspect_scope(request),'pinned finite scope differs from current census')
    files[request['scope']['file']]=request['scope']['sha256']
    artifacts=Path(artifact_root).resolve() if artifact_root is not None else None
    if artifacts:require(not artifacts.exists(),'fresh preparation output required');artifacts.mkdir(parents=True)
    keys={(c['book_id'],c['card_id']):c for c in scope['cards']}
    require(all(book in BOOKS for book,_ in keys), 'foreign book in preparation scope')
    for t in targets.values():
        if t['kind']=='supplemental':keys[(t['book_id'],t['card_id'])]={'book_id':t['book_id'],'card_id':t['card_id'],'word':t['word'],'snapshot_id':None}
    moved,origins={},{}
    with closing(sc._connect(candidate)) as db:
        for book in BOOKS:
            for key,case in CASES.items():
                if key=='be':continue
                source=next(r for r in scope['rows'] if r['book_id']==book and r['word']==case['word'] and r['occurrence_id']==case['occurrence_id'])
                parent=sc._read_parent(db,book,source['card_id'],source['snapshot_id']);old=next(r for r in parent['occurrences'] if r['occurrence_id']==case['occurrence_id'])
                row=_correct(old,parent,sentences[old['sentence_id']],request,target=targets[(key,book)]);history_origins=[_origin(parent,old)]
                if key=='deep-rooted':
                    component=next(r for r in scope['rows'] if r['book_id']==book and r['word']=='deep' and r['occurrence_id']==DEEP_COMPONENT_ID)
                    cp=sc._read_parent(db,book,component['card_id'],component['snapshot_id']);cr=next(r for r in cp['occurrences'] if r['occurrence_id']==DEEP_COMPONENT_ID)
                    require(cr['physical_source']==old['physical_source'] and cr['target_range']==[2,6],'compound component physical origin differs')
                    history_origins.append(_origin(cp,cr))
                history=row['source_provenance']['source_confirmation'];history.pop('history_sha256');history['origins']=history_origins
                history['native_target']=deepcopy(targets[(key,book)]);history['history_sha256']=digest(history)
                moved[(key,book)]=row;origins[(key,book)]=history_origins
    cards,operations,changed_rows=[],[],0
    with closing(sc._connect(candidate)) as db:
        graph=sc._graph(db)
        for n,(identity,ref) in enumerate(sorted(keys.items()),1):
            target=next((t for t in targets.values() if (t['book_id'],t['card_id'])==identity),None);created=ref['snapshot_id'] is None
            parent=_template(target) if created else sc._read_parent(db,*identity,ref['snapshot_id'])
            record=sc._producer(parent);changed=[];retirements=[];mapping=[]
            for item,old in zip(record['occurrences'],parent['occurrences']):
                rev=sentences.get(old['sentence_id'])
                if rev is None:changed.append(item);continue
                changed_rows+=1;key=rev['key'];case=CASES[key]
                special=old['occurrence_id']==case['occurrence_id'] and parent['word']==case['word']
                component=key=='deep-rooted' and parent['word']=='deep' and old['occurrence_id']==DEEP_COMPONENT_ID
                if special or component:
                    incoming=moved.get((key,identity[0]));destination=targets.get((key,identity[0]))
                    action='remove_spurious_token' if key=='be' else 'merge_compound_component' if component else 'correct_source_and_rehome_once'
                    retirement={'key':key,'action':action,'original_row':deepcopy(old),'original_row_sha256':digest(old),
                        'target_card_id':destination['card_id'] if destination else None,'target_occurrence_id':incoming['occurrence_id'] if incoming else None,'evidence':deepcopy(request['confirmations'][key])}
                    retirements.append(retirement)
                    op={'book_id':identity[0],'card_id':identity[1],'key':key,'action':action,'original_occurrence_id':old['occurrence_id'],
                        'occurrence_id':retirement['target_occurrence_id'],'target_card_id':retirement['target_card_id'],'sentence_id':old['sentence_id']}
                    operations.append(op);mapping.append(op);continue
                row=_correct(old,parent,rev,request);row['sense_index']=item['sense_index'];changed.append(row)
                mapping.append({'book_id':identity[0],'card_id':identity[1],'key':key,'action':'correct_source_or_metadata',
                    'original_occurrence_id':old['occurrence_id'],'occurrence_id':row['occurrence_id'],'target_card_id':identity[1],'sentence_id':row['sentence_id']})
            for (key,book),incoming in moved.items():
                destination=targets[(key,book)]
                if (book,destination['card_id'])!=identity:continue
                require(len(record['senses'])>destination['sense_ordinal'] and record['senses'][destination['sense_ordinal']]['text']==destination['native_sense']['original_chinese'],'actual native destination sense differs')
                require(not any(r['physical_source']==incoming['physical_source'] and r['target_range']==incoming['target_range'] for r in changed),'destination already owns correction; cannot double count')
                changed.append(deepcopy(incoming));op={'book_id':book,'card_id':identity[1],'key':key,'action':'receive_corrected_source_once',
                    'original_occurrence_id':CASES[key]['occurrence_id'],'occurrence_id':incoming['occurrence_id'],'target_card_id':identity[1],'sentence_id':incoming['sentence_id'],
                    'origins':[{'card_id':o['card_id'],'occurrence_id':o['original_row']['occurrence_id']} for o in origins[(key,book)]]}
                operations.append(op);mapping.append(op)
            record['occurrences']=changed;record['expected_occurrences']=len(changed);policy=record['exam_usage_policy']
            policy['final_source_corrections']={'schema':'final-source-correction-card.v1','parent_snapshot_id':ref['snapshot_id'],'removed_rows':retirements,'operations':mapping,'dictionary_target':deepcopy(target) if created else None}
            updates=policy.get('residual_display_updates',[])
            if updates:
                hashes={s['old']['englishHash'] for s in sentences.values()};retired=[u for u in updates if u.get('before',{}).get('english_hash') in hashes]
                policy['final_source_corrections']['prior_display_updates']=retired;policy['residual_display_updates']=[u for u in updates if u not in retired]
            child=sc._seal(record,parent)
            card={'book_id':identity[0],'card_id':identity[1],'word':child['word'],'created':created,'parent_snapshot_id':ref['snapshot_id'],'child_snapshot_id':child['snapshot_id'],
                'before_payload_sha256':digest(None if created else parent),'payload_sha256':digest(child),'before_payload':None if created else parent,'payload':child,
                'original_count':0 if created else parent['expected_occurrences'],'new_count':child['expected_occurrences'],'source_retirements':retirements,'row_mapping':mapping,
                'supplemental_lexeme':deepcopy(target) if created else None,'new_definitions':[]}
            if created:card['definition_template']=parent
            cards.append(card)
            if artifacts:_export_card(card,artifacts,files)
            if progress and (n%10==0 or n==len(keys)):progress({'stage':'exported_cards' if artifacts else 'sealed_cards','completed':n,'total':len(keys)})
    delta={b:sum(c['new_count']-c['original_count'] for c in cards if c['book_id']==b) for b in BOOKS}
    require(delta==scope['expected_physical_count_delta_by_book'],'deletion/transfer/compound counts differ')
    require(changed_rows==scope['expected_changed_rows'],'finite row count differs')
    child_ids={(c['book_id'],c['card_id']):c['child_snapshot_id'] for c in cards}
    child_graph=[[b,c,child_ids.pop((b,c),sid)] for b,c,sid in graph];child_graph.extend([b,c,sid] for (b,c),sid in child_ids.items());child_graph.sort()
    for module in (__file__,sc.__file__,sf.__file__,ro.__file__):files[str(Path(module).resolve())]=digest(Path(module).read_bytes())
    result={'schema':PLAN,'request':deepcopy(request),'protected':deepcopy(request['protected']),'candidate':str(candidate),'candidate_stat':stat_pin(candidate),
        'active_graph_sha256':digest(graph),'child_graph_sha256':digest(child_graph),'cards':cards,'source_files':files,
        'summary':{'cards':len(cards),'created_cards':sum(c['created'] for c in cards),'changed_source_rows':changed_rows,
            'physical_count_delta_by_book':delta,'physical_count_delta':sum(delta.values()),'operations':operations,'original_sources_modified':False,'study_progress_modified':False},
        'native_corrections':[{'book_id':c['book_id'],'card_id':c['card_id'],'word':c['word'],'created':c['created'],'row_mapping':c['row_mapping'],'source_retirements':c['source_retirements']} for c in cards]}
    require(stat_pin(candidate)==scope['candidate_stat'] and stat_pin(request['protected']['file'])==request['protected']['stat'],'database changed during preparation')
    result['run_id']=digest(result);return result


def _export_card(card,output,files):
    prefix=digest([card['book_id'],card['card_id']])
    for field,checksum in (('before_payload','before_payload_sha256'),('payload','payload_sha256')):
        pin=sc._write_json(output/(prefix+('-before.json' if field=='before_payload' else '-after.json')),card[field],card[checksum])
        card[field+'_file']=pin;files[pin['file']]=pin['sha256'];del card[field]


def payload(card,before=False):
    key='before_payload' if before else 'payload'
    return card[key] if key in card else ro.read_json(card[key+'_file'])


def materialize(plan,output):
    require(plan['run_id']==digest({k:v for k,v in plan.items() if k!='run_id'}),'plan seal differs');output=Path(output).resolve()
    if all('payload_file' in c for c in plan['cards']):
        require(output.is_dir() and not (output/'plan.json').exists(),'fresh streamed plan required');wire=plan
    else:
        require(not output.exists(),'fresh preparation directory required');output.mkdir(parents=True)
        wire={**plan,'cards':[dict(c) for c in plan['cards']],'source_files':dict(plan['source_files'])}
        for card in wire['cards']:_export_card(card,output,wire['source_files'])
        wire['run_id']=digest({k:v for k,v in wire.items() if k!='run_id'})
    pin=sc._write_json(output/'plan.json',wire);return {'plan':pin,'run_id':wire['run_id'],'summary':wire['summary']}


def _validate(plan):
    require(plan.get('schema')==PLAN and plan['run_id']==digest({k:v for k,v in plan.items() if k!='run_id'}),'plan seal differs')
    candidate=_boundary(plan['request']);require(str(candidate)==plan['candidate'] and plan['protected']==plan['request']['protected'],'plan boundary differs')
    require(all(c['book_id'] in BOOKS for c in plan['cards']), 'foreign book in apply scope')
    leaf_paths={c[field]['file'] for c in plan['cards'] for field in ('payload_file','before_payload_file') if field in c}
    for file,sha in plan['source_files'].items():
        if file not in leaf_paths:ro.read_pin({'file':file,'sha256':sha})
    sentences,targets,_=_inputs(plan['request'])
    scope=ro.read_json(plan['request']['scope'])
    expected_keys={(c['book_id'],c['card_id'],False) for c in scope['cards']} | {(c['book_id'],c['card_id'],True) for c in scope['created_cards']}
    require({(c['book_id'],c['card_id'],c['created']) for c in plan['cards']}==expected_keys, 'finite card identity scope differs')
    for card in plan['cards']:
        before,after=payload(card,True),payload(card)
        require(digest(before)==card['before_payload_sha256'] and digest(after)==card['payload_sha256'],'complete payload export differs')
        require(card['new_count']==after['expected_occurrences'] and card['original_count']==(before['expected_occurrences'] if before else 0), 'card count export differs')
        for field in ('payload_file','before_payload_file'):
            if field in card:require(plan['source_files'].get(card[field]['file'])==card[field]['sha256'], 'payload pin omitted or conflicting in source manifest')
        sc._identity(after)
        if before is not None:sc._identity(before)
        parent=before or card['definition_template']
        if card['created']:
            declared=next(t for t in targets.values() if t['book_id']==card['book_id'] and t['card_id']==card['card_id'])
            require(before is None and parent==_template(declared) and card['supplemental_lexeme']==declared,'new supplemental definition identity differs')
        require((after['book_id'],after['card_id'],after['word'])==(card['book_id'],card['card_id'],card['word']),'child identity differs')
        require(all(after[k]==parent[k] for k in ('definition_provenance','definition_source','senses','definition_snapshot_id')),'original/native dictionary definition changed')
        ordinals={s['sense_id']:s['ordinal'] for s in after['senses']};data=sf._definition(after)
        originals={r['occurrence_id']:r for r in parent['occurrences']}
        for row in after['occurrences']:
            if originals.get(row['occurrence_id'])==row:continue
            history=row['source_provenance'].get('source_confirmation')
            require(history and history.get('schema')=='final-source-confirmation-row.v1' and history['history_sha256']==digest({k:v for k,v in history.items() if k!='history_sha256'}),'history seal differs')
            old=history['original_row'];require(digest(old)==history['original_row_sha256'],'original row differs')
            if history.get('origins'):
                target=targets[(history['key'],after['book_id'])];require(target['card_id']==after['card_id'] and history['native_target']==target,'incoming target differs')
                require(len(history['origins'])==(2 if history['key']=='deep-rooted' else 1),'full origin count differs')
                expected_origin_ids={CASES[history['key']]['occurrence_id']} | ({DEEP_COMPONENT_ID} if history['key']=='deep-rooted' else set())
                require(old['occurrence_id']==CASES[history['key']]['occurrence_id'] and
                    {o['original_row']['occurrence_id'] for o in history['origins']}==expected_origin_ids, 'incoming source physical identities differ')
                for origin in history['origins']:
                    source=next((c for c in plan['cards'] if c['book_id']==origin['book_id'] and c['card_id']==origin['card_id']),None)
                    require(source is not None,'incoming source outside plan');p=payload(source,True)
                    require(p['snapshot_id']==origin['parent_snapshot_id'] and any(r==origin['original_row'] for r in p['occurrences']) and digest(origin['original_row'])==origin['original_row_sha256'],'incoming original differs')
            else:
                require(any(r==old for r in parent['occurrences']),'corrected original outside parent');target=None
            expected=_correct(old,{'book_id':history['original_book_id'],'card_id':history['original_card_id'],'snapshot_id':history['original_parent_snapshot_id']},sentences[old['sentence_id']],plan['request'],target=target)
            expected['source_provenance']['source_confirmation']=history;expected['sense_index']=ordinals[row['sense_id']] if row['status']=='reviewed' else None
            require(sf._occurrence(expected,data,require_binding=False)==row,'row changed beyond approved source edit')
        for retirement in after['exam_usage_policy']['final_source_corrections']['removed_rows']:
            require(digest(retirement['original_row'])==retirement['original_row_sha256'] and any(r==retirement['original_row'] for r in parent['occurrences']),'retired original differs')
            key=retirement['key'];old=retirement['original_row']
            require((parent['word']==CASES[key]['word'] and old['occurrence_id']==CASES[key]['occurrence_id']) or
                    (key=='deep-rooted' and parent['word']=='deep' and old['occurrence_id']==DEEP_COMPONENT_ID), 'retirement exceeds approved source position')
        mapped={m['original_occurrence_id'] for m in card['row_mapping'] if m['action']!='receive_corrected_source_once'}
        require({r['occurrence_id'] for r in parent['occurrences']}-mapped <= {r['occurrence_id'] for r in after['occurrences']},'unrelated occurrence lost')
    delta={b:sum(c['new_count']-c['original_count'] for c in plan['cards'] if c['book_id']==b) for b in BOOKS}
    require(delta=={b:-2 for b in BOOKS}==plan['summary']['physical_count_delta_by_book'],'count guards differ')
    require(len(plan['cards'])==ro.read_json(plan['request']['scope'])['expected_cards'], 'complete card scope differs')
    return candidate


def _receipt(plan,*,already=False,rollback=False):
    return {'schema':RECEIPT,'run_id':plan['run_id'],'database':{'file':plan['candidate'],'stat':stat_pin(plan['candidate'])},
        'state':'rolled_back' if rollback else 'applied','already_applied':already and not rollback,'already_rolled_back':already and rollback,'summary':plan['summary']}


def apply(plan,*,root_write_approved=False,fail_after_cards=None):
    require(root_write_approved is True,'explicit root write approval required');candidate=_validate(plan)
    with closing(sc._connect(candidate,write=True)) as db:
        db.execute('BEGIN IMMEDIATE')
        try:
            for ddl in _DDL:db.execute(ddl)
            previous=db.execute('SELECT plan_sha256,state FROM final_source_correction_runs WHERE run_id=?',(plan['run_id'],)).fetchone()
            if previous:
                require(tuple(previous)==(digest(plan),'applied') and digest(sc._graph(db))==plan['child_graph_sha256'],'existing run or graph differs')
                for card in plan['cards']:ro._reconcile(db,payload(card))
                db.rollback();return _receipt(plan,already=True)
            require(stat_pin(candidate)==plan['candidate_stat'] and digest(sc._graph(db))==plan['active_graph_sha256'],'candidate identity or complete active graph changed')
            db.execute('INSERT INTO final_source_correction_runs VALUES(?,?,?,?)',(plan['run_id'],digest(plan),'applied',utc_now()))
            for n,card in enumerate(plan['cards'],1):
                identity=card['book_id'],card['card_id'];current=db.execute('SELECT snapshot_id FROM active_snapshots WHERE book_id=? AND card_id=?',identity).fetchone()
                if card['created']:require(current is None,'supplemental target appeared')
                else:
                    require(current is not None and current[0]==card['parent_snapshot_id'],'current parent pointer changed')
                    require(sc._read_parent(db,*identity,card['parent_snapshot_id'])==payload(card,True),'complete current parent differs')
                child=payload(card);ro._insert(db,child);ro._reconcile(db,child)
                if card['created']:
                    db.execute('INSERT INTO active_snapshots VALUES(?,?,?)',(*identity,card['child_snapshot_id']))
                    db.execute('INSERT INTO final_source_correction_lexemes VALUES(?,?,?,?,?)',(plan['run_id'],*identity,card['child_snapshot_id'],canonical(card['supplemental_lexeme'])))
                else:
                    db.execute('UPDATE active_snapshots SET snapshot_id=? WHERE book_id=? AND card_id=? AND snapshot_id=?',(card['child_snapshot_id'],*identity,card['parent_snapshot_id']))
                    require(db.execute('SELECT changes()').fetchone()[0]==1,'guarded activation differs')
                db.execute('INSERT INTO final_source_correction_cards VALUES(?,?,?,?,?,?,?)',(plan['run_id'],*identity,card['parent_snapshot_id'],card['child_snapshot_id'],card['before_payload_sha256'],int(card['created'])))
                if fail_after_cards==n:raise RuntimeError('injected final source correction failure')
            require(digest(sc._graph(db))==plan['child_graph_sha256'],'unrelated active graph changed')
            require(stat_pin(plan['protected']['file'])==plan['protected']['stat'],'protected changed during write');db.commit()
        except BaseException:db.rollback();raise
    return _receipt(plan)


def rollback(plan,*,root_write_approved=False):
    require(root_write_approved is True,'explicit root rollback approval required');candidate=_validate(plan)
    with closing(sc._connect(candidate,write=True)) as db:
        db.execute('BEGIN IMMEDIATE')
        try:
            previous=db.execute('SELECT plan_sha256,state FROM final_source_correction_runs WHERE run_id=?',(plan['run_id'],)).fetchone()
            require(previous is not None and previous[0]==digest(plan) and previous[1] in {'applied','rolled_back'},'exact applied run required');already=previous[1]=='rolled_back'
            require(digest(sc._graph(db))==(plan['active_graph_sha256'] if already else plan['child_graph_sha256']),'rollback would overwrite later graph')
            for card in plan['cards']:
                identity=card['book_id'],card['card_id']
                if card['created']:
                    if not already:db.execute('DELETE FROM active_snapshots WHERE book_id=? AND card_id=? AND snapshot_id=?',(*identity,card['child_snapshot_id']))
                else:
                    require(sc._read_parent(db,*identity,card['parent_snapshot_id'])==payload(card,True),'immutable recovery parent differs')
                    if not already:db.execute('UPDATE active_snapshots SET snapshot_id=? WHERE book_id=? AND card_id=?',(card['parent_snapshot_id'],*identity))
            db.execute('UPDATE final_source_correction_runs SET state=? WHERE run_id=?',('rolled_back',plan['run_id']))
            require(digest(sc._graph(db))==plan['active_graph_sha256'],'complete active graph inverse differs');db.commit()
        except BaseException:db.rollback();raise
    return _receipt(plan,already=already,rollback=True)
