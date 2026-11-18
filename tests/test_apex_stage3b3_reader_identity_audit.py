import hashlib
import importlib.util
import json
import sqlite3
import zlib
from pathlib import Path
import pytest

SCRIPT=Path(__file__).resolve().parents[1]/'scripts'/'apex_stage3b3_reader_identity_audit.py'
spec=importlib.util.spec_from_file_location('stage3b3', SCRIPT)
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)

def fixtures(tmp_path, bad_gamma=False, bad_trigger_decision=False):
    root=tmp_path/'data';root.mkdir()
    def db(name,ddl):
        c=sqlite3.connect(root/name);c.executescript(ddl);return c
    gamma=db('apex_tracking.db','''CREATE TABLE gamma_observational_snapshots(canonical_gamma_snapshot_id TEXT PRIMARY KEY, ticker TEXT);
        CREATE INDEX idx_gamma_canonical ON gamma_observational_snapshots(canonical_gamma_snapshot_id);''')
    gamma.execute('INSERT INTO gamma_observational_snapshots VALUES (?,?)',('gamma-1','QQQ' if bad_gamma else 'SPX'));gamma.commit();gamma.close()
    dec=db('apex_evidence_pipeline.db','''CREATE TABLE decisions(decision_id TEXT PRIMARY KEY,observed_at TEXT,snapshot_json TEXT,canonical_gamma_snapshot_id TEXT,ticker TEXT);''')
    trg=db('apex_trigger_observatory.db','''CREATE TABLE observed_trade_triggers(trigger_id TEXT PRIMARY KEY,triggered_at TEXT,evidence_json TEXT,canonical_gamma_snapshot_id TEXT,decision_id TEXT,symbol TEXT);''')
    arc=db('apex_historical_payload_archive.db','''CREATE TABLE historical_payload_archive(payload_type TEXT,row_id TEXT,source_table TEXT,source_column TEXT,observed_at TEXT,source_sha256 TEXT,source_bytes INTEGER,archive_codec TEXT,archive_blob BLOB,archive_bytes INTEGER);
        CREATE UNIQUE INDEX ux_arch_identity ON historical_payload_archive(payload_type,row_id);''')
    for kind, rowid, table, col, ts, payload in [
        ('DECISION_SNAPSHOT','decision-1','decisions','snapshot_json','2026-11-01T12:00:00Z','{"x":1}'),
        ('TRIGGER_EVIDENCE','trigger-1','observed_trade_triggers','evidence_json','2026-11-01T12:00:00Z','{"y":2}')]:
        if kind=='DECISION_SNAPSHOT':dec.execute('INSERT INTO decisions VALUES (?,?,?,?,?)',(rowid,ts,payload,'gamma-1','SPX'))
        else:trg.execute('INSERT INTO observed_trade_triggers VALUES (?,?,?,?,?,?)',(rowid,ts,payload,'gamma-1','missing' if bad_trigger_decision else 'decision-1','SPX'))
        raw=payload.encode(); compressed=zlib.compress(raw,9)
        arc.execute('INSERT INTO historical_payload_archive VALUES (?,?,?,?,?,?,?,?,?,?)',
            (kind,rowid,table,col,ts,hashlib.sha256(raw).hexdigest(),len(raw),'ZLIB_9',compressed,len(compressed)))
    dec.commit();trg.commit();arc.commit()
    for c in [dec,trg,arc]:c.close()
    return root

def test_exact_and_cross_database_agreement(tmp_path):
    result=a.run(fixtures(tmp_path),samples=1)
    assert result['migration_authority']=='BLOCKED_RESEARCH_ONLY'
    assert [v['exact_matches'] for v in result['types'].values()]==[1,1]
    c=result['cross_database_identity']['states']
    assert c['GAMMA_ID_FOUND_TICKER_AGREES']==2
    assert c['TRIGGER_DECISION_GAMMA_ID_AGREES']==1

def test_gamma_ticker_mismatch_is_reported(tmp_path):
    r=a.run(fixtures(tmp_path,bad_gamma=True),samples=1)
    assert r['cross_database_identity']['states']['GAMMA_ID_FOUND_TICKER_CONFLICT']==2
    assert r['types']['DECISION_SNAPSHOT']['exact_matches']==1

def test_trigger_missing_decision_separately_reported(tmp_path):
    r=a.run(fixtures(tmp_path,bad_trigger_decision=True),samples=1)
    assert r['cross_database_identity']['states']['TRIGGER_DECISION_NOT_FOUND']==1

