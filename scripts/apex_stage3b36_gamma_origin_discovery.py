#!/usr/bin/env python3
"""Stage 3B.3.6: bounded, local-only source-marker origins and deployment ancestry.

Source-marker introduction != semantic policy implementation != runtime activation.
This script performs no clone, fetch, Git writes, database access or deploy actions.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime,timezone
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

HERE=Path(__file__).resolve().parent
SPEC=importlib.util.spec_from_file_location('apex_stage3b35',HERE/'apex_stage3b35_git_boundary_audit.py')
B35=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(B35)
SCHEMA='apex.stage3b36_gamma_origin_deployment_boundary.v1'
MAX_CHANGED=256
MAX_DEPLOYS=128
SHA=B35.SHA


def git(repo,*args,max_bytes=1024*1024,timeout=12):
    """Git commands are allowlisted by call sites; disable optional network / hooks."""
    env=os.environ.copy()
    env.update({'GIT_NO_REPLACE_OBJECTS':'1','GIT_OPTIONAL_LOCKS':'0','GIT_TERMINAL_PROMPT':'0',
      'GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':os.devnull,'GIT_NO_LAZY_FETCH':'1',
      'GIT_PAGER':'cat','GIT_PROTOCOL_FROM_USER':'0'})
    try:
        p=subprocess.run(B35.git_command(repo,*args),stdout=subprocess.PIPE,
          stderr=subprocess.DEVNULL,check=False,timeout=timeout,env=env)
    except (OSError,subprocess.TimeoutExpired):return None,'GIT_UNAVAILABLE_OR_TIMEOUT'
    if len(p.stdout)>max_bytes:return None,'GIT_OUTPUT_OVERSIZE'
    return (p.stdout,None) if p.returncode==0 else (None,'GIT_COMMAND_UNAVAILABLE')


def changed_commits(repo,marker,max_hits):
    # -S catches changes in global occurrence count, not every source behavior change.
    data,error=git(repo,'log','--all','--format=%H',f'-S{marker.decode()}',
                   '--',*B35.MODULES,max_bytes=1_200_000,timeout=25)
    if error:return None,error
    found=[]
    for line in data.splitlines():
        s=line.decode('ascii','replace').strip()
        if not SHA.fullmatch(s):return None,'INVALID_GIT_LOG_RECORD'
        if s not in found:found.append(s)
    if len(found)>max_hits:return None,'SEARCH_HIT_CAP_EXCEEDED'
    return found,None


def marker_snapshot(repo,sha,cache):
    if sha in cache:return cache[sha]
    # Inspect only the declared five source paths, never import or execute their contents.
    present=0;hit=set();missing=[]
    for mod in B35.MODULES:
        data,err=git(repo,'show',f'{sha}:{mod}',max_bytes=262144,timeout=5)
        if err:missing.append(mod);continue
        present+=1
        for m in B35.MARKERS:
            if m in data:hit.add(m.decode())
    o={'marker_set_complete':len(hit)==len(B35.MARKERS),
       'modules_present':present,'modules_total':len(B35.MODULES),
       'complete_source_coverage':present==len(B35.MODULES),
       'markers':sorted(hit)}
    cache[sha]=o
    return o


def parents(repo,sha):
    raw,error=git(repo,'rev-list','--parents','-n','1',sha,max_bytes=250,timeout=5)
    if error:return None,error
    vals=raw.decode('ascii','replace').strip().split()
    if not vals or vals[0]!=sha or any(not SHA.fullmatch(x) for x in vals):return None,'INVALID_COMMIT_PARENT_RECORD'
    if len(vals)>5:return None,'PARENT_LIMIT_EXCEEDED'
    return vals[1:],None


def is_ancestor(repo,older,newer):
    if not SHA.fullmatch(older) or not SHA.fullmatch(newer):return 'UNVERIFIED'
    # git merge-base --is-ancestor returns 1 for proven non-ancestor and >1 on errors.
    env=os.environ.copy();env.update({'GIT_NO_REPLACE_OBJECTS':'1','GIT_OPTIONAL_LOCKS':'0',
      'GIT_NO_LAZY_FETCH':'1','GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':os.devnull,
      'GIT_TERMINAL_PROMPT':'0'})
    try:
        p=subprocess.run(B35.git_command(repo,'merge-base','--is-ancestor',older,newer),
          stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=5,env=env)
    except (OSError,subprocess.TimeoutExpired):return 'UNVERIFIED'
    return 'ANCESTOR' if p.returncode==0 else 'NOT_ANCESTOR' if p.returncode==1 else 'UNVERIFIED'


def source_reachability(repo,commits):
    """Defensive: reachable from at least one local ref does not imply deployed."""
    reachable=set()
    for sha in commits:
        raw,err=git(repo,'branch','-a','--contains',sha,max_bytes=8192,timeout=8)
        # For bare repositories branch -a works; unreachable objects stay unverified.
        if err is None and raw.strip():reachable.add(sha)
    return reachable


def run(repo,history_path,native_path,service_id,max_changed=128):
    previous=B35.run(repo,history_path,native_path,service_id,MAX_DEPLOYS)
    state=previous['inputs']['git_repository']
    counts=Counter();issues=[];all_hits=set();marker_hit_counts={};candidate=[]
    cache={};search_complete=True
    if state=='EXTERNAL_GIT_REPOSITORY_READABLE':
        for marker in B35.MARKERS:
            hits,error=changed_commits(repo,marker,max_changed)
            marker_hit_counts[marker.decode()]={'changed_commits':len(hits) if hits is not None else None,
                                                   'search_state':'COMPLETE' if error is None else error}
            if error:
                search_complete=False;issues.append(f'{marker.decode()}:{error}')
            else:all_hits.update(hits)
    else:
        search_complete=False;issues.append('GIT_REPOSITORY_UNAVAILABLE')
    if len(all_hits)>max_changed:
        search_complete=False;issues.append('COMBINED_CHANGESET_CAP_EXCEEDED')
    # Incomplete marker history must not produce purported introduction candidates.
    if not search_complete:all_hits=set()
    for sha in sorted(all_hits):
        snap=marker_snapshot(repo,sha,cache)
        pp,err=parents(repo,sha)
        if err:
            counts['PARENT_QUERY_FAILED']+=1;continue
        parent_snapshots=[marker_snapshot(repo,p,cache) for p in pp]
        if not snap['marker_set_complete']:
            counts['MARKERS_INCOMPLETE_AT_CHANGED_COMMIT']+=1;continue
        if any(p['marker_set_complete'] for p in parent_snapshots):
            counts['MARKERS_ALREADY_PRESENT_IN_PARENT']+=1;continue
        if not pp:
            counts['ROOT_MARKER_CANDIDATE']+=1
        elif all(p['complete_source_coverage'] for p in parent_snapshots) and snap['complete_source_coverage']:
            counts['DIRECT_PARENT_MARKER_BOUNDARY_CANDIDATE']+=1
        else:
            counts['PARTIAL_MODULE_COVERAGE_CANDIDATE']+=1
        candidate.append({'sha':sha,'root':not pp,'parent_count':len(pp),
                          'complete_source_coverage':snap['complete_source_coverage'],
                          'parents_complete_source_coverage':all(p['complete_source_coverage'] for p in parent_snapshots),
                          'candidate_type':'DIRECT_PARENT_MARKER_CHANGE' if pp and snap['complete_source_coverage'] and all(p['complete_source_coverage'] for p in parent_snapshots) else 'INCOMPLETE_COVERAGE_OR_ROOT'})
    # Critically: -S and marker search alone cannot establish first *semantic* implementation.
    # Correlate proposed marker candidates only with deployment commits that were validated by 3B.3.5.
    h,hs=B35.load(history_path)
    dep_rows=h.get('deployments',[]) if isinstance(h,dict) else []
    deploy_shas=[]
    # We do not assume all loaded deployments are corroborated: verify per deployment using event joins.
    normalized=h.get('events',[]) if isinstance(h,dict) else []
    n,ns=B35.load(native_path)
    native=n.get('native_events',[]) if isinstance(n,dict) else []
    native_ok={}
    for ev in native if isinstance(native,list) else []:
        if isinstance(ev,dict) and ev.get('service_id')==service_id and ev.get('type')=='deploy_ended' and ev.get('deploy_status')=='succeeded':
            t=B35.timestamp(ev.get('timestamp'))
            if t:native_ok.setdefault(ev.get('deploy_id'),[]).append(t)
    claims_ok={}
    for ev in normalized if isinstance(normalized,list) else []:
        if isinstance(ev,dict) and ev.get('service_id')==service_id and ev.get('event_type')=='deploy_activated' and ev.get('outcome')=='succeeded':
            t=B35.timestamp(ev.get('occurred_at'))
            if t:claims_ok.setdefault(ev.get('deploy_id'),[]).append(t)
    seen=set()
    for d in dep_rows if isinstance(dep_rows,list) else []:
        if not isinstance(d,dict) or d.get('service_id')!=service_id:continue
        dep=d.get('deploy_id');sha=d.get('commit_sha')
        if dep in seen:continue
        seen.add(dep)
        if not SHA.fullmatch(str(sha or '')):continue
        start=B35.timestamp(d.get('started_at'));end=B35.timestamp(d.get('live_at'))
        if not start or not end or end<start or d.get('status') not in ('live','deactivated'):continue
        if not any(t>=start and abs((t-end).total_seconds())<=10 and any(abs((t-c).total_seconds())<=1 for c in claims_ok.get(dep,[])) for t in native_ok.get(dep,[])):continue
        deploy_shas.append(sha)
    relations=[]
    for c in candidate:
        r=Counter(is_ancestor(repo,c['sha'],d) for d in deploy_shas)
        relations.append({'sha':c['sha'],'candidate_type':c['candidate_type'],
          'ancestor_of_sampled_deployments':r['ANCESTOR'],
          'not_ancestor_of_sampled_deployments':r['NOT_ANCESTOR'],
          'ancestry_unverified':r['UNVERIFIED']})
    # A historic deployment boundary requires an observed before/after deployed marker transition.
    # The current 8 recent deployments are not a claim of comprehensive Render history.
    all_deployed_markers=[marker_snapshot(repo,sha,cache) for sha in set(deploy_shas)] if state=='EXTERNAL_GIT_REPOSITORY_READABLE' else []
    before=sum(not a['marker_set_complete'] for a in all_deployed_markers)
    after=sum(a['marker_set_complete'] for a in all_deployed_markers)
    summary={'schema':SCHEMA,'status':'ORIGIN_CANDIDATES_IDENTIFIED_EFFECTIVITY_UNVERIFIED' if candidate else 'ORIGIN_BOUNDARY_UNVERIFIED',
     'mode':'READ_ONLY_HISTORICAL_GIT_MARKER_ORIGIN', 'migration_authority':'BLOCKED_RESEARCH_ONLY',
     'inputs':{'git_repository':state,'deployment_history':hs,'native_evidence':ns,
       'provider_export_authenticated':False},
     'observations':{'marker_change_searches':marker_hit_counts,'search_complete_within_caps':search_complete,
       'changed_commits_examined':len(all_hits),'source_snapshots_examined':len(cache),
       'candidate_counts':dict(counts),'marker_origin_candidates':len(candidate),
       'direct_parent_marker_boundary_candidates':counts['DIRECT_PARENT_MARKER_BOUNDARY_CANDIDATE'],
       'corroborated_sampled_deployments':len(deploy_shas),
       'sampled_deployments_with_markers':after,'sampled_deployments_without_markers':before,
       'sampled_deployment_before_and_after_marker_states':before>0 and after>0,
       'first_semantic_implementation_commit_verified':False,
       'render_deployment_policy_boundary_verified':False,
       'runtime_gamma_activation_verified':False,'historical_policy_effective_date_verified':False,
       'record_level_eligibility_verified':False,'search_issues':issues},
     'limitations':['Git -S source-marker occurrence search does not prove semantic implementation or identify all changes',
       'Full Git history and ref completeness are not independently authenticated by this local audit',
       'Ancestor relationships do not establish feature deployment, runtime activation or policy effective dates',
       'Eight recent Render deployments do not bracket the original gamma introduction',
       'Render offline events are correlated copies, not provider-signed attestation',
       'Output intentionally excludes deployment IDs and commit SHAs; optional private details is local only'],
     'guardrails':{'read_only':True,'no_remote_calls':True,'no_fetch_or_clone':True,
       'no_git_mutations':True,'no_database_access':True,'no_deployments_modified':True,
       'no_backfill':True,'no_migration':True,'no_reader_cutover':True,'no_trade_execution':True,
       'no_policy_effective_date_assigned':True},
     'remaining_gates':['full_history_source_authentication','semantic_implementation_at_candidate',
       'provider_authenticated_historical_deployments','runtime_activation_attestation',
       'record_origin_and_population_identity','utf8_reader_fix','historical_replay',
       'external_backup_restore','isolated_rollback']}
    return summary,{'schema':'apex.stage3b36_local_private_candidates.v1',
      'warning':'Untrusted local Git/offline deployment evidence; not policy effective-date or record eligibility authority',
      'marker_candidate_commits':candidate,'sampled_deployment_ancestry':relations}


def write_json(destination,record,private=False):
    dest=Path(destination).resolve()
    dest.parent.mkdir(parents=True,exist_ok=True)
    if private:
        flags=os.O_WRONLY|os.O_CREAT|os.O_TRUNC
        fd=os.open(str(dest),flags,0o600)
        try:
            os.fchmod(fd,0o600)
            with os.fdopen(fd,'w',encoding='utf-8') as out:json.dump(record,out,indent=2,sort_keys=True);out.write('\n')
        except Exception:
            os.close(fd);raise
    else:dest.write_text(json.dumps(record,indent=2,sort_keys=True)+'\n',encoding='utf-8')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--git-repository',required=True)
    p.add_argument('--service-id',required=True)
    p.add_argument('--deployment-history',required=True)
    p.add_argument('--native-evidence',required=True)
    p.add_argument('--max-changed-commits',type=int,default=128)
    p.add_argument('--output',required=True)
    p.add_argument('--private-details-output',help='Optional chmod 0600 local artifact containing candidate SHAs')
    a=p.parse_args()
    if not 1<=a.max_changed_commits<=MAX_CHANGED:p.error('--max-changed-commits must be 1..256')
    repo=Path(a.git_repository).resolve()
    outputs=[Path(a.output).resolve()]
    if a.private_details_output:outputs.append(Path(a.private_details_output).resolve())
    if len(set(outputs))!=len(outputs):p.error('output paths must be different')
    if any(x==repo or repo in x.parents for x in outputs):p.error('outputs must be outside Git repository')
    summary,detail=run(repo,a.deployment_history,a.native_evidence,a.service_id,a.max_changed_commits)
    write_json(outputs[0],summary)
    if len(outputs)>1:write_json(outputs[1],detail,private=True)
    print('Stage 3B.3.6 report:',outputs[0],'| status='+summary['status'],'| migration=BLOCKED_RESEARCH_ONLY')
    print('Candidates:',summary['observations']['marker_origin_candidates'], '| reviewed change commits:',summary['observations']['changed_commits_examined'])

if __name__=='__main__':main()
