import importlib.util,json,subprocess
from pathlib import Path
import pytest
SCRIPT=Path(__file__).resolve().parents[1]/'scripts'/'apex_stage3b34_gamma_commit_activation_audit.py'
spec=importlib.util.spec_from_file_location('audit',SCRIPT)
audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)
SERVICE='srv-d7p3u2navr4c73d2q0jg';SHA='a'*40

def fixture(tmp_path,status='deactivated',matched=True):
    d={'deploy_id':'dep-abc123','service_id':SERVICE,'commit_sha':SHA,'status':status,'started_at':'2026-11-18T12:00:00Z','live_at':'2026-11-18T12:02:00Z'}
    claims=[{'deploy_id':'dep-abc123','service_id':SERVICE,'event_type':'deploy_activated','outcome':'succeeded','occurred_at':'2026-11-18T12:02:00Z'}]
    native=[{'deploy_id':'dep-abc123','service_id':SERVICE,'type':'deploy_ended','timestamp':'2026-11-18T12:02:00Z','deploy_status':'succeeded' if matched else 'failed'}]
    (tmp_path/'history.json').write_text(json.dumps({'deployments':[d],'events':claims}))
    (tmp_path/'native.json').write_text(json.dumps({'native_events':native}))
    return d

def report(tmp_path):return audit.run(tmp_path,tmp_path/'history.json',tmp_path/'native.json',SERVICE)
def test_missing_inputs_safe(tmp_path):
    r=report(tmp_path);assert r['observations']['corroborated_deployments']==0;assert r['migration_authority']=='BLOCKED_RESEARCH_ONLY'
def test_linked_replaced_deployment(tmp_path):
    fixture(tmp_path);r=report(tmp_path)
    assert r['observations']['corroborated_deployments']==1
    assert r['observations']['counts']['REPLACED_DEPLOYMENT_WITH_SUCCESS_CLAIM']==1
    assert not r['observations']['runtime_gamma_activation_verified']
def test_failed_native_not_matched(tmp_path):
    fixture(tmp_path,matched=False);assert report(tmp_path)['observations']['corroborated_deployments']==0
def test_wrong_service_not_matched(tmp_path):
    fixture(tmp_path);p=tmp_path/'native.json';x=json.loads(p.read_text());x['native_events'][0]['service_id']='srv-other';p.write_text(json.dumps(x))
    assert report(tmp_path)['observations']['corroborated_deployments']==0
def test_no_retroactive_dates(tmp_path):
    fixture(tmp_path,status='live');r=report(tmp_path)
    assert not r['observations']['historical_effective_date_verified']
    assert not r['observations']['historical_eligibility_verified']
def test_duplicate_deployment_rejected(tmp_path):
    d=fixture(tmp_path);p=tmp_path/'history.json';x=json.loads(p.read_text());x['deployments'].append(d);p.write_text(json.dumps(x))
    assert report(tmp_path)['observations']['eligible_deployments']==0
def test_bad_commit_rejected(tmp_path):
    fixture(tmp_path);p=tmp_path/'history.json';x=json.loads(p.read_text());x['deployments'][0]['commit_sha']='BAD';p.write_text(json.dumps(x))
    assert report(tmp_path)['observations']['eligible_deployments']==0
def test_missing_parent_not_first_commit(tmp_path):
    z=audit.classify_commit(tmp_path,SHA,{})
    assert not z['code_markers_seen']
def test_input_size_cap(tmp_path):
    p=tmp_path/'large';p.write_bytes(b'a'*(audit.MAX_BYTES+1))
    assert audit.load(p)[1]=='UNAVAILABLE_OR_OVERSIZE'
def test_output_no_identifiers(tmp_path):
    fixture(tmp_path);s=json.dumps(report(tmp_path));assert 'dep-abc123' not in s and SHA not in s
def test_invalid_timestamps(tmp_path):
    fixture(tmp_path);p=tmp_path/'history.json';x=json.loads(p.read_text());x['deployments'][0]['started_at']='nottime';p.write_text(json.dumps(x))
    assert report(tmp_path)['observations']['eligible_deployments']==0
def test_commit_parent_introduction_candidate(tmp_path):
    root=tmp_path;subprocess.run(['git','init','-q',str(root)],check=True)
    subprocess.run(['git','-C',str(root),'config','user.email','apex@test.invalid'],check=True)
    subprocess.run(['git','-C',str(root),'config','user.name','APEX test'],check=True)
    for m in audit.MODULES:
        p=root/m;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('unrelated = 1\n')
    subprocess.run(['git','-C',str(root),'add','.'],check=True)
    subprocess.run(['git','-C',str(root),'commit','-qm','before'],check=True)
    for m in audit.MODULES:
        p=root/m;p.write_text('canonical_gamma_snapshot_id = 1\nLEGACY_OR_UNKNOWN = 1\n')
    subprocess.run(['git','-C',str(root),'add','.'],check=True)
    subprocess.run(['git','-C',str(root),'commit','-qm','after'],check=True)
    sha=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
    c=audit.classify_commit(root,sha,{})
    assert c['code_markers_seen'] and c['parent_markers_seen'] is False
    assert c['implementation_contract_verified'] is False
def test_runtime_claim_not_promoted(tmp_path):
    fixture(tmp_path)
    p=tmp_path/'runtime.json'
    p.write_text(json.dumps({'observations':[{'service_id':SERVICE,'commit_sha':SHA,
        'observed_at':'2026-11-18T12:04:00Z',
        'feature':'canonical_gamma_decision_time_identity','state':'enabled'}]}))
    r=audit.run(tmp_path,tmp_path/'history.json',tmp_path/'native.json',SERVICE,runtime_path=p)
    assert r['observations']['runtime_claim_states']['RUNTIME_FEATURE_ENABLED_CLAIM_UNAUTHENTICATED']==1
    assert not r['observations']['runtime_gamma_activation_verified']
def test_runtime_wrong_sha_rejected(tmp_path):
    fixture(tmp_path)
    p=tmp_path/'runtime.json'
    p.write_text(json.dumps({'observations':[{'service_id':SERVICE,'commit_sha':'b'*40,
        'observed_at':'2026-11-18T12:04:00Z','feature':'canonical_gamma_decision_time_identity','state':'enabled'}]}))
    r=audit.run(tmp_path,tmp_path/'history.json',tmp_path/'native.json',SERVICE,runtime_path=p)
    assert r['observations']['runtime_claim_states']['COMMIT_NOT_IN_DEPLOYMENT_COHORT']==1
