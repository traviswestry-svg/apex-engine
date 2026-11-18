import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

P = Path(__file__).resolve().parents[1]/'scripts'/'apex_stage3a2_record_audit.py'
spec = importlib.util.spec_from_file_location('stage3a2', P)
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)

@pytest.fixture
def sqlite_root(tmp_path):
    root = tmp_path/'data'
    root.mkdir()
    c = sqlite3.connect(root/'apex_evidence_pipeline.db')
    c.execute('CREATE TABLE decisions (id INTEGER PRIMARY KEY, decision_time TEXT, payload_json TEXT, score INTEGER)')
    c.execute('CREATE INDEX ix_decision_time ON decisions(decision_time)')
    c.executemany('INSERT INTO decisions(decision_time,payload_json,score) VALUES (?,?,?)', [('2026-11-17',json.dumps({'secret':'SENSITIVE_'+str(i)}),i) for i in range(35)])
    c.execute('CREATE TABLE decision_effectiveness_attribution (id INTEGER PRIMARY KEY, context TEXT)')
    c.execute('INSERT INTO decision_effectiveness_attribution(context) VALUES (?)',('HIDE_ME',))
    c.commit();c.close()
    return root

def test_bounded_lengths_no_payload(sqlite_root):
    before = (sqlite_root/'apex_evidence_pipeline.db').read_bytes()
    r = a.audit(sqlite_root,targets={'apex_evidence_pipeline.db':['decisions']},rows=7)
    tab = r['databases'][0]['tables'][0]
    assert tab['status']=='SAMPLED_BOUNDED_NONREPRESENTATIVE'
    assert tab['sampled_rows']==7
    assert tab['access_path']=='ROWID_DESC'
    assert len(tab['column_lengths'])<=a.MAX_COLUMNS
    assert 'SENSITIVE' not in json.dumps(r)
    assert (sqlite_root/'apex_evidence_pipeline.db').read_bytes()==before
    assert not (sqlite_root/'apex_evidence_pipeline.db-wal').exists()

def test_missing_target_no_create(sqlite_root):
    r=a.audit(sqlite_root,targets={'apex_tracking.db':['flow_features']})
    assert r['databases'][0]['status']=='DATABASE_UNAVAILABLE'
    assert not (sqlite_root/'apex_tracking.db').exists()

def test_unknown_table_safe(sqlite_root):
    r=a.audit(sqlite_root,targets={'apex_evidence_pipeline.db':['not_a_table']})
    assert r['databases'][0]['tables'][0]['status']=='TABLE_NOT_FOUND'

def test_injection_block(sqlite_root):
    with pytest.raises(ValueError):
        a.audit(sqlite_root,targets={'apex_evidence_pipeline.db':['decisions;DROP TABLE decisions']})

def test_without_rowid_skipped_if_no_key(sqlite_root):
    c=sqlite3.connect(sqlite_root/'apex_calibration.db')
    c.execute('CREATE TABLE level_transition_observations (key TEXT PRIMARY KEY, payload TEXT) WITHOUT ROWID')
    c.execute('INSERT INTO level_transition_observations VALUES (?,?)',('a','Hello'))
    c.commit();c.close()
    r=a.audit(sqlite_root,targets={'apex_calibration.db':['level_transition_observations']})
    assert r['databases'][0]['tables'][0]['status'] in {'SAMPLED_BOUNDED_NONREPRESENTATIVE','SKIPPED_UNSAFE_ACCESS_PATH'}

def test_source_hints_not_certification(tmp_path,sqlite_root):
    source=tmp_path/'repo';source.mkdir();(source/'sample.py').write_text('table = "decisions"\n')
    r=a.audit(sqlite_root,repo_root=source,targets={'apex_evidence_pipeline.db':['decisions']})
    hints=r['databases'][0]['tables'][0]['dependency_review']['code_reference_hints']
    assert 'sample.py' in hints['references']
    assert hints['dependency_confirmed'] is False
    assert r['retention_guardrails']['no_delete']

def test_cap_limits(sqlite_root):
    r=a.audit(sqlite_root,rows=999,columns=999,budget_ms=99999,total_budget_ms=99999,
              targets={'apex_evidence_pipeline.db':['decisions']})
    assert r['limits']['rows_per_table']==a.MAX_ROWS
    assert r['limits']['columns_per_table']==a.MAX_COLUMNS
    assert r['limits']['per_table_query_budget_ms']==a.MAX_PER_TABLE_MS

def test_no_report_inside_data(sqlite_root):
    p=subprocess.run([sys.executable,str(P),'--root',str(sqlite_root),'--output',str(sqlite_root/'report.json')],capture_output=True,text=True)
    assert p.returncode != 0
    assert not (sqlite_root/'report.json').exists()

def test_empty_sample(sqlite_root):
    c=sqlite3.connect(sqlite_root/'apex_calibration.db')
    c.execute('CREATE TABLE level_transition_observations (id INTEGER PRIMARY KEY, raw_payload BLOB)')
    c.commit();c.close()
    r=a.audit(sqlite_root,targets={'apex_calibration.db':['level_transition_observations']})
    assert r['databases'][0]['tables'][0]['status']=='EMPTY_SAMPLE'

def test_no_follow_symlink(tmp_path,sqlite_root):
    (sqlite_root/'apex_tracking.db').symlink_to(sqlite_root/'apex_evidence_pipeline.db')
    r=a.audit(sqlite_root,targets={'apex_tracking.db':['decisions']})
    assert r['databases'][0]['status']=='DATABASE_UNAVAILABLE'

def test_local_foreign_key_metadata(sqlite_root):
    c=sqlite3.connect(sqlite_root/'apex_tracking.db')
    c.execute('CREATE TABLE flow_features(id INTEGER PRIMARY KEY, evidence_id INTEGER REFERENCES decisions(id), payload_json TEXT)')
    c.commit();c.close()
    r=a.audit(sqlite_root,targets={'apex_tracking.db':['flow_features']})
    fk=r['databases'][0]['tables'][0]['dependency_review']['declared_local_foreign_keys']
    assert fk[0]['referenced_table']=='decisions'
    assert not r['databases'][0]['tables'][0]['dependency_review']['cross_database_references_verified']


def test_indexed_timestamp_endpoints_are_dates_only(sqlite_root):
    r=a.audit(sqlite_root,targets={'apex_evidence_pipeline.db':['decisions']})
    date=r['databases'][0]['tables'][0]['indexed_time_boundary']
    assert date['status']=='INDEXED_ENDPOINTS_ONLY_NOT_DISTRIBUTION'
    assert date['earliest_date']=='2026-11-17'
    assert date['latest_date']=='2026-11-17'
    assert date['retention_age_eligibility_inferred'] is False
