#!/usr/bin/env python3
"""Stage 3B.3.12: read-only decision-time linkage and runtime evidence reconciliation.

This report is an evidence inventory, NOT a runtime attestation, historical replay,
producer provenance proof, or permission to migrate. Reuses 3B.3.10 bounded indexed
SQLite walk; never exports decision or gamma IDs, records, timestamps, or payloads.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile

SCHEMA='apex.stage3b312_decision_time_linkage_runtime_evidence.v1'
REFERENCE='2026-09-18T13:45:00.256463Z'
MAX_INPUT=4*1024*1024
RISK_KEYS=(
 'GAMMA_ID_MISSING_LEGACY_OR_UNKNOWN','GAMMA_ID_UNRESOLVED',
 'GAMMA_ID_AMBIGUOUS_DUPLICATE','PERSISTED_SNAPSHOT_ID_CONFLICT',
 'GAMMA_SYMBOL_CONFLICT','GAMMA_OBSERVATION_AFTER_DECISION',
 'GAMMA_TIME_INVALID','GAMMA_TIME_UNVERIFIABLE',
 'GAMMA_SYMBOL_UNVERIFIABLE','GAMMA_LOOKUP_UNVERIFIABLE',
 'SNAPSHOT_UNVERIFIABLE_ID_NOT_RECONCILED','GAMMA_ID_COLUMN_UNAVAILABLE',
 'DECISION_TIME_UNVERIFIABLE'
)


def load_report(path, schema):
    if not path: return None,'NOT_SUPPLIED',None
    p=Path(path)
    if not p.is_file() or p.is_symlink() or p.stat().st_size>MAX_INPUT:
        return None,'MISSING_OR_OVERSIZE',None
    data=p.read_bytes()
    try: obj=json.loads(data)
    except (ValueError, UnicodeError): return None,'INVALID_JSON',None
    if not isinstance(obj,dict) or obj.get('schema')!=schema:
        return None,'SCHEMA_MISMATCH',None
    return obj,'READ_AND_SCHEMA_CHECKED',hashlib.sha256(data).hexdigest()


def evaluate(pop, semantic, *, source_states=None, source_hashes=None):
    source_states=source_states or {};source_hashes=source_hashes or {}
    result={
      'schema':SCHEMA,'mode':'READ_ONLY_LINKAGE_AND_RUNTIME_EVIDENCE_RECONCILIATION',
      'status':'INSUFFICIENT_EVIDENCE','migration_authority':'BLOCKED_RESEARCH_ONLY',
      'sources':source_states,'source_sha256':source_hashes,
      'semantic_gate':{'passed':False,'scope':'SELECTED_FUNCTIONS_ONLY'},
      'population_gate':{'reconciled':False,'scanned':None,'total':None,
                         'decision_time_gamma_correlated':0,'post_reference_total':0,
                         'linked_share_of_post_reference':None,'linkage_exceptions':{},
                         'origin_claims_attested':False},
      'runtime_gate':{'deployment_lifecycle_correlated':False,
                      'runtime_activation_attested':False,
                      'decision_writer_origin_attested':False,
                      'independent_source_authenticated':False,
                      'cross_database_point_in_time_consistency_attested':False,
                      'provider_available_at_decision_attested':False},
      'gate_results':{},'remaining_gates':[],
      'guardrails':{'sqlite_mode':'ro','no_writes':True,'no_record_exports':True,
                    'no_history_reclassification':True,'no_gamma_backfill':True,
                    'no_latest_substitution':True,'no_trades':True,'no_cutover':True},
      'limitations':[
        'Uses Stage 3B.3.10 bounded stored-record lookup; does not attest which code actually wrote each decision.',
        'Source hashes attest report transfer integrity only, not independent authenticity.',
        'Observed gamma timestamp <= decision timestamp does not attest provider availability at decision time.',
        'Deployment lifecycle events are not proof that gamma feature logic executed.',
        'Two independent SQLite read transactions cannot establish a shared point-in-time snapshot.',
        'Historical eligibility and exact production runtime activation are not independently replayed.'
      ]
    }
    s=bool(semantic and semantic.get('status')=='SELECTED_SEMANTIC_FIXTURES_PASSED_OTHER_GATES_UNVERIFIED'
           and semantic.get('fixture_passed')==15 and not semantic.get('fixture_failed')
           and semantic.get('snapshot_freeze_selected_execution',{}).get('passed')==6
           and semantic.get('migration_authority')=='BLOCKED_RESEARCH_ONLY')
    result['semantic_gate']['passed']=s
    result['gate_results']['selected_semantic_fixture_gate']='PASS' if s else 'UNVERIFIED'
    if pop:
        cv=pop.get('coverage',{}); ob=pop.get('observations',{}); link=ob.get('linkage_counts',{})
        counts=ob.get('time_partition_counts',{})
        if not isinstance(link,dict) or not isinstance(counts,dict):link={};counts={}
        post=counts.get('POST_REFERENCE',0); good=link.get('GAMMA_ID_SYMBOL_TIME_CONSISTENT',0)
        valid=(all(type(v) is int and v>=0 for v in list(link.values())+list(counts.values()))
          and type(post) is int and type(good) is int and post>=good
          and isinstance(cv.get('scanned_rows'),int) and cv.get('scanned_rows')>=0
          and sum(counts.values())==cv.get('scanned_rows')
          and sum(link.values())==cv.get('scanned_rows')
          and pop.get('migration_authority')=='BLOCKED_RESEARCH_ONLY')
        complete=(valid and cv.get('population_coverage_verified') is True
                  and cv.get('count_reconciled') is True
                  and cv.get('decision_table_exhausted') is True
                  and cv.get('scanned_rows')==cv.get('decision_total'))
        pg=result['population_gate']
        pg.update({'reconciled':bool(complete),'scanned':cv.get('scanned_rows'),
                   'total':cv.get('decision_total'),
                   'decision_time_gamma_correlated':good if valid else 0,
                   'post_reference_total':post if valid else 0,
                   'linked_share_of_post_reference':round(good/post,6) if valid and post else None,
                   'linkage_exceptions':{k:v for k,v in sorted(link.items()) if k!= 'GAMMA_ID_SYMBOL_TIME_CONSISTENT' and v>0} if valid else {},
                   'origin_claims_attested':False})
        provenance=pop.get('deployment_provenance',{})
        result['runtime_gate']['deployment_lifecycle_correlated']=(
            provenance.get('deployment_completion_correlated') is True)
        result['gate_results']['population_coverage_gate']='PASS' if complete else 'PARTIAL_OR_UNVERIFIED'
        result['gate_results']['exact_id_symbol_time_gate']='CORRELATED_NOT_ATTESTED' if complete and good else 'UNVERIFIED'
        result['gate_results']['reference_boundary_gate']='REFERENCE_ONLY_NOT_POLICY_EFFECTIVE_DATE'
    else:
        result['gate_results']['population_coverage_gate']='MISSING'
        result['gate_results']['exact_id_symbol_time_gate']='MISSING'
        result['gate_results']['reference_boundary_gate']='UNVERIFIED'
    result['gate_results'].update({
        'producer_origin_attestation':'UNVERIFIED',
        'runtime_feature_activation_attestation':'UNVERIFIED',
        'provider_availability_at_decision':'UNVERIFIED',
        'cross_database_snapshot_consistency':'UNVERIFIED',
        'full_historical_decision_replay':'UNVERIFIED'})
    result['remaining_gates']=[k for k,v in result['gate_results'].items() if v not in ('PASS',)]
    if s and result['population_gate']['reconciled']:
        result['status']='LINKAGE_POPULATION_RECONCILED_RUNTIME_NOT_ATTESTED'
    elif s:
        result['status']='SEMANTIC_FIXTURES_PASSED_LINKAGE_NOT_RECONCILED'
    return result


def save(path,obj,protected_root=None):
    dest=Path(path).resolve()
    if protected_root:
        root=Path(protected_root).resolve()
        if dest==root or root in dest.parents:raise ValueError('OUTPUT_INSIDE_PRODUCTION_DATA_REJECTED')
    dest.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.apex312-',dir=dest.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf8') as f:
            json.dump(obj,f,sort_keys=True,indent=2);f.write('\n')
        os.chmod(tmp,0o600);os.replace(tmp,dest)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode',required=True,choices=['review','local-audit'])
    p.add_argument('--stage3b310-report',help='Existing aggregate report (review mode)')
    p.add_argument('--stage3b311-report',help='Downloaded GitHub Actions JSON')
    p.add_argument('--root',default='/data',help='Read-only APEX DB directory (local-audit only)')
    p.add_argument('--boundary',default=REFERENCE)
    p.add_argument('--deployment-history',help='Stage3B38 deployment history JSON')
    p.add_argument('--native-evidence',help='Stage3B38 Render native JSON')
    p.add_argument('--max-rows',type=int,default=10000)
    p.add_argument('--batch-size',type=int,default=200)
    p.add_argument('--query-budget-ms',type=int,default=500)
    p.add_argument('--total-budget-ms',type=int,default=20000)
    p.add_argument('--output',required=True)
    args=p.parse_args(argv)
    if args.mode=='local-audit' and args.stage3b310_report:p.error('Do not mix --stage3b310-report with local-audit')
    if args.mode=='review' and not args.stage3b310_report:p.error('review requires --stage3b310-report')
    semantic,ss,sh=load_report(args.stage3b311_report,'apex.stage3b311_semantic_replay.v1')
    sources={'stage3b311':ss}; hashes={'stage3b311':sh} if sh else {}
    if args.mode=='local-audit':
        # No historical source execution. Reuses existing B310 indexed SQLite lookups.
        from apex_stage3b310_origin_population_audit import audit,write_report
        from apex_stage3b39_runtime_decision_gamma_audit import parse_time,deployment_boundary
        boundary=parse_time(args.boundary)
        if not boundary:p.error('boundary must be timezone-aware ISO-8601')
        pop=audit(args.root,boundary=boundary,max_rows=args.max_rows,batch_size=args.batch_size,
                  query_ms=args.query_budget_ms,total_ms=args.total_budget_ms)
        pop['deployment_provenance']=deployment_boundary(args.deployment_history,args.native_evidence,
          service='srv-d7p3u2navr4c73d2q0jg',deploy_id='dep-damjvajncjis73dmepo0',
          commit_sha='e14c343dcd14b9987a92a45dda44bbbdf54a60e4')
        if pop['deployment_provenance'].get('deployment_completion_correlated') and \
                parse_time(pop['deployment_provenance']['completion_time'])!=boundary:
            pop['deployment_provenance']['deployment_completion_correlated']=False
            pop['deployment_provenance']['state']='BOUNDARY_TIMESTAMP_CONFLICT'
        sources['stage3b310']='LOCALLY_RECOMPUTED_READ_ONLY'
    else:
        pop,ps,ph=load_report(args.stage3b310_report,'apex.stage3b310_record_origin_gamma_population_coverage.v1')
        sources['stage3b310']=ps
        if ph:hashes['stage3b310']=ph
    report=evaluate(pop,semantic,source_states=sources,source_hashes=hashes)
    report['input_mode']=args.mode
    save(args.output,report,protected_root=args.root if args.mode=='local-audit' else None)
    print('Stage 3B.3.12:',report['status'],'|',report['migration_authority'])
    return 0 if pop is not None and semantic is not None else 2

if __name__=='__main__':raise SystemExit(main())
