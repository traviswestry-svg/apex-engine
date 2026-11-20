#!/usr/bin/env python3
"""APEX 3B.3.8: bounded historical Render recovery and runtime-claim inspection.

Two acquisition modes: OFFLINE verified operator-provided raw Render pages; API HTTPS
GET with separately provisioned RENDER_API_KEY. Both are READS, not cryptographic
provider attestation. Historical code is not imported, executed, or migrated.

Stage 3B.3.7 performs Git ancestry + static source checks; runtime JSON, even when
correlated, is NEVER treated as independent runtime activation attestation.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone, timedelta
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import tempfile
import urllib.parse

HERE=Path(__file__).resolve().parent

def dependency(filename,name):
    spec=importlib.util.spec_from_file_location(name,HERE/filename)
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

B332=dependency('apex_stage3b332_render_evidence_collector.py','apex_stage3b332_for_38')
B37=dependency('apex_stage3b37_semantic_deployment_bracketing.py','apex_stage3b37_for_38')
B35=B37.B35
SCHEMA='apex.stage3b38_historical_render_runtime_evidence.v1'
MAX_RAW_BYTES=8*1024*1024
MAX_PAGES=64
MAX_ROWS=6000
MAX_SELECTED=128
MAX_EVENTS=1024
MAX_RUNTIME=256
MAX_FILE=3*1024*1024
DEFAULT_START='2026-09-01T00:00:00Z'
DEFAULT_END='2026-10-15T00:00:00Z'


def utc(value):
    return B35.timestamp(value)


def read_json(path,limit=MAX_RAW_BYTES):
    p=Path(path)
    if not p.is_file() or p.stat().st_size>limit:raise ValueError('INPUT_MISSING_OR_OVERSIZE')
    with p.open('rb') as f:return json.load(f)


def flatten_pages(doc,kind):
    """Accept a raw list, one Render API page, or explicit list of pages.

    Each item can be a raw Render {deploy:...}/{event:...} wrapper; no synthesis.
    """
    if isinstance(doc,dict) and 'pages' in doc:
        pages=doc['pages']
    elif isinstance(doc,dict):pages=[doc]
    elif isinstance(doc,list):
        pages=doc if doc and all(isinstance(x,dict) and ('items' in x or 'results' in x or 'data' in x) for x in doc) else [doc]
    else:raise ValueError('INVALID_PAGES')
    if not isinstance(pages,list) or not 1<=len(pages)<=MAX_PAGES:raise ValueError('PAGE_COUNT_LIMIT')
    out=[]
    for page in pages:
        raw=B332.unwrap(page)
        if not all(isinstance(x,dict) for x in raw):raise ValueError('INVALID_PROVIDER_RECORD')
        out.extend(raw)
        if len(out)>MAX_ROWS:raise ValueError('RAW_ROW_LIMIT')
    return out, len(pages)


def acquire_pages(service,api_key,kind,limit,max_pages,fetch=None):
    """Read-only Render REST pagination, preserving provider cursors.

    Fails closed when a cursor is repeated or missing on a full page. No claimed
    completeness unless an empty/short final provider page is actually observed.
    """
    fetch=fetch or B332.render_get
    out=[]; seen=set();cursor=None; pages=0; exhausted=False; reason='BOUNDED'
    page_size=100
    while pages<max_pages and len(out)<limit:
        take=min(page_size,limit-len(out))
        args={'limit':take}
        if cursor:args['cursor']=cursor
        url='https://api.render.com/v1/services/'+service+'/'+kind+'?'+urllib.parse.urlencode(args)
        raw=fetch(url,api_key)
        page=B332.unwrap(raw)
        pages+=1
        if not isinstance(page,list) or not all(isinstance(x,dict) for x in page):raise ValueError('INVALID_API_PAGE')
        if len(page)>take:raise ValueError('API_PAGE_OVERFLOW')
        out.extend(page)
        if len(page)<take:
            exhausted=True;reason='SHORT_OR_EMPTY_FINAL_PAGE';break
        # Render API commonly sends a cursor on the final item wrapper.
        nxt=page[-1].get('cursor')
        # A full page without cursor cannot certify exhaustion.
        if not nxt:
            reason='FULL_PAGE_WITHOUT_CURSOR';break
        if not isinstance(nxt,str) or len(nxt)>1024 or nxt in seen:
            reason='CURSOR_UNSAFE_OR_REPEATED';break
        seen.add(nxt);cursor=nxt
    return out,{'pages':pages,'pagination_exhausted':exhausted,'stop_reason':reason}


def normalize_window(deploys,events,service,start,end):
    """Select candidates around the target window; fail closed on caps.

    A deployment can start before the target but complete in it. Preserve the
    matching raw events for candidate deployments without dropping lifecycle data.
    """
    selected=[]; selected_ids=set(); invalid=Counter()
    for item in deploys:
        d=B332.normalize_deploy(item,service)
        if d is None:
            invalid['INVALID_DEPLOYMENT']+=1;continue
        finished=utc(d['live_at'])
        if start<=finished<=end:
            selected.append(item);selected_ids.add(d['deploy_id'])
    if len(selected)>MAX_SELECTED:raise ValueError('DEPLOYMENT_SELECTION_CAP_EXCEEDED')
    related=[]
    for item in events:
        e=B332.normalize_event(item,service)
        if e and e['deploy_id'] in selected_ids:related.append(item)
    if len(related)>MAX_EVENTS:raise ValueError('EVENT_SELECTION_CAP_EXCEEDED')
    return selected,related,dict(invalid)


def runtime_observations(doc,service,deployments):
    """Correlate user-supplied claims, never grant activation verification.

    A claim may say a gamma identity was observed in a runtime decision. It is
    still an unauthenticated claim, and never changes migration authority.
    """
    if doc is None:return {'input_state':'MISSING','claims_supplied':0,'linked_claims':0,
                          'claims_with_gamma_identity':0,'claim_states':{},'runtime_activation_verified':False}
    rows=doc.get('observations') if isinstance(doc,dict) else doc
    if not isinstance(rows,list) or len(rows)>MAX_RUNTIME:raise ValueError('RUNTIME_INPUT_INVALID_OR_OVERSIZE')
    by_id={d['deploy_id']:d for d in deployments}
    counts=Counter();linked=0;with_id=0
    for row in rows:
        if not isinstance(row,dict):counts['INVALID_ROW']+=1;continue
        dep=by_id.get(row.get('deploy_id'))
        when=utc(row.get('observed_at'))
        sha=row.get('commit_sha')
        snap=row.get('canonical_gamma_snapshot_id')
        if not dep or not when or not isinstance(sha,str) or sha!=dep['sha']:
            counts['UNLINKED_OR_UNVERIFIED']+=1;continue
        if when<dep['started_at'] or (when-dep['completed_at']).total_seconds() > 60*60*24*30:
            counts['TIME_INCONSISTENT']+=1;continue
        linked+=1
        if isinstance(snap,str) and 0<len(snap)<=256 and snap.strip():
            with_id+=1;counts['LINKED_GAMMA_ID_CLAIM_UNATTESTED']+=1
        else:counts['LINKED_NO_GAMMA_ID_CLAIM']+=1
    return {'input_state':'OFFLINE_UNTRUSTED_CLAIMS','claims_supplied':len(rows),
       'linked_claims':linked,'claims_with_gamma_identity':with_id,
       'claim_states':dict(counts),'runtime_activation_verified':False}


def write_json_atomic(path,obj):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    content=(json.dumps(obj,indent=2,sort_keys=True)+'\n').encode()
    if len(content)>MAX_FILE:raise ValueError('OUTPUT_LIMIT_EXCEEDED')
    fd,temp=tempfile.mkstemp(prefix='.stage3b38-',dir=p.parent)
    try:
        with os.fdopen(fd,'wb') as f:f.write(content);f.flush();os.fsync(f.fileno())
        os.chmod(temp,0o600)
        os.replace(temp,p)
    finally:
        if os.path.exists(temp):os.unlink(temp)
    return hashlib.sha256(content).hexdigest()


def run(*,repo,service,candidate,deploy_raw,event_raw,start,end,runtime=None,
        acquisition='OFFLINE_OPERATOR_SUPPLIED',pagination=None,evidence_out_dir=None):
    subset_d,subset_e,rejected=normalize_window(deploy_raw,event_raw,service,start,end)
    # Use existing vetted stage3b332 contract for downstream B37 schema.
    normalized,native=B332.compile_evidence(subset_d,subset_e,service,acquisition,False,
          {'max_deployments':MAX_SELECTED,'max_events':MAX_EVENTS,'stage3b38_window_start':start.isoformat(),
           'stage3b38_window_end':end.isoformat()})
    if evidence_out_dir:
        folder=Path(evidence_out_dir)
        write_json_atomic(folder/'stage3b38-deployment-history.json',normalized)
        write_json_atomic(folder/'stage3b38-render-native-evidence.json',native)
    with tempfile.TemporaryDirectory(prefix='apex-stage3b38-') as temp:
        history_file=Path(temp)/'history.json';native_file=Path(temp)/'native.json'
        write_json_atomic(history_file,normalized);write_json_atomic(native_file,native)
        source_report,private=B37.run(repo,service,str(history_file),str(native_file),candidate)
    # Reuse vetted matching via the private B37 output, without assuming all deployed rows match.
    counts=source_report['observations']['deployment_relation_counts']
    runtime_result=runtime_observations(None,service,[])
    # The B37 private output may not expose an implementation-independent list;
    # build a read-only correlation from the normalized events for claim matching.
    # Runtime claims remain untrusted even if keys match.
    if runtime is not None:
        matches=[]
        claims={e['deploy_id'] for e in normalized.get('events',[]) if e.get('outcome')=='succeeded'}
        for d in normalized.get('deployments',[]):
            if d['deploy_id'] in claims and B35.SHA.fullmatch(d.get('commit_sha','')):
                s=utc(d['started_at']);e=utc(d['live_at'])
                if s and e:matches.append({'deploy_id':d['deploy_id'],'sha':d['commit_sha'],'started_at':s,'completed_at':e})
        runtime_result=runtime_observations(runtime,service,matches)
    search_complete=bool(pagination and pagination.get('deploys',{}).get('pagination_exhausted') and pagination.get('events',{}).get('pagination_exhausted'))
    bracket=bool(source_report['observations']['offline_before_after_bracket_candidate']
                 and source_report['observations']['semantic_source_contract'].get('static_contract_introduced_at_candidate'))
    report={'schema':SCHEMA,'mode':'READ_ONLY_HISTORICAL_RENDER_BOUNDARY_AND_RUNTIME_CLAIMS',
       'status':('OFFLINE_BRACKET_CANDIDATE_RUNTIME_UNVERIFIED' if bracket else
                'HISTORICAL_DEPLOYMENT_BOUNDARY_UNVERIFIED_RUNTIME_UNVERIFIED'),
       'migration_authority':'BLOCKED_RESEARCH_ONLY',
       'inputs':{'acquisition':acquisition,'provider_export_authenticated':False,
                 'historical_coverage_exhaustive':search_complete,'runtime_observations':'LOADED' if runtime is not None else 'MISSING'},
       'observations':{'raw_deployment_records':len(deploy_raw),'raw_event_records':len(event_raw),
           'selected_window_deployments':len(normalized['deployments']),
           'selected_window_native_events':len(native['native_events']),
           'selected_window_successful_event_claims':len(normalized['events']),
           'rejected_raw_deployments':rejected,
           'source_contract':source_report['observations']['semantic_source_contract'],
           'candidate_relation_counts':counts,
           'offline_before_after_bracket_candidate':bracket,
           'runtime_observations':runtime_result,
           'history_acquisition':pagination or {'status':'OFFLINE_PAGE_EXPORT_COVERAGE_UNVERIFIED'},
           'historical_policy_effective_date_verified':False,
           'runtime_gamma_activation_verified':False,
           'record_level_eligibility_verified':False},
       'guardrails':{'read_only':True,'no_database_reads':True,'no_db_writes':True,'no_git_mutations':True,
          'no_historical_code_execution':True,'no_migration':True,'no_reader_cutover':True,
          'no_trade_execution':True,'no_policy_effective_date_assigned':True},
       'limitations':['Historical page selection is not independently authenticated.',
          'API bearer authentication authenticates a transport session, not historical provider-signed attestation.',
          'Runtime JSON observations are unauthenticated claims, not operational feature activation proof.',
          'Static AST/token evidence is not semantic behavior replay.',
          'A before/after deployment ancestry bracket does not prove runtime gamma execution.',
          'No DB records or production gamma data were read.'],
       'remaining_gates':['independently_authenticated_historical_render_history',
           'isolated_semantic_behavior_replay','runtime_feature_activation_attestation',
           'record_origin_version_correlation','record_level_eligibility','utf8_reader_fix',
           'historical_replay_equivalence','external_backup_restore','isolated_rollback']}
    details={'schema':'apex.stage3b38_private_details.v1','source_b37':private,
       'selected_window':{'start':start.isoformat(),'end':end.isoformat()},
       'warning':'Offline claims only; never policy effective-date authority'}
    return report,details


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode',choices=['offline','api'],required=True)
    p.add_argument('--service-id',required=True)
    p.add_argument('--git-repository',required=True)
    p.add_argument('--candidate-sha',default=B37.DEFAULT_CANDIDATE)
    p.add_argument('--raw-deployments');p.add_argument('--raw-events')
    p.add_argument('--runtime-observations')
    p.add_argument('--window-start',default=DEFAULT_START)
    p.add_argument('--window-end',default=DEFAULT_END)
    p.add_argument('--max-pages',type=int,default=48)
    p.add_argument('--max-records',type=int,default=5000)
    p.add_argument('--output',required=True)
    p.add_argument('--private-details-output')
    p.add_argument('--evidence-out-dir',help='Optional stage-owned normalized historical evidence files; never overwrites Stage 3B.3.3.2 files')
    a=p.parse_args(argv)
    if not B332.SERVICE.fullmatch(a.service_id):p.error('invalid service')
    if not B35.SHA.fullmatch(a.candidate_sha):p.error('invalid candidate sha')
    start=utc(a.window_start);end=utc(a.window_end)
    if not start or not end or not start<end or (end-start)>timedelta(days=180):p.error('invalid bounded window')
    if not 1<=a.max_pages<=MAX_PAGES or not 1<=a.max_records<=MAX_ROWS:p.error('invalid collection caps')
    outputs=[Path(a.output).resolve()]
    if a.private_details_output:outputs.append(Path(a.private_details_output).resolve())
    if a.evidence_out_dir:
        folder=Path(a.evidence_out_dir).resolve()
        outputs.extend([folder/'stage3b38-deployment-history.json',folder/'stage3b38-render-native-evidence.json'])
    if len(set(outputs))!=len(outputs):p.error('output paths must be distinct')
    repo=Path(a.git_repository).resolve()
    if any(x==repo or repo in x.parents for x in outputs):p.error('outputs cannot be written inside Git mirror')
    protected=[Path(x).resolve() for x in (a.raw_deployments,a.raw_events,a.runtime_observations) if x]
    if any(x in protected for x in outputs):p.error('output would overwrite a raw input')
    if a.mode=='offline':
        if not a.raw_deployments or not a.raw_events:p.error('offline requires raw deployments and events')
        ds,dp=flatten_pages(read_json(a.raw_deployments),'deploys')
        es,ep=flatten_pages(read_json(a.raw_events),'events')
        pagination={'deploys':{'pages':dp,'pagination_exhausted':False},'events':{'pages':ep,'pagination_exhausted':False}}
        acquisition='OFFLINE_OPERATOR_SUPPLIED'
    else:
        key=os.getenv('RENDER_API_KEY')
        if not key:p.error('RENDER_API_KEY unavailable; use offline mode or configure securely')
        ds,dp=acquire_pages(a.service_id,key,'deploys',a.max_records,a.max_pages)
        es,ep=acquire_pages(a.service_id,key,'events',a.max_records,a.max_pages)
        pagination={'deploys':dp,'events':ep};acquisition='DIRECT_RENDER_API_HTTPS_GET'
    runtime=read_json(a.runtime_observations,MAX_FILE) if a.runtime_observations else None
    summary,details=run(repo=a.git_repository,service=a.service_id,candidate=a.candidate_sha,
        deploy_raw=ds,event_raw=es,start=start,end=end,runtime=runtime,
        acquisition=acquisition,pagination=pagination,evidence_out_dir=a.evidence_out_dir)
    digest=write_json_atomic(a.output,summary)
    if a.private_details_output:write_json_atomic(a.private_details_output,details)
    print('Stage 3B.3.8 |',summary['status'],'| migration=BLOCKED_RESEARCH_ONLY | sha256',digest)
    return 0

if __name__=='__main__':raise SystemExit(main())
