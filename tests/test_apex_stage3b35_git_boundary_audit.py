import importlib.util,json,subprocess
from pathlib import Path
import pytest
SRC=Path(__file__).resolve().parents[1]/'scripts'/'apex_stage3b35_git_boundary_audit.py'
spec=importlib.util.spec_from_file_location('b35',SRC)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
S='srv-d7p3u2navr4c73d2q0jg'
def cmd(repo,*args):return subprocess.check_output(['git','-C',str(repo),*args],text=True).strip()
def repo(tmp):
    root=tmp/'source';root.mkdir();subprocess.run(['git','init','-q',str(root)],check=True)
    cmd(root,'config','user.email','test@example.invalid');cmd(root,'config','user.name','Test')
    for file in m.MODULES:
        p=root/file;p.parent.mkdir(exist_ok=True,parents=True);p.write_text('value = 1\n')
    cmd(root,'add','.');cmd(root,'commit','-qm','before');old=cmd(root,'rev-parse','HEAD')
    for file in m.MODULES:(root/file).write_text('canonical_gamma_snapshot_id=1\nLEGACY_OR_UNKNOWN=1\n')
    cmd(root,'add','.');cmd(root,'commit','-qm','after');new=cmd(root,'rev-parse','HEAD')
    return root,old,new

def fixture(tmp,sha,matched=True,status='deactivated'):
    d={'deploy_id':'dep-abc123','service_id':S,'commit_sha':sha,'status':status,
       'started_at':'2026-11-18T12:00:00Z','live_at':'2026-11-18T12:02:00Z'}
    e={'deploy_id':'dep-abc123','service_id':S,'event_type':'deploy_activated','outcome':'succeeded','occurred_at':'2026-11-18T12:02:00Z'}
    n={'deploy_id':'dep-abc123','service_id':S,'type':'deploy_ended','deploy_status':'succeeded' if matched else 'failed','timestamp':'2026-11-18T12:02:00Z'}
    (tmp/'h.json').write_text(json.dumps({'deployments':[d],'events':[e]}))
    (tmp/'n.json').write_text(json.dumps({'native_events':[n]}))
    return d,e,n

def run(tmp,repository):return m.run(repository,tmp/'h.json',tmp/'n.json',S)
def test_direct_parent_candidate(tmp_path):
    r,old,new=repo(tmp_path);fixture(tmp_path,new)
    out=run(tmp_path,r);assert out['observations']['direct_parent_marker_boundary_candidates']==1
    assert not out['observations']['first_historical_implementation_commit_verified']
    assert not out['observations']['historical_effective_date_verified']
def test_parent_already_marked(tmp_path):
    r,old,new=repo(tmp_path);p=r/'engine/evidence_pipeline.py';p.write_text(p.read_text()+'z=3\n');cmd(r,'add','.');cmd(r,'commit','-qm','again');fixture(tmp_path,cmd(r,'rev-parse','HEAD'))
    assert run(tmp_path,r)['observations']['counts']['MARKERS_PRESENT_IN_PARENT']==1
def test_marker_absent(tmp_path):
    r,old,new=repo(tmp_path);fixture(tmp_path,old)
    assert run(tmp_path,r)['observations']['counts']['IMPLEMENTATION_MARKERS_UNVERIFIED']==1
def test_missing_git_safe(tmp_path):
    fixture(tmp_path,'a'*40)
    o=run(tmp_path,tmp_path/'missing')
    assert o['inputs']['git_repository']=='GIT_REPOSITORY_UNAVAILABLE'
    assert not o['observations']['runtime_gamma_activation_verified']
def test_failed_event_rejected(tmp_path):
    r,old,new=repo(tmp_path);fixture(tmp_path,new,matched=False)
    assert run(tmp_path,r)['observations']['successful_deployment_correlations']==0
def test_replaced_deployment_valid(tmp_path):
    r,old,new=repo(tmp_path);fixture(tmp_path,new,status='deactivated')
    assert run(tmp_path,r)['observations']['counts']['REPLACED_DEPLOYMENT_SUCCESS_CORROBORATED']==1
def test_bad_sha_rejected(tmp_path):
    r,old,new=repo(tmp_path);fixture(tmp_path,'a'*39)
    assert run(tmp_path,r)['observations']['counts']['INVALID_DEPLOYMENT']==1
def test_dup_id_rejected(tmp_path):
    r,old,new=repo(tmp_path);d,e,n=fixture(tmp_path,new);p=tmp_path/'h.json';v=json.loads(p.read_text());v['deployments'].append(d);p.write_text(json.dumps(v))
    assert run(tmp_path,r)['observations']['successful_deployment_correlations']==0
def test_wrong_service_rejected(tmp_path):
    r,old,new=repo(tmp_path);fixture(tmp_path,new);p=tmp_path/'n.json';v=json.loads(p.read_text());v['native_events'][0]['service_id']='srv-wrong';p.write_text(json.dumps(v))
    assert run(tmp_path,r)['observations']['successful_deployment_correlations']==0
def test_no_identifiers_exported(tmp_path):
    r,old,new=repo(tmp_path);fixture(tmp_path,new);out=json.dumps(run(tmp_path,r));assert new not in out and 'dep-abc123' not in out
def test_shallow_or_unavailable_commit(tmp_path):
    r,old,new=repo(tmp_path);x=m.commit(r,'f'*40,{});assert x['state']!='COMMIT_OBJECT_READABLE'
def test_oversized_file(tmp_path):
    p=tmp_path/'big.json';p.write_bytes(b'x'*(m.MAX_FILE_BYTES+1));assert m.load(p)[1]=='MISSING_OR_OVERSIZE'
def test_bad_timestamps(tmp_path):
    r,old,new=repo(tmp_path);fixture(tmp_path,new);p=tmp_path/'h.json';v=json.loads(p.read_text());v['deployments'][0]['started_at']='bad';p.write_text(json.dumps(v))
    assert run(tmp_path,r)['observations']['counts']['INVALID_DEPLOYMENT']==1
def test_no_remote_commands_in_script():
    source=SRC.read_text();assert "'fetch'" not in source and "'clone'" not in source
