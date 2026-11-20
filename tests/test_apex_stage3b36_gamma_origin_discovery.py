import importlib.util,json,os,subprocess,stat
from pathlib import Path
import pytest
SRC=Path(__file__).resolve().parents[1]/'scripts'/'apex_stage3b36_gamma_origin_discovery.py'
spec=importlib.util.spec_from_file_location('b36',SRC);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
S='srv-d7p3u2navr4c73d2q0jg'
def cmd(repo,*args):return subprocess.check_output(['git','-C',str(repo),*args],text=True).strip()
def make_repo(tmp):
    repo=tmp/'r';repo.mkdir();subprocess.run(['git','init','-q',str(repo)],check=True)
    cmd(repo,'config','user.email','test@example.invalid');cmd(repo,'config','user.name','Test')
    for mod in m.B35.MODULES:
        f=repo/mod;f.parent.mkdir(exist_ok=True,parents=True);f.write_text('baseline = 1\n')
    cmd(repo,'add','.');cmd(repo,'commit','-qm','before');a=cmd(repo,'rev-parse','HEAD')
    for mod in m.B35.MODULES:
        f=repo/mod;f.write_text('canonical_gamma_snapshot_id=1\nLEGACY_OR_UNKNOWN=1\n')
    cmd(repo,'add','.');cmd(repo,'commit','-qm','after');b=cmd(repo,'rev-parse','HEAD')
    (repo/'other.txt').write_text('unrelated\n');cmd(repo,'add','.');cmd(repo,'commit','-qm','newer');c=cmd(repo,'rev-parse','HEAD')
    return repo,a,b,c

def evidence(tmp,sha):
    d={'deploy_id':'dep-abc123','service_id':S,'commit_sha':sha,'status':'deactivated','started_at':'2026-11-18T12:00:00Z','live_at':'2026-11-18T12:02:00Z'}
    e={'deploy_id':'dep-abc123','service_id':S,'event_type':'deploy_activated','outcome':'succeeded','occurred_at':'2026-11-18T12:02:00Z'}
    n={'deploy_id':'dep-abc123','service_id':S,'type':'deploy_ended','deploy_status':'succeeded','timestamp':'2026-11-18T12:02:00Z'}
    (tmp/'h.json').write_text(json.dumps({'deployments':[d],'events':[e]}))
    (tmp/'n.json').write_text(json.dumps({'native_events':[n]}))
def audit(tmp,repo):return m.run(repo,tmp/'h.json',tmp/'n.json',S)
def test_full_history_marker_intro_found(tmp_path):
    r,a,b,c=make_repo(tmp_path);evidence(tmp_path,c);out,details=audit(tmp_path,r)
    assert out['observations']['marker_origin_candidates']>=1
    assert out['observations']['direct_parent_marker_boundary_candidates']>=1
    assert out['observations']['sampled_deployments_with_markers']==1
    assert any(x['sha']==b and x['ancestor_of_sampled_deployments']==1 for x in details['sampled_deployment_ancestry'])
    assert out['observations']['first_semantic_implementation_commit_verified'] is False
    assert out['observations']['runtime_gamma_activation_verified'] is False

def test_old_deploy_before_marker(tmp_path):
    r,a,b,c=make_repo(tmp_path);evidence(tmp_path,a);out,details=audit(tmp_path,r)
    assert out['observations']['sampled_deployments_without_markers']==1
    assert any(x['sha']==b and x['not_ancestor_of_sampled_deployments']==1 for x in details['sampled_deployment_ancestry'])

def test_missing_git_safe(tmp_path):
    evidence(tmp_path,'a'*40);out,detail=audit(tmp_path,tmp_path/'missing')
    assert out['inputs']['git_repository']=='GIT_REPOSITORY_UNAVAILABLE'
    assert out['observations']['marker_origin_candidates']==0

def test_bounded_changed_search(tmp_path):
    r,a,b,c=make_repo(tmp_path);evidence(tmp_path,c)
    f=r/m.B35.MODULES[0];f.write_text(f.read_text().replace('canonical_gamma_snapshot_id=1','canonical_gamma_snapshot_id=2')+'canonical_gamma_snapshot_id=3\n')
    cmd(r,'add','.');cmd(r,'commit','-qm','extra marker instance')
    out,details=m.run(r,tmp_path/'h.json',tmp_path/'n.json',S,1)
    assert out['observations']['search_complete_within_caps'] is False
    assert out['observations']['marker_origin_candidates']==0

def test_bad_native_event_not_deployed(tmp_path):
    r,a,b,c=make_repo(tmp_path);evidence(tmp_path,c)
    j=tmp_path/'n.json';v=json.loads(j.read_text());v['native_events'][0]['deploy_status']='failed';j.write_text(json.dumps(v))
    out,details=audit(tmp_path,r);assert out['observations']['corroborated_sampled_deployments']==0

def test_no_shas_in_public_report(tmp_path):
    r,a,b,c=make_repo(tmp_path);evidence(tmp_path,c);out,_=audit(tmp_path,r)
    s=json.dumps(out);assert a not in s and b not in s and c not in s and 'dep-abc123' not in s

def test_private_file_permissions(tmp_path):
    p=tmp_path/'private.json';m.write_json(p,{'sha':'a'*40},private=True)
    assert stat.S_IMODE(p.stat().st_mode)==0o600

def test_no_external_git_actions_in_source():
    s=SRC.read_text();assert "'fetch'" not in s and "'clone'" not in s and "'push'" not in s

def test_status_never_verified(tmp_path):
    r,a,b,c=make_repo(tmp_path);evidence(tmp_path,c);out,_=audit(tmp_path,r)
    assert out['migration_authority']=='BLOCKED_RESEARCH_ONLY'
    assert not out['observations']['render_deployment_policy_boundary_verified']
    assert not out['observations']['historical_policy_effective_date_verified']

def test_bare_git_mirror(tmp_path):
    r,a,b,c=make_repo(tmp_path);evidence(tmp_path,c)
    bare=tmp_path/'mirror.git';subprocess.run(['git','clone','--bare','-q',str(r),str(bare)],check=True)
    out,detail=audit(tmp_path,bare)
    assert out['inputs']['git_repository']=='EXTERNAL_GIT_REPOSITORY_READABLE'
    assert out['observations']['direct_parent_marker_boundary_candidates']>=1
