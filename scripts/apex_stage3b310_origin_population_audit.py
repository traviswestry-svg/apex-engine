#!/usr/bin/env python3
"""APEX Stage 3B.3.10: bounded, read-only historical origin and gamma population audit.

No writes, migrations, historical code execution, or retroactive eligibility changes.
Population completeness is asserted only for a fully exhausted, bounded rowid walk
with a consistent reported COUNT(*) in the decision database. It is not historical
source authenticity or cross-DB snapshot attestation.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import timezone
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time

try:
    from apex_stage3b39_runtime_decision_gamma_audit import (
        ro_open, columns, bounded, has_identity_index, parse_time,
        limited_snapshot, extract_snapshot_identity, deployment_boundary,
        DEFAULT_BOUNDARY,
    )
except ImportError:
    from scripts.apex_stage3b39_runtime_decision_gamma_audit import (
        ro_open, columns, bounded, has_identity_index, parse_time,
        limited_snapshot, extract_snapshot_identity, deployment_boundary,
        DEFAULT_BOUNDARY,
    )

SCHEMA='apex.stage3b310_record_origin_gamma_population_coverage.v1'
DECISION_DB='apex_evidence_pipeline.db'
GAMMA_DB='apex_tracking.db'
DECISION_TABLE='decisions'
GAMMA_TABLE='gamma_observational_snapshots'
MAX_ROWS=200000
MAX_BATCH=500
MAX_QUERY_MS=2000
MAX_TOTAL_MS=120000
MAX_BYTES=1024*1024
ORIGIN_KEYS=('apex_release_version','git_sha','deployment_id','deploy_id','apex_version')


def make_report(boundary, max_rows,batch_size,query_ms,total_ms):
    return {
      'schema':SCHEMA,'mode':'READ_ONLY_BOUNDED_KEYSET_POPULATION_AUDIT',
      'status':'NOT_EVALUATED','migration_authority':'BLOCKED_RESEARCH_ONLY',
      'boundary':{'reference':boundary.isoformat(),'policy_effective_date_verified':False},
      'inputs':{'decisions':'NOT_CHECKED','gamma':'NOT_CHECKED'},
      'coverage':{'decision_table_exhausted':False,'count_reconciled':False,
         'population_coverage_verified':False,'scanned_rows':0,'decision_total':None,
         'max_rows':max_rows,'batch_size':batch_size,'query_budget_ms':query_ms,
         'total_budget_ms':total_ms,'stop_reason':'NOT_EVALUATED',
         'cross_database_point_in_time_consistency_verified':False},
      'observations':{'linkage_counts':{},'time_partition_counts':{},'origin_claim_states':{},
         'origin_version_attested':False,'runtime_gamma_activation_verified':False,
         'historical_eligibility_verified':False,'provider_availability_at_decision_verified':False,
         'gamma_index_verified':False,'gamma_time_column':None,'gamma_symbol_column':None,
         'query_errors':{}},
      'guardrails':{'sqlite_uri_mode':'ro','sqlite_query_only':True,'no_database_writes':True,
         'no_schema_changes':True,'no_checkpoint_or_vacuum':True,'no_git_mutations':True,
         'no_later_gamma_substitution':True,'no_backfill':True,'no_record_reclassification':True,
         'no_record_ids_or_payloads_exported':True,'no_trade_execution':True,
         'no_reader_cutover':True,'query_progress_deadlines_cooperative':True},
      'limitations':[
         'Exhaustion counts rows currently visible in the decision database; it does not independently attest the historical population or cross-database consistency.',
         'Stored version, commit and deployment identifiers are untrusted origin claims, never an attestation of which process wrote a record.',
         'Gamma timestamp ordering is not proof of provider availability or runtime feature activation.',
         'The deployment completion time is a reference boundary, not a verified policy-effective date.',
         'No historical replay, eligibility reclassification, archive reader cutover, or recovery verification is performed.'
      ],
      'remaining_gates':['record_origin_version_attestation','runtime_feature_activation_attestation',
         'independent_source_authentication','historical_semantic_behavior_replay','utf8_reader_fix',
         'historical_replay_equivalence','reader_cutover_coverage','external_backup_restore','isolated_rollback']}


def audit(root,*,boundary,max_rows=10000,batch_size=200,query_ms=500,total_ms=20000):
    if not 1<=max_rows<=MAX_ROWS:raise ValueError('MAX_ROWS_OUT_OF_RANGE')
    if not 1<=batch_size<=MAX_BATCH:raise ValueError('BATCH_SIZE_OUT_OF_RANGE')
    if not 20<=query_ms<=MAX_QUERY_MS:raise ValueError('QUERY_BUDGET_OUT_OF_RANGE')
    if not 100<=total_ms<=MAX_TOTAL_MS:raise ValueError('TOTAL_BUDGET_OUT_OF_RANGE')
    root=Path(root)
    report=make_report(boundary,max_rows,batch_size,query_ms,total_ms)
    deadline=time.monotonic()+total_ms/1000
    d=ro_open(root/DECISION_DB);g=ro_open(root/GAMMA_DB)
    report['inputs']['decisions']='READABLE_RO' if d else 'MISSING'
    report['inputs']['gamma']='READABLE_RO' if g else 'MISSING'
    if not d or not g:
        if d:d.close()
        if g:g.close()
        report['status']='INPUT_MISSING';report['coverage']['stop_reason']='INPUT_MISSING'
        return report
    try:
        # Independent read-only transactions stabilize each database as much as
        # SQLite allows; there is no global cross-database snapshot guarantee.
        d.execute('BEGIN');g.execute('BEGIN')
        dc=columns(d,DECISION_TABLE);gc=columns(g,GAMMA_TABLE)
        if not {'decision_id','observed_at','ticker'}.issubset(dc) or not {'canonical_gamma_snapshot_id'}.issubset(gc):
            report['status']='REQUIRED_SCHEMA_MISSING';report['coverage']['stop_reason']='SCHEMA_MISSING';return report
        indexed=has_identity_index(g,GAMMA_TABLE,'canonical_gamma_snapshot_id',deadline,query_ms)
        report['observations']['gamma_index_verified']=indexed
        if not indexed:
            report['status']='GAMMA_IDENTITY_INDEX_MISSING';report['coverage']['stop_reason']='GAMMA_INDEX_MISSING';return report
        gc_symbol=next((name for name in ('ticker','symbol') if name in gc),None)
        gc_time=next((name for name in ('observed_at','captured_at','snapshot_at','created_at','timestamp','as_of') if name in gc),None)
        report['observations']['gamma_symbol_column']=gc_symbol
        report['observations']['gamma_time_column']=gc_time
        # SQLite rowid walk must really work. No table-wide ORDER BY timestamp.
        test,err=bounded(d,'SELECT rowid FROM "decisions" WHERE rowid>? ORDER BY rowid LIMIT 1',(0,),deadline,query_ms,True)
        if err:
            report['status']='ROWID_WALK_UNAVAILABLE';report['coverage']['stop_reason']=err;return report
        total,err=bounded(d,'SELECT count(*) AS n FROM "decisions"',(),deadline,query_ms)
        if err or total is None:
            report['status']='COUNT_UNAVAILABLE';report['coverage']['stop_reason']=err or 'COUNT_UNAVAILABLE';return report
        expected=int(total['n']);report['coverage']['decision_total']=expected
        if expected>max_rows:
            report['coverage']['stop_reason']='CAP_BELOW_POPULATION';report['status']='BOUNDED_PARTIAL_POPULATION'
        has_id='canonical_gamma_snapshot_id' in dc
        has_snapshot='snapshot_json' in dc
        fields=['rowid AS scan_rowid','observed_at','ticker']
        if has_id:fields.append('canonical_gamma_snapshot_id')
        if has_snapshot:fields.append('substr(snapshot_json,1,1048577) AS snapshot_json')
        # Structured-data selection only; no SELECT * or raw record export.
        sql='SELECT '+','.join(fields)+' FROM "decisions" WHERE rowid>? ORDER BY rowid LIMIT ?'
        gc_fields=['canonical_gamma_snapshot_id']
        if gc_symbol:gc_fields.append(gc_symbol)
        if gc_time and gc_time not in gc_fields:gc_fields.append(gc_time)
        lookup='SELECT '+','.join('"'+f+'"' for f in gc_fields)+' FROM "gamma_observational_snapshots" WHERE canonical_gamma_snapshot_id=? LIMIT 2'
        counts=Counter();partitions=Counter();origin=Counter();errors=Counter()
        cursor=0;exhausted=False;stopped=None
        while report['coverage']['scanned_rows']<max_rows:
            if time.monotonic()>=deadline:
                stopped='GLOBAL_DEADLINE_EXCEEDED';break
            limit=min(batch_size,max_rows-report['coverage']['scanned_rows'])
            batch,err=bounded(d,sql,(cursor,limit),deadline,query_ms,True)
            if err:
                stopped=err;errors[err]+=1;break
            if not batch:
                exhausted=True;stopped='ROWID_EXHAUSTED';break
            for row in batch:
                cursor=row['scan_rowid']
                report['coverage']['scanned_rows']+=1
                timestamp=parse_time(row['observed_at'])
                if timestamp is None:partitions['TIME_INVALID']+=1
                elif timestamp<boundary:partitions['PRE_REFERENCE']+=1
                else:partitions['POST_REFERENCE']+=1
                snap={};snap_state='SNAPSHOT_COLUMN_ABSENT'
                if has_snapshot:snap,snap_state=limited_snapshot(row['snapshot_json'])
                if not has_snapshot:origin['ORIGIN_COLUMN_UNAVAILABLE']+=1
                elif snap_state!='SNAPSHOT_PARSED':origin['ORIGIN_SNAPSHOT_UNVERIFIABLE']+=1
                else:
                    claims={k:snap.get(k) for k in ORIGIN_KEYS if isinstance(snap.get(k),str) and snap.get(k).strip()}
                    origin['ORIGIN_VERSION_CLAIM_ONLY' if claims else 'ORIGIN_NOT_RECORDED']+=1
                    if len({str(claims[k]) for k in ('git_sha','deployment_id','deploy_id') if k in claims})>1:
                        # Different namespaces cannot be equated; do not assert an origin mismatch.
                        pass
                if timestamp is None:
                    counts['DECISION_TIME_UNVERIFIABLE']+=1;continue
                # Pre-implementation records must not be retroactively governed.
                if timestamp<boundary:
                    counts['PRE_REFERENCE_NO_RETROACTIVE_POLICY']+=1;continue
                if not has_id:
                    counts['GAMMA_ID_COLUMN_UNAVAILABLE']+=1;continue
                stored=row['canonical_gamma_snapshot_id']
                if not isinstance(stored,str) or not stored.strip():
                    counts['GAMMA_ID_MISSING_LEGACY_OR_UNKNOWN']+=1;continue
                snap_id=extract_snapshot_identity(snap) if snap_state=='SNAPSHOT_PARSED' else None
                if snap_id=='ROOT_NESTED_ID_CONFLICT' or (isinstance(snap_id,str) and snap_id!=stored.strip()):
                    counts['PERSISTED_SNAPSHOT_ID_CONFLICT']+=1;continue
                if has_snapshot and snap_state!='SNAPSHOT_PARSED':
                    counts['SNAPSHOT_UNVERIFIABLE_ID_NOT_RECONCILED']+=1;continue
                match,err=bounded(g,lookup,(stored.strip(),),deadline,query_ms,True)
                if err:
                    errors[err]+=1;counts['GAMMA_LOOKUP_UNVERIFIABLE']+=1;continue
                if not match:
                    counts['GAMMA_ID_UNRESOLVED']+=1;continue
                if len(match)>1:
                    counts['GAMMA_ID_AMBIGUOUS_DUPLICATE']+=1;continue
                value=dict(match[0])
                if not gc_symbol:
                    counts['GAMMA_SYMBOL_UNVERIFIABLE']+=1;continue
                if value[gc_symbol]!=row['ticker']:
                    counts['GAMMA_SYMBOL_CONFLICT']+=1;continue
                if not gc_time:
                    counts['GAMMA_TIME_UNVERIFIABLE']+=1;continue
                gtime=parse_time(value[gc_time])
                if not gtime:
                    counts['GAMMA_TIME_INVALID']+=1;continue
                if gtime>timestamp:
                    counts['GAMMA_OBSERVATION_AFTER_DECISION']+=1;continue
                counts['GAMMA_ID_SYMBOL_TIME_CONSISTENT']+=1
            if stopped:break
            if len(batch)<limit:
                exhausted=True;stopped='ROWID_EXHAUSTED';break
        if not stopped and report['coverage']['scanned_rows']==max_rows:
            # If cap equals the exact COUNT(*) and no rows were missed, the
            # bounded rowid walk is complete without one extra fetch.
            if report['coverage']['scanned_rows']==expected:
                exhausted=True;stopped='POPULATION_COUNT_REACHED'
            else:stopped='ROW_LIMIT_REACHED'
        n=report['coverage']['scanned_rows']
        report['coverage'].update({'decision_table_exhausted':exhausted,
           'count_reconciled':exhausted and n==expected,
           'population_coverage_verified':exhausted and n==expected and not errors,
           'stop_reason':stopped or 'UNSPECIFIED'})
        report['observations'].update({'linkage_counts':dict(sorted(counts.items())),
           'time_partition_counts':dict(sorted(partitions.items())),
           'origin_claim_states':dict(sorted(origin.items())),
           'query_errors':dict(sorted(errors.items()))})
        if sum(counts.values())!=n or sum(partitions.values())!=n or sum(origin.values())!=n:
            report['status']='INTERNAL_COUNT_INVARIANT_FAILURE'
            report['coverage']['population_coverage_verified']=False
        elif report['coverage']['population_coverage_verified']:
            report['status']='POPULATION_COUNT_RECONCILED_ORIGIN_UNATTESTED'
        else:
            report['status']='BOUNDED_PARTIAL_POPULATION_OR_UNVERIFIABLE'
        return report
    except sqlite3.Error:
        report['status']='SQLITE_READ_UNAVAILABLE';report['coverage']['stop_reason']='SQLITE_READ_UNAVAILABLE'
        return report
    finally:
        d.close();g.close()


def write_report(path,report,root):
    dest=Path(path).resolve();protected=Path(root).resolve()
    if dest==protected or protected in dest.parents:raise ValueError('OUTPUT_INSIDE_PRODUCTION_DATA_REJECTED')
    dest.parent.mkdir(parents=True,exist_ok=True)
    raw=(json.dumps(report,sort_keys=True,indent=2)+'\n').encode('utf8')
    fd,temp=tempfile.mkstemp(prefix='.stage3b310-',dir=dest.parent)
    try:
        with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
        os.chmod(temp,0o600);os.replace(temp,dest)
    finally:
        if os.path.exists(temp):os.unlink(temp)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',default='/data')
    p.add_argument('--boundary',default=DEFAULT_BOUNDARY)
    p.add_argument('--deployment-history',default='/data/apex_audit_evidence/stage3b38-deployment-history.json')
    p.add_argument('--native-evidence',default='/data/apex_audit_evidence/stage3b38-render-native-evidence.json')
    p.add_argument('--service-id',default='srv-d7p3u2navr4c73d2q0jg')
    p.add_argument('--post-deployment-id',default='dep-damjvajncjis73dmepo0')
    p.add_argument('--post-deployment-commit',default='e14c343dcd14b9987a92a45dda44bbbdf54a60e4')
    p.add_argument('--max-rows',type=int,default=10000)
    p.add_argument('--batch-size',type=int,default=200)
    p.add_argument('--query-budget-ms',type=int,default=500)
    p.add_argument('--total-budget-ms',type=int,default=20000)
    p.add_argument('--output',required=True)
    args=p.parse_args(argv)
    boundary=parse_time(args.boundary)
    if not boundary:p.error('boundary must be timezone-aware ISO-8601')
    try:out=audit(args.root,boundary=boundary,max_rows=args.max_rows,batch_size=args.batch_size,
                  query_ms=args.query_budget_ms,total_ms=args.total_budget_ms)
    except ValueError as ex:p.error(str(ex))
    provenance=deployment_boundary(args.deployment_history,args.native_evidence,
           service=args.service_id,deploy_id=args.post_deployment_id,commit_sha=args.post_deployment_commit)
    if provenance.get('deployment_completion_correlated') and parse_time(provenance['completion_time'])!=boundary:
        provenance['state']='BOUNDARY_TIMESTAMP_CONFLICT';provenance['deployment_completion_correlated']=False
    out['deployment_provenance']=provenance
    if not provenance.get('deployment_completion_correlated'):
        out['status']='DEPLOYMENT_REFERENCE_UNVERIFIED_'+out['status']
    write_report(args.output,out,args.root)
    print('Stage 3B.3.10 |',out['status'],'| migration='+out['migration_authority'])
    return 0
if __name__=='__main__':raise SystemExit(main())
