#!/usr/bin/env python3
"""Prepare, rehearse and explicitly apply the bounded final source patch."""
from __future__ import annotations
import argparse
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from anki_pipeline import final_source_corrections as fs, source_confirmations as sc
from anki_pipeline import residual_optimization as ro, sense_frequency as sf


def owned(path):
    path=Path(path).resolve()
    fs.require(path.is_relative_to(fs.OWNED) and path!=fs.OWNED,'artifacts must stay in source-apply-owned directory')
    return path


def pin(path):
    path=Path(path).resolve(strict=True)
    return {'file':str(path),'sha256':fs.digest(path.read_bytes())}


def reseal(plan):
    plan['run_id']=fs.digest({k:v for k,v in plan.items() if k!='run_id'})


def rehearse(plan,output,*,all_cards=False):
    """Real full source/target parents, metadata representatives and DB failures.

No whole candidate copy. All six source lexemes and every destination from
both books are included, plus the smallest metadata-only card in each book.
Pass all_cards to exercise every prepared affected parent instead.
"""
    output=owned(output);fs.require(not output.exists(),'fresh rehearsal directory required');output.mkdir(parents=True)
    words={'be','promote','date','root','deep','team','prompt','data','deep-rooted','teem'}
    selected=list(plan['cards']) if all_cards else [c for c in plan['cards'] if c['word'] in words]
    if not all_cards:
        for book in fs.BOOKS:
            candidates=[c for c in plan['cards'] if c['book_id']==book and c not in selected and not c['created']]
            if candidates:selected.append(min(candidates,key=lambda c:c['original_count']))
    database=output/'affected-only.sqlite3'
    with closing(sqlite3.connect(database)) as db:
        db.executescript(sf._SQL+'\nPRAGMA user_version=2;');db.execute('PRAGMA foreign_keys=ON')
        for card in selected:
            if card['created']:continue
            before=fs.payload(card,True);ro._insert(db,before)
            db.execute('INSERT INTO active_snapshots VALUES(?,?,?)',(card['book_id'],card['card_id'],card['parent_snapshot_id']))
        db.commit();before_graph=sc._graph(db)
    trial=deepcopy(plan);trial['cards']=deepcopy(selected);trial['candidate']=str(database);trial['candidate_stat']=fs.stat_pin(database)
    all_leafs={c[field]['file'] for c in plan['cards'] for field in ('payload_file','before_payload_file') if field in c}
    selected_leafs={c[field]['file'] for c in selected for field in ('payload_file','before_payload_file') if field in c}
    trial['source_files']={name:sha for name,sha in trial['source_files'].items() if name not in all_leafs or name in selected_leafs}
    trial['request']['candidate']={'file':str(database),'stat':trial['candidate_stat']};trial['active_graph_sha256']=fs.digest(before_graph)
    scope=ro.read_json(plan['request']['scope']);selected_ids={(c['book_id'],c['card_id']) for c in selected}
    scope['cards']=[c for c in scope['cards'] if (c['book_id'],c['card_id']) in selected_ids]
    scope['rows']=[r for r in scope['rows'] if (r['book_id'],r['card_id']) in selected_ids]
    scope['created_cards']=[c for c in scope['created_cards'] if (c['book_id'],c['card_id']) in selected_ids]
    scope.update(candidate=str(database),candidate_stat=trial['candidate_stat'],active_graph_sha256=trial['active_graph_sha256'],expected_cards=len(selected),expected_changed_rows=len(scope['rows']))
    scope['scope_sha256']=fs.digest({k:v for k,v in scope.items() if k!='scope_sha256'})
    scope_pin=sc._write_json(output/'scratch-scope.json',scope)
    trial['request']['scope']=scope_pin;trial['source_files'][scope_pin['file']]=scope_pin['sha256']
    child_graph=sorted([[c['book_id'],c['card_id'],c['child_snapshot_id']] for c in selected])
    trial['child_graph_sha256']=fs.digest(child_graph);trial['summary']['cards']=len(selected);reseal(trial)
    try:
        fs.apply(trial,root_write_approved=True,fail_after_cards=2)
        raise AssertionError('real failure injection did not trigger')
    except RuntimeError as error:
        fs.require('injected' in str(error),'unexpected rehearsal failure')
    with closing(sc._connect(database)) as db:
        fs.require(sc._graph(db)==before_graph,'failed transaction changed active graph')
        for card in selected:
            if not card['created']:
                fs.require(sc._read_parent(db,card['book_id'],card['card_id'],card['parent_snapshot_id'])==fs.payload(card,True),'failed transaction changed immutable parent')
    trial['candidate_stat']=fs.stat_pin(database);reseal(trial)
    applied=fs.apply(trial,root_write_approved=True)
    repeated=fs.apply(trial,root_write_approved=True)
    with closing(sc._connect(database)) as db:
        for card in selected:
            ro._reconcile(db,fs.payload(card))
            fs.require(sc._read_parent(db,card['book_id'],card['card_id'],card['child_snapshot_id'])==fs.payload(card),'applied full payload readback differs')
    restored=fs.rollback(trial,root_write_approved=True)
    repeated_restore=fs.rollback(trial,root_write_approved=True)
    with closing(sc._connect(database)) as db:
        fs.require(sc._graph(db)==before_graph,'full active pointer recovery differs')
        for card in selected:
            if not card['created']:fs.require(sc._read_parent(db,card['book_id'],card['card_id'],card['parent_snapshot_id'])==fs.payload(card,True),'recovery full parent differs')
            ro._reconcile(db,fs.payload(card))
        fs.require(db.execute('PRAGMA integrity_check').fetchone()[0]=='ok' and not db.execute('PRAGMA foreign_key_check').fetchall(),'scratch integrity or FK failed')
    result={'schema':'final-source-corrections-rehearsal.v1','plan_run_id':plan['run_id'],'trial_run_id':trial['run_id'],
        'actual_candidate_modified':False,'cards':len(selected),'full_prepared_scope_cards':len(plan['cards']),
        'all_prepared_cards_exercised':len(selected)==len(plan['cards']),'real_full_parent_scope':'all source and destination cards plus paragraph representatives',
        'database_bytes':database.stat().st_size,'injected_failure_atomic':True,'apply_idempotent':repeated['already_applied'],
        'rollback_idempotent':repeated_restore['already_rolled_back'],'full_parent_recovery_exact':True,
        'full_child_payload_readback_exact':True,'normalized_before_after_exact':True,'integrity_check':'ok',
        'applied':applied['state'],'restored':restored['state']}
    proof=sc._write_json(output/'rehearsal.json',result);result['proof']=proof
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=('scope','prepare','validate','rehearse','apply','rollback'))
    parser.add_argument('--request');parser.add_argument('--request-sha256');parser.add_argument('--plan');parser.add_argument('--plan-sha256')
    parser.add_argument('--output');parser.add_argument('--root-candidate-write-approved',action='store_true');parser.add_argument('--all-cards',action='store_true')
    args=parser.parse_args(argv)
    if args.mode in {'scope','prepare'}:
        if not(args.request and args.request_sha256 and args.output):parser.error('request, exact SHA and fresh owned output required')
        request=ro.read_json({'file':args.request,'sha256':args.request_sha256});output=owned(args.output)
        if args.mode=='scope':
            result={'scope':sc._write_json(output,fs.inspect_scope(request))}
        else:
            plan=fs.prepare(request,artifact_root=output,progress=lambda x:print(fs.canonical(x),flush=True))
            result=fs.materialize(plan,output)
    else:
        if not(args.plan and args.plan_sha256):parser.error('exact plan pin required')
        plan=ro.read_json({'file':args.plan,'sha256':args.plan_sha256})
        if args.mode=='validate':
            fs._validate(plan);result={'schema':fs.PLAN,'run_id':plan['run_id'],'validated':True,'database_writes':0}
        elif args.mode=='rehearse':
            if not args.output:parser.error('fresh owned rehearsal output required')
            result=rehearse(plan,args.output,all_cards=args.all_cards)
        else:
            if not args.root_candidate_write_approved:parser.error('explicit ROOT candidate write approval required')
            method=fs.apply if args.mode=='apply' else fs.rollback;result=method(plan,root_write_approved=True)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))


if __name__=='__main__':main()
