"""Isolated forward-only provenance contract tests."""
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from engine import forward_provenance as fp


class ForwardProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / 'receipts.sqlite'
        self.env = patch.dict(os.environ, {'APEX_FORWARD_PROVENANCE_ENABLED': '1'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.dbpatch = patch.object(fp, 'DEFAULT_DB', str(self.db))
        self.dbpatch.start()
        self.addCleanup(self.dbpatch.stop)

    def test_disabled_creates_no_file(self):
        with patch.dict(os.environ, {'APEX_FORWARD_PROVENANCE_ENABLED': '0'}):
            self.assertEqual(fp.append('GAMMA_CALCULATED', 'a')['status'], 'DISABLED')
        self.assertFalse(self.db.exists())

    def test_three_stage_chain_and_claim_not_promotion(self):
        execution = fp.new_execution_id()
        calc = fp.record_calculation(execution, ticker='SPX', path_version='abc')
        self.assertEqual(calc['status'], 'RECORDED')
        g = fp.record_gamma('gamma1', execution, inserted=True, source_timestamp_provenance='APEX_DERIVED_PARSE_TIME')
        self.assertEqual(g['status'], 'RECORDED')
        d = fp.record_decision('decision1', 'gamma1', inserted=True, observed_at='2026-11-22T11:00:00+00:00')
        self.assertEqual(d['status'], 'RECORDED')
        with sqlite3.connect(self.db) as c:
            payload = c.execute("SELECT payload_json FROM forward_provenance_events WHERE kind='DECISION_PERSISTED'").fetchone()[0]
            self.assertIn('SAME_PROCESS_RECEIPT_CLAIM', payload)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM forward_provenance_events').fetchone()[0], 3)
        self.assertTrue(fp.verify_chain(path=self.db)['ok'])
        self.assertEqual(fp.verify_chain(path=self.db)['authentication'], 'RUNTIME_CLAIM_UNVERIFIED')

    def test_missing_gamma_receipt_fails_closed(self):
        result = fp.record_decision('decision2', 'legacy_gamma', inserted=True, observed_at='2026-11-22T11:00:00+00:00')
        self.assertEqual(result['authentication'], 'RUNTIME_CLAIM_UNVERIFIED')
        with sqlite3.connect(self.db) as c:
            self.assertIn('UNVERIFIED', c.execute('SELECT payload_json FROM forward_provenance_events').fetchone()[0])

    def test_immutable_triggers_and_chain(self):
        fp.append('GAMMA_CALCULATED', 'calc1')
        with sqlite3.connect(self.db) as c:
            with self.assertRaises(sqlite3.DatabaseError):
                c.execute("DELETE FROM forward_provenance_events")
            with self.assertRaises(sqlite3.DatabaseError):
                c.execute("UPDATE forward_provenance_events SET kind='DECISION_PERSISTED'")
        self.assertTrue(fp.verify_chain(path=self.db)['ok'])

    def test_duplicate_snapshots_no_new_receipts(self):
        result = fp.record_gamma('gamma1', 'test', inserted=False, source_timestamp_provenance=None)
        self.assertEqual(result['status'], 'NOT_ELIGIBLE')
        self.assertFalse(self.db.exists())


if __name__ == '__main__':
    unittest.main()
