import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

PATH=Path(__file__).resolve().parents[1]/'scripts'/'apex_stage3b32_historical_gamma_policy_audit.py'
spec=importlib.util.spec_from_file_location('stage3b32',PATH)
audit=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=audit
spec.loader.exec_module(audit)

DOC='''# APEX 69.10.14
canonical_gamma_snapshot_id
LEGACY_OR_UNKNOWN
It does **not** query the latest gamma snapshot
rather than being retroactively reclassified
'''

class TestStage3B32(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        (self.root/'config').mkdir()
        (self.root/audit.REQUIRED_DOC).write_text(DOC)
        (self.root/audit.REQUIRED_MANIFEST).write_text(json.dumps({'apex_version':'69.10.47','released_at':'2026-10-20','database_schema_version':'8'}))
    def test_documented_not_certified(self):
        data=audit.source_evidence(self.root)
        self.assertTrue(data['repository_evidence_complete'])
        self.assertFalse(data['historical_policy_effective_dates_verified'])
        self.assertTrue(all(not r['classification_authority'] for r in data['documented_contracts']))
    def test_manifest_not_deployment_attestation(self):
        d=audit.source_evidence(self.root)
        self.assertFalse(d['manifest']['release_is_verified_deployment_at_historical_time'])
        self.assertEqual(d['manifest']['apex_version'],'69.10.47')
    def test_no_document_no_inferred_rules(self):
        (self.root/audit.REQUIRED_DOC).unlink()
        self.assertFalse(audit.source_evidence(self.root)['repository_evidence_complete'])
        self.assertTrue(all(not r['documented'] for r in audit.source_evidence(self.root)['documented_contracts']))
    def test_invalid_manifest(self):
        (self.root/audit.REQUIRED_MANIFEST).write_text('{')
        self.assertEqual(audit.source_evidence(self.root)['manifest']['status'],'INVALID_JSON')
    def test_missing_manifest(self):
        (self.root/audit.REQUIRED_MANIFEST).unlink()
        self.assertEqual(audit.source_evidence(self.root)['manifest']['status'],'UNAVAILABLE_OR_OVERSIZE')
    def test_never_promotes_historical_eligibility(self):
        d=audit.build_report(self.root)
        self.assertFalse(d['production_rule_eligibility_verified'])
        self.assertEqual(d['migration_authority'],'BLOCKED_RESEARCH_ONLY')
    def test_no_payload_leak_in_report(self):
        d=audit.build_report(self.root)
        self.assertNotIn('It does **not** query',json.dumps(d))
        self.assertFalse(d['guardrails']['no_payload_export'] is False)
    def test_missing_data_root(self):
        d=audit.build_report(self.root,root=self.root/'does-not-exist')
        self.assertEqual(d['production_record_samples']['TRIGGER']['status'],'DATABASE_UNAVAILABLE')
    def _make_db(self,filename,table,key,ticker,date,provenance=False):
        db=self.root/filename
        con=sqlite3.connect(db)
        con.execute(f'CREATE TABLE {table} ({key} TEXT PRIMARY KEY,{ticker} TEXT,{date} TEXT, canonical_gamma_snapshot_id TEXT'+(',gamma_provenance_class TEXT' if provenance else '')+')')
        if provenance:
            con.execute(f'INSERT INTO {table} VALUES (?,?,?,?,?)',('a','SPX','2026-09-01',None,None))
            con.execute(f'INSERT INTO {table} VALUES (?,?,?,?,?)',('b','SPX','2026-11-01','g_abc','SAMPLED'))
        else:
            con.execute(f'INSERT INTO {table} VALUES (?,?,?,?)',('a','SPX','2026-09-01',None))
            con.execute(f'INSERT INTO {table} VALUES (?,?,?,?)',('b','SPX','2026-11-01','g_abc'))
        con.commit();con.close()
    def test_samples_without_claiming_effectivity(self):
        self._make_db('apex_evidence_pipeline.db','decisions','decision_id','ticker','observed_at',True)
        self._make_db('apex_trigger_observatory.db','observed_trade_triggers','trigger_id','symbol','triggered_at')
        d=audit.build_report(self.root,self.root,sample_rows=2)
        self.assertEqual(d['production_record_samples']['DECISION']['sampled'],2)
        self.assertEqual(d['production_record_samples']['TRIGGER']['sampled'],2)
        self.assertEqual(d['production_record_samples']['DECISION']['historical_rule_eligibility'],{'UNVERIFIABLE_HISTORICAL_POLICY':2})
        self.assertEqual(d['production_record_samples']['DECISION']['gamma_linkage_presence']['GAMMA_ID_NULL_OR_UNLINKED'],1)
    def test_query_budget_expiry_is_explicit(self):
        self._make_db('apex_evidence_pipeline.db','decisions','decision_id','ticker','observed_at',True)
        d=audit.sample_db(self.root,2,400,100)
        self.assertIn('DECISION',d)
    def test_sqlite_open_read_only(self):
        self._make_db('apex_evidence_pipeline.db','decisions','decision_id','ticker','observed_at',True)
        c=audit._ro(self.root/'apex_evidence_pipeline.db')
        with self.assertRaises(sqlite3.OperationalError):c.execute('DELETE FROM decisions')
        c.close()
    def test_oversize_source_excluded(self):
        (self.root/audit.REQUIRED_DOC).write_text('a'*100001)
        self.assertFalse(audit.source_evidence(self.root)['repository_evidence_complete'])

if __name__=='__main__':unittest.main()
