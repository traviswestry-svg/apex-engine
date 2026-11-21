import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

SCRIPT=Path(__file__).resolve().parents[1]/'scripts'/'apex_stage3b39_runtime_decision_gamma_audit.py'
spec=importlib.util.spec_from_file_location('b39',SCRIPT)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
BOUND=m.parse_time('2026-09-18T13:45:00.256463Z')

def mkdb(root,with_time=True):
    root.mkdir(exist_ok=True,parents=True)
    with sqlite3.connect(root/'apex_evidence_pipeline.db') as c:
        c.execute('CREATE TABLE decisions (decision_id TEXT PRIMARY KEY, observed_at TEXT, ticker TEXT, canonical_gamma_snapshot_id TEXT, snapshot_json TEXT)')
        c.execute('CREATE INDEX idx_observed ON decisions(observed_at)')
        records=[('p','2026-09-14T20:00:00Z','SPX',None,'{}'),
          ('a','2026-09-18T14:00:00Z','SPX','g1',json.dumps({'canonical_gamma_snapshot_id':'g1','apex_release_version':'69.10.14'})),
          ('b','2026-09-18T15:00:00Z','SPX',None,'{}'),
          ('c','2026-09-19T16:00:00Z','SPX','g2','{}'),
          ('d','2026-09-19T17:00:00Z','SPX','g3','{}'),
          ('e','2026-09-19T18:00:00Z','SPX','g1',json.dumps({'canonical_gamma_snapshot_id':'OTHER'}))]
        c.executemany('INSERT INTO decisions VALUES (?,?,?,?,?)',records)
    with sqlite3.connect(root/'apex_tracking.db') as c:
        time='observed_at TEXT,' if with_time else ''
        c.execute(f'CREATE TABLE gamma_observational_snapshots(canonical_gamma_snapshot_id TEXT PRIMARY KEY,ticker TEXT,{time} extra TEXT)')
        if with_time:c.executemany('INSERT INTO gamma_observational_snapshots VALUES (?,?,?,?)',[
          ('g1','SPX','2026-09-18T13:50:00Z',''),('g2','SPX','2026-09-20T00:00:00Z',''),('g3','QQQ','2026-09-19T16:00:00Z','')])
        else:c.executemany('INSERT INTO gamma_observational_snapshots VALUES (?,?,?)', [('g1','SPX',''),('g2','SPX',''),('g3','QQQ','')])
    return root

def test_pure_classifications():
    base={'observed_at':'2026-09-18T15:00:00Z','ticker':'SPX','canonical_gamma_snapshot_id':'id'}
    assert m.classify_decision(base,{'ticker':'SPX','observed_at':'2026-09-18T14:00:00Z'},boundary=BOUND,gamma_time_col='observed_at')=='GAMMA_ID_MATCHED_SYMBOL_TIME_ORDER_CONSISTENT'
    assert m.classify_decision(base,{'ticker':'SPX','observed_at':'2026-09-18T16:00:00Z'},boundary=BOUND,gamma_time_col='observed_at')=='GAMMA_OBSERVATION_AFTER_DECISION_TIME'
    assert m.classify_decision(base,{'ticker':'QQQ','observed_at':'2026-09-18T14:00:00Z'},boundary=BOUND,gamma_time_col='observed_at')=='GAMMA_SYMBOL_CONFLICT'
    assert m.classify_decision(base,None,boundary=BOUND)=='GAMMA_ID_NOT_FOUND'
    assert m.classify_decision({**base,'canonical_gamma_snapshot_id':None},None,boundary=BOUND)=='POST_BOUNDARY_ID_NULL_LEGACY_OR_UNKNOWN'
    assert m.classify_decision({**base,'snapshot_id_conflict':True,'canonical_gamma_snapshot_id':None},None,boundary=BOUND)=='PERSISTED_SNAPSHOT_ID_CONFLICT'
    assert m.classify_decision({**base,'observed_at':'2026-09-14T00:00:00Z'},None,boundary=BOUND)=='PRE_BOUNDARY_RECORD_NO_RETROACTIVE_POLICY'
    assert m.classify_decision({**base,'observed_at':'invalid'},None,boundary=BOUND)=='DECISION_TIME_UNVERIFIABLE'
    assert m.classify_decision(base,{'ticker':'SPX'},boundary=BOUND)=='GAMMA_ID_MATCHED_TIME_COLUMN_UNVERIFIED'

def test_no_latest_substitution_and_counts(tmp_path):
    root=mkdb(tmp_path/'data')
    result=m.sample(root,boundary=BOUND,rows=8)
    assert result['status']=='SAMPLED_RUNTIME_ACTIVATION_AND_RECORD_ORIGIN_UNVERIFIED'
    counts=result['observations']['linkage_counts']
    assert counts['GAMMA_ID_MATCHED_SYMBOL_TIME_ORDER_CONSISTENT']==1
    assert counts['GAMMA_OBSERVATION_AFTER_DECISION_TIME']==1
    assert counts['GAMMA_SYMBOL_CONFLICT']==1
    assert counts['POST_BOUNDARY_ID_NULL_LEGACY_OR_UNKNOWN']==1
    assert counts['PERSISTED_SNAPSHOT_ID_CONFLICT']==1
    assert counts['PRE_BOUNDARY_RECORD_NO_RETROACTIVE_POLICY']==1
    assert result['coverage']['time_window_index_verified']
    assert result['observations']['record_origin_claims_unverified']==1
    assert result['migration_authority']=='BLOCKED_RESEARCH_ONLY'

