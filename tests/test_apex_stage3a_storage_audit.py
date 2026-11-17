"""Read-only contract tests for Stage 3A operator-side audit."""
import importlib.util
import json
import sqlite3
import hashlib
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'apex_stage3a_storage_audit.py'
spec = importlib.util.spec_from_file_location('stage3a_storage', SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def fixture_db(root):
    path = root / 'apex_evidence_pipeline.db'
    with sqlite3.connect(path) as c:
        c.execute('CREATE TABLE decisions (id INTEGER PRIMARY KEY, snapshot_json TEXT)')
        c.execute('CREATE INDEX decisions_snapshot_idx ON decisions(snapshot_json)')
        c.execute('INSERT INTO decisions(snapshot_json) VALUES (?)', ('protected',))
    return path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_metadata_audit_no_data_writes(tmp_path):
    db=fixture_db(tmp_path); before=digest(db)
    report=mod.audit(tmp_path)
    assert digest(db)==before
    assert report['mode']=='READ_ONLY'
    assert report['databases'][0]['metadata']['table_count']==1
    assert report['databases'][0]['metadata']['index_count']==1
    assert report['databases'][0]['metadata']['object_size_status']=='SKIPPED_OPT_IN_REQUIRED'
    assert report['retention_guardrails']['backup_verified'] is False
    assert report['accounting']['quarantine_bytes_automatically_reclaimable']==0


def test_dbstat_opt_in(tmp_path):
    fixture_db(tmp_path)
    report=mod.audit(tmp_path,dbstat=True,budget_ms=1000)
    meta=report['databases'][0]['metadata']
    assert meta['object_size_status'] in {'OK','UNAVAILABLE_OR_BUDGET_EXCEEDED'}
    if meta['object_size_status']=='OK':
        assert any('decisions' in x['name'] for x in meta['top_objects'])


def test_wal_shm_and_quarantine_protected(tmp_path):
    fixture_db(tmp_path)
    (tmp_path/'apex_evidence_pipeline.db-wal').write_bytes(b'WAL')
    (tmp_path/'apex_tracking.db.corrupt-20260720').write_bytes(b'data')
    r=mod.audit(tmp_path)
    assert r['accounting']['wal_bytes']==3
    assert r['accounting']['quarantined_review_bytes']==4
    assert all(not x.get('cleanup_authorized',True) for x in r['inventory'])


def test_symlinks_not_followed(tmp_path):
    root=tmp_path/'data'; root.mkdir()
    outside=fixture_db(tmp_path)
    (root/'linked.db').symlink_to(outside)
    r=mod.audit(root)
    assert r['inventory'][0]['class']=='NON_REGULAR_OR_SYMLINK_SKIPPED'
    assert not r['databases']
    with pytest.raises(ValueError):mod.audit(root/'linked.db')


def test_compare_snapshot_growth(tmp_path):
    db=fixture_db(tmp_path)
    a=mod.audit(tmp_path)
    time.sleep(.02)
    with sqlite3.connect(db) as c:
        c.execute('INSERT INTO decisions(snapshot_json) VALUES (?)', ('y'*10000,))
    b=mod.audit(tmp_path)
    changes=mod.compare(a,b)
    assert changes['seconds_between_samples']>0
    assert changes['changed_files'][0]['delta_bytes']>=0
    assert changes['growth_rate_projection_not_established']


def test_compare_rejects_mismatched_roots(tmp_path):
    a=mod.audit(tmp_path)
    b=dict(a);b['root']='/other'
    with pytest.raises(ValueError):mod.compare(a,b)


def test_capacity_thresholds_and_warning_headroom():
    p=mod._policy(24.65,25,15,100000,24650)
    assert p['state']=='WARNING'
    assert p['bytes_to_warning_recovery']==350
    assert not p['automatic_cleanup']
    assert mod._policy(15,25,15,100,15)['state']=='CRITICAL'


def test_command_refuses_output_in_data_root(tmp_path):
    fixture_db(tmp_path)
    with pytest.raises(SystemExit):
        mod.main(['--root',str(tmp_path),'--output',str(tmp_path/'snapshot.json')])
    assert not (tmp_path/'snapshot.json').exists()


def test_truncated_inventory(tmp_path,monkeypatch):
    fixture_db(tmp_path)
    for i in range(5):(tmp_path/f'unknown{i}.db.extra').write_bytes(b'')
    monkeypatch.setattr(mod,'MAX_FILES',2)
    r=mod.audit(tmp_path)
    assert r['inventory_limits']['omitted_files']==4
    assert len(r['inventory'])==2
