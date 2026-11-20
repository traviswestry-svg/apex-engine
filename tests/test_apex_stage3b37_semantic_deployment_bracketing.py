import importlib.util,json,stat,subprocess
from pathlib import Path
SRC=Path(__file__).resolve().parents[1]/'scripts'/'apex_stage3b37_semantic_deployment_bracketing.py'
spec=importlib.util.spec_from_file_location('b37',SRC);b37=importlib.util.module_from_spec(spec);spec.loader.exec_module(b37)
SERVICE='srv-d7p3u2navr4c73d2q0jg'
def git(repo,*args):return subprocess.check_output(['git','-C',str(repo),*args],text=True).strip()
def make_repo(tmp):
    r=tmp/'repo';r.mkdir();git(r,'init','-q');git(r,'config','user.name','Test');git(r,'config','user.email','test@example.invalid')
    for path,contract in b37.CONTRACT.items():
        p=r/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('baseline=1\n')
    git(r,'add','.');git(r,'commit','-qm','before');a=git(r,'rev-parse','HEAD')
    for path,contract in b37.CONTRACT.items():
        funcs='\n'.join('def '+f+'(): pass' for f in contract['functions'])
        s='\n'.join('# '+v for v in contract['tokens'])
        (r/path).write_text(funcs+'\n'+s+'\n')
    git(r,'add','.');git(r,'commit','-qm','implementation candidate');b=git(r,'rev-parse','HEAD')
    (r/'unrelated.txt').write_text('unrelated');git(r,'add','.');git(r,'commit','-qm','after');c=git(r,'rev-parse','HEAD')
    return r,a,b,c

def evidence(tmp,deps):
    rows=[];claims=[];native=[]
    for i,(sha,hour) in enumerate(deps):
        id=f'dep-test{i}';start=f'2026-09-18T{hour:02d}:00:00Z';end=f'2026-09-18T{hour:02d}:02:00Z'
        rows.append(dict(deploy_id=id,service_id=SERVICE,commit_sha=sha,status='deactivated',started_at=start,live_at=end))
        claims.append(dict(deploy_id=id,service_id=SERVICE,event_type='deploy_activated',outcome='succeeded',occurred_at=end))
        native.append(dict(deploy_id=id,service_id=SERVICE,type='deploy_ended',deploy_status='succeeded',timestamp=end))
    (tmp/'h.json').write_text(json.dumps(dict(deployments=rows,events=claims)))
    (tmp/'n.json').write_text(json.dumps(dict(native_events=native)))
    return tmp/'h.json',tmp/'n.json'

def test_source_candidate_and_bracket(tmp_path):
    r,a,b,c=make_repo(tmp_path);h,n=evidence(tmp_path,[(a,10),(c,12)])
    report,detail=b37.run(r,SERVICE,h,n,b)
    x=report['observations']
    assert x['semantic_source_contract']['static_contract_introduced_at_candidate']
    assert x['offline_before_after_bracket_candidate']
    assert x['deployment_relation_counts']=={'before':1,'after':1,'unclassifiable':0}
    assert detail['deployment_bracket_candidate']['before_sha']==a
    assert report['migration_authority']=='BLOCKED_RESEARCH_ONLY'
    assert not x['runtime_gamma_activation_verified']
    assert not x['historical_policy_effective_date_verified']

def test_eight_after_only_not_bracket(tmp_path):
    r,a,b,c=make_repo(tmp_path);h,n=evidence(tmp_path,[(c,12),(c,13)])
    report,_=b37.run(r,SERVICE,h,n,b)
    assert not report['observations']['offline_before_after_bracket_candidate']
    assert report['observations']['deployment_relation_counts']['after']==2

def test_bad_native_event_rejected(tmp_path):
    r,a,b,c=make_repo(tmp_path);h,n=evidence(tmp_path,[(a,10),(c,12)])
    j=json.loads(n.read_text());j['native_events'][0]['deploy_status']='failed';n.write_text(json.dumps(j))
    report,_=b37.run(r,SERVICE,h,n,b)
    assert not report['observations']['offline_before_after_bracket_candidate']
    assert report['observations']['deployments_correlated']==1

def test_source_partial_not_semantic(tmp_path):
    r,a,b,c=make_repo(tmp_path);h,n=evidence(tmp_path,[(a,10),(c,12)])
    (r/'engine/trigger_observatory.py').write_text('something_else=1\n')
    git(r,'add','.');git(r,'commit','-qm','new broken source');broken=git(r,'rev-parse','HEAD')
    report,_=b37.run(r,SERVICE,h,n,broken)
    assert not report['observations']['semantic_source_contract']['static_contract_introduced_at_candidate']
    assert not report['observations']['offline_before_after_bracket_candidate']

def test_invalid_git_fails_closed(tmp_path):
    h,n=evidence(tmp_path,[('a'*40,12)])
    report,_=b37.run(tmp_path/'missing',SERVICE,h,n,'b'*40)
    assert report['status']=='SOURCE_PROVENANCE_UNVERIFIED'
    assert report['migration_authority']=='BLOCKED_RESEARCH_ONLY'

def test_duplicate_deployment_id_rejected(tmp_path):
    r,a,b,c=make_repo(tmp_path);h,n=evidence(tmp_path,[(a,10),(c,12)])
    j=json.loads(h.read_text());j['deployments'].append(j['deployments'][0]);h.write_text(json.dumps(j))
    report,_=b37.run(r,SERVICE,h,n,b)
    assert not report['observations']['offline_before_after_bracket_candidate']
    assert report['observations']['rejected_deployments']['DUPLICATE_ID']==1

def test_private_vs_summary(tmp_path):
    r,a,b,c=make_repo(tmp_path);h,n=evidence(tmp_path,[(a,10),(c,12)])
    report,details=b37.run(r,SERVICE,h,n,b)
    assert b not in json.dumps(report) and a not in json.dumps(report) and 'dep-test' not in json.dumps(report)
    out=tmp_path/'private.json';b37.B36.write_json(out,details,private=True)
    assert stat.S_IMODE(out.stat().st_mode)==0o600

def test_historical_source_never_imported():
    assert 'no_historical_code_execution' in SRC.read_text()
    assert 'subprocess.run' not in SRC.read_text()
