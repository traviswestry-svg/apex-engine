import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'apex_stage3b314_evidence_source_inventory.py'
spec = importlib.util.spec_from_file_location('stage314', SCRIPT)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'data'; self.root.mkdir()
    def tearDown(self): self.tmp.cleanup()
    def db(self, name='audit.db', ddl='CREATE TABLE historical_decisions(decision_id TEXT, canonical_gamma_snapshot_id TEXT, producer_commit TEXT, decision_at TEXT)'):
        p=self.root/name; con=sqlite3.connect(p); con.execute(ddl); con.commit();con.close();return p
    def run_scan(self, **kwargs):return m.inventory(self.root,**kwargs)
    def test_metadata_classification(self):
        self.db(); r=self.run_scan(); self.assertEqual(r['status'],'BOUNDED_INVENTORY_COMPLETED');self.assertIn('decision_linkage',r['sources'][0]['signals'])
    def test_no_row_values_exported(self):
        p=self.db();c=sqlite3.connect(p);c.execute('INSERT INTO historical_decisions VALUES (?,?,?,?)',('SECRET_ID_123','SECRET_SNAP_456','SECRET_COMMIT','SECRET_TIME'));c.commit();c.close()
        self.assertNotIn('SECRET_',json.dumps(self.run_scan()))
    def test_unreadable_db_works(self):
        (self.root/'bad.db').write_bytes(b'bad');r=self.run_scan();self.assertEqual(r['sources'][0]['status'],'UNREADABLE_OR_INVALID_SQLITE')
    def test_filename_only_log(self):
        (self.root/'gamma_execution.jsonl').write_text('PRIVATE_DATA')
        r=self.run_scan();self.assertNotIn('PRIVATE_DATA',json.dumps(r));self.assertEqual(r['sources'][0]['status'],'FILENAME_ONLY_UNINSPECTED_CONTENT')
    def test_symlinks_ignored(self):
        external=Path(self.tmp.name)/'external.db';external.write_bytes(b'foo'); (self.root/'linked.db').symlink_to(external);self.assertEqual(self.run_scan()['sources'],[])
    def test_nested_subdir(self):
        x=self.root/'archive';x.mkdir();self.db('archive/foo.db');self.assertEqual(len(self.run_scan()['sources']),1)
    def test_depth_cutoff(self):
        x=self.root/'archive';x.mkdir();self.db('archive/foo.db');self.assertEqual(len(self.run_scan(max_depth=0)['sources']),0)
    def test_file_budget(self):
        self.db('one.db');self.db('two.db');r=self.run_scan(max_files=1);self.assertTrue(r['inventory']['truncated'])
    def test_table_budget(self):
        self.db(ddl='CREATE TABLE a(x TEXT);'); c=sqlite3.connect(self.root/'audit.db');c.execute('CREATE TABLE b(y TEXT)');c.commit();c.close()
        self.assertEqual(self.run_scan(max_tables=1)['sources'][0]['status'],'TABLE_LIMIT_EXCEEDED')
    def test_previous_report_acceptance(self):
        p=Path(self.tmp.name)/'prior.json';p.write_text(json.dumps({'schema':'apex.stage3b313_producer_origin_runtime_activation_evidence.v1','migration_authority':'BLOCKED_RESEARCH_ONLY','status':'TRACE_INPUTS_INCOMPLETE_RUNTIME_UNVERIFIED'}));self.assertEqual(self.run_scan(prior=p)['prior_stage3b313']['state'],'READ_AND_SCHEMA_CHECKED')
    def test_previous_report_invalid(self):
        p=Path(self.tmp.name)/'prior.json';p.write_text('{bad');self.assertEqual(self.run_scan(prior=p)['prior_stage3b313']['state'],'INVALID')
    def test_fail_closed_attestation(self):
        self.db();r=self.run_scan();self.assertTrue(all(v=='UNVERIFIED' for v in r['attestation'].values()))
    def test_missing_root_rejected(self):
        with self.assertRaises(ValueError):m.inventory(self.root/'missing')
    def test_invalid_budgets_rejected(self):
        with self.assertRaises(ValueError):m.inventory(self.root,max_files=0)
    def test_no_production_output(self):
        self.db();withheld=self.root/'result.json'
        with self.assertRaises(SystemExit):m.main(['--root',str(self.root),'--output',str(withheld)])
    def test_sqlite_remains_unchanged(self):
        p=self.db(); before=p.read_bytes();self.run_scan();self.assertEqual(before,p.read_bytes())
    def test_no_raw_paths(self):
        self.db('my-private-database.db');self.assertNotIn('my-private-database',json.dumps(self.run_scan()))

if __name__ == '__main__':unittest.main()
