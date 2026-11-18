#!/usr/bin/env python3
"""APEX Stage 3B.3.2 — versioned gamma policy provenance, research only.

Reads repository documents/manifest and optionally bounded production SQLite metadata.
Never infers rule effective-at-row-time from release number, timestamps, or missing IDs.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time

SCHEMA='apex.stage3b32_historical_gamma_policy_provenance.v1'
REQUIRED_DOC='APEX_69_10_14_CANONICAL_GAMMA_EVIDENCE_IDENTITY_DECISION_TIME_PROVENANCE.md'
REQUIRED_MANIFEST='config/apex_release_manifest.json'
DOCUMENTED_RULES=(
 ('CANONICAL_GAMMA_LINKAGE_CREATED','canonical_gamma_snapshot_id','canonical gamma snapshot ID'),
 ('LEGACY_NULL_REMAINS_UNKNOWN','LEGACY_OR_UNKNOWN','LEGACY_OR_UNKNOWN'),
 ('NO_LATEST_GAMMA_BACKFILL','does **not** query the latest gamma snapshot','does **not** query the latest gamma snapshot'),
 ('LEGACY_PREEXISTING_BEHAVIOR','rather than being retroactively reclassified','rather than being retroactively reclassified'),
)
TABLES={
 'DECISION':('apex_evidence_pipeline.db','decisions','decision_id','ticker','observed_at','gamma_provenance_class'),
 'TRIGGER':('apex_trigger_observatory.db','observed_trade_triggers','trigger_id','symbol','triggered_at',None),
}

def sha(b):return hashlib.sha256(b).hexdigest()

def _safe_file(repo,relative,maximum=100000):
    p=(repo/relative).resolve()
    if repo not in p.parents or not p.is_file() or p.stat().st_size>maximum:
        return None
    return p.read_bytes()

def source_evidence(repo):
    out={'source_snapshot':'LOCAL_REPOSITORY_NOT_DEPLOYMENT_ATTESTATION',
         'documented_contracts':[], 'manifest':{}, 'repository_evidence_complete':False,
         'historical_policy_effective_dates_verified':False,
         'historical_rule_status':'NO_INDEPENDENTLY_VERIFIED_EFFECTIVE_DATED_RULE',
         'document_semantics_not_production_behavior_proof':True}
    raw=_safe_file(repo,REQUIRED_DOC)
    if raw is not None:
        doc=raw.decode('utf-8',errors='replace')
        # Captures documented semantics, not proof that a release was running.
        for name,needle,_ in DOCUMENTED_RULES:
            out['documented_contracts'].append({'rule':name,'documented':needle in doc,
                'source_file':REQUIRED_DOC,'source_sha256':sha(raw),
                'effective_at_historical_row':'UNVERIFIED','classification_authority':False})
    else:
        out['documented_contracts']=[{'rule':name,'documented':False,
         'source_file':REQUIRED_DOC,'effective_at_historical_row':'UNVERIFIED',
         'classification_authority':False} for name,_,_ in DOCUMENTED_RULES]
    manifest_raw=_safe_file(repo,REQUIRED_MANIFEST,maximum=250000)
    if manifest_raw is not None:
        try:
            obj=json.loads(manifest_raw)
            out['manifest']={'file_sha256':sha(manifest_raw),
              'apex_version':str(obj.get('apex_version',''))[:64],
              'released_at_claim':str(obj.get('released_at',''))[:64],
              'release_is_verified_deployment_at_historical_time':False,
              'snapshot_schema_version':str(obj.get('database_schema_version',''))[:64]}
        except (ValueError,TypeError):out['manifest']={'status':'INVALID_JSON'}
    else:out['manifest']={'status':'UNAVAILABLE_OR_OVERSIZE'}
    out['repository_evidence_complete']=bool(raw is not None and manifest_raw is not None and
             all(r['documented'] for r in out['documented_contracts']))
    return out

def _ro(path):
    if not path.is_file():return None
    con=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=.2)
    con.row_factory=sqlite3.Row
    con.execute('PRAGMA query_only=ON')
    return con

def _bounded(con,sql,args,deadline,query_ms):
    if time.monotonic()>deadline:return None,'TOTAL_BUDGET_EXHAUSTED'
    stop=min(deadline,time.monotonic()+query_ms/1000)
    calls=[0]
    def progress():
        calls[0]+=1
        return int(calls[0]>20000 or time.monotonic()>stop)
    con.set_progress_handler(progress,100)
    try:return con.execute(sql,args).fetchall(),None
    except sqlite3.Error as e:
        return None,'QUERY_INTERRUPTED' if 'interrupt' in str(e).lower() else 'QUERY_UNAVAILABLE'
    finally:con.set_progress_handler(None,0)

def sample_db(root,sample_rows,query_ms,total_ms):
    results={}
    deadline=time.monotonic()+total_ms/1000
    for kind,(database,table,key,ticker,date,prov) in TABLES.items():
        item={'status':'NOT_RUN','sampled':0,'cohort':'OLDEST_AND_NEWEST',
              'gamma_linkage_presence':{},'provenance_presence':{},
              'historical_rule_eligibility':{'UNVERIFIABLE_HISTORICAL_POLICY':0},
              'deployment_contract_at_record_time_verified':False,
              'legacy_null_is_not_a_violation':True,'population_representative':False,
              'payloads_or_identifiers_exported':False}
        results[kind]=item
        con=_ro(root/database)
        if con is None:item['status']='DATABASE_UNAVAILABLE';continue
        try:
            # Source primary-key indexes are not required for edge scans; require bounded rowid plan.
            fields=f'"{key}","{ticker}","{date}",canonical_gamma_snapshot_id'
            if prov:fields+=f',"{prov}"'
            collected={}
            errors=[]
            for edge in ('ASC','DESC'):
                rows,error=_bounded(con,f'SELECT {fields} FROM "{table}" ORDER BY rowid {edge} LIMIT ?',
                                    (sample_rows,),deadline,query_ms)
                if error:errors.append(error);continue
                for r in rows: collected.setdefault(r[0],r)
            counts=Counter('GAMMA_ID_PRESENT_UNVERIFIED' if r[3] else 'GAMMA_ID_NULL_OR_UNLINKED' for r in collected.values())
            item['sampled']=len(collected)
            item['gamma_linkage_presence']=dict(counts)
            if prov:
                item['provenance_presence']=dict(Counter('PRESENT_NOT_RULE_PROOF' if r[4] else 'ABSENT' for r in collected.values()))
            item['historical_rule_eligibility']={'UNVERIFIABLE_HISTORICAL_POLICY':len(collected)}
            item['status']='SAMPLED_HISTORICAL_RULE_UNVERIFIED' if collected else 'NO_ROWS_OR_LIMIT'
            if errors:item['query_states']=dict(Counter(errors))
        finally:con.close()
    return results

def build_report(repo,root=None,sample_rows=4,query_ms=400,total_ms=8000):
    result={'schema':SCHEMA,'mode':'READ_ONLY_HISTORICAL_POLICY_RESEARCH',
      'migration_authority':'BLOCKED_RESEARCH_ONLY',
      'source_evidence':source_evidence(repo),
      'production_rule_eligibility_verified':False,
      'version_number_does_not_establish_effective_policy':True,
      'missing_link_not_deemed_defect_or_exemption':True,
      'guardrails':{'no_sqlite_writes':True,'no_backfill':True,'no_archive_blob_reads':True,
        'no_payload_export':True,'no_record_identifiers_export':True,
        'no_checkpoint':True,'no_vacuum':True,'no_delete':True,
        'no_trading_execution_authority':True,'no_reader_cutover':True},
      'limits':{'sample_rows_per_edge_per_type':sample_rows,'query_budget_ms':query_ms,'total_budget_ms':total_ms},
      'production_record_samples':None,
      'requirements_for_historical_classification':[
        'INDEPENDENT_EFFECTIVE_DATED_POLICY_AND_RELEASE_ATTESTATION',
        'VERIFIED_RECORD_TIME_AND_VERSION_ORIGIN',
        'EVIDENCE_TYPE_AND_ELIGIBILITY_CONTEXT',
        'SOURCE_IDENTITY_AND_GAMMA_LINK_PROVENANCE'],
      'remaining_gates':['historical_rule_deployment_provenance',
       'cross_database_population_identity','reader_utf8_fix_verified',
       'historical_engine_replay','reader_cutover_coverage',
       'external_backup_restore','isolated_rollback']}
    if root is not None:result['production_record_samples']=sample_db(root,sample_rows,query_ms,total_ms)
    result['status']='HISTORICAL_POLICY_DOCUMENTED_EFFECTIVITY_UNVERIFIED_MIGRATION_BLOCKED'
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo-root',default='.')
    p.add_argument('--root',default=None,help='Optional production root, read-only metadata only')
    p.add_argument('--sample-rows',type=int,default=4)
    p.add_argument('--query-budget-ms',type=int,default=400)
    p.add_argument('--total-budget-ms',type=int,default=8000)
    p.add_argument('--output',required=True)
    a=p.parse_args()
    repo=Path(a.repo_root).resolve()
    root=Path(a.root).resolve() if a.root else None
    output=Path(a.output).resolve()
    if root and (output==root or root in output.parents):p.error('output must be outside read-only database root')
    if a.sample_rows<1 or a.sample_rows>16 or not 20<=a.query_budget_ms<=1000 or not 100<=a.total_budget_ms<=20000:
        p.error('sample rows 1..16, query budget 20..1000ms, total budget 100..20000ms')
    report=build_report(repo,root,a.sample_rows,a.query_budget_ms,a.total_budget_ms)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf-8')
    print('Stage 3B.3.2 report:',output,'| migration='+report['migration_authority'],'| status='+report['status'])
if __name__=='__main__':main()
