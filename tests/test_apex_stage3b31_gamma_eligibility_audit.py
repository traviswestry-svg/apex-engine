import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

SRC=Path(__file__).resolve().parents[1]/'scripts'/'apex_stage3b31_gamma_eligibility_audit.py'
spec=importlib.util.spec_from_file_location('audit331', SRC)
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)

class ClassificationTests(unittest.TestCase):
    def test_null_not_automatically_defect(self):
        r=a.classify({'canonical_gamma_snapshot_id':None,'ticker':'SPX'},None)
        self.assertEqual(r['linkage'],'GAMMA_ID_NULL_OR_UNLINKED')
        self.assertEqual(r['historical_eligibility'],'UNVERIFIABLE_HISTORICAL_POLICY')
    def test_present_match_is_not_eligibility(self):
        r=a.classify({'canonical_gamma_snapshot_id':'a','ticker':'SPX'},{'ticker':'SPX'})
        self.assertEqual(r['linkage'],'GAMMA_ID_FOUND_TICKER_AGREES')
        self.assertEqual(r['historical_eligibility'],'UNVERIFIABLE_HISTORICAL_POLICY')
    def test_missing_gamma_identity(self):
        self.assertEqual(a.classify({'canonical_gamma_snapshot_id':'a','ticker':'SPX'},None)['linkage'],'GAMMA_ID_NOT_FOUND')
    def test_wrong_symbol(self):
        self.assertEqual(a.classify({'canonical_gamma_snapshot_id':'a','ticker':'SPX'},{'ticker':'ES'})['linkage'],'GAMMA_SYMBOL_CONFLICT')
    def test_trigger_decision_conflict(self):
        r=a.classify({'canonical_gamma_snapshot_id':'a','ticker':'SPX'},{'ticker':'SPX'},{'canonical_gamma_snapshot_id':'b'})
        self.assertEqual(r['linkage'],'TRIGGER_DECISION_GAMMA_ID_CONFLICT')
    def test_explicit_verified_required_rule(self):
        self.assertEqual(a.classify({'canonical_gamma_snapshot_id':None,'ticker':'SPX'},None,historical_rule='REQUIRED')['historical_eligibility'],'REQUIRED_LINK_MISSING_OR_INVALID')
    def test_explicit_verified_ineligible_rule(self):
        self.assertEqual(a.classify({'canonical_gamma_snapshot_id':None,'ticker':'SPX'},None,historical_rule='NOT_REQUIRED')['historical_eligibility'],'HISTORICALLY_NOT_REQUIRED_BY_VERIFIED_RULE')

class FixtureTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.root=Path(self.t.name)
        dbs={
          'apex_tracking.db':('CREATE TABLE gamma_observational_snapshots (canonical_gamma_snapshot_id TEXT PRIMARY KEY,ticker TEXT)',
            [('INSERT INTO gamma_observational_snapshots VALUES (?,?)',('g1','SPX'))]),
          'apex_evidence_pipeline.db':('CREATE TABLE decisions (decision_id TEXT PRIMARY KEY,observed_at TEXT,ticker TEXT,canonical_gamma_snapshot_id TEXT,gamma_provenance_class TEXT)',
            [('INSERT INTO decisions VALUES (?,?,?,?,?)',('d1','2026-09-01','SPX','g1','VERIFIED')),
             ('INSERT INTO decisions VALUES (?,?,?,?,?)',('d2','2026-09-02','SPX',None,None))]),
          'apex_trigger_observatory.db':('CREATE TABLE observed_trade_triggers (trigger_id TEXT PRIMARY KEY,triggered_at TEXT,symbol TEXT,canonical_gamma_snapshot_id TEXT,decision_id TEXT)',
            [('INSERT INTO observed_trade_triggers VALUES (?,?,?,?,?)',('t1','2026-09-01','SPX','g1','d1')),
             ('INSERT INTO observed_trade_triggers VALUES (?,?,?,?,?)',('t2','2026-09-02','SPX',None,'d2'))])}
        for name,(ddl,entries) in dbs.items():
            c=sqlite3.connect(self.root/name);c.execute(ddl)
            for sql,params in entries:c.execute(sql,params)
            c.commit();c.close()
    def tearDown(self):self.t.cleanup()
    def test_sample(self):
        r=a.sample(self.root,2)
        self.assertEqual(r['migration_authority'],'BLOCKED_RESEARCH_ONLY')
        self.assertTrue(r['gamma_identity_index_verified'])
        self.assertEqual(r['types']['DECISION']['sampled'],2)
        self.assertEqual(r['types']['DECISION']['linkage_counts']['GAMMA_ID_FOUND_TICKER_AGREES'],1)
        self.assertEqual(r['types']['DECISION']['linkage_counts']['GAMMA_ID_NULL_OR_UNLINKED'],1)
        self.assertEqual(r['types']['TRIGGER']['decision_link_counts']['DECISION_FOUND_TICKER_AGREES'],2)
        self.assertEqual(r['types']['TRIGGER']['historical_eligibility_counts']['UNVERIFIABLE_HISTORICAL_POLICY'],2)
        self.assertNotIn('d1',json.dumps(r))
        self.assertNotIn('t1',json.dumps(r))
    def test_sample_missing_gamma_db(self):
        (self.root/'apex_tracking.db').unlink()
        self.assertEqual(a.sample(self.root)['status'],'GAMMA_DB_UNAVAILABLE')
    def test_index_gate(self):
        c=sqlite3.connect(self.root/'apex_tracking.db');c.execute('DROP TABLE gamma_observational_snapshots');c.execute('CREATE TABLE gamma_observational_snapshots (canonical_gamma_snapshot_id TEXT,ticker TEXT)');c.commit();c.close()
        self.assertEqual(a.sample(self.root)['status'],'GAMMA_INDEX_UNVERIFIED')
    def test_budget_limits(self):
        r=a.sample(self.root,10000,10000,100000)
        self.assertEqual(r['limits']['rows_per_edge_per_type'],16)
        self.assertEqual(r['limits']['query_ms'],1000)
        self.assertEqual(r['limits']['total_ms'],20000)
    def test_readonly_preserves(self):
        before=(self.root/'apex_evidence_pipeline.db').read_bytes()
        a.sample(self.root,2)
        self.assertEqual(before,(self.root/'apex_evidence_pipeline.db').read_bytes())

if __name__=='__main__':unittest.main()
