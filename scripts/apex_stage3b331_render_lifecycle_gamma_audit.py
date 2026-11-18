#!/usr/bin/env python3
"""APEX Stage 3B.3.3.1: read-only Render lifecycle / gamma policy evidence reconciliation.

An offline export is NOT authenticated. A historical deployment's current status
'deactivated' neither proves prior activation nor proves failure. An explicit,
deployment-linked activation event can support a CANDIDATE historical transition,
never a policy-effective-date or migration authorization.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime,timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys

SCHEMA='apex.stage3b331_render_lifecycle_gamma_evidence.v1'
SHA=re.compile(r'^[0-9a-fA-F]{40}$')
DEPLOY_ID=re.compile(r'^dep-[a-zA-Z0-9]+$')
EVENT_TYPES={'deploy_live','deploy_activated'}
MAX_EXPORT_BYTES=2*1024*1024

def load_prior(repo:Path):
    path=repo/'scripts'/'apex_stage3b33_deployment_gamma_contract_audit.py'
    if not path.is_file():
        raise FileNotFoundError('Stage 3B.3.3 prerequisite missing: scripts/apex_stage3b33_deployment_gamma_contract_audit.py')
    spec=importlib.util.spec_from_file_location('apex_stage3b33_base',path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def read_export(path,max_deployments,max_events):
    if path is None:return [],[],'NO_DEPLOYMENT_EXPORT_SUPPLIED'
    p=Path(path)
    if not p.is_file() or p.stat().st_size>MAX_EXPORT_BYTES:return [],[],'EXPORT_UNAVAILABLE_OR_OVERSIZE'
    try:doc=json.loads(p.read_text(encoding='utf-8'))
    except (ValueError,UnicodeError):return [],[],'EXPORT_INVALID_JSON'
    if not isinstance(doc,dict) or not isinstance(doc.get('deployments'),list) or not isinstance(doc.get('events',[]),list):
        return [],[],'EXPORT_INVALID_SCHEMA'
    if len(doc['deployments'])>max_deployments or len(doc.get('events',[]))>max_events:
        return [],[],'EXPORT_EXCEEDS_CONFIGURED_LIMITS'
    return doc['deployments'],doc.get('events',[]),'EXPORT_PROVIDED_NOT_AUTHENTICATED'

def reconcile(prior,repo,deployments,events,service_id):
    counts=Counter(); event_counts=Counter();valid={}; event_map={}; git_cache={}; observed=[]
    for entry in deployments:
        if not isinstance(entry,dict):counts['INVALID_DEPLOYMENT_ENTRY']+=1;continue
        if entry.get('service_id')!=service_id:counts['OTHER_SERVICE']+=1;continue
        sha=entry.get('commit_sha'); dep=entry.get('deploy_id')
        started=prior.timestamp(entry.get('started_at')); finished=prior.timestamp(entry.get('live_at'))
        if not SHA.fullmatch(str(sha or '')):counts['MISSING_OR_INVALID_COMMIT']+=1;continue
        if not started or not finished or finished<started:
            counts['INVALID_OR_INCOMPLETE_TIMESTAMPS']+=1;continue
        if not isinstance(dep,str) or not DEPLOY_ID.fullmatch(dep):
            counts['MISSING_OR_INVALID_DEPLOY_ID']+=1;continue
        if dep in valid:
            counts['DUPLICATE_DEPLOY_ID']+=1
            valid.pop(dep,None) # reject ambiguous identity, not last-write wins
            continue
        valid[dep]=(sha,entry.get('status'),started,finished)
    # A duplicate must remain disqualified even if later repeated.
    duplicates={d for d in (e.get('deploy_id') for e in deployments if isinstance(e,dict)) if sum(1 for x in deployments if isinstance(x,dict) and x.get('deploy_id')==d)>1}
    for d in duplicates:valid.pop(d,None)
    for event in events:
        if not isinstance(event,dict):event_counts['INVALID_EVENT']+=1;continue
        if event.get('service_id')!=service_id:event_counts['OTHER_SERVICE']+=1;continue
        dep=event.get('deploy_id')
        if dep not in valid:event_counts['UNMATCHED_DEPLOY_ID']+=1;continue
        when=prior.timestamp(event.get('occurred_at'))
        if when is None:event_counts['INVALID_EVENT_TIMESTAMP']+=1;continue
        if event.get('event_type') not in EVENT_TYPES:
            event_counts['NON_ACTIVATION_EVENT']+=1;continue
        # require status explicitly successful, do not infer from event name alone
        if event.get('outcome')!='succeeded':
            event_counts['ACTIVATION_OUTCOME_NOT_SUCCEEDED']+=1;continue
        sha,status,started,finished=valid[dep]
        if when<started:
            event_counts['EVENT_BEFORE_DEPLOY_START']+=1;continue
        # Event cannot occur after explicit deactivation timestamp if one is available.
        deactivated=next((prior.timestamp(e.get('deactivated_at')) for e in deployments if isinstance(e,dict) and e.get('deploy_id')==dep),None)
        if deactivated and when>deactivated:
            event_counts['EVENT_AFTER_DEACTIVATION']+=1;continue
        event_map.setdefault(dep,[]).append(when)
        event_counts['DEPLOY_LINKED_SUCCESSFUL_ACTIVATION_CLAIM']+=1
    for dep,(sha,status,started,finished) in valid.items():
        has_event=bool(event_map.get(dep))
        if status=='live':
            counts['CURRENT_LIVE_EXPORTED']+=1
            if has_event:counts['CURRENT_LIVE_EVENT_CORROBORATED_IN_EXPORT']+=1
            else:counts['CURRENT_LIVE_NO_LINKED_EVENT']+=1
            potential=True
        elif status=='deactivated':
            if has_event:counts['HISTORICALLY_DEACTIVATED_WITH_LINKED_ACTIVATION_EVENT']+=1;potential=True
            else:counts['HISTORICALLY_DEACTIVATED_ACTIVATION_UNVERIFIED']+=1;potential=False
        else:
            counts['OTHER_OR_FAILED_DEPLOYMENT_STATE']+=1
            potential=False
        if not potential:continue
        if sha not in git_cache:git_cache[sha]=prior.git_validate(repo,sha)
        check=git_cache[sha]
        if check.get('code_contract_verified'):
            counts['CANDIDATE_ACTIVATION_WITH_GIT_POLICY_MARKERS']+=1
        else:counts['CANDIDATE_ACTIVATION_POLICY_IMPLEMENTATION_UNVERIFIED']+=1
        # When event available, prefer first event timestamp over finish time as rough marker.
        marker=min(event_map[dep]) if has_event else finished
        observed.append((marker,sha,bool(check.get('code_contract_verified'))))
    observed.sort(key=lambda x:x[0]);conflicting=False
    for i in range(1,len(observed)):
        if observed[i][0]==observed[i-1][0] and observed[i][1]!=observed[i-1][1]:conflicting=True
    earliest=next((x for x in observed if x[2]),None)
    earlier_without=any((not x[2]) and earliest and x[0]<earliest[0] for x in observed)
    return {'deployments_supplied':len(deployments),'events_supplied':len(events),
        'validated_unique_deployments':len(valid),'counts':dict(counts),'event_counts':dict(event_counts),
        'git_unique_commits_checked':len(git_cache),
        'candidate_transition_interval_seen':bool(earliest and earlier_without and not conflicting),
        'conflicting_candidate_activation_markers':conflicting,
        'event_claims_are_authenticated':False,
        'historical_activation_proven_from_export_alone':False,
        'runtime_gamma_feature_activation_verified':False,
        'historical_gamma_effective_date_verified':False,
        'record_eligibility_verified':False,
        'temporal_boundaries_are_classification_authority':False,
        'limitation':'Offline exports and event claims are untrusted; matching deploy ID + commit + event does not establish independent Render attestation, runtime gamma activation, or record origin.'}

def build_report(repo,deployments_file=None,service_id='srv-d7p3u2navr4c73d2q0jg',max_deployments=128,max_events=256):
    root=Path(repo).resolve();prior=load_prior(root)
    deployments,events,status=read_export(deployments_file,max_deployments,max_events)
    r=reconcile(prior,root,deployments,events,service_id)
    r['export_status']=status
    return {'schema':SCHEMA,'status':'HISTORICAL_LIFECYCLE_EVIDENCE_SAMPLED_EFFECTIVITY_UNVERIFIED_MIGRATION_BLOCKED',
        'migration_authority':'BLOCKED_RESEARCH_ONLY','mode':'READ_ONLY_OFFLINE_LIFECYCLE_RECONCILIATION',
        'source_contract':prior.source_contract(root),'deployment_reconciliation':r,
        'historical_gamma_effective_date_verified':False,'record_level_eligibility_verified':False,
        'guardrails':{'no_automatic_remote_calls':True,'no_database_reads':True,'no_sqlite_writes':True,
            'no_git_mutations':True,'no_backfill':True,'no_reader_cutover':True,'no_migration':True,
            'no_trade_execution_authority':True,'no_deployment_or_record_ids_exported':True},
        'remaining_gates':['authenticated_render_deployment_and_event_attestation',
            'historical_commit_implementation_verified','runtime_gamma_activation_attested',
            'record_origin_correlated_to_deployed_version','population_identity_coverage',
            'stage3b1_reader_utf8_fix_verified','historical_engine_replay_equivalence',
            'reader_cutover_coverage','external_backup_restore','isolated_rollback']}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo-root',default='.')
    p.add_argument('--service-id',default='srv-d7p3u2navr4c73d2q0jg')
    p.add_argument('--deployments')
    p.add_argument('--max-deployments',type=int,default=128)
    p.add_argument('--max-events',type=int,default=256)
    p.add_argument('--output',required=True)
    a=p.parse_args()
    if not 1<=a.max_deployments<=256 or not 1<=a.max_events<=1024:p.error('invalid max item limits')
    repo=Path(a.repo_root).resolve();output=Path(a.output).resolve()
    if output==repo or repo in output.parents:p.error('output must be outside repository root')
    out=build_report(repo,a.deployments,a.service_id,a.max_deployments,a.max_events)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(out,indent=2,sort_keys=True)+'\n')
    print('Stage 3B.3.3.1 report:',output,'| migration='+out['migration_authority'],'| status='+out['status'])

if __name__=='__main__':main()
