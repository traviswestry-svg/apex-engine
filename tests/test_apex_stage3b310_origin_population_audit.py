import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import pytest

SCRIPTS=Path(__file__).resolve().parents[1]/'scripts'
sys.path.insert(0,str(SCRIPTS))
spec=importlib.util.spec_from_file_location('b310',SCRIPTS/'apex_stage3b310_origin_population_audit.py')
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
BOUND=m.parse_time('2026-09-18T13:45:00.256463Z')


def fixture(root,with_index=True,with_snapshot=True,missing_id=False,without_gamma=False):
    root.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(root/'apex_evidence_pipeline.db') as db:
        cols='decision_id TEXT PRIMARY KEY, observed_at TEXT, ticker TEXT'
        if not missing_id:cols+=', canonical_gamma_snapshot_id TEXT'
        if with_snapshot:cols+=', snapshot_json TEXT'
        db.execute(f'CREATE TABLE decisions ({cols})')
        decisions=[
          ('p','2026-09-14T20:00:00Z','SPX',None,{}),
          ('a','2026-09-18T14:00:00Z','SPX','g1',{'canonical_gamma_snapshot_id':'g1','apex_release_version':'69.10.14'}),
          ('b','2026-09-18T15:00:00Z','SPX',None,{}),
          ('c','2026-09-19T16:00:00Z','SPX','g2',{}),
          ('d','2026-09-19T17:00:00Z','SPX','g3',{}),
          ('e','2026-09-19T18:00:00Z','SPX','g1',{'canonical_gamma_snapshot_id':'other'}),
          ('f','2026-09-20T00:00:00Z','SPX','missing',{}),
          ('g','2026-09-20T01:00:00Z','SPX','gdup',{}),
        ]
        for did,ts,symbol,gid,snap in decisions:
            values=[did,ts,symbol]
            if not missing_id:values.append(gid)
            if with_snapshot:values.append(json.dumps(snap))
            db.execute('INSERT INTO decisions VALUES ('+','.join('?' for _ in values)+')',values)
    if not without_gamma:
        with sqlite3.connect(root/'apex_tracking.db') as db:
            db.execute('CREATE TABLE gamma_observational_snapshots(canonical_gamma_snapshot_id TEXT,ticker TEXT,observed_at TEXT)')
            if with_index:db.execute('CREATE INDEX gamma_idx ON gamma_observational_snapshots(canonical_gamma_snapshot_id)')
            db.executemany('INSERT INTO gamma_observational_snapshots VALUES (?,?,?)',[
               ('g1','SPX','2026-09-18T13:50:00Z'),('g2','SPX','2026-09-20T00:00:00Z'),
               ('g3','QQQ','2026-09-19T16:00:00Z'),('gdup','SPX','2026-09-19T00:00:00Z'),
               ('gdup','SPX','2026-09-19T00:00:00Z')])
    return root


def test_full_reconciled_population(tmp_path):
    root=fixture(tmp_path/'data')
    r=m.audit(root,boundary=BOUND,max_rows=8,batch_size=3)
    assert r['status']=='POPULATION_COUNT_RECONCILED_ORIGIN_UNATTESTED'
    assert r['coverage']['population_coverage_verified'] is True
    assert r['coverage']['scanned_rows']==8
    assert r['coverage']['decision_total']==8
    assert r['observations']['linkage_counts']=={
      'PRE_REFERENCE_NO_RETROACTIVE_POLICY':1,
      'GAMMA_ID_SYMBOL_TIME_CONSISTENT':1,
      'GAMMA_ID_MISSING_LEGACY_OR_UNKNOWN':1,
      'GAMMA_OBSERVATION_AFTER_DECISION':1,
      'GAMMA_SYMBOL_CONFLICT':1,
      'PERSISTED_SNAPSHOT_ID_CONFLICT':1,
      'GAMMA_ID_UNRESOLVED':1,
      'GAMMA_ID_AMBIGUOUS_DUPLICATE':1,
    }
    assert r['observations']['origin_claim_states']['ORIGIN_VERSION_CLAIM_ONLY']==1
    assert not r['observations']['origin_version_attested']
    assert not r['observations']['runtime_gamma_activation_verified']
    assert r['migration_authority']=='BLOCKED_RESEARCH_ONLY'


def test_cap_is_partial_not_population(tmp_path):
    root=fixture(tmp_path/'data')
    r=m.audit(root,boundary=BOUND,max_rows=3,batch_size=2)
    assert r['coverage']['scanned_rows']==3
    assert r['coverage']['stop_reason']=='ROW_LIMIT_REACHED'
    assert not r['coverage']['population_coverage_verified']


def test_missing_gamma_fails_closed(tmp_path):
    r=m.audit(fixture(tmp_path/'data',without_gamma=True),boundary=BOUND)
    assert r['status']=='INPUT_MISSING'


def test_missing_index_fails_closed(tmp_path):
    r=m.audit(fixture(tmp_path/'data',with_index=False),boundary=BOUND)
    assert r['status']=='GAMMA_IDENTITY_INDEX_MISSING'


def test_missing_decision_id_column_never_backfills(tmp_path):
    r=m.audit(fixture(tmp_path/'data',missing_id=True),boundary=BOUND)
    assert r['observations']['linkage_counts']['GAMMA_ID_COLUMN_UNAVAILABLE']==7
    assert r['observations']['linkage_counts']['PRE_REFERENCE_NO_RETROACTIVE_POLICY']==1


def test_output_restriction_and_modes(tmp_path):
    root=fixture(tmp_path/'data')
    r=m.audit(root,boundary=BOUND,max_rows=8)
    with pytest.raises(ValueError):m.write_report(root/'new-report.json',r,root)
    out=tmp_path/'report.json'
    m.write_report(out,r,root)
    assert out.stat().st_mode & 0o777==0o600
    text=out.read_text()
    assert '"decision_id": "a"' not in text
    assert 'gdup' not in text


def test_invalid_budgets(tmp_path):
    for kwargs in ({'max_rows':0},{'max_rows':200001},{'batch_size':0},{'query_ms':1},{'total_ms':5}):
        with pytest.raises(ValueError):m.audit(tmp_path,boundary=BOUND,**kwargs)


def test_empty_tables_reconciles(tmp_path):
    root=fixture(tmp_path/'data')
    with sqlite3.connect(root/'apex_evidence_pipeline.db') as db:db.execute('DELETE FROM decisions')
    r=m.audit(root,boundary=BOUND)
    assert r['coverage']['decision_total']==0
    assert r['coverage']['population_coverage_verified']


def test_run_main_without_deployment_evidence(tmp_path):
    import subprocess
    root=fixture(tmp_path/'data')
    out=tmp_path/'report.json'
    a=subprocess.run([sys.executable,str(SCRIPTS/'apex_stage3b310_origin_population_audit.py'), '--root',str(root),
        '--max-rows','8','--output',str(out)],text=True,capture_output=True)
    assert a.returncode==0,a.stderr
    r=json.loads(out.read_text())
    assert r['deployment_provenance']['deployment_completion_correlated'] is False
    assert r['status'].startswith('DEPLOYMENT_REFERENCE_UNVERIFIED_')
    assert r['migration_authority']=='BLOCKED_RESEARCH_ONLY'