def test_byte_mismatch(tmp_path):
    root=fixtures(tmp_path)
    c=sqlite3.connect(root/'apex_evidence_pipeline.db');c.execute("UPDATE decisions SET snapshot_json='{}'");c.commit();c.close()
    r=a.run(root,samples=1)
    assert r['types']['DECISION_SNAPSHOT']['states']['ARCHIVE_SOURCE_DIVERGED']==1

def test_bad_archive_hash(tmp_path):
    root=fixtures(tmp_path)
    c=sqlite3.connect(root/'apex_historical_payload_archive.db');c.execute("UPDATE historical_payload_archive SET source_sha256='bad' WHERE payload_type='DECISION_SNAPSHOT'");c.commit();c.close()
    r=a.run(root,samples=1)
    assert r['types']['DECISION_SNAPSHOT']['states']['ARCHIVE_HASH_MISMATCH']==1

def test_invalid_utf8_fail_closed():
    raw=b'\xff';data=zlib.compress(raw,9)
    meta={'source_bytes':len(raw),'archive_bytes':len(data),'source_sha256':hashlib.sha256(raw).hexdigest()}
    state=a.compare_bytes(meta,{'archive_codec':'ZLIB_9','archive_blob':data},raw,4096)
    assert state=='ARCHIVE_INVALID_UTF8_FAIL_CLOSED_REQUIRED'

def test_truncated_blob_fail_closed():
    raw=b'{"hello":"world"}';data=zlib.compress(raw,9)[:-2]
    meta={'source_bytes':len(raw),'archive_bytes':len(data),'source_sha256':hashlib.sha256(raw).hexdigest()}
    assert a.compare_bytes(meta,{'archive_codec':'ZLIB_9','archive_blob':data},raw,4096)=='ARCHIVE_DECODE_FAILURE'

def test_per_record_cap(tmp_path):
    root=fixtures(tmp_path)
    # Bound clamps minimum cap to 1024; fixture with 1200-byte payload.
    payload=json.dumps({'blob':'a'*1200})
    c=sqlite3.connect(root/'apex_evidence_pipeline.db');c.execute('UPDATE decisions SET snapshot_json=?',(payload,));c.commit();c.close()
    raw=payload.encode();blob=zlib.compress(raw,9)
    c=sqlite3.connect(root/'apex_historical_payload_archive.db');c.execute('UPDATE historical_payload_archive SET archive_blob=?,archive_bytes=?,source_sha256=?,source_bytes=? WHERE payload_type=?',
        (blob,len(blob),hashlib.sha256(raw).hexdigest(),len(raw),'DECISION_SNAPSHOT'));c.commit();c.close()
    r=a.run(root,samples=1,cap=1024)
    assert r['types']['DECISION_SNAPSHOT']['states']['PER_RECORD_CAP_EXCEEDED']==1

def test_archive_absent(tmp_path):
    r=a.run(tmp_path)
    assert r['status']=='ARCHIVE_DATABASE_NOT_FOUND'
    assert r['migration_authority']=='BLOCKED_RESEARCH_ONLY'

def test_output_guardrails_and_no_ids(tmp_path):
    root=fixtures(tmp_path)
    r=a.run(root,samples=1)
    text=json.dumps(r)
    for secret in ['decision-1','trigger-1','gamma-1','{"x":1}']:
        assert secret not in text
    assert r['guardrails']['no_sqlite_writes']

def test_source_absent(tmp_path):
    root=fixtures(tmp_path)
    (root/'apex_evidence_pipeline.db').unlink()
    r=a.run(root,samples=1)
    assert r['types']['DECISION_SNAPSHOT']['status']=='SOURCE_DB_NOT_FOUND'

def test_reference_inventory(tmp_path):
    engine=tmp_path/'engine';engine.mkdir();(engine/'mock.py').write_text('snapshot_json decisions retrieve_archived_payload')
    r=a.reference_inventory(tmp_path)
    assert r['scanned']==1
    assert r['categories']['DECISION_SNAPSHOT']['both_in_same_file']==1
    assert r['scope']=='STATIC_TEXT_HINTS_ONLY_NOT_CALL_GRAPH'

@pytest.mark.parametrize('limit',[-1,0,99999999])
def test_bounds_clamped(tmp_path,limit):
    root=fixtures(tmp_path)
    r=a.run(root,samples=limit,query_ms=limit,total_ms=limit,cap=limit,budget=limit)
    assert 1<=r['limits']['per_edge_per_type']<=4
    assert r['limits']['per_record_bytes']<=a.MAX_PER_RECORD
    assert r['migration_authority']=='BLOCKED_RESEARCH_ONLY'
