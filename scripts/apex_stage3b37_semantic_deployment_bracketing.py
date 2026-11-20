#!/usr/bin/env python3
"""APEX Stage 3B.3.7 — read-only historical gamma source-contract and deployment bracketing.

Historical source is INSPECTED, never executed/imported. Static contracts are *not*
semantic behavior proofs. Render offline evidence is not independent attestation.
Never infers runtime activation, effective dates, historical eligibility, or migration.
"""
from __future__ import annotations
import argparse
import ast
from collections import Counter
import importlib.util
import json
import os
from pathlib import Path
import re

HERE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location('apex_b36',HERE/'apex_stage3b36_gamma_origin_discovery.py')
B36=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(B36)
B35=B36.B35
SHA=B35.SHA
DEFAULT_CANDIDATE='6f15e854b21b6406a570c100d955ccbbb0debe59'
SCHEMA='apex.stage3b37_semantic_contract_deployment_bracketing.v1'
MAX_DEPLOYMENTS=128
MAX_BLOB=512*1024
# Conservatively identify contract elements; never interpret their presence as execution.
CONTRACT={
 'engine/evidence_eligibility.py':{
  'functions':('evaluate_evidence_eligibility',),
  'tokens':('evidence_integrity_available','canonical_gamma_snapshot_id','freshness_state',
            'continuity_state','provenance_class','NON_CONTEMPORANEOUS_GAMMA_PROVENANCE',
            'STALE_CANONICAL_GAMMA_EVIDENCE')},
 'engine/historical_evidence_lifecycle.py':{
  'functions':('_freeze_gamma_evidence','build_snapshot'),
  'tokens':('decision_time_gamma_evidence','LEGACY_OR_UNKNOWN','canonical_gamma_snapshot_id',
            'later_gamma_substitution_allowed','decision_time_frozen')},
 'engine/evidence_pipeline.py':{
  'functions':('record_snapshot',),
  'tokens':('canonical_gamma_snapshot_id','gamma_snapshot_age_seconds','gamma_provenance_class',
            'gamma_evidence')},
 'engine/gamma_transition.py':{
  'functions':('decision_time_gamma_evidence',),
  'tokens':('canonical_gamma_snapshot_id','freshness_state','provenance_class')},
 'engine/trigger_observatory.py':{
  'functions':(),
  'tokens':('canonical_gamma_snapshot_id',)}
}

def inspect_source(repo,sha):
    """Bounded AST/text inspection of one Git tree, without importing its code."""
    details={};complete=True
    for path,spec in CONTRACT.items():
        raw,error=B36.git(repo,'show',f'{sha}:{path}',max_bytes=MAX_BLOB,timeout=8)
        if error:
            details[path]={'state':'SOURCE_UNAVAILABLE','missing_functions':list(spec['functions']),
                           'missing_tokens':list(spec['tokens'])};complete=False;continue
        try:
            s=raw.decode('utf-8','strict');tree=ast.parse(s,filename=path)
        except (UnicodeError,SyntaxError,ValueError):
            details[path]={'state':'SOURCE_NOT_PARSEABLE','missing_functions':[], 'missing_tokens':[]}
            complete=False;continue
        funcs={node.name for node in ast.walk(tree) if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef))}
        missing_f=[x for x in spec['functions'] if x not in funcs]
        missing_t=[x for x in spec['tokens'] if x not in s]
        ok=not missing_f and not missing_t
        complete &= ok
        details[path]={'state':'STATIC_CONTRACT_PRESENT' if ok else 'STATIC_CONTRACT_INCOMPLETE',
                       'missing_functions':missing_f,'missing_tokens':missing_t}
    return {'static_contract_all_modules_present':complete,'module_results':details,
            'semantic_behavior_executed':False,'runtime_activation_verified':False}

