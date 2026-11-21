#!/usr/bin/env python3
"""Stage 3B.3.11: collect historical Git source only; replay selected pure functions offline.

No production database access, network fetching, Git mutation, or historical package imports.
The offline runner is NOT a hardened sandbox for untrusted code: run only in a disposable VM.
"""
import argparse
import builtins
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile
from datetime import datetime, timezone

CANDIDATE = '6f15e854b21b6406a570c100d955ccbbb0debe59'
PARENT = '6d8df89bda76765be4efeb5bbbdc5cb94f3518ab'
FILES = ('engine/evidence_eligibility.py','engine/historical_evidence_lifecycle.py','engine/gamma_transition.py', 'engine/evidence_pipeline.py', 'engine/trigger_observatory.py')
LIMIT = 512_000

def git(repo, *args):
    p = subprocess.run(['git',f'--git-dir={repo}', *args],capture_output=True,timeout=12,check=True)
    if len(p.stdout)>LIMIT: raise ValueError('SOURCE_EXCEEDS_LIMIT')
    return p.stdout

def collect(repo, output):
    repo=Path(repo).resolve()
    if not repo.is_dir(): raise ValueError('GIT_MIRROR_MISSING')
    manifest={'schema':'apex.stage3b311_source_bundle.v1','candidate':CANDIDATE,'parent':PARENT,'files':{},'purpose':'OFFLINE_DISPOSABLE_SEMANTIC_REPLAY_NOT_RUNTIME_ATTESTATION'}
    payload={}
    for label,sha in (('parent',PARENT),('candidate',CANDIDATE)):
        actual=git(repo,'rev-parse','--verify',f'{sha}^{{commit}}').decode().strip()
        if actual!=sha: raise ValueError('COMMIT_IDENTITY_MISMATCH')
        for fname in FILES:
            data=git(repo,'show',f'{sha}:{fname}')
            data.decode('utf-8','strict')
            arc=f'{label}/{fname}'
            payload[arc]=data
            manifest['files'][arc]={'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}
    out=Path(output)
    if out.exists(): raise ValueError('REFUSE_OVERWRITE')
    out.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(out,'x',compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr('manifest.json',json.dumps(manifest,indent=2,sort_keys=True))
        for name,data in payload.items():z.writestr(name,data)
    os.chmod(out,0o600)
    print(f'STAGE3B311_COLLECTION_OK {out} files={len(payload)}; historical code NOT executed')

def bundle_load(path):
    with zipfile.ZipFile(path) as z:
        names=set(z.namelist())
        if names!={'manifest.json'}|{f'{v}/{n}' for v in ('candidate','parent') for n in FILES}:raise ValueError('BUNDLE_CONTENTS_INVALID')
        manifest=json.loads(z.read('manifest.json'))
        if manifest['candidate']!=CANDIDATE or manifest['parent']!=PARENT:raise ValueError('COMMIT_MISMATCH')
        src={}
        for name,meta in manifest['files'].items():
            data=z.read(name)
            if len(data)>LIMIT or len(data)!=meta['bytes'] or hashlib.sha256(data).hexdigest()!=meta['sha256']: raise ValueError('SOURCE_INTEGRITY_ERROR')
            src[name]=data.decode('utf8','strict')
    return src,manifest

# Restricted callable subset: AST extraction of exactly selected pure functions, with
# a deliberately tiny builtins scope. Do not import historical packages or run module top-level.
def eligibility_namespace(source):
    import typing
    tree=ast.parse(source)
    selected=[]
    for node in tree.body:
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) and node.name in {'_m','_f','evaluate_evidence_eligibility'}:
            selected.append(node)
    if {n.name for n in selected}!={'_m','_f','evaluate_evidence_eligibility'}:raise ValueError('ELIGIBILITY_FUNCTIONS_MISSING')
    allowed={'Any':typing.Any,'Dict':typing.Dict,'Mapping':typing.Mapping,'Optional':typing.Optional,
        'SCHEMA_VERSION':'offline.contract','VERSION':'historical',
        '__builtins__':{k:getattr(builtins,k) for k in ('dict','isinstance','str','float','bool','min','max','round','len','list','tuple','int','Exception','TypeError','ValueError','type','KeyError') if hasattr(builtins,k)}}
    # f annotations resolved lazily as needed, without importing historic module
    class StripAnnotations(ast.NodeTransformer):
        def visit_arg(self, node):
            node.annotation=None
            return node
        def visit_FunctionDef(self, node):
            node.returns=None
            self.generic_visit(node)
            return node
    selected=[StripAnnotations().visit(n) for n in selected]
    mod=ast.fix_missing_locations(ast.Module(body=selected,type_ignores=[]))
    code=compile(mod,'<historical-eligibility-selected-functions>','exec')
    exec(code,allowed)
    return allowed

def fixtures():
    base={'freshness_state':'CURRENT','direction':'BULLISH'}
    def ds(**kw):return {'gamma_context':{'structure_durability':'HIGH','capacity_state':'STRONG'},'gamma_transition':{'canonical_gamma_snapshot_id':'G-001','freshness_state':'FRESH','continuity_state':'CONTINUOUS','provenance_class':'LIVE',**kw}}
    return [
      ('valid_contemporaneous',base,ds(), 'FULL',[]),
      ('unknown_freshness',base,ds(freshness_state='UNKNOWN'),'INELIGIBLE',['GAMMA_INTEGRITY_FRESHNESS_UNKNOWN']),
      ('stale',base,ds(freshness_state='STALE'),'CONTEXT_ONLY',['STALE_CANONICAL_GAMMA_EVIDENCE']),
      ('aging',base,ds(freshness_state='AGING'),'DISCOUNTED',['AGING_CANONICAL_GAMMA_EVIDENCE']),
      ('reconstructed',base,ds(provenance_class='RECONSTRUCTED'),'CONTEXT_ONLY',['NON_CONTEMPORANEOUS_GAMMA_PROVENANCE']),
      ('replayed',base,ds(provenance_class='REPLAYED'),'CONTEXT_ONLY',['NON_CONTEMPORANEOUS_GAMMA_PROVENANCE']),
      ('backfilled',base,ds(provenance_class='BACKFILLED'),'CONTEXT_ONLY',['NON_CONTEMPORANEOUS_GAMMA_PROVENANCE']),
      ('gapped',base,ds(continuity_state='GAPPED'),'CONTEXT_ONLY',['GAPPED_GAMMA_OBSERVATION_SEQUENCE']),
      ('unknown_continuity',base,ds(continuity_state='UNKNOWN'),'CONTEXT_ONLY',['GAMMA_CONTINUITY_UNKNOWN']),
      ('unknown_id_without_freshness',base,ds(freshness_state=None),'INELIGIBLE',['GAMMA_INTEGRITY_FRESHNESS_UNKNOWN']),
      ('no_identity_legacy',base,{'gamma_transition':{},'gamma_context':{}},'FULL',[]),
      ('low_durability',base,{'gamma_transition':{},'gamma_context':{'structure_durability':'LOW'}},'CONTEXT_ONLY',['LOW_GAMMA_STRUCTURE_DURABILITY']),
      ('weak_capacity',base,{'gamma_transition':{},'gamma_context':{'capacity_state':'WEAK'}},'DISCOUNTED',['WEAK_GAMMA_STABILIZATION_CAPACITY']),
      ('watch_only_event',base,{**ds(),'event_phase':{'phase':'RELEASE'}},'WATCH_ONLY',['EVENT_RELEASE_BOUNDARY']),
      ('stale_opinion',{'freshness_state':'STALE','direction':'BULLISH'},ds(),'CONTEXT_ONLY',['STALE_EVIDENCE']),
    ]

def freeze_namespace(source, lookup):
    import typing
    tree=ast.parse(source)
    picked=[]
    for node in tree.body:
        if isinstance(node,ast.FunctionDef) and node.name in {'_path','_dealer_gamma_eligibility','_freeze_gamma_evidence'}:
            picked.append(node)
    if {n.name for n in picked}!={'_path','_dealer_gamma_eligibility','_freeze_gamma_evidence'}:
        return None
    class ContractTransformer(ast.NodeTransformer):
        def visit_arg(self, node):
            node.annotation=None;return node
        def visit_FunctionDef(self,node):
            node.returns=None;self.generic_visit(node);return node
        def visit_ImportFrom(self,node):
            if node.level==1 and node.module=='gamma_transition' and len(node.names)==1 and node.names[0].name=='decision_time_gamma_evidence':
                return ast.Assign(targets=[ast.Name(id='decision_time_gamma_evidence',ctx=ast.Store())],value=ast.Name(id='__gamma_lookup',ctx=ast.Load()))
            raise ValueError('UNAPPROVED_IMPORT')
    picked=[ContractTransformer().visit(n) for n in picked]
    safe={'Mapping':typing.Mapping,'Dict':typing.Dict,'Optional':typing.Optional,'Any':typing.Any,
        '__gamma_lookup':lookup,
        '__builtins__':{k:getattr(builtins,k) for k in ('dict','isinstance','str','float','bool','min','max','round','len','list','tuple','int','Exception','TypeError','ValueError','type','KeyError')}}
    exec(compile(ast.fix_missing_locations(ast.Module(body=picked,type_ignores=[])),'<historical-freeze-selected-functions>','exec'),safe)
    return safe

def validate_freeze(candidate_source):
    called=[]
    def lookup(snapshot_id,*,decision_time,market_state):
        called.append({'id':snapshot_id,'decision_time':decision_time,'market_state':market_state})
        if snapshot_id=='MISSING':raise KeyError('NO_SUCH_GAMMA_ID')
        return {'canonical_gamma_snapshot_id':snapshot_id,'linkage_status':'EXACT_ID_MATCH',
                'freshness_state':'FRESH','continuity_state':'CONTINUOUS','provenance_class':'LIVE',
                'gamma_snapshot_age_seconds':0,'durability':'HIGH'}
    ns=freeze_namespace(candidate_source,lookup)
    if ns is None:return {'state':'FUNCTION_MISSING','passed':0,'tests':[]}
    fn=ns['_freeze_gamma_evidence']
    def run(root,ds=None):
        return fn(root,{},ds or {},decision_time='2026-09-18T14:00:00Z',session_state='REGULAR')
    tests=[]
    def record(name,passed,details):tests.append({'fixture':name,'pass':bool(passed),'details':details})
    b=len(called);v=run({});record('legacy_no_latest_substitution',v.get('linkage_status')=='LEGACY_OR_UNKNOWN' and v.get('canonical_gamma_snapshot_id') is None and len(called)==b,{'linkage_status':v.get('linkage_status'),'lookup_calls':len(called)-b})
    b=len(called);v=run({'gamma_transition':{'canonical_gamma_snapshot_id':'A'}});record('exact_id_only',len(called)==b+1 and called[-1]['id']=='A' and v.get('canonical_gamma_snapshot_id')=='A' and v.get('later_gamma_substitution_allowed') is False,{'result_id':v.get('canonical_gamma_snapshot_id')})
    b=len(called);v=run({'gamma_transition':{'canonical_gamma_snapshot_id':'MISSING'}});record('missing_id_lookup_error_no_fallback',len(called)==b+1 and called[-1]['id']=='MISSING' and v.get('linkage_status')=='LINKAGE_LOOKUP_ERROR' and v.get('canonical_gamma_snapshot_id')=='MISSING',{'linkage_status':v.get('linkage_status')})
    b=len(called);v=run({'gamma_transition':{'canonical_gamma_snapshot_id':'A'}},{'gamma_transition':{'canonical_gamma_snapshot_id':'B'},'gamma_context':{'capacity_ratio':2,'capacity_state':'STRONG'}});record('mismatched_dynamic_id_does_not_steal_capacity',len(called)==b+1 and 'capacity_ratio' not in v and 'gamma_context_snapshot_id' not in v,{'capacity_present':'capacity_ratio' in v})
    v=run({'gamma_transition':{'canonical_gamma_snapshot_id':'A'}},{'gamma_transition':{'canonical_gamma_snapshot_id':'A'},'gamma_context':{'capacity_ratio':2,'capacity_state':'STRONG'}});record('matching_dynamic_id_copies_capacity',v.get('capacity_ratio')==2 and v.get('gamma_context_snapshot_id')=='A',{'capacity_ratio':v.get('capacity_ratio')})
    v=run({'gamma_transition':{'canonical_gamma_snapshot_id':'A'}});record('replay_deterministic',v==run({'gamma_transition':{'canonical_gamma_snapshot_id':'A'}}),{'equal':True})
    return {'state':'SELECTED_FUNCTION_EXECUTED','passed':sum(x['pass'] for x in tests),'tests':tests}

def run_validate(bundle, output):
    if os.getenv('RENDER_SERVICE_ID') or os.getenv('RENDER') or Path('/opt/render/project').exists():
        raise ValueError('REFUSE_HISTORICAL_EXECUTION_ON_RENDER')
    src,man=bundle_load(bundle)
    en={v:eligibility_namespace(src[f'{v}/engine/evidence_eligibility.py']) for v in ('parent','candidate')}
    results=[]; critical_failed=[]
    for name,op,state,expect,reasons in fixtures():
        d={}
        for ver in ('parent','candidate'):
            fn=en[ver]['evaluate_evidence_eligibility']
            a=fn('dealer',op,state); b=fn('dealer',op,state)
            d[ver]={'state':a['state'],'weight_factor':a['weight_factor'],'reasons':a['reasons'],'deterministic':a==b}
        c=d['candidate']; passed=c['state']==expect and all(r in c['reasons'] for r in reasons) and c['deterministic']
        if not passed:critical_failed.append(name)
        results.append({'fixture':name,'pass':passed,'parent':d['parent'],'candidate':c,'changed':d['parent']!=c})
    # Must not claim persistence/decision snapshot semantic validity: inspected statically only.
    checks={}
    for ver in ('parent','candidate'):
        s=src[f'{ver}/engine/historical_evidence_lifecycle.py']; t=ast.parse(s)
        names={x.name for x in t.body if isinstance(x,ast.FunctionDef)}
        checks[ver]={'freeze_function_present':'_freeze_gamma_evidence' in names,'has_legacy_unknown':'LEGACY_OR_UNKNOWN' in s,'has_no_later_substitution_indicator':'later_gamma_substitution_allowed' in s}
    freeze=validate_freeze(src['candidate/engine/historical_evidence_lifecycle.py'])
    if freeze['passed']!=len(freeze['tests']) or freeze['state']!='SELECTED_FUNCTION_EXECUTED':critical_failed.append('freeze_contract')
    report={'schema':'apex.stage3b311_semantic_replay.v1','mode':'OFFLINE_DISPOSABLE_SELECTED_FUNCTION_REPLAY',
      'status':'SELECTED_SEMANTIC_FIXTURES_PASSED_OTHER_GATES_UNVERIFIED' if not critical_failed else 'SEMANTIC_FIXTURE_FAILURE_MIGRATION_BLOCKED',
      'fixture_count':len(results),'fixture_passed':len(results)-len(critical_failed),'fixture_failed':critical_failed,
      'fixtures':results,'snapshot_freeze_selected_execution':freeze,'snapshot_freeze_static_indicators':checks,
      'coverage':{'eligibility_function_executed':True,'snapshot_freeze_function_executed':freeze['state']=='SELECTED_FUNCTION_EXECUTED','decision_time_lookup_executed':False,'persistence_tested':False,'production_runtime_activation_verified':False,'historical_population_replay_verified':False,'isolation_attested':False},
      'limitations':['Selected function extraction is not full historical module execution','Python subprocess/VM separation must be independently enforced; this is not a security sandbox','No historical gamma database or real historical decision records were used','Snapshot freeze function tested only against a synthetic exact-ID gamma lookup; real provider availability and lookup implementation untested','Git source SHA256 is transfer integrity, not independent source attestation'],
      'migration_authority':'BLOCKED_RESEARCH_ONLY','guardrails':{'no_production_db_access':True,'no_git_mutations':True,'no_backfill':True,'no_trade_execution':True,'no_reader_cutover':True}}
    out=Path(output)
    if out.exists(): raise ValueError('REFUSE_OVERWRITE')
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(f'STAGE3B311 {report["status"]} eligibility={sum(r["pass"] for r in results)}/{len(results)} freeze={freeze["passed"]}/{len(freeze["tests"])} migration=BLOCKED_RESEARCH_ONLY')
    return 0 if not critical_failed else 2

def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--mode',choices=['collect','validate'],required=True)
    p.add_argument('--git-repository');p.add_argument('--bundle');p.add_argument('--output',required=True)
    a=p.parse_args(argv)
    if a.mode=='collect':
        if not a.git_repository: p.error('--git-repository required for collect')
        collect(a.git_repository,a.output);return 0
    if not a.bundle:p.error('--bundle required for validate')
    return run_validate(a.bundle,a.output)
if __name__=='__main__':raise SystemExit(main())
