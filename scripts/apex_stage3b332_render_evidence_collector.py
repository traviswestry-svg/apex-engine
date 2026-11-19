#!/usr/bin/env python3
"""Stage 3B.3.3.2: bounded read-only Render deployment/event evidence collector.

Two acquisition modes:
  --mode api: HTTPS GET Render API with RENDER_API_KEY (never stored).
  --mode offline: convert real raw Render exports supplied as JSON files.

A direct API read authenticates the API session, NOT a historical deployment
attestation, feature activation, or record eligibility. Offline imports have
no authenticated acquisition provenance. No deployment or trading mutations.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request

SCHEMA='apex.stage3b332_render_collection.v1'
SERVICE=re.compile(r'^srv-[a-zA-Z0-9]+$')
DEPLOY=re.compile(r'^dep-[a-zA-Z0-9]+$')
SHA=re.compile(r'^[0-9a-fA-F]{40}$')
MAX_INPUT=5*1024*1024
MAX_OUTPUT=2*1024*1024  # Stage 3B.3.3.1 accepts <=2 MiB
MAX_PAGE_BYTES=1024*1024
EVENT_KINDS={'deploy_started','deploy_ended'}


def stamp(v):
    if not isinstance(v,str): return None
    try:
        t=datetime.fromisoformat(v.replace('Z','+00:00'))
        if t.tzinfo is None:return None
        return t.astimezone(timezone.utc)
    except ValueError:return None


def utc(t):return t.isoformat(timespec='microseconds').replace('+00:00','Z')


def safe_json(data):
    if len(data)>MAX_PAGE_BYTES:raise ValueError('PAGE_BYTE_LIMIT_EXCEEDED')
    return json.loads(data)


def load_document(path):
    p=Path(path)
    if not p.is_file() or p.stat().st_size>MAX_INPUT:raise ValueError('INPUT_MISSING_OR_OVERSIZE')
    with p.open('rb') as f:return json.loads(f.read())


def unwrap(doc):
    if isinstance(doc,list):return doc
    if isinstance(doc,dict):
        for k in ('results','items','data','deployments','events'):
            if isinstance(doc.get(k),list):return doc[k]
    raise ValueError('INVALID_COLLECTION_SCHEMA')


def normalize_deploy(item,service):
    d=item.get('deploy',item) if isinstance(item,dict) else None
    if not isinstance(d,dict):return None
    ident=d.get('id') or d.get('deploy_id')
    sha=(d.get('commit') or {}).get('id') if isinstance(d.get('commit'),dict) else d.get('commit_sha')
    started=d.get('startedAt') or d.get('started_at')
    ended=d.get('finishedAt') or d.get('live_at')
    st=stamp(started);et=stamp(ended)
    status=d.get('status')
    if not DEPLOY.fullmatch(str(ident)) or not SHA.fullmatch(str(sha)) or st is None or et is None or st>et or not isinstance(status,str):return None
    return {'deploy_id':ident,'service_id':service,'commit_sha':sha.lower(),'status':status,'started_at':utc(st),'live_at':utc(et)}


def normalize_event(item,service):
    e=item.get('event',item) if isinstance(item,dict) else None
    if not isinstance(e,dict):return None
    if e.get('serviceId',e.get('service_id'))!=service:return None
    if e.get('type') not in EVENT_KINDS:return None
    details=e.get('details') or {}
    if not isinstance(details,dict):return None
    dep=details.get('deployId')
    tm=stamp(e.get('timestamp'))
    if not DEPLOY.fullmatch(str(dep)) or tm is None:return None
    return {'event_id':e.get('id'),'service_id':service,'deploy_id':dep,'type':e['type'],'timestamp':utc(tm),'details':details}


def event_claim(e,dep):
    # Render-native successful deploy completion is NOT an explicit runtime feature activation.
    if e['type']!='deploy_ended' or e['details'].get('deployStatus')!='succeeded':return None
    if stamp(e['timestamp'])<stamp(dep['started_at']):return None
    # Stage 3B.3.3.1 expects normalized event claims. Store source event separately.
    return {'deploy_id':dep['deploy_id'],'service_id':dep['service_id'],
            'event_type':'deploy_activated','outcome':'succeeded','occurred_at':e['timestamp']}


def compile_evidence(deploy_raw,event_raw,service,acquisition,complete,limits):
    dc=Counter();ec=Counter(); deployments={};rejected_deploy_ids=set();events={};claims=[]
    for item in deploy_raw:
        d=normalize_deploy(item,service)
        if d is None:dc['INVALID_DEPLOYMENT']+=1;continue
        if d['deploy_id'] in rejected_deploy_ids:continue
        if d['deploy_id'] in deployments:
            if deployments[d['deploy_id']]!=d:
                dc['CONFLICTING_DUPLICATE_DEPLOYMENT']+=1
                del deployments[d['deploy_id']]
                rejected_deploy_ids.add(d['deploy_id'])
            else:dc['DUPLICATE_DEPLOYMENT']+=1
            continue
        deployments[d['deploy_id']]=d
    for item in event_raw:
        e=normalize_event(item,service)
        if e is None:ec['INVALID_OR_UNSUPPORTED_EVENT']+=1;continue
        key=e['event_id'] if isinstance(e['event_id'],str) else (e['deploy_id'],e['type'],e['timestamp'])
        if key in events:
            ec['DUPLICATE_EVENT']+=1;continue
        events[key]=e
    for e in events.values():
        dep=deployments.get(e['deploy_id'])
        if not dep:ec['EVENT_DEPLOYMENT_NOT_PRESENT']+=1;continue
        claim=event_claim(e,dep)
        if claim:claims.append(claim);ec['NATIVE_SUCCEEDED_DEPLOY_COMPLETION']+=1
        else:ec['NO_SUCCESSFUL_DEPLOY_CLAIM']+=1
    ordered=sorted(deployments.values(),key=lambda d:d['started_at'])
    claims=sorted(claims,key=lambda e:e['occurred_at'])
    # preserve native evidence separately for reviewer, with no secrets/cookies
    raw_native=[{'id':e['event_id'],'service_id':e['service_id'],'deploy_id':e['deploy_id'],
                 'type':e['type'],'timestamp':e['timestamp'],
                 'deploy_status':e['details'].get('deployStatus') if e['type']=='deploy_ended' else None}
                for e in sorted(events.values(),key=lambda x:x['timestamp'])]
    export={'deployments':ordered,'events':claims}
    proof={'schema':SCHEMA,'source':'Render','service_id':service,
          'acquisition':acquisition,
          'api_transport_authenticated_at_collection':acquisition=='DIRECT_RENDER_API_HTTPS_GET',
          'provider_export_is_cryptographically_signed':False,
          'historical_runtime_gamma_activation_verified':False,
          'historical_policy_effective_date_verified':False,
          'record_level_eligibility_verified':False,
          'migration_authority':'BLOCKED_RESEARCH_ONLY',
          'historical_coverage_complete':bool(complete),
          'native_events':raw_native,'collector_counts':{'deployments':len(ordered),'native_events':len(raw_native),
          'normalized_successful_deploy_completion_claims':len(claims),
          'deployment_rejections':dict(dc),'event_rejections':dict(ec)},
          'limits':limits,'guardrails':{'read_only':True,'no_remote_mutation':True,'no_db_access':True,
          'no_trading_execution':True,'no_gamma_policy_inference':True,'token_not_written':True}}
    return export,proof


def render_get(url,key,timeout=15):
    if not url.startswith('https://api.render.com/v1/'):raise ValueError('UNSAFE_API_URL')
    req=urllib.request.Request(url,headers={'Authorization':'Bearer '+key,'Accept':'application/json'},method='GET')
    with urllib.request.urlopen(req,timeout=timeout) as resp:
        if resp.status!=200:raise ValueError('NON_200_API_RESPONSE')
        data=resp.read(MAX_PAGE_BYTES+1)
        return safe_json(data)


def acquire_api(service,api_key,max_deploys,max_events,per_page):
    base='https://api.render.com/v1/services/'+service
    ds=[]; es=[];seen=set();complete={'deployments':False,'events':False}
    for kind,limit,items in [('deploys',max_deploys,ds),('events',max_events,es)]:
        cursor=None
        while len(items)<limit:
            params={'limit':min(per_page,limit-len(items))}
            if cursor:params['cursor']=cursor
            url=f'{base}/{kind}?'+urllib.parse.urlencode(params)
            page=unwrap(render_get(url,api_key))
            if not page:complete['deployments' if kind=='deploys' else 'events']=True;break
            if kind=='events':
                # Only native deploy lifecycle records are meaningful here; page still counts to API limit
                items.extend(page)
            else:items.extend(page)
            # The Render API list format may use per-item `cursor`; never invent pagination tokens.
            last=page[-1] if page else {}
            nxt=last.get('cursor') if isinstance(last,dict) else None
            if not nxt or nxt==cursor or nxt in seen:
                complete['deployments' if kind=='deploys' else 'events']=not bool(nxt)
                break
            seen.add(nxt);cursor=nxt
    return ds,es,complete


def atomic_json(path,obj,limit=None):
    p=Path(path)
    p.parent.mkdir(parents=True,exist_ok=True)
    encoded=(json.dumps(obj,indent=2,sort_keys=True,ensure_ascii=False)+'\n').encode('utf-8')
    if limit and len(encoded)>limit:raise ValueError('OUTPUT_EXCEEDS_COMPATIBILITY_LIMIT')
    fd,tmp=tempfile.mkstemp(prefix='.apex-stage3b332-',dir=p.parent)
    try:
        with os.fdopen(fd,'wb') as f:
            f.write(encoded);f.flush();os.fsync(f.fileno())
        os.chmod(tmp,0o600)
        os.replace(tmp,p)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
    return hashlib.sha256(encoded).hexdigest(),len(encoded)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mode',choices=['api','offline'],required=True)
    p.add_argument('--service-id',default='srv-d7p3u2navr4c73d2q0jg')
    p.add_argument('--raw-deployments',help='Offline JSON list or Render API response')
    p.add_argument('--raw-events',help='Offline JSON list or Render API response')
    p.add_argument('--max-deployments',type=int,default=128)
    p.add_argument('--max-events',type=int,default=256)
    p.add_argument('--page-size',type=int,default=50)
    p.add_argument('--out-dir',default='/data/apex_audit_evidence')
    a=p.parse_args(argv)
    if not SERVICE.fullmatch(a.service_id):p.error('invalid service ID')
    if not 1<=a.max_deployments<=128 or not 1<=a.max_events<=256 or not 1<=a.page_size<=100:p.error('invalid bounds')
    out=Path(a.out_dir).resolve()
    if a.mode=='api':
        key=os.getenv('RENDER_API_KEY')
        if not key:p.error('RENDER_API_KEY unavailable; use offline mode with real provider responses or configure key securely')
        ds,es,complete=acquire_api(a.service_id,key,a.max_deployments,a.max_events,a.page_size)
        acquisition='DIRECT_RENDER_API_HTTPS_GET'
    else:
        if not a.raw_deployments or not a.raw_events:p.error('offline mode requires both provider exports')
        ds=unwrap(load_document(a.raw_deployments));es=unwrap(load_document(a.raw_events))
        if len(ds)>a.max_deployments or len(es)>a.max_events:p.error('input count exceeds configured bounds')
        complete={'deployments':False,'events':False}
        acquisition='OPERATOR_SUPPLIED_PROVIDER_JSON_UNAUTHENTICATED'
    normalized,proof=compile_evidence(ds,es,a.service_id,acquisition,False,
        {'max_deployments':a.max_deployments,'max_events':a.max_events,'page_size':a.page_size})
    proof['pagination_exhausted']=complete
    proof['historical_coverage_complete']=all(complete.values())
    names={'deployment-history.json':normalized,'render-native-evidence.json':proof}
    for name,obj in names.items():
        digest,nbytes=atomic_json(out/name,obj,MAX_OUTPUT if name=='deployment-history.json' else None)
        print(name,'bytes',nbytes,'sha256',digest)
    print('Stage 3B.3.3.2 | deployments',len(normalized['deployments']),'| native events',len(proof['native_events']),
          '| claims',len(normalized['events']),'| migration=BLOCKED_RESEARCH_ONLY')
    return 0

if __name__=='__main__':
    try:sys.exit(main())
    except (OSError,ValueError,urllib.error.URLError) as e:
        print('STAGE3B332_COLLECTION_FAILED:',type(e).__name__,str(e)[:160],file=sys.stderr)
        sys.exit(2)