def correlated_deployments(history_path,native_path,service_id):
    """Join normalized claims to native successful completion timestamps; fail closed on duplicates."""
    h,hs=B35.load(history_path);n,ns=B35.load(native_path)
    deployments=h.get('deployments',[]) if isinstance(h,dict) else []
    claims=h.get('events',[]) if isinstance(h,dict) else []
    native=n.get('native_events',[]) if isinstance(n,dict) else []
    if not all(isinstance(x,list) for x in (deployments,claims,native)) or len(deployments)>MAX_DEPLOYMENTS or len(claims)>512 or len(native)>1024:
        return [], {'deployment_history':'INVALID_OR_OVERSIZE','native_evidence':ns}, 'INVALID_INPUT'
    normalized={};successful={}
    for e in claims:
        if not isinstance(e,dict) or e.get('service_id')!=service_id or e.get('event_type')!='deploy_activated' or e.get('outcome')!='succeeded':continue
        t=B35.timestamp(e.get('occurred_at'));dep=e.get('deploy_id')
        if t and B35.DEP.fullmatch(str(dep or '')):normalized.setdefault(dep,[]).append(t)
    for e in native:
        if not isinstance(e,dict) or e.get('service_id')!=service_id or e.get('type')!='deploy_ended' or e.get('deploy_status')!='succeeded':continue
        t=B35.timestamp(e.get('timestamp'));dep=e.get('deploy_id')
        if t and B35.DEP.fullmatch(str(dep or '')):successful.setdefault(dep,[]).append(t)
    groups={}
    for d in deployments:
        if isinstance(d,dict) and d.get('service_id')==service_id:
            groups.setdefault(str(d.get('deploy_id')),[]).append(d)
    matches=[];rejected=Counter()
    for dep,rows in groups.items():
        if len(rows)!=1:rejected['DUPLICATE_ID']+=1;continue
        d=rows[0];sha=d.get('commit_sha')
        start=B35.timestamp(d.get('started_at'));end=B35.timestamp(d.get('live_at'))
        if not B35.DEP.fullmatch(dep) or not SHA.fullmatch(str(sha or '')) or not start or not end or end<start or d.get('status') not in ('live','deactivated'):
            rejected['INVALID_DEPLOYMENT']+=1;continue
        if not any(t>=start and abs((t-end).total_seconds())<=10 and any(abs((t-c).total_seconds())<=1 for c in normalized.get(dep,[])) for t in successful.get(dep,[])):
            rejected['EVENT_UNCORROBORATED']+=1;continue
        matches.append({'deploy_id':dep,'sha':sha,'started_at':start,'completed_at':end,'status':d['status']})
    return sorted(matches,key=lambda x:x['completed_at']), {'deployment_history':hs,'native_evidence':ns},dict(rejected)

