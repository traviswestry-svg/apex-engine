"""Synthetic-only, no network, production files or external dependencies."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

MODULE=Path(__file__).resolve().parents[1]/'scripts/apex_stage3b315_gamma_receipt_provenance_correlation.py'
spec=importlib.util.spec_from_file_location('apex315',MODULE)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class Tests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory(prefix='apex315-test-',dir='/tmp')
        self.addCleanup(self.t.cleanup)
        self.root=Path(self.t.name)/'data';self.root.mkdir()
        self.out=Path(self.t.name)/'report.json'
        self.db1=self.root/'decision.db'; self.db2=self.root/'gamma.db'
        with sqlite3.connect(self.db1) as d:
            d.execute('CREATE TABLE decisions(decision_id TEXT, canonical_gamma_snapshot_id TEXT, decision_time TEXT, symbol TEXT)')
            d.execute('INSERT INTO decisions VALUES (?,?,?,?)',('decision-unique-secret','gamma-unique-secret','2026-09-21T12:00:00Z','SPX'))
        with sqlite3.connect(self.db2) as d:
            d.execute('CREATE TABLE gamma_observational_snapshots(canonical_gamma_snapshot_id TEXT, received_at TEXT,persisted_at TEXT,symbol TEXT)')
            d.execute('CREATE INDEX idx_gamma_id ON gamma_observational_snapshots(canonical_gamma_snapshot_id)')
            d.execute('INSERT INTO gamma_observational_snapshots VALUES (?,?,?,?)',('gamma-unique-secret','2026-09-21T11:58:00Z','2026-09-21T11:59:00Z','SPX'))

    def run_audit(self,**kw):
        import argparse
        args={'root':str(self.root),'stage3b314_report':None,'require_previous':False,'decision_db':str(self.db1),
              'gamma_db':str(self.db2),'max_files':25,'max_depth':2,'max_rows':100,'budget_seconds':10,
              'reference':m.REFERENCE}
        args.update(kw)
        return m.audit(argparse.Namespace(**args))

    def test_happy_path(self):
        x=self.run_audit()
        self.assertEqual(x['status'],'BOUNDED_RECEIPT_CORRELATION_COMPLETED_NOT_ATTESTED')
        self.assertEqual(x['counts']['receipt_and_persistence_predecision_claim_matches'],1)
        self.assertEqual(x['counts']['exact_id_correlated'],1)
        self.assertEqual(x['gates']['provider_actual_availability'],'UNVERIFIED')
        self.assertEqual(x['gates']['runtime_gamma_activation'],'UNVERIFIED')

    def test_no_raw_data(self):
        x=json.dumps(self.run_audit())
        self.assertNotIn('decision-unique-secret',x)
        self.assertNotIn('gamma-unique-secret',x)
        self.assertNotIn('2026-09-21T',x)
        self.assertNotIn(str(self.root),x)

    def test_receipt_after_decision(self):
        with sqlite3.connect(self.db2) as d:d.execute('UPDATE gamma_observational_snapshots SET received_at=?, persisted_at=?',('2026-09-21T12:01:00Z','2026-09-21T12:02:00Z'))
        self.assertEqual(self.run_audit()['counts']['receipt_after_decision'],1)

    def test_persist_after_decision(self):
        with sqlite3.connect(self.db2) as d:d.execute('UPDATE gamma_observational_snapshots SET persisted_at=?',('2026-09-21T12:01:00Z',))
        self.assertEqual(self.run_audit()['counts']['persistence_after_decision'],1)

    def test_persist_before_receipt(self):
        with sqlite3.connect(self.db2) as d:d.execute('UPDATE gamma_observational_snapshots SET persisted_at=?',('2026-09-21T11:55:00Z',))
        self.assertEqual(self.run_audit()['counts']['persistence_before_receipt_claim_conflict'],1)

    def test_duplicate_id(self):
        with sqlite3.connect(self.db2) as d:
            d.execute('INSERT INTO gamma_observational_snapshots VALUES (?,?,?,?)',('gamma-unique-secret','2026-09-21T11:58:00Z','2026-09-21T11:59:00Z','SPX'))
        self.assertEqual(self.run_audit()['counts']['duplicate_gamma_snapshot_id'],1)

    def test_missing_id(self):
        with sqlite3.connect(self.db1) as d:d.execute('UPDATE decisions SET canonical_gamma_snapshot_id=NULL')
        self.assertEqual(self.run_audit()['counts']['missing_canonical_gamma_id'],1)

    def test_missing_snapshot(self):
        with sqlite3.connect(self.db1) as d:d.execute("UPDATE decisions SET canonical_gamma_snapshot_id='absent'")
        self.assertEqual(self.run_audit()['counts']['gamma_snapshot_not_found'],1)

    def test_symbol_conflict(self):
        with sqlite3.connect(self.db2) as d:d.execute("UPDATE gamma_observational_snapshots SET symbol='QQQ'")
        self.assertEqual(self.run_audit()['counts']['symbol_mismatch'],1)

    def test_naive_timestamp_invalid(self):
        with sqlite3.connect(self.db1) as d:d.execute("UPDATE decisions SET decision_time='2026-09-21 12:00:00'")
        self.assertEqual(self.run_audit()['counts']['decision_time_invalid'],1)

    def test_unindexed_fail_closed(self):
        with sqlite3.connect(self.db2) as d:d.execute('DROP INDEX idx_gamma_id')
        self.assertEqual(self.run_audit()['status'],'GAMMA_EXACT_ID_UNINDEXED_FAIL_CLOSED')

    def test_truncation(self):
        with sqlite3.connect(self.db1) as d:d.execute('INSERT INTO decisions VALUES (?,?,?,?)',('second','gamma-unique-secret','2026-09-21T12:00:00Z','SPX'))
        x=self.run_audit(max_rows=1)
        self.assertEqual(x['status'],'DECISION_SCAN_TRUNCATED')
        self.assertEqual(x['gates']['bounded_coverage'],'PARTIAL')

    def test_previous_report(self):
        p=Path(self.t.name)/'previous.json'
        p.write_text(json.dumps({'schema':m.PREV_SCHEMA,'status':'BOUNDED_INVENTORY_COMPLETED','migration_authority':'BLOCKED_RESEARCH_ONLY'}))
        x=self.run_audit(stage3b314_report=str(p),require_previous=True)
        self.assertEqual(x['sources']['stage3b314'],'READ_AND_SCHEMA_CHECKED')
        self.assertTrue(x['stage3b314_sha256'])

    def test_invalid_previous_fail_closed(self):
        self.assertEqual(self.run_audit(require_previous=True)['status'],'PREREQUISITE_UNVERIFIED')

    def test_root_bounds(self):
        other=Path(self.t.name)/'other.db'
        other.write_bytes(b'')
        with self.assertRaises(m.AuditIssue):self.run_audit(decision_db=str(other))

    def test_symlink_rejected(self):
        link=self.root/'linked.db';link.symlink_to(self.db1)
        with self.assertRaises(m.AuditIssue):self.run_audit(decision_db=str(link))

    def test_saver_protects_original(self):
        with self.assertRaises(m.AuditIssue):m.save(str(self.root/'forbidden.json'),{},str(self.root))

    def test_input_not_modified(self):
        old=(self.db1.read_bytes(),self.db2.read_bytes())
        self.run_audit()
        self.assertEqual(old,(self.db1.read_bytes(),self.db2.read_bytes()))

    def test_autodiscovery(self):
        x=self.run_audit(decision_db=None,gamma_db=None)
        self.assertEqual(x['counts']['exact_id_correlated'],1)

    def test_bad_time(self):
        self.assertIsNone(m.timestamp('2026-09-21 12:00:00'))
        self.assertIsNone(m.timestamp('bad'))
        self.assertIsNotNone(m.timestamp('2026-09-21T12:00:00+00:00'))

if __name__=='__main__':unittest.main()
