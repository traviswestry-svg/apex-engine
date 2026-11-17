import importlib.util
import json
import sqlite3
import subprocess
import sys
from pathlib import Path
import pytest

PATH=Path(__file__).resolve().parents[1]/'scripts'/'apex_stage3a3_json_audit.py'
spec=importlib.util.spec_from_file_location('stage3a3',PATH)
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)

@pytest.fixture
def root(tmp_path):
    d=tmp_path/'data';d.mkdir()
    con=sqlite3.connect(d/'apex_evidence_pipeline.db')
    con.execute('CREATE TABLE decisions (id INTEGER PRIMARY KEY, snapshot_json TEXT)')
    rows=[(json.dumps({'secret':'DO_NOT_SHOW_'+str(i),'values':[1,2,3],'nested':{'v':i}}),) for i in range(22)]
    con.executemany('INSERT INTO decisions(snapshot_json) VALUES (?)',rows)
    con.commit();con.close()
    return d

def call(root,**kw):return a.audit(root,targets={'apex_evidence_pipeline.db':{'decisions':('snapshot_json',)}},**kw)

def col(r):return r['databases'][0]['tables'][0]['columns'][0]

def test_read_only_and_no_sensitive_exports(root):
    p=root/'apex_evidence_pipeline.db';before=p.read_bytes()
    r=call(root)
    c=col(r)
    assert c['status']=='SAMPLED_BOUNDED_NONREPRESENTATIVE'
    assert c['sampled_rows']==16
    assert c['zlib_level6']['valid_samples']==16
    assert c['shape']['valid_traversals']==16
    serialized=json.dumps(r)
    assert 'DO_NOT_SHOW' not in serialized and 'secret' not in serialized
    assert p.read_bytes()==before
    assert not (root/'apex_evidence_pipeline.db-wal').exists()

def test_modes(root):
    a1=col(call(root,mode='structure'))
    assert 'shape' in a1 and 'zlib_level6' not in a1
    a2=col(call(root,mode='compression'))
    assert 'shape' not in a2 and 'zlib_level6' in a2

def test_shape_repetition_not_content_equality(root):
    c=col(call(root))
    assert c['shape']['distinct_shapes_in_sample']==1
    assert c['shape']['largest_repeated_shape_count']==16
    assert c['shape']['shape_equality_is_not_payload_equality']

def test_caps(root):
    r=call(root,rows=500,max_chars=1000000,total_bytes=100000000,
           table_budget_ms=500000,total_budget_ms=500000)
    limits=r['limits']
    assert limits['rows_per_column']==a.MAX_ROWS
    assert limits['max_chars_per_value']==a.MAX_CHARS_PER_VALUE
    assert limits['raw_byte_budget_total']==a.MAX_TOTAL_RAW_BYTES
    assert limits['query_budget_per_table_ms']==a.MAX_TABLE_MS

def test_missing_db_not_created(root):
    r=a.audit(root,targets={'apex_tracking.db':{'flow_features':('features_json',)}})
    assert r['databases'][0]['status']=='DATABASE_UNAVAILABLE'
    assert not (root/'apex_tracking.db').exists()

def test_injection_denied(root):
    with pytest.raises(ValueError):
        a.audit(root,targets={'apex_evidence_pipeline.db':{'decisions;drop':('snapshot_json',)}})

def test_oversize_skipped(root):
    con=sqlite3.connect(root/'apex_evidence_pipeline.db')
    con.execute('INSERT INTO decisions(snapshot_json) VALUES (?)',(json.dumps({'payload':'x'*4000}),))
    con.commit();con.close()
    c=col(call(root,max_chars=1024))
    assert c['oversize_or_truncated_rows']>=1
    assert c['sampled_rows']==16

def test_invalid_json_and_null(root):
    con=sqlite3.connect(root/'apex_evidence_pipeline.db')
    con.execute('INSERT INTO decisions(snapshot_json) VALUES (?)',('not valid JSON',))
    con.execute('INSERT INTO decisions(snapshot_json) VALUES (NULL)')
    con.commit();con.close()
    c=col(call(root))
    assert c['null_rows']==1 and c['invalid_json_rows']==1

def test_without_rowid_skipped(root):
    con=sqlite3.connect(root/'apex_calibration.db')
    con.execute('CREATE TABLE level_transition_observations (id TEXT PRIMARY KEY, target_cluster_json TEXT) WITHOUT ROWID')
    con.commit();con.close()
    r=a.audit(root,targets={'apex_calibration.db':{'level_transition_observations':('target_cluster_json',)}})
    assert r['databases'][0]['tables'][0]['status']=='SKIPPED_WITHOUT_ROWID_UNVERIFIED_ACCESS_PATH'

def test_output_reject_data_volume(root):
    p=subprocess.run([sys.executable,str(PATH),'--root',str(root),'--output',str(root/'bad.json')],capture_output=True,text=True)
    assert p.returncode != 0 and not (root/'bad.json').exists()

def test_symlink_target_denied(root):
    (root/'apex_tracking.db').symlink_to(root/'apex_evidence_pipeline.db')
    r=a.audit(root,targets={'apex_tracking.db':{'decisions':('snapshot_json',)}})
    assert r['databases'][0]['status']=='DATABASE_UNAVAILABLE'

def test_no_column(root):
    c=col(a.audit(root,targets={'apex_evidence_pipeline.db':{'decisions':('no_column',)}}))
    assert c['status']=='COLUMN_NOT_FOUND'

def test_byte_budget_exhaustion(root):
    c=col(call(root,total_bytes=1024))
    assert c['status']=='GLOBAL_RAW_BYTE_BUDGET_EXHAUSTED' or c['sampled_rows'] <=16
    assert c['zlib_level6']['aggregate_original_bytes']<=1024

@pytest.mark.parametrize('bad', ['NO','',None])
def test_invalid_mode(root,bad):
    with pytest.raises(ValueError): call(root,mode=bad)