def run(repo,service_id,history_path,native_path,candidate=DEFAULT_CANDIDATE):
    state=B35.repo_state(repo)
    deployments,inputs,rejected=correlated_deployments(history_path,native_path,service_id)
    candidate_valid=bool(SHA.fullmatch(str(candidate))) and state=='EXTERNAL_GIT_REPOSITORY_READABLE'
    parent=None;current=None;parent_state='UNVERIFIED'
    if candidate_valid:
        pp,err=B36.parents(repo,candidate)
        if err:parent_state=err
        elif len(pp)!=1:parent_state='NOT_SINGLE_PARENT'
        else:
            parent=pp[0]
            current=inspect_source(repo,candidate)
            previous=inspect_source(repo,parent)
            parent_state='BOTH_SOURCE_TREES_INSPECTED'
    else:previous=None
    semantic={'state':'HISTORICAL_SOURCE_UNVERIFIED','candidate_static_contract_present':False,
              'parent_static_contract_present':None,'static_contract_introduced_at_candidate':False,
              'historical_behavior_executed':False,'first_semantic_implementation_verified':False,
              'source_module_states':{},'parent_module_states':{}}
    if current is not None and previous is not None:
        c=current['static_contract_all_modules_present'];p=previous['static_contract_all_modules_present']
        semantic.update({'state':'STATIC_CONTRACT_INTRODUCTION_CANDIDATE' if c and not p else
                         'STATIC_CONTRACT_PREEXISTING' if c and p else 'STATIC_CONTRACT_INCOMPLETE',
                         'candidate_static_contract_present':c,'parent_static_contract_present':p,
                         'static_contract_introduced_at_candidate':bool(c and not p),
                         'source_module_states':{k:v['state'] for k,v in current['module_results'].items()},
                         'parent_module_states':{k:v['state'] for k,v in previous['module_results'].items()}})
    before=[];after=[];unverified=[]
    if candidate_valid:
        for d in deployments:
            # Only ancestry comparison; don't infer that timestamp determines code presence.
            relation=B36.is_ancestor(repo,candidate,d['sha'])
            if relation=='ANCESTOR':after.append(d)
            elif relation=='NOT_ANCESTOR':
                # Prove pre-introduction only if a deployment is an ancestor of the candidate.
                reverse=B36.is_ancestor(repo,d['sha'],candidate)
                if reverse=='ANCESTOR':before.append(d)
                else:unverified.append(d)
            else:unverified.append(d)
    else:unverified=deployments[:]
    # Bracketing additionally requires a chronological before/after deployment (non-overlapping).
    pairs=[(a,b) for a in before for b in after if a['completed_at']<b['started_at']]
    bracket=sorted(pairs,key=lambda q:(q[1]['started_at']-q[0]['completed_at']).total_seconds())[0] if pairs else None
    states={'before':len(before),'after':len(after),'unclassifiable':len(unverified)}
    summary={'schema':SCHEMA,'mode':'READ_ONLY_GAMMA_SEMANTIC_SOURCE_AND_OFFLINE_DEPLOYMENT_BRACKETING',
       'status':'STATIC_CONTRACT_AND_OFFLINE_DEPLOYMENT_BRACKET_CANDIDATE' if bracket and semantic['static_contract_introduced_at_candidate'] else
                'STATIC_SOURCE_INSPECTED_DEPLOYMENT_BOUNDARY_UNVERIFIED' if current is not None else 'SOURCE_PROVENANCE_UNVERIFIED',
       'migration_authority':'BLOCKED_RESEARCH_ONLY',
       'inputs':{'git_repository':state,**inputs,'provider_export_authenticated':False},
       'observations':{'candidate_parent_state':parent_state,'semantic_source_contract':semantic,
            'deployments_correlated':len(deployments),'deployment_relation_counts':states,
            'offline_before_after_bracket_candidate':bracket is not None,
            'before_after_bracket_is_authenticated':False,
            'historical_policy_effective_date_verified':False,'runtime_gamma_activation_verified':False,
            'record_origin_verified':False,'record_eligibility_verified':False,
            'rejected_deployments':rejected},
       'guardrails':{'read_only':True,'no_database_access':True,'no_remote_calls':True,
            'no_fetch_or_clone':True,'no_git_mutations':True,'no_historical_code_execution':True,
            'no_migration':True,'no_reader_cutover':True,'no_trade_execution':True,
            'no_policy_effective_date_assigned':True,'no_ids_or_shas_in_public_summary':True},
       'limitations':['Static AST/token checks are not functional correctness or semantic execution proof',
            'Parent-child source comparison does not rule out preexisting equivalent behavior',
            'Git ancestry and successful Render deploy events do not prove gamma runtime activation',
            'Offline Render JSON cannot independently authenticate a deployment boundary',
            'A before/after bracket requires historical Render records; recent samples alone do not suffice',
            'No decision-time database records, gamma payloads or replay were examined'],
       'remaining_gates':['isolated_historical_behavior_tests','independent_git_source_authentication',
          'provider_authenticated_historical_deployment_boundary','runtime_activation_attestation',
          'record_origin_correlation','historical_record_eligibility','utf8_reader_fix',
          'historical_replay','external_backup_restore','isolated_rollback']}
    details={'schema':'apex.stage3b37_private_details.v1',
       'warning':'Untrusted offline provenance; these IDs are not policy-effective-date or eligibility authority',
       'candidate_sha':candidate,'candidate_parent_sha':parent,
       'source_contract_detail':current,'parent_contract_detail':previous,
       'deployment_bracket_candidate':({'before_deployment_id':bracket[0]['deploy_id'],
           'before_sha':bracket[0]['sha'],'before_completed_at':bracket[0]['completed_at'].isoformat(),
           'after_deployment_id':bracket[1]['deploy_id'],'after_sha':bracket[1]['sha'],
           'after_started_at':bracket[1]['started_at'].isoformat()} if bracket else None)}
    return summary,details

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--git-repository',required=True)
    p.add_argument('--candidate-sha',default=DEFAULT_CANDIDATE)
    p.add_argument('--service-id',required=True)
    p.add_argument('--deployment-history',required=True)
    p.add_argument('--native-evidence',required=True)
    p.add_argument('--output',required=True)
    p.add_argument('--private-details-output')
    a=p.parse_args()
    if not SHA.fullmatch(a.candidate_sha):p.error('candidate SHA must be 40 lowercase hex digits')
    outputs=[Path(a.output).resolve()]
    if a.private_details_output:outputs.append(Path(a.private_details_output).resolve())
    if len(set(outputs))!=len(outputs):p.error('output paths must be distinct')
    repo=Path(a.git_repository).resolve()
    if any(p==repo or repo in p.parents for p in outputs):p.error('outputs must be outside the Git repository')
    summary,details=run(repo,a.service_id,a.deployment_history,a.native_evidence,a.candidate_sha)
    B36.write_json(outputs[0],summary)
    if a.private_details_output:B36.write_json(outputs[1],details,private=True)
    print('Stage 3B.3.7 report:',outputs[0],'| status='+summary['status'],'| migration='+summary['migration_authority'])
if __name__=='__main__':main()