def test_time_column_unavailable(tmp_path):
    root=mkdb(tmp_path/'data',False)
    r=m.sample(root,boundary=BOUND,rows=8)
    assert r['observations']['gamma_observation_time_column'] is None
    assert r['observations']['linkage_counts']['GAMMA_ID_MATCHED_TIME_COLUMN_UNVERIFIED']==2

def test_missing_db(tmp_path):
    r=m.sample(tmp_path,boundary=BOUND)
    assert r['status']=='DATABASE_INPUT_MISSING'

def test_no_gamma_index(tmp_path):
    root=mkdb(tmp_path/'data')
    with sqlite3.connect(root/'apex_tracking.db') as c:
        c.execute('DROP TABLE gamma_observational_snapshots')
        c.execute('CREATE TABLE gamma_observational_snapshots(canonical_gamma_snapshot_id TEXT,ticker TEXT,observed_at TEXT)')
    r=m.sample(root,boundary=BOUND)
    assert r['status']=='GAMMA_IDENTITY_INDEX_UNVERIFIED'

def test_protect_data_from_output(tmp_path):
    root=mkdb(tmp_path/'data')
    try:m.write_report(root/'report.json',{},root)
    except ValueError:pass
    else:assert False
    report=m.sample(root,boundary=BOUND)
    dest=tmp_path/'out.json'
    m.write_report(dest,report,root)
    assert dest.exists()
    assert 'decision_id' not in json.loads(dest.read_text())['observations']
    assert dest.stat().st_mode & 0o777==0o600

def test_cli(tmp_path):
    root=mkdb(tmp_path/'data')
    out=tmp_path/'report.json'
    res=subprocess.run([sys.executable,str(SCRIPT),'--root',str(root),'--output',str(out)],capture_output=True,text=True)
    assert res.returncode==0,res.stderr
    assert json.loads(out.read_text())['observations']['sampled_decisions']==6


def test_snapshot_identity():
    assert m.extract_snapshot_identity({'canonical_gamma_snapshot_id':'A','gamma_evidence':{'canonical_gamma_snapshot_id':'B'}})=='ROOT_NESTED_ID_CONFLICT'
    assert m.extract_snapshot_identity({'gamma_evidence':{'canonical_gamma_snapshot_id':'B'}})=='B'
    assert m.extract_snapshot_identity({}) is None


def test_missing_column_no_backfill(tmp_path):
    root=mkdb(tmp_path/'data')
    with sqlite3.connect(root/'apex_evidence_pipeline.db') as c:
        c.execute('ALTER TABLE decisions RENAME TO old_decisions')
        c.execute('CREATE TABLE decisions (decision_id TEXT PRIMARY KEY, observed_at TEXT, ticker TEXT, snapshot_json TEXT)')
        c.execute("INSERT INTO decisions VALUES ('only','2026-09-19T00:00:00Z','SPX','{\"canonical_gamma_snapshot_id\":\"g1\"}')")
    r=m.sample(root,boundary=BOUND)
    assert r['observations']['linkage_counts']=={'GAMMA_ID_COLUMN_ABSENT':1}

def test_deployment_boundary_corroboration(tmp_path):
    h=tmp_path/'history.json';n=tmp_path/'native.json'
    h.write_text(json.dumps({'deployments':[{'deploy_id':'dep-good','commit_sha':'a'*40,'service_id':'srv-test','status':'deactivated','started_at':'2026-09-18T13:40:00Z','live_at':'2026-09-18T13:45:00Z'}],
       'events':[{'deploy_id':'dep-good','service_id':'srv-test','event_type':'deploy_activated','outcome':'succeeded','occurred_at':'2026-09-18T13:45:00.1Z'}]}))
    n.write_text(json.dumps({'native_events':[{'deploy_id':'dep-good','service_id':'srv-test','type':'deploy_ended','deploy_status':'succeeded','timestamp':'2026-09-18T13:45:00.1Z'}]}))
    r=m.deployment_boundary(h,n,service='srv-test',deploy_id='dep-good',commit_sha='a'*40)
    assert r['deployment_completion_correlated'] and not r['provider_signed']
    assert not r['runtime_activation_verified']
    assert m.deployment_boundary(h,n,service='srv-test',deploy_id='dep-good',commit_sha='b'*40)['state']=='DEPLOYMENT_IDENTITY_CONFLICT'
    raw=json.loads(n.read_text());raw['native_events'][0]['deploy_status']='failed';n.write_text(json.dumps(raw))
    assert not m.deployment_boundary(h,n,service='srv-test',deploy_id='dep-good',commit_sha='a'*40)['deployment_completion_correlated']
