#!/usr/bin/env python3
"""Guarded policy-only reader contexts and full affected-parent recovery."""
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
from anki_pipeline import final_reader_contexts as fc, source_confirmations as sc
from anki_pipeline import residual_optimization as ro, sense_frequency as sf


def owned(path):
    path=Path(path).resolve()
    fc.require(path.is_relative_to(fc.OWNED) and path!=fc.OWNED, 'context artifacts must stay in owned directory')
    return path


def reseal(plan):
    plan['run_id']=fc.digest({k:v for k,v in plan.items() if k!='run_id'})


def rehearse(plan,output):
    """Exercise every complete affected parent; never copy the full candidate."""
    output=owned(output);fc.require(not output.exists(), 'fresh context rehearsal directory required');output.mkdir(parents=True)
    candidate_stat=fc.stat_pin(plan['candidate']);database=output/'affected-only.sqlite3'
    with closing(sqlite3.connect(database)) as db:
        db.executescript(sf._SQL+'\nPRAGMA user_version=2;');db.execute('PRAGMA foreign_keys=ON')
        for card in plan['cards']:
            before=fc.payload(card,True);ro._insert(db,before)
            db.execute('INSERT INTO active_snapshots VALUES(?,?,?)',(card['book_id'],card['card_id'],card['parent_snapshot_id']))
        db.commit();before_graph=sc._graph(db)
    trial=deepcopy(plan);trial['candidate']=str(database);trial['candidate_stat']=fc.stat_pin(database)
    trial['request']['candidate']={'file':str(database),'stat':trial['candidate_stat']}
    trial['active_graph_sha256']=fc.digest(before_graph)
    trial['child_graph_sha256']=fc.digest(sorted([[c['book_id'],c['card_id'],c['child_snapshot_id']] for c in plan['cards']]))
    scope=ro.read_json(plan['request']['scope'])
    scope.update(candidate=str(database),candidate_stat=trial['candidate_stat'],active_graph_sha256=trial['active_graph_sha256'])
    scope['scope_sha256']=fc.digest({k:v for k,v in scope.items() if k!='scope_sha256'})
    scope_pin=sc._write_json(output/'scratch-scope.json',scope)
    trial['request']['scope']=scope_pin;trial['source_files'][scope_pin['file']]=scope_pin['sha256'];reseal(trial)
    try:
        fc.apply(trial,root_write_approved=True,fail_after_cards=2)
        raise AssertionError('real context failure injection did not trigger')
    except RuntimeError as error:
        fc.require('injected' in str(error), 'unexpected rehearsal failure')
    with closing(sc._connect(database)) as db:
        fc.require(sc._graph(db)==before_graph, 'injected transaction changed parent graph')
        fc.require(db.execute('SELECT COUNT(*) FROM snapshots').fetchone()[0]==len(plan['cards']), 'injected transaction leaked child snapshots')
        for card in plan['cards']:
            fc.require(sc._read_parent(db,card['book_id'],card['card_id'],card['parent_snapshot_id'])==fc.payload(card,True), 'injected transaction changed full immutable parent')
    trial['candidate_stat']=fc.stat_pin(database);reseal(trial)
    applied=fc.apply(trial,root_write_approved=True);repeated=fc.apply(trial,root_write_approved=True)
    with closing(sc._connect(database)) as db:
        for card in plan['cards']:
            child=fc.payload(card);ro._reconcile(db,child)
            fc.require(sc._read_parent(db,card['book_id'],card['card_id'],card['child_snapshot_id'])==child, 'full child readback differs')
    restored=fc.rollback(trial,root_write_approved=True);repeated_restore=fc.rollback(trial,root_write_approved=True)
    with closing(sc._connect(database)) as db:
        fc.require(sc._graph(db)==before_graph, 'complete context recovery graph differs')
        for card in plan['cards']:
            fc.require(sc._read_parent(db,card['book_id'],card['card_id'],card['parent_snapshot_id'])==fc.payload(card,True), 'complete parent recovery differs')
            ro._reconcile(db,fc.payload(card))
        fc.require(db.execute('PRAGMA integrity_check').fetchone()[0]=='ok' and not db.execute('PRAGMA foreign_key_check').fetchall(), 'scratch integrity/FK failed')
    fc.require(fc.stat_pin(plan['candidate'])==candidate_stat, 'formal candidate changed during scratch rehearsal')
    result={'schema':'final-reader-contexts-rehearsal.v1','plan_run_id':plan['run_id'],'trial_run_id':trial['run_id'],
        'cards':len(plan['cards']),'context_rows':plan['summary']['context_rows'],'all_prepared_cards_exercised':True,
        'formal_candidate_modified':False,'injected_failure_atomic':True,'apply_idempotent':repeated['already_applied'],
        'rollback_idempotent':repeated_restore['already_rolled_back'],'full_parent_recovery_exact':True,
        'full_child_payload_readback_exact':True,'normalized_before_after_exact':True,'raw_occurrences_and_dictionary_exact':True,
        'physical_count_delta_by_book':plan['summary']['physical_count_delta_by_book'],'database_bytes':database.stat().st_size,
        'integrity_check':'ok','foreign_key_check':[],'applied':applied['state'],'restored':restored['state']}
    result['proof']=sc._write_json(output/'rehearsal.json',result)
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=('scope','prepare','validate','rehearse','apply','rollback'))
    parser.add_argument('--request');parser.add_argument('--request-sha256');parser.add_argument('--plan');parser.add_argument('--plan-sha256')
    parser.add_argument('--output');parser.add_argument('--root-candidate-write-approved',action='store_true')
    args=parser.parse_args(argv)
    if args.mode in {'scope','prepare'}:
        if not(args.request and args.request_sha256 and args.output):parser.error('request, exact SHA and fresh owned output required')
        request=ro.read_json({'file':args.request,'sha256':args.request_sha256});output=owned(args.output)
        if args.mode=='scope':result={'scope':sc._write_json(output,fc.inspect_scope(request))}
        else:
            plan=fc.prepare(request,artifact_root=output,progress=lambda v:print(fc.canonical(v),flush=True))
            result={'plan':sc._write_json(output/'plan.json',plan),'run_id':plan['run_id'],'summary':plan['summary']}
    else:
        if not(args.plan and args.plan_sha256):parser.error('exact plan pin required')
        plan=ro.read_json({'file':args.plan,'sha256':args.plan_sha256})
        if args.mode=='validate':fc._validate(plan);result={'validated':True,'database_writes':0,'run_id':plan['run_id']}
        elif args.mode=='rehearse':
            if not args.output:parser.error('fresh owned rehearsal output required')
            result=rehearse(plan,args.output)
        else:
            if not args.root_candidate_write_approved:parser.error('explicit ROOT write approval required')
            result=(fc.apply if args.mode=='apply' else fc.rollback)(plan,root_write_approved=True)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))


if __name__=='__main__':main()
