#!/usr/bin/env python3
"""APEX Stage 3B.3.9 — sampled, read-only gamma runtime/decision-time correlation.

Reads only an existing SQLite source in mode=ro, with query_only and progress
budgets. Never executes historical APEX modules, reclassifies legacy decisions,
backfills identities, modifies any DB, or asserts runtime activation. A sample
of persisted data is NOT an independently attested runtime feature activation.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time

SCHEMA='apex.stage3b39_runtime_decision_time_gamma_correlation.v1'
DEFAULT_BOUNDARY='2026-09-18T13:45:00.256463Z'
MAX_SAMPLE=32
MAX_QUERY_MS=1000
MAX_TOTAL_MS=20000
MAX_SNAPSHOT_BYTES=1024*1024
GAMMA_TABLE='gamma_observational_snapshots'
DECISION_TABLE='decisions'
SOURCE_TIME_COLUMNS=('observed_at','captured_at','snapshot_at','created_at','timestamp','as_of')
SOURCE_ID_COLUMNS=('canonical_gamma_snapshot_id',)
SOURCE_SYMBOL_COLUMNS=('ticker','symbol')


def parse_time(raw):
    if not isinstance(raw,str) or not raw or len(raw)>80:return None
    try:
        dt=datetime.fromisoformat(raw.replace('Z','+00:00'))
        return dt.astimezone(timezone.utc) if dt.tzinfo is not None else None
    except (ValueError,OverflowError):return None


def ro_open(path):
    path=Path(path)
    if not path.is_file() or path.is_symlink():return None
    uri='file:'+str(path.resolve()).replace('?','%3F').replace('#','%23')+'?mode=ro&immutable=0'
    con=sqlite3.connect(uri,uri=True,timeout=.2)
    con.row_factory=sqlite3.Row
    con.execute('PRAGMA query_only=ON')
    return con


def columns(con,table):
    try:return {x['name'] for x in con.execute(f'PRAGMA table_info("{table}")')}
    except sqlite3.Error:return set()


def bounded(con,sql,args,deadline,query_ms,many=False):
    if time.monotonic()>=deadline:return None,'GLOBAL_DEADLINE_EXCEEDED'
    until=min(deadline,time.monotonic()+query_ms/1000)
    calls=[0]
    def progress():
        calls[0]+=1
        return int(calls[0]>20000 or time.monotonic()>until)
    con.set_progress_handler(progress,100)
    try:
        cur=con.execute(sql,args)
        return (cur.fetchall() if many else cur.fetchone()),None
    except sqlite3.Error as e:
        return None,'QUERY_INTERRUPTED' if 'interrupt' in str(e).lower() else 'QUERY_UNAVAILABLE'
    finally:con.set_progress_handler(None,0)


def has_identity_index(con,table,col,deadline,ms):
    plan,error=bounded(con,f'EXPLAIN QUERY PLAN SELECT "{col}" FROM "{table}" WHERE "{col}"=? LIMIT 1',('!APEX_NONMATCH!',),deadline,ms,True)
    if error or not plan:return False
    detail=' '.join(str(r[3]).upper() for r in plan)
    return 'SEARCH ' in detail and 'SCAN ' not in detail


def limited_snapshot(raw):
    if not isinstance(raw,str) or len(raw.encode('utf8'))>MAX_SNAPSHOT_BYTES:return {},'SNAPSHOT_UNAVAILABLE_OR_OVERSIZE'
    try:result=json.loads(raw)
    except (ValueError,UnicodeError):return {},'SNAPSHOT_INVALID_JSON'
    return (result,'SNAPSHOT_PARSED') if isinstance(result,dict) else ({},'SNAPSHOT_NONOBJECT')


def extract_snapshot_identity(snap):
    # Existing canonical root field is only an independent comparison when it
    # is actually persisted; never discover a gamma ID from newest market data.
    cid=snap.get('canonical_gamma_snapshot_id')
    nested=snap.get('gamma_evidence')
    nested_cid=nested.get('canonical_gamma_snapshot_id') if isinstance(nested,dict) else None
    if cid and nested_cid and cid!=nested_cid:return 'ROOT_NESTED_ID_CONFLICT'
    if isinstance(cid,str) and cid.strip():return cid.strip()
    if isinstance(nested_cid,str) and nested_cid.strip():return nested_cid.strip()
    return None


def classify_decision(decision,gamma_row,*,boundary,gamma_time_col=None,gamma_symbol_col='ticker'):
    """Pure classification; never emits identifiers or changes eligibility."""
    dtime=parse_time(decision.get('observed_at'))
    if not dtime:return 'DECISION_TIME_UNVERIFIABLE'
    if dtime<boundary:return 'PRE_BOUNDARY_RECORD_NO_RETROACTIVE_POLICY'
    if not decision.get('id_column_available',True):return 'GAMMA_ID_COLUMN_ABSENT'
    cid=decision.get('canonical_gamma_snapshot_id')
    if decision.get('snapshot_id_conflict'):return 'PERSISTED_SNAPSHOT_ID_CONFLICT'
    if not isinstance(cid,str) or not cid.strip():return 'POST_BOUNDARY_ID_NULL_LEGACY_OR_UNKNOWN'
    if gamma_row is None:return 'GAMMA_ID_NOT_FOUND'
    if gamma_symbol_col and gamma_row.get(gamma_symbol_col)!=decision.get('ticker'):
        return 'GAMMA_SYMBOL_CONFLICT'
    if not gamma_time_col:return 'GAMMA_ID_MATCHED_TIME_COLUMN_UNVERIFIED'
    gtime=parse_time(gamma_row.get(gamma_time_col))
    if not gtime:return 'GAMMA_ID_MATCHED_TIME_INVALID'
    if gtime>dtime:return 'GAMMA_OBSERVATION_AFTER_DECISION_TIME'
    return 'GAMMA_ID_MATCHED_SYMBOL_TIME_ORDER_CONSISTENT'



def deployment_boundary(history_file,native_file,*,service,deploy_id,commit_sha):
    """Correlate a specific offline Render success event; never attest runtime activation."""
    state={'state':'NOT_SUPPLIED','provider_signed':False,'runtime_activation_verified':False,
           'deployment_completion_correlated':False,'completion_time':None}
    if not history_file or not native_file:return state
    try:
        hp=Path(history_file);np=Path(native_file)
        if any(not p.is_file() or p.stat().st_size>2*1024*1024 for p in (hp,np)):
            return {**state,'state':'INPUT_MISSING_OR_OVERSIZE'}
        h=json.loads(hp.read_bytes());n=json.loads(np.read_bytes())
        ds=[x for x in h.get('deployments',[]) if isinstance(x,dict) and x.get('deploy_id')==deploy_id]
        if len(ds)!=1:return {**state,'state':'DEPLOYMENT_MISSING_OR_DUPLICATE'}
        d=ds[0]
        if d.get('service_id')!=service or d.get('commit_sha')!=commit_sha or d.get('status') not in ('live','deactivated'):
            return {**state,'state':'DEPLOYMENT_IDENTITY_CONFLICT'}
        started=parse_time(d.get('started_at'));ended=parse_time(d.get('live_at'))
        if not started or not ended or ended<started:return {**state,'state':'DEPLOYMENT_TIMESTAMP_INVALID'}
        events=n.get('native_events',[])
        claims=h.get('events',[])
        matched=[e for e in events if isinstance(e,dict) and e.get('deploy_id')==deploy_id
           and e.get('service_id')==service and e.get('type')=='deploy_ended'
           and e.get('deploy_status')=='succeeded' and parse_time(e.get('timestamp'))
           and abs((parse_time(e['timestamp'])-ended).total_seconds())<=10]
        normalized=[e for e in claims if isinstance(e,dict) and e.get('deploy_id')==deploy_id
           and e.get('service_id')==service and e.get('event_type')=='deploy_activated'
           and e.get('outcome')=='succeeded' and parse_time(e.get('occurred_at'))
           and abs((parse_time(e['occurred_at'])-ended).total_seconds())<=10]
        if len(matched)!=1 or len(normalized)!=1:
            return {**state,'state':'LIFECYCLE_UNCORROBORATED_OR_AMBIGUOUS'}
        return {**state,'state':'OFFLINE_LIFECYCLE_CORRELATED_NOT_ATTESTED',
                'deployment_completion_correlated':True,'completion_time':ended.isoformat()}
    except (OSError,UnicodeError,ValueError,TypeError,KeyError,AttributeError):
        return {**state,'state':'EVIDENCE_INVALID'}

def sample(root,*,boundary,rows=8,query_ms=300,total_ms=10000,read_snapshot=True):
    rows=max(1,min(MAX_SAMPLE,int(rows)))
    query_ms=max(20,min(MAX_QUERY_MS,int(query_ms)))
    total_ms=max(100,min(MAX_TOTAL_MS,int(total_ms)))
    deadline=time.monotonic()+total_ms/1000
    report={'schema':SCHEMA,'mode':'READ_ONLY_BOUNDED_SQLITE_DECISION_TIME_CORRELATION',
       'status':'NOT_EVALUATED','migration_authority':'BLOCKED_RESEARCH_ONLY',
       'boundary':{'source':'HISTORICAL_RENDER_DEPLOYMENT_COMPLETION_EXPORT',
                   'is_verified_policy_effective_date':False},
       'inputs':{'decision_database':'NOT_CHECKED','gamma_database':'NOT_CHECKED'},
       'coverage':{'sampling':'ROWID_OLDEST_AND_NEWEST_NOT_REPRESENTATIVE',
                   'population_coverage_verified':False,'origin_version_coverage_verified':False,
                   'query_budget_ms':query_ms,'total_budget_ms':total_ms,'max_edge_rows':rows,
                   'time_window_index_verified':False,'window_sample_used':False},
       'observations':{'sampled_decisions':0,'post_boundary_sampled':0,'linkage_counts':{},'query_states':{},
                       'record_origin_claims_unverified':0,
                       'gamma_lookup_index_verified':False,'gamma_observation_time_column':None,
                       'runtime_feature_activation_verified':False,
                       'verified_record_origin_version':False,'historical_eligibility_verified':False,
                       'no_later_gamma_substitution':True},
       'guardrails':{'sqlite_uri_mode':'ro','sqlite_query_only':True,'no_database_writes':True,
          'no_checkpoint_or_vacuum':True,'no_historical_code_execution':True,'no_latest_gamma_lookup':True,
          'no_backfill':True,'no_trade_execution':True,'no_reader_cutover':True,
          'no_record_ids_or_payloads_exported':True,'query_progress_deadlines_cooperative':True},
       'limitations':['Rowid-edge sampling is not population-wide or time-window coverage.',
           'Source data is not an independently attested historical runtime observation.',
           'Deployment completion is not proof which version produced a decision.',
           'Gamma time ordering alone does not prove provider availability at decision time.',
           'No record backfill or historical eligibility reclassification authorized.'],
       'remaining_gates':['record_origin_version_attestation','runtime_feature_activation_attestation',
           'population_identity_coverage','historical_semantic_behavior_replay','utf8_reader_fix',
           'historical_replay_equivalence','reader_cutover_coverage','external_backup_restore','isolated_rollback']}
    root=Path(root)
    con=ro_open(root/'apex_evidence_pipeline.db')
    gamma=ro_open(root/'apex_tracking.db')
    report['inputs']['decision_database']='READABLE_RO' if con else 'MISSING'
    report['inputs']['gamma_database']='READABLE_RO' if gamma else 'MISSING'
    if not con or not gamma:
        if con:con.close()
        if gamma:gamma.close()
        report['status']='DATABASE_INPUT_MISSING';return report
    try:
        dc=columns(con,DECISION_TABLE);gc=columns(gamma,GAMMA_TABLE)
        required={'decision_id','observed_at','ticker'}
        if not required.issubset(dc) or not {'canonical_gamma_snapshot_id'}.issubset(gc):
            report['status']='REQUIRED_SCHEMA_UNAVAILABLE';return report
        gamma_symbol=next((x for x in SOURCE_SYMBOL_COLUMNS if x in gc),None)
        gamma_time=next((x for x in SOURCE_TIME_COLUMNS if x in gc),None)
        report['observations']['gamma_observation_time_column']=gamma_time
        report['observations']['gamma_symbol_column_verified']=bool(gamma_symbol)
        indexed=has_identity_index(gamma,GAMMA_TABLE,'canonical_gamma_snapshot_id',deadline,query_ms)
        report['observations']['gamma_lookup_index_verified']=indexed
        if not indexed:
            report['status']='GAMMA_IDENTITY_INDEX_UNVERIFIED';return report
        # Never SELECT * or fetch entire blobs except capped bounded edges.
        idcol='canonical_gamma_snapshot_id' in dc
        sncol=read_snapshot and 'snapshot_json' in dc
        fields='decision_id, observed_at, ticker'+(',canonical_gamma_snapshot_id' if idcol else '')+(',substr(snapshot_json,1,1048577) AS snapshot_json' if sncol else '')
        unique={};counts=Counter();errors=Counter()
        for direction in ('ASC','DESC'):
            result,err=bounded(con,f'SELECT {fields} FROM "decisions" ORDER BY rowid {direction} LIMIT ?', (rows,),deadline,query_ms,True)
            if err:errors[err]+=1;continue
            for row in result:unique.setdefault(row['decision_id'],dict(row))
        # Add a focused near-boundary sample only when EXPLAIN proves a bounded
        # indexed search; never let a time filter trigger a table scan.
        time_index=has_identity_index(con,DECISION_TABLE,'observed_at',deadline,query_ms)
        report['coverage']['time_window_index_verified']=time_index
        if time_index:
            boundary_s=boundary.isoformat()
            for op,order in (('>=','ASC'),('<','DESC')):
                r,err=bounded(con,f'SELECT {fields} FROM "decisions" WHERE observed_at {op} ? '
                    f'ORDER BY observed_at {order} LIMIT ?', (boundary_s,rows),deadline,query_ms,True)
                if err:errors[err]+=1
                else:
                    report['coverage']['window_sample_used']=True
                    for item in r:unique.setdefault(item['decision_id'],dict(item))
        report['observations']['sampled_decisions']=len(unique)
        gamma_fields=['canonical_gamma_snapshot_id']
        if gamma_symbol:gamma_fields.append(gamma_symbol)
        if gamma_time and gamma_time not in gamma_fields:gamma_fields.append(gamma_time)
        for rec in unique.values():
            cid=rec.get('canonical_gamma_snapshot_id') if idcol else None
            snapshot={};snap_state='NOT_INSPECTED'
            if sncol:
                snapshot,snap_state=limited_snapshot(rec.get('snapshot_json'))
                if snap_state!='SNAPSHOT_PARSED':errors[snap_state]+=1
            snap_id=extract_snapshot_identity(snapshot) if snapshot else None
            if snapshot and (snapshot.get('apex_release_version') or snapshot.get('git_sha') or snapshot.get('deployment_id')):
                report['observations']['record_origin_claims_unverified']+=1
            conflict=snap_id=='ROOT_NESTED_ID_CONFLICT' or bool(cid and snap_id and snap_id!=cid)
            # Missing canonical column stays missing. Snapshot text alone doesn't
            # retrofit a DB ID and cannot be used to look up a gamma row.
            query_id=cid if idcol and isinstance(cid,str) and cid.strip() and not conflict else None
            g=None
            if query_id:
                row,err=bounded(gamma,'SELECT '+','.join('"'+x+'"' for x in gamma_fields)+
                   ' FROM "gamma_observational_snapshots" WHERE canonical_gamma_snapshot_id=? LIMIT 1',
                   (query_id,),deadline,query_ms)
                if err:errors[err]+=1;counts['GAMMA_QUERY_UNVERIFIABLE']+=1;continue
                if row:g=dict(row)
            datum={'observed_at':rec.get('observed_at'),'ticker':rec.get('ticker'),
                'canonical_gamma_snapshot_id':query_id,'id_column_available':idcol,
                'snapshot_id_conflict':conflict}
            outcome=classify_decision(datum,g,boundary=boundary,gamma_time_col=gamma_time,
               gamma_symbol_col=gamma_symbol)
            counts[outcome]+=1
            when=parse_time(rec.get('observed_at'))
            if when and when>=boundary:report['observations']['post_boundary_sampled']+=1
        report['observations']['linkage_counts']=dict(counts)
        report['observations']['query_states']=dict(errors)
        report['status']='SAMPLED_RUNTIME_ACTIVATION_AND_RECORD_ORIGIN_UNVERIFIED' if unique else 'NO_SAMPLE_OR_BUDGET'
        return report
    finally:
        con.close();gamma.close()


def write_report(path,report,root):
    p=Path(path).resolve();base=Path(root).resolve()
    if p==base or base in p.parents:raise ValueError('OUTPUT_INSIDE_PRODUCTION_DATA_REJECTED')
    p.parent.mkdir(parents=True,exist_ok=True)
    payload=(json.dumps(report,indent=2,sort_keys=True)+'\n').encode('utf8')
    fd,tmp=tempfile.mkstemp(prefix='.apex-stage3b39-',dir=p.parent)
    try:
        with os.fdopen(fd,'wb') as out:out.write(payload);out.flush();os.fsync(out.fileno())
        os.chmod(tmp,0o600);os.replace(tmp,p)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',default='/data')
    p.add_argument('--boundary',default=DEFAULT_BOUNDARY)
    p.add_argument('--deployment-history',default='/data/apex_audit_evidence/stage3b38-deployment-history.json')
    p.add_argument('--native-evidence',default='/data/apex_audit_evidence/stage3b38-render-native-evidence.json')
    p.add_argument('--service-id',default='srv-d7p3u2navr4c73d2q0jg')
    p.add_argument('--post-deployment-id',default='dep-damjvajncjis73dmepo0')
    p.add_argument('--post-deployment-commit',default='e14c343dcd14b9987a92a45dda44bbbdf54a60e4')
    p.add_argument('--sample-rows',type=int,default=8)
    p.add_argument('--query-budget-ms',type=int,default=300)
    p.add_argument('--total-budget-ms',type=int,default=10000)
    p.add_argument('--output',required=True)
    a=p.parse_args(argv)
    boundary=parse_time(a.boundary)
    if not boundary:p.error('boundary must be timezone-aware ISO8601')
    provenance=deployment_boundary(a.deployment_history,a.native_evidence,service=a.service_id,
                                    deploy_id=a.post_deployment_id,commit_sha=a.post_deployment_commit)
    if provenance['deployment_completion_correlated'] and parse_time(provenance['completion_time'])!=boundary:
        provenance['state']='BOUNDARY_TIMESTAMP_CONFLICT'
        provenance['deployment_completion_correlated']=False
    out=sample(a.root,boundary=boundary,rows=a.sample_rows,query_ms=a.query_budget_ms,total_ms=a.total_budget_ms)
    out['deployment_provenance']=provenance
    if not provenance['deployment_completion_correlated']:
        out['status']='DEPLOYMENT_BOUNDARY_UNVERIFIED_'+out['status']
    write_report(a.output,out,a.root)
    print('Stage 3B.3.9 |',out['status'],'| migration='+out['migration_authority'])
    return 0
if __name__=='__main__':raise SystemExit(main())
