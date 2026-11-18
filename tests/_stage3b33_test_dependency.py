#!/usr/bin/env python3
"""APEX Stage 3B.3.3: bounded, read-only deployment/policy provenance reconciliation.

Repository release documents describe intent, not deployed behavior. External export
is untrusted and local Git commit-object checks are independent only of the export,
not proof of successful runtime activation. Never grants record classification or migration.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess

SCHEMA = 'apex.stage3b33_deployment_gamma_contract_reconciliation.v1'
DOCUMENT = 'APEX_69_10_14_CANONICAL_GAMMA_EVIDENCE_IDENTITY_DECISION_TIME_PROVENANCE.md'
BUILD = 'APEX_69_10_14_BUILD_REPORT.md'
CHANGED = 'APEX_69_10_14_CHANGED_FILES.md'
SOURCE_MODULES = ('engine/gamma_transition.py', 'engine/evidence_pipeline.py',
                  'engine/historical_evidence_lifecycle.py', 'engine/trigger_observatory.py',
                  'engine/evidence_eligibility.py')
CONTRACT_MARKERS = {
 'CANONICAL_IDENTITY': ('canonical_gamma_snapshot_id',),
 'LEGACY_UNKNOWN': ('LEGACY_OR_UNKNOWN',),
 'NO_LATEST_BACKFILL': ('does **not** query the latest gamma snapshot',),
 'NO_RETROACTIVE_RECLASSIFICATION': ('rather than being retroactively reclassified',),
}
SHA = re.compile(r'^[0-9a-fA-F]{40}$')
HEX = re.compile(r'^[0-9a-fA-F]{64}$')
VER = re.compile(r'^[0-9]+(?:\.[0-9]+){2}$')

def read_bounded(root: Path, relative: str, max_bytes: int=250000) -> bytes|None:
    base=root.resolve()
    p=(base/relative).resolve()
    if base not in p.parents or not p.is_file() or p.stat().st_size>max_bytes:
        return None
    return p.read_bytes()

def timestamp(raw):
    if not isinstance(raw,str) or len(raw)>45:return None
    try:
        t=datetime.fromisoformat(raw.replace('Z','+00:00'))
        return t.astimezone(timezone.utc) if t.tzinfo is not None else None
    except ValueError:return None

def source_contract(repo):
    files={}
    for name in (DOCUMENT,BUILD,CHANGED,'config/apex_release_manifest.json')+SOURCE_MODULES:
        raw=read_bounded(repo,name,1000000)
        files[name]={'present':raw is not None,
                     'sha256':hashlib.sha256(raw).hexdigest() if raw is not None else None}
    raw=read_bounded(repo,DOCUMENT)
    content=raw.decode('utf8','replace') if raw is not None else ''
    rules={key:all(token in content for token in needles) for key,needles in CONTRACT_MARKERS.items()}
    return {'source_is_deployment_attestation':False, 'rules_documented':rules,
            'documentation_complete':all(rules.values()), 'source_file_fingerprints':files}

def git_blob(repo:Path,commit:str,path:str):
    if not SHA.fullmatch(commit):return None,'INVALID_SHA'
    if not (repo/'.git').exists():return None,'GIT_HISTORY_UNAVAILABLE'
    try:
        result=subprocess.run(['git','-C',str(repo),'show',f'{commit}:{path}'],
                              capture_output=True,timeout=2,check=False)
    except (OSError,subprocess.TimeoutExpired):return None,'GIT_OBJECT_QUERY_FAILED'
    if result.returncode != 0:return None,'GIT_OBJECT_UNAVAILABLE'
    if len(result.stdout)>1000000:return None,'GIT_BLOB_OVERSIZE'
    return result.stdout,None

def git_validate(repo,commit):
    # Checks repository object presence and policy implementation marker consistency.
    doc,err=git_blob(repo,commit,DOCUMENT)
    if err:return {'state':err,'code_contract_verified':False}
    dtext=doc.decode('utf8','replace')
    rules=all(all(tok in dtext for tok in markers) for markers in CONTRACT_MARKERS.values())
    code_ok=True
    for module in SOURCE_MODULES:
        src,e=git_blob(repo,commit,module)
        if e or b'canonical_gamma_snapshot_id' not in src:code_ok=False
    return {'state':'GIT_POLICY_CONTRACT_MARKERS_PRESENT' if (rules and code_ok) else 'GIT_POLICY_CONTRACT_NOT_ESTABLISHED',
            'documented_markers_present':rules,'code_contract_verified':rules and code_ok,
            'commit_document_sha256':hashlib.sha256(doc).hexdigest()}

def read_export(path,max_items):
    if not path:return [],'NO_DEPLOYMENT_EXPORT_SUPPLIED'
    p=Path(path)
    if not p.is_file() or p.stat().st_size>1024*1024:return [],'EXPORT_UNAVAILABLE_OR_OVERSIZE'
    try:
        raw=json.loads(p.read_text(encoding='utf8'))
    except (ValueError,UnicodeError):return [],'EXPORT_INVALID_JSON'
    if not isinstance(raw,dict) or not isinstance(raw.get('deployments'),list):return [],'EXPORT_INVALID_SCHEMA'
    if len(raw['deployments'])>max_items:return [],'EXPORT_EXCEEDS_MAX_ITEMS'
    return raw['deployments'],'EXPORT_PROVIDED_NOT_AUTHENTICATED'

def reconcile(repo,entries,expected_service,max_items):
    counts=Counter(); candidates=[]; observed=[]; git_cache={}
    for item in entries:
        if not isinstance(item,dict):counts['INVALID_ENTRY']+=1;continue
        service=item.get('service_id'); commit=item.get('commit_sha')
        start=timestamp(item.get('started_at'))
        live=timestamp(item.get('live_at'))
        # No permissive status aliases; undefined lifecycle means unverified.
        if expected_service and service !=expected_service:counts['OTHER_SERVICE']+=1;continue
        if not isinstance(service,str) or not service.strip() or not SHA.fullmatch(str(commit or '')):
            counts['MISSING_SERVICE_OR_FULL_COMMIT']+=1;continue
        if not live or not start or live<start:
            counts['INVALID_OR_INCOMPLETE_UTC_DEPLOYMENT_TIMES']+=1;continue
        if item.get('status') != 'live':counts['NOT_EXPLICITLY_LIVE']+=1;continue
        if commit not in git_cache:git_cache[commit]=git_validate(repo,commit)
        check=git_cache[commit]
        if check['code_contract_verified']:
            counts['EXPORTED_LIVE_WITH_GIT_POLICY_MARKERS']+=1
        elif check['state']=='GIT_HISTORY_UNAVAILABLE':
            counts['EXPORTED_LIVE_GIT_HISTORY_UNAVAILABLE']+=1
        else:counts['EXPORTED_LIVE_POLICY_CODE_UNVERIFIED']+=1
        observed.append((live,commit,check['code_contract_verified']))
    observed.sort(key=lambda x:x[0])
    conflict=False
    for i in range(1,len(observed)):
        if observed[i][0]==observed[i-1][0] and observed[i][1]!=observed[i-1][1]:conflict=True
    earliest=next((d for d in observed if d[2]),None)
    last_without=next((d for d in reversed(observed) if not d[2]),None)
    # Times intentionally NOT exported: do not leak precise historical deployment times
    # or imply exact activation instant from a status transition.
    if conflict:counts['CONFLICTING_LIVE_TIMESTAMPS']+=1
    return {'entries_supplied':len(entries),'counts':dict(counts),
      'git_unique_commits_checked':len(git_cache),
      'potential_policy_transition_seen':bool(earliest and last_without and last_without[0]<earliest[0]),
      'conflicting_live_timestamps':conflict,
      'effective_date_verified':False,'runtime_feature_activation_verified':False,
      'export_authenticity_verified':False,
      'limitation':'Deployment export is unauthenticated; Git object contents do not prove deployed runtime feature activation',
      'candidate_intervals_not_classification_authority':True}

def build_report(repo,deployments=None,service_id=None,max_deployments=128):
    repo=Path(repo).resolve()
    entries,status=read_export(deployments,max_deployments)
    d=reconcile(repo,entries,service_id,max_deployments)
    d['export_status']=status
    return {'schema':SCHEMA,'status':'DEPLOYMENT_POLICY_EFFECTIVITY_UNVERIFIED_MIGRATION_BLOCKED',
      'mode':'READ_ONLY_OFFLINE_DEPLOYMENT_POLICY_RESEARCH',
      'migration_authority':'BLOCKED_RESEARCH_ONLY','source_contract':source_contract(repo),
      'deployment_reconciliation':d,
      'record_level_eligibility_verified':False,
      'historical_gamma_effective_date_verified':False,
      'policy_effectivity_rule':'REQUIRES_AUTHENTICATED_DEPLOYMENT_TIMELINE_COMMIT_IMPLEMENTATION_RUNTIME_ACTIVATION_AND_RECORD_ORIGIN',
      'guardrails':{'no_database_reads':True,'no_db_writes':True,'no_backfill':True,
       'no_record_ids_or_payloads_exported':True,'no_automatic_remote_calls':True,
       'no_git_mutations':True,'no_trade_or_execution_authority':True,
       'no_reader_cutover':True,'no_migration':True},
      'remaining_gates':['authenticated_render_deployment_export','git_commit_object_implementation_verification',
       'deployment_runtime_feature_activation_attestation','verified_record_version_origin',
       'cross_database_population_identity','reader_utf8_fix_verified',
       'historical_engine_replay','reader_cutover_coverage','external_backup_restore','isolated_rollback']}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo-root',default='.')
    p.add_argument('--deployments',help='Optional manually exported JSON file; never treated as authenticated')
    p.add_argument('--service-id',default='srv-d7p3u2navr4c73d2q0jg')
    p.add_argument('--max-deployments',type=int,default=128)
    p.add_argument('--output',required=True)
    a=p.parse_args()
    if not 1<=a.max_deployments<=256:p.error('max-deployments must be 1..256')
    output=Path(a.output).resolve()
    repo=Path(a.repo_root).resolve()
    if output==repo or repo in output.parents:p.error('output must be outside repository root')
    report=build_report(repo,a.deployments,a.service_id,a.max_deployments)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n',encoding='utf8')
    print('Stage 3B.3.3 report:',output,'| migration='+report['migration_authority'],
          '| status='+report['status'])
if __name__=='__main__':main()
