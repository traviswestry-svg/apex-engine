#!/usr/bin/env python3
"""APEX Stage 3B.3.1: read-only sampled historical gamma-link classification.

No implied historical requirement from present-day policy. No backfill or writes.
If a historical policy is supplied, it is *advisory only* until independently verified.
"""
from __future__ import annotations
import argparse
import json
import sqlite3
import time
from collections import Counter
from pathlib import Path

SCHEMA='apex.stage3b31_gamma_linkage_historical_eligibility.v1'
SPECS={
 'DECISION':('apex_evidence_pipeline.db','decisions','decision_id','observed_at','ticker'),
 'TRIGGER':('apex_trigger_observatory.db','observed_trade_triggers','trigger_id','triggered_at','symbol'),
}
GAMMA_DB='apex_tracking.db'
CAP_SAMPLES=16

def ro(path):
    if not path.is_file():return None
    c=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=.2)
    c.row_factory=sqlite3.Row
    c.execute('PRAGMA query_only=ON')
    return c

def bounded(c,sql,args,deadline,ms,many=False):
    if time.monotonic()>=deadline:return None,'GLOBAL_DEADLINE_EXCEEDED'
    stop=min(deadline,time.monotonic()+ms/1000)
    calls=[0]
    def cb():
        calls[0]+=1
        return int(calls[0]>20000 or time.monotonic()>stop)
    c.set_progress_handler(cb,100)
    try:
        cur=c.execute(sql,args)
        return (cur.fetchall() if many else cur.fetchone()),None
    except sqlite3.Error as e:
        return None,'QUERY_INTERRUPTED' if 'interrupt' in str(e).lower() else 'QUERY_UNAVAILABLE'
    finally:c.set_progress_handler(None,0)

def is_indexed(c,table,col,deadline,ms):
    plan,err=bounded(c,f'EXPLAIN QUERY PLAN SELECT "{col}" FROM "{table}" WHERE "{col}"=? LIMIT 1',('!!APEX_MISS!!',),deadline,ms,True)
    if err or not plan:return False
    descriptions=' '.join(str(r[3]).upper() for r in plan)
    return 'SEARCH ' in descriptions and 'SCAN ' not in descriptions

def classify(record, gamma, decision=None, historical_rule=None):
    """Pure classification, historical_rule is verified external rule or None.

    historical_rule: 'REQUIRED' or 'NOT_REQUIRED', NEVER inferred from null identity.
    """
    cid=record.get('canonical_gamma_snapshot_id')
    base={'linkage':'', 'historical_eligibility':'UNVERIFIABLE_HISTORICAL_POLICY', 'reason':''}
    if not cid:
        base['linkage']='GAMMA_ID_NULL_OR_UNLINKED'
    elif gamma is None:
        base['linkage']='GAMMA_ID_NOT_FOUND'
    elif gamma.get('ticker')!=record.get('ticker'):
        base['linkage']='GAMMA_SYMBOL_CONFLICT'
    else:
        base['linkage']='GAMMA_ID_FOUND_TICKER_AGREES'
    if decision is not None:
        dcid=decision.get('canonical_gamma_snapshot_id')
        if dcid and cid and dcid!=cid:
            base['linkage']='TRIGGER_DECISION_GAMMA_ID_CONFLICT'
    if historical_rule=='NOT_REQUIRED':
        base['historical_eligibility']='HISTORICALLY_NOT_REQUIRED_BY_VERIFIED_RULE'
    elif historical_rule=='REQUIRED':
        base['historical_eligibility']=('REQUIRED_LINK_VERIFIED' if base['linkage']=='GAMMA_ID_FOUND_TICKER_AGREES' else 'REQUIRED_LINK_MISSING_OR_INVALID')
    return base

