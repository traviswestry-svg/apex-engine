#!/usr/bin/env python3
"""Stage 3B.3.4: bounded offline gamma implementation commit and runtime-evidence audit.

Operator initiated, read-only. Provider-derived JSON is NOT an independent attestation.
A successful Render deploy does not prove runtime activation or historical record origin.
No policy-effective dates, historical eligibility, migrations or trades are authorized.
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

SCHEMA='apex.stage3b34_gamma_commit_runtime_provenance.v1'
SHA=re.compile(r'^[0-9a-f]{40}$')
DEP=re.compile(r'^dep-[A-Za-z0-9]+$')
MAX_BYTES=2*1024*1024
# These are heuristics only, not a proof of a running code path.
MODULES=('engine/evidence_pipeline.py','engine/evidence_eligibility.py','engine/gamma_transition.py',
         'engine/historical_evidence_lifecycle.py','engine/trigger_observatory.py')
MARKERS=(b'canonical_gamma_snapshot_id',b'LEGACY_OR_UNKNOWN')

def stamp(v):
    if not isinstance(v,str) or len(v)>48:return None
    try:
        t=datetime.fromisoformat(v.replace('Z','+00:00'))
        if t.tzinfo is None:return None
        return t.astimezone(timezone.utc)
    except ValueError:return None

def load(path,limit=MAX_BYTES):
    if not path:return None,'MISSING'
    p=Path(path)
    if not p.is_file() or p.stat().st_size>limit:return None,'UNAVAILABLE_OR_OVERSIZE'
    try:
        x=json.loads(p.read_bytes())
        return x,'LOADED' if isinstance(x,dict) else 'INVALID_SCHEMA'
    except (ValueError,UnicodeError,OSError):return None,'INVALID_JSON'

def git(repo,*args,timeout=3,max_bytes=300000):
    if not (repo/'.git').exists():return None,'GIT_HISTORY_UNAVAILABLE'
    try:
        r=subprocess.run(['git','-C',str(repo),*args],capture_output=True,check=False,timeout=timeout)
    except (OSError,subprocess.TimeoutExpired):return None,'GIT_QUERY_FAILED'
    if r.returncode:return None,'GIT_OBJECT_UNAVAILABLE'
    if len(r.stdout)>max_bytes:return None,'GIT_OUTPUT_OVERSIZE'
    return r.stdout,None

def classify_commit(repo,sha,cache):
    if sha in cache:return cache[sha]
    if not SHA.fullmatch(str(sha or '')):
        return {'state':'INVALID_COMMIT','code_markers_seen':False}
    row,err=git(repo,'rev-list','--parents','-n','1',sha)
    if err:
        out={'state':err,'code_markers_seen':False};cache[sha]=out;return out
    fields=row.decode('ascii','replace').strip().split()
    if not fields or fields[0]!=sha:
        out={'state':'GIT_OBJECT_IDENTITY_UNVERIFIED','code_markers_seen':False};cache[sha]=out;return out
    parent=fields[1] if len(fields)>1 else None
    file_states={}; marker_hits={k:False for k in MARKERS}; source_count=0
    for module in MODULES:
        blob,error=git(repo,'show',f'{sha}:{module}',max_bytes=300000)
        if error:file_states[module]=error;continue
        source_count+=1;file_states[module]='PRESENT'
        for k in MARKERS:
            marker_hits[k]=marker_hits[k] or k in blob
    out={'state':'GIT_COMMIT_INSPECTED','code_markers_seen':all(marker_hits.values()),
         'modules_available':source_count,'modules_expected':len(MODULES),
         'parent_available':bool(parent),'code_coverage_partial':source_count<len(MODULES),
         'implementation_contract_verified':False,
         'runtime_activation_verified':False}
    if parent and SHA.fullmatch(parent):
        parent_hits={k:False for k in MARKERS};available=0
        for module in MODULES:
            blob,error=git(repo,'show',f'{parent}:{module}',max_bytes=300000)
            if error:continue
            available+=1
            for k in MARKERS:parent_hits[k]=parent_hits[k] or k in blob
        out['parent_markers_seen']=all(parent_hits.values()) if available==len(MODULES) else None
        out['parent_code_coverage_partial']=available<len(MODULES)
    else:out['parent_markers_seen']=None;out['parent_code_coverage_partial']=True
    cache[sha]=out
    return out

def run(repo,history_path,proof_path,service_id,max_deployments=128,max_events=256,runtime_path=None):
    history,hstate=load(history_path);proof,pstate=load(proof_path)
    counts=Counter();git_counts=Counter();cache={};candidate=[];matched=set()
    deployments=history.get('deployments',[]) if isinstance(history,dict) else []
    events=history.get('events',[]) if isinstance(history,dict) else []
    native=proof.get('native_events',[]) if isinstance(proof,dict) else []
    if not isinstance(deployments,list) or not isinstance(events,list) or not isinstance(native,list):
        deployments=[];events=[];native=[];hstate='INVALID_SCHEMA'
    if len(deployments)>max_deployments or len(events)>max_events or len(native)>max_events*2:
        deployments=[];events=[];native=[];hstate='OVER_LIMIT'
    # Correlate a raw provider success to the normalized claim: independent *data shape* only.
    native_success=set()
    for ev in native:
        if not isinstance(ev,dict) or ev.get('service_id')!=service_id:continue
        if ev.get('type')=='deploy_ended' and ev.get('deploy_status')=='succeeded' and DEP.fullmatch(str(ev.get('deploy_id') or '')) and stamp(ev.get('timestamp')):
            native_success.add((ev['deploy_id'],stamp(ev['timestamp'])))
    claims={}
    for ev in events:
        if not isinstance(ev,dict) or ev.get('service_id')!=service_id:continue
        if ev.get('event_type')!='deploy_activated' or ev.get('outcome')!='succeeded':continue
        ts=stamp(ev.get('occurred_at'))
        if ts:claims.setdefault(ev.get('deploy_id'),[]).append(ts)
    duplicates=set();seen={}
    for d in deployments:
        if not isinstance(d,dict) or d.get('service_id')!=service_id:counts['INVALID_OR_OTHER_SERVICE']+=1;continue
        dep=d.get('deploy_id');sha=d.get('commit_sha');start=stamp(d.get('started_at'));end=stamp(d.get('live_at'))
        if not DEP.fullmatch(str(dep or '')) or not SHA.fullmatch(str(sha or '')) or start is None or end is None or end<start:
            counts['INVALID_DEPLOYMENT']+=1;continue
        if dep in seen:
            duplicates.add(dep);counts['DUPLICATE_DEPLOYMENT']+=1;continue
        seen[dep]=(sha,d.get('status'),start,end)
    for dep in duplicates:seen.pop(dep,None)
    for dep,(sha,status,start,end) in seen.items():
        if status not in ('live','deactivated'):
            counts['FAILED_OR_UNKNOWN_STATE']+=1;continue
        linked=any((dep,t) in native_success and t>=start and any(abs((t-c).total_seconds())<1 for c in claims.get(dep,[])) for t in claims.get(dep,[]))
        if linked:counts['NATIVE_SUCCESS_NORMALIZED_CLAIM_MATCH']+=1
        else:counts['NO_MATCHED_NATIVE_COMPLETION']+=1;continue
        if status=='deactivated':counts['REPLACED_DEPLOYMENT_WITH_SUCCESS_CLAIM']+=1
        checked=classify_commit(repo,sha,cache)
        git_counts[checked['state']]+=1
        if checked.get('code_markers_seen'):
            counts['GIT_CODE_MARKERS_PRESENT']+=1
            if checked.get('parent_markers_seen') is False and not checked.get('parent_code_coverage_partial'):
                counts['PARENT_TO_COMMIT_MARKER_INTRODUCTION_CANDIDATE']+=1
            elif checked.get('parent_markers_seen') is True:
                counts['POLICY_MARKERS_ALREADY_IN_PARENT']+=1
            else:counts['GIT_MARKER_INTRODUCTION_UNBOUNDED']+=1
        else:counts['GIT_CODE_MARKERS_NOT_VERIFIED']+=1
        candidate.append((end,sha,checked.get('code_markers_seen'),checked.get('parent_markers_seen')))
    candidate.sort()
    with_markers=[t for t in candidate if t[2]]
    prior_without=any(t[0]<with_markers[0][0] and not t[2] for t in candidate) if with_markers else False
    # Optional runtime records are UNAUTHENTICATED claims: never classification authority.
    runtime,rstate=load(runtime_path)
    rows=runtime.get('observations',[]) if isinstance(runtime,dict) else []
    rc=Counter()
    if not isinstance(rows,list) or len(rows)>128:
        rows=[];rstate='INVALID_OR_OVER_LIMIT'
    sha_set={x[0] for x in seen.values()}
    for row in rows:
        if not isinstance(row,dict) or row.get('service_id')!=service_id:
            rc['INVALID_OR_OTHER_SERVICE']+=1;continue
        sha=row.get('commit_sha');timestamp=stamp(row.get('observed_at'))
        if not SHA.fullmatch(str(sha or '')) or not timestamp:
            rc['INVALID_PROVENANCE_FIELDS']+=1;continue
        if sha not in sha_set:
            rc['COMMIT_NOT_IN_DEPLOYMENT_COHORT']+=1;continue
        if row.get('feature')!='canonical_gamma_decision_time_identity':
            rc['UNRECOGNIZED_FEATURE']+=1;continue
        if row.get('state')=='enabled':rc['RUNTIME_FEATURE_ENABLED_CLAIM_UNAUTHENTICATED']+=1
        elif row.get('state')=='disabled':rc['RUNTIME_FEATURE_DISABLED_CLAIM_UNAUTHENTICATED']+=1
        else:rc['RUNTIME_FEATURE_STATE_UNKNOWN']+=1
    return {'schema':SCHEMA,'status':'COMMIT_AND_DEPLOYMENT_EVIDENCE_SAMPLED_RUNTIME_ACTIVATION_UNVERIFIED',
            'migration_authority':'BLOCKED_RESEARCH_ONLY','mode':'READ_ONLY_OFFLINE_GAMMA_PROVENANCE',
            'inputs':{'deployment_history':hstate,'native_evidence':pstate,
                      'provider_export_authenticated':False,'native_evidence_is_offline_copy':True,'runtime_claims':rstate},
            'observations':{'deployments_supplied':len(deployments),'normalized_claims_supplied':len(events),
                            'native_events_supplied':len(native),'eligible_deployments':len(seen),
                            'corroborated_deployments':counts['NATIVE_SUCCESS_NORMALIZED_CLAIM_MATCH'],
                            'unique_git_commits_inspected':len(cache),'counts':dict(counts),
                            'git_query_states':dict(git_counts),
                            'runtime_claims_supplied':len(rows),'runtime_claim_states':dict(rc),
                            'sampled_possible_transition_boundary':prior_without,
                            'introduction_established':False,
                            'runtime_gamma_activation_verified':False,'historical_effective_date_verified':False,
                            'record_origin_verified':False,'historical_eligibility_verified':False},
            'limitations':['Git marker presence is not proof of policy behavior, feature gating, or commit first-introduction',
                           'Render deploy success is not runtime gamma feature activation',
                           'Offline native event extracts are not independently authenticated',
                           'Optional runtime observations are untrusted and not proof of feature activation',
                           'Source snapshot may have no Git history, incomplete parents, or shallow commit objects',
                           'No production database or replay was read'],
            'guardrails':{'read_only':True,'no_git_mutations':True,'no_remote_calls':True,
                          'no_database_reads':True,'no_runtime_code_imports':True,
                          'no_record_identifiers_exported':True,'no_deployment_ids_or_commits_exported':True,
                          'no_policy_effective_date_assigned':True,'no_trade_execution':True,
                          'no_migration':True,'no_reader_cutover':True,'no_backfill':True},
            'remaining_gates':['verified_historical_first_implementation_commit','authenticated_historical_render_lifecycle',
                               'independent_runtime_activation_attestation','record_origin_version_mapping',
                               'cross_database_population_identity','stage3b1_utf8_fix_verified',
                               'production_replay_equivalence','reader_cutover_coverage',
                               'external_backup_restore','isolated_restore_rollback']}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo-root',default='.')
    p.add_argument('--service-id',required=True)
    p.add_argument('--deployment-history',required=True)
    p.add_argument('--native-evidence',required=True)
    p.add_argument('--runtime-attestations',help='Optional bounded JSON with observations list; classified as untrusted claims')
    p.add_argument('--max-deployments',type=int,default=128)
    p.add_argument('--max-events',type=int,default=256)
    p.add_argument('--output',required=True)
    a=p.parse_args()
    if not 1<=a.max_deployments<=256 or not 1<=a.max_events<=1024:p.error('invalid item limits')
    repo=Path(a.repo_root).resolve();dest=Path(a.output).resolve()
    if dest==repo or repo in dest.parents:p.error('output must be outside repository root')
    report=run(repo,a.deployment_history,a.native_evidence,a.service_id,a.max_deployments,a.max_events,a.runtime_attestations)
    dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(report,sort_keys=True,indent=2)+'\n',encoding='utf8')
    print('Stage 3B.3.4 report:',dest,'| migration='+report['migration_authority'], '| status='+report['status'])
if __name__=='__main__':main()
