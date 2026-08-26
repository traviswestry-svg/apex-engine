import datetime as dt, os, sqlite3
from pathlib import Path
from engine.storage_retention import audit, cleanup_quarantined_backups, prune_mature_price_samples

def _db(p):
 c=sqlite3.connect(p); c.executescript("CREATE TABLE decisions(decision_id TEXT PRIMARY KEY, observed_at TEXT, status TEXT); CREATE TABLE price_samples(id INTEGER PRIMARY KEY,ticker TEXT,observed_at TEXT,price REAL); CREATE TABLE grading_results(id INTEGER PRIMARY KEY,decision_id TEXT,status TEXT);"); c.commit(); c.close()

def test_audit_classifies_quarantine_without_deleting(tmp_path):
 q=tmp_path/'apex_tracking.db.corrupt-20260720.bak'; q.write_bytes(b'x'*10); os.utime(q,(1,1))
 r=audit(tmp_path); x=next(v for v in r['files'] if v['name']==q.name)
 assert x['classification']=='QUARANTINED_CORRUPT_DB' and x['operator_cleanup_eligible']; assert q.exists(); assert r['guardrails']['automatic_delete'] is False

def test_cleanup_requires_apply(tmp_path):
 q=tmp_path/'x.db.corrupt-20260720.bak'; q.write_bytes(b'x'); os.utime(q,(1,1))
 assert cleanup_quarantined_backups(tmp_path,apply=False)['reclaimed_bytes']==0 and q.exists()
 assert cleanup_quarantined_backups(tmp_path,apply=True)['reclaimed_bytes']==1 and not q.exists()

def test_price_prune_preserves_pending_window_and_canonical_records(tmp_path):
 p=tmp_path/'e.db'; _db(p); now=dt.datetime.now(dt.timezone.utc); old=(now-dt.timedelta(days=30)).isoformat(); pending=(now-dt.timedelta(days=2)).isoformat()
 with sqlite3.connect(p) as c:
  c.execute("INSERT INTO decisions VALUES('d1',?,'GRADED')",(old,)); c.execute("INSERT INTO decisions VALUES('d2',?,'PENDING')",(pending,)); c.execute("INSERT INTO grading_results VALUES(1,'d1','GRADED')"); c.execute("INSERT INTO price_samples VALUES(1,'SPX',?,1)",(old,)); c.execute("INSERT INTO price_samples VALUES(2,'SPX',?,2)",(pending,)); c.commit()
 r=prune_mature_price_samples(p,14,apply=True); assert r['deleted_rows']==1 and r['vacuum_performed'] is False
 with sqlite3.connect(p) as c:
  assert c.execute('SELECT COUNT(*) FROM decisions').fetchone()[0]==2; assert c.execute('SELECT COUNT(*) FROM grading_results').fetchone()[0]==1; assert c.execute('SELECT COUNT(*) FROM price_samples').fetchone()[0]==1

def test_release_truth_preserves_storage_guardrails():
 import json
 from pathlib import Path
 d=json.loads(Path('config/apex_release_manifest.json').read_text())['storage_retention_guardrails']
 assert d['automatic_delete'] is False and d['automatic_vacuum'] is False and d['canonical_evidence_delete'] is False
 assert d['decisions_preserved'] and d['grading_results_preserved'] and d['flow_features_preserved'] and d['excursion_evidence_preserved']
 s=Path('config/apex_capability_registry.yaml').read_text()
 assert 'governed_storage_retention:' in s and 'production_effect: OPERATIONS_ONLY' in s and 'decision_authority: none' in s