def sample(root, sample_rows=4, query_ms=400, total_ms=8000):
    n=max(1,min(int(sample_rows),CAP_SAMPLES))
    ms=max(20,min(int(query_ms),1000))
    total=max(100,min(int(total_ms),20000))
    deadline=time.monotonic()+total/1000
    result={'schema':SCHEMA,'mode':'READ_ONLY_HISTORICAL_RESEARCH', 'migration_authority':'BLOCKED_RESEARCH_ONLY',
      'historical_rule_status':'NO_INDEPENDENTLY_VERIFIED_VERSIONED_RULE_LOADED',
      'production_engine_replay_performed':False,'gamma_identity_backfilled':False,
      'limits':{'rows_per_edge_per_type':n,'max_per_type':2*n,'query_ms':ms,'total_ms':total},
      'guardrails':{'sqlite_mode':'ro','no_sqlite_writes':True,'no_archive_payload_reads':True,
        'no_checkpoint':True,'no_vacuum':True,'no_delete':True,'no_backfill':True,
        'no_payloads_record_ids_or_raw_timestamps_exported':True,'requires_indexed_lookups':True,
        'query_time_limits_cooperative':True,'no_trade_execution_authority':True},
      'types':{},'remaining_gates':['historical_rule_version_provenance_verified',
        'cross_database_identity_population_coverage','stage3b1_reader_fix_verified',
        'production_replay_equivalence','all_reader_cutover_coverage',
        'external_backup_restore','isolated_restore_rollback']}
    gamma=ro(root/GAMMA_DB)
    if gamma is None:result['status']='GAMMA_DB_UNAVAILABLE';return result
    try:
        gamma_ok=is_indexed(gamma,'gamma_observational_snapshots','canonical_gamma_snapshot_id',deadline,ms)
        result['gamma_identity_index_verified']=gamma_ok
        if not gamma_ok:result['status']='GAMMA_INDEX_UNVERIFIED';return result
        decision=ro(root/'apex_evidence_pipeline.db')
        decision_index=bool(decision and is_indexed(decision,'decisions','decision_id',deadline,ms))
        result['decision_identity_index_verified']=decision_index
        try:
            for kind,(db,table,key,dt,tickercol) in SPECS.items():
                info={'sampled':0,'linkage_counts':{},'historical_eligibility_counts':{},
                      'decision_link_counts':{},'provenance_counts':{},'query_states':{},
                      'historical_eligibility_verified':False,'representative':False,
                      'source_lookup_index_verified':False}
                result['types'][kind]=info
                con=ro(root/db)
                if con is None:info['status']='SOURCE_DB_UNAVAILABLE';continue
                try:
                    if not is_indexed(con,table,key,deadline,ms):
                        info['status']='SOURCE_ID_INDEX_UNVERIFIED';continue
                    info['source_lookup_index_verified']=True
                    # Bounded PK/rowid edge windows; avoids aggregate count scans.
                    fields=f'"{key}" AS row_key,"{dt}" AS event_time,"{tickercol}" AS ticker,canonical_gamma_snapshot_id'
                    if kind=='DECISION':fields+=',gamma_provenance_class'
                    else:fields+=',decision_id'
                    unique={}
                    for direction in ('ASC','DESC'):
                        rows,error=bounded(con,f'SELECT {fields} FROM "{table}" ORDER BY rowid {direction} LIMIT ?', (n,),deadline,ms,True)
                        if error:info['query_states'][error]=info['query_states'].get(error,0)+1;continue
                        for r in rows:unique.setdefault(r['row_key'],dict(r))
                    info['sampled']=len(unique)
                    info['status']='SAMPLED' if unique else 'NO_ROWS_OR_BUDGET'
                    for row in unique.values():
                        gamma_row=None
                        cid=row['canonical_gamma_snapshot_id']
                        if cid:
                            gr,err=bounded(gamma,'SELECT ticker FROM gamma_observational_snapshots WHERE canonical_gamma_snapshot_id=? LIMIT 1',(cid,),deadline,ms)
                            if err:info['query_states'][err]=info['query_states'].get(err,0)+1;continue
                            gamma_row=dict(gr) if gr else None
                        drow=None
                        if kind=='TRIGGER':
                            did=row['decision_id']
                            if not did:info['decision_link_counts']['DECISION_ID_NULL']=info['decision_link_counts'].get('DECISION_ID_NULL',0)+1
                            elif not decision_index:info['decision_link_counts']['DECISION_INDEX_UNVERIFIED']=info['decision_link_counts'].get('DECISION_INDEX_UNVERIFIED',0)+1
                            else:
                                dr,err=bounded(decision,'SELECT canonical_gamma_snapshot_id,ticker FROM decisions WHERE decision_id=? LIMIT 1',(did,),deadline,ms)
                                if err:info['query_states'][err]=info['query_states'].get(err,0)+1;continue
                                if dr is None:info['decision_link_counts']['DECISION_NOT_FOUND']=info['decision_link_counts'].get('DECISION_NOT_FOUND',0)+1
                                else:
                                    drow=dict(dr)
                                    state='DECISION_FOUND_TICKER_AGREES' if dr['ticker']==row['ticker'] else 'DECISION_FOUND_TICKER_CONFLICT'
                                    info['decision_link_counts'][state]=info['decision_link_counts'].get(state,0)+1
                        v=classify(row,gamma_row,drow)
                        for dest,keyname in (('linkage_counts','linkage'),('historical_eligibility_counts','historical_eligibility')):
                            keyval=v[keyname];info[dest][keyval]=info[dest].get(keyval,0)+1
                        if kind=='DECISION':
                            # Categorize presence only; never export arbitrary provenance text.
                            pstate='PROVENANCE_PRESENT_UNVERIFIED' if row['gamma_provenance_class'] else 'PROVENANCE_ABSENT'
                            info['provenance_counts'][pstate]=info['provenance_counts'].get(pstate,0)+1
                finally:con.close()
            result['status']='SAMPLED_HISTORICAL_ELIGIBILITY_UNVERIFIED_MIGRATION_BLOCKED'
            return result
        finally:
            if decision:decision.close()
    finally:gamma.close()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',default='/data')
    p.add_argument('--sample-rows',type=int,default=4)
    p.add_argument('--query-budget-ms',type=int,default=400)
    p.add_argument('--total-budget-ms',type=int,default=8000)
    p.add_argument('--output',required=True)
    a=p.parse_args()
    root=Path(a.root).resolve();output=Path(a.output).resolve()
    if output==root or root in output.parents:p.error('output must be outside /data')
    report=sample(root,a.sample_rows,a.query_budget_ms,a.total_budget_ms)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    print('Stage 3B.3.1 report:',output,'| migration='+report['migration_authority'],'| status='+report['status'])
if __name__=='__main__':main()
