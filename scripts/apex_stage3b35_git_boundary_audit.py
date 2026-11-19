#!/usr/bin/env python3
"""APEX Stage 3B.3.5 — read-only external Git provenance and deployment boundary audit.

No Git fetch/clone, database access, deployment changes, historical policy effective-date
assignment, migration, reader cutover, or trade authority. Local Git data is untrusted
until separately authenticated; marker checks are necessary clues, not semantic proof.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess

SCHEMA='apex.stage3b35_git_implementation_boundary.v1'
SHA=re.compile(r'^[0-9a-f]{40}$')
DEP=re.compile(r'^dep-[A-Za-z0-9]+$')
MODULES=('engine/evidence_pipeline.py','engine/evidence_eligibility.py','engine/gamma_transition.py','engine/historical_evidence_lifecycle.py','engine/trigger_observatory.py')
MARKERS=(b'canonical_gamma_snapshot_id',b'LEGACY_OR_UNKNOWN')
MAX_FILE_BYTES=2*1024*1024

def timestamp(v):
    if not isinstance(v,str) or len(v)>48:return None
    try:
        d=datetime.fromisoformat(v.replace('Z','+00:00'))
        return d.astimezone(timezone.utc) if d.tzinfo else None
    except ValueError:return None

def load(path):
    try:
        p=Path(path)
        if not p.is_file() or p.stat().st_size>MAX_FILE_BYTES:return None,'MISSING_OR_OVERSIZE'
        data=json.loads(p.read_bytes())
        return (data,'LOADED') if isinstance(data,dict) else (None,'INVALID_SCHEMA')
    except (OSError,ValueError,UnicodeError):return None,'INVALID_JSON'

def git(repo,*args,limit=262144):
    # Never use network, hooks, pagers, replace refs, external diff or optional locks.
    env=os.environ.copy()
    env.update({'GIT_NO_REPLACE_OBJECTS':'1','GIT_OPTIONAL_LOCKS':'0','GIT_TERMINAL_PROMPT':'0',
                'GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':os.devnull,'GIT_PAGER':'cat',
                'GIT_NO_LAZY_FETCH':'1'})
    try:
        cmd=['git','-C',str(repo),'--no-pager',*args]
        cp=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=3,env=env,check=False)
        if cp.returncode:return None,'OBJECT_UNAVAILABLE_OR_COMMAND_FAILED'
        if len(cp.stdout)>limit:return None,'GIT_OUTPUT_OVERSIZE'
        return cp.stdout,None
    except (OSError,subprocess.TimeoutExpired):return None,'GIT_TIMEOUT_OR_UNAVAILABLE'

def repo_state(repo):
    result,err=git(repo,'rev-parse','--is-inside-work-tree','--is-bare-repository',limit=300)
    if err:return 'GIT_REPOSITORY_UNAVAILABLE'
    lines=result.decode('ascii','replace').strip().splitlines()
    return 'EXTERNAL_GIT_REPOSITORY_READABLE' if len(lines)==2 and all(x in ('true','false') for x in lines) else 'GIT_REPOSITORY_UNVERIFIED'

def commit(repo,sha,cache):
    if sha in cache:return cache[sha]
    if not SHA.fullmatch(str(sha)):
        return {'state':'INVALID_SHA'}
    raw,err=git(repo,'rev-list','--parents','-n','1',sha,limit=200)
    if err:
        result={'state':err};cache[sha]=result;return result
    parts=raw.decode('ascii','replace').strip().split()
    if not parts or parts[0]!=sha or any(not SHA.fullmatch(x) for x in parts):
        result={'state':'COMMIT_OBJECT_IDENTITY_UNVERIFIED'};cache[sha]=result;return result
    if len(parts)>3:
        result={'state':'MULTI_PARENT_HISTORY_UNSUPPORTED'};cache[sha]=result;return result
    presence=[];hit=set()
    for module in MODULES:
        blob,error=git(repo,'show',f'{sha}:{module}')
        if error:presence.append('UNAVAILABLE');continue
        presence.append('PRESENT')
        for marker in MARKERS:
            if marker in blob:hit.add(marker)
    result={'state':'COMMIT_OBJECT_READABLE','all_modules_available':all(v=='PRESENT' for v in presence),
            'marker_set_complete':len(hit)==len(MARKERS),'parent_count':len(parts)-1,
            'implementation_semantics_verified':False}
    parents=[]
    for parent in parts[1:]:
        p=commit_shallow(repo,parent)
        parents.append(p)
    result['parents']=parents
    # Only identify strict direct-parent boundary if all parents have full source coverage
    # and none show all markers. A merge with any parent already marked is not an introduction.
    result['direct_parent_boundary_candidate']=(result['all_modules_available'] and result['marker_set_complete']
        and bool(parents) and all(x['state']=='COMMIT_OBJECT_READABLE' and x['all_modules_available'] and not x['marker_set_complete'] for x in parents))
    result['parents_marker_already_present']=any(x.get('marker_set_complete') for x in parents)
    cache[sha]=result
    return result

def commit_shallow(repo,sha):
    raw,err=git(repo,'cat-file','-t',sha,limit=100)
    if err or raw.strip()!=b'commit':return {'state':'PARENT_OBJECT_UNAVAILABLE'}
    hits=set();complete=True
    for m in MODULES:
        blob,error=git(repo,'show',f'{sha}:{m}')
        if error:complete=False;continue
        for k in MARKERS:
            if k in blob:hits.add(k)
    return {'state':'COMMIT_OBJECT_READABLE','all_modules_available':complete,'marker_set_complete':len(hits)==len(MARKERS)}

def run(repo,history_path,native_path,service_id,max_deployments=128):
    h,hs=load(history_path);n,ns=load(native_path)
    deployments=h.get('deployments',[]) if isinstance(h,dict) else []
    claims=h.get('events',[]) if isinstance(h,dict) else []
    native=n.get('native_events',[]) if isinstance(n,dict) else []
    if not all(isinstance(a,list) for a in (deployments,claims,native)) or len(deployments)>max_deployments or len(claims)>512 or len(native)>1024:
        deployments=[];claims=[];native=[];hs='INVALID_OR_LIMIT_EXCEEDED'
    counts=Counter();git_states=Counter();cache={};seen={};duplicates=set()
    success={}
    for ev in native:
        if not isinstance(ev,dict) or ev.get('service_id')!=service_id or ev.get('type')!='deploy_ended' or ev.get('deploy_status')!='succeeded':continue
        dep=ev.get('deploy_id');t=timestamp(ev.get('timestamp'))
        if DEP.fullmatch(str(dep or '')) and t:success.setdefault(dep,[]).append(t)
    normalized={}
    for ev in claims:
        if not isinstance(ev,dict) or ev.get('service_id')!=service_id or ev.get('event_type')!='deploy_activated' or ev.get('outcome')!='succeeded':continue
        dep=ev.get('deploy_id');t=timestamp(ev.get('occurred_at'))
        if DEP.fullmatch(str(dep or '')) and t:normalized.setdefault(dep,[]).append(t)
    for d in deployments:
        if not isinstance(d,dict) or d.get('service_id')!=service_id:counts['OTHER_SERVICE_OR_INVALID']+=1;continue
        dep=d.get('deploy_id');sha=d.get('commit_sha');start=timestamp(d.get('started_at'));end=timestamp(d.get('live_at'))
        if not DEP.fullmatch(str(dep or '')) or not SHA.fullmatch(str(sha or '')) or start is None or end is None or end<start or d.get('status') not in ('live','deactivated'):
            counts['INVALID_DEPLOYMENT']+=1;continue
        if dep in seen:duplicates.add(dep);continue
        seen[dep]=(sha,start,end,d['status'])
    for dep in duplicates:seen.pop(dep,None)
    counts['DUPLICATE_DEPLOYMENT_IDS']=len(duplicates)
    accepted=[]
    state=repo_state(repo)
    for dep,(sha,start,end,status) in seen.items():
        candidates=success.get(dep,[])
        if not any(t>=start and abs((t-end).total_seconds())<=10 and any(abs((t-v).total_seconds())<=1 for v in normalized.get(dep,[])) for t in candidates):
            counts['DEPLOYMENT_NOT_LIFECYCLE_CORROBORATED']+=1;continue
        counts['DEPLOYMENT_LIFECYCLE_CORROBORATED']+=1
        if status=='deactivated':counts['REPLACED_DEPLOYMENT_SUCCESS_CORROBORATED']+=1
        result=commit(repo,sha,cache) if state=='EXTERNAL_GIT_REPOSITORY_READABLE' else {'state':'GIT_REPOSITORY_UNAVAILABLE'}
        git_states[result['state']]+=1
        if result.get('direct_parent_boundary_candidate'):counts['DIRECT_PARENT_MARKER_INTRODUCTION_CANDIDATE']+=1
        elif result.get('marker_set_complete') and result.get('parents_marker_already_present'):counts['MARKERS_PRESENT_IN_PARENT']+=1
        elif result.get('marker_set_complete'):counts['MARKERS_PRESENT_BOUNDARY_UNVERIFIED']+=1
        else:counts['IMPLEMENTATION_MARKERS_UNVERIFIED']+=1
        accepted.append((end,sha,result))
    accepted.sort(key=lambda x:x[0])
    candidates=[x for x in accepted if x[2].get('direct_parent_boundary_candidate')]
    marker_records=[x for x in accepted if x[2].get('marker_set_complete')]
    return {'schema':SCHEMA,'status':'HISTORICAL_GIT_BOUNDARY_SAMPLED_EFFECTIVITY_UNVERIFIED',
      'mode':'READ_ONLY_EXTERNAL_GIT_PROVENANCE','migration_authority':'BLOCKED_RESEARCH_ONLY',
      'inputs':{'deployment_history':hs,'native_evidence':ns,'git_repository':state,'provider_export_authenticated':False},
      'observations':{'deployments_supplied':len(deployments),'native_events_supplied':len(native),
        'successful_deployment_correlations':counts['DEPLOYMENT_LIFECYCLE_CORROBORATED'],
        'unique_git_commit_queries':len(cache),'git_query_states':dict(git_states),'counts':dict(counts),
        'direct_parent_marker_boundary_candidates':len(candidates),
        'earliest_sampled_marker_deployment_present':bool(marker_records),
        'first_historical_implementation_commit_verified':False,
        'runtime_gamma_activation_verified':False,'historical_effective_date_verified':False,
        'record_origin_verified':False,'historical_record_eligibility_verified':False},
      'limitations':['Local Git checkout or mirror is not independently authenticated by this audit',
        'External source may be incomplete, shallow, or differ from historical deployed repositories',
        'Direct-parent marker change is not semantic implementation verification or historical first introduction',
        'Deployment-event correlation from offline copies is not provider-signed evidence',
        'No runtime feature activation, record origin or historical effective date is established',
        'No remote Git calls or Git object acquisition performed'],
      'guardrails':{'read_only':True,'no_fetch_or_clone':True,'no_git_mutations':True,'no_database_reads':True,
        'no_deployments_modified':True,'no_trade_execution':True,'no_migration':True,'no_reader_cutover':True,
        'no_identifiers_or_commit_shas_exported':True,'bounded_git_output':True,'bounded_command_time':True},
      'remaining_gates':['independently_authenticated_full_git_history','implementation_behavior_at_boundary',
        'authenticated_render_lifecycle','runtime_activation_attestation','record_version_origin',
        'population_identity_coverage','stage3b1_utf8_fix_verified','historical_replay_equivalence',
        'reader_cutover_coverage','external_backup_restore','isolated_rollback']}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--git-repository',required=True,help='Independent local Git checkout/mirror; no cloning or fetching occurs')
    p.add_argument('--service-id',required=True)
    p.add_argument('--deployment-history',required=True)
    p.add_argument('--native-evidence',required=True)
    p.add_argument('--max-deployments',type=int,default=128)
    p.add_argument('--output',required=True)
    a=p.parse_args()
    if not 1<=a.max_deployments<=128:p.error('max-deployments must be 1..128')
    repo=Path(a.git_repository).resolve();dest=Path(a.output).resolve()
    if dest==repo or repo in dest.parents:p.error('output must be outside Git repository')
    result=run(repo,a.deployment_history,a.native_evidence,a.service_id,a.max_deployments)
    dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(result,sort_keys=True,indent=2)+'\n',encoding='utf-8')
    print('Stage 3B.3.5 report:',dest,'| migration='+result['migration_authority'],'| status='+result['status'])
if __name__=='__main__':main()
