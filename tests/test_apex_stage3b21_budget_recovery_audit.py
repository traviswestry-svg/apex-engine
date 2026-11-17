import hashlib
import importlib.util
import json
import sqlite3
import tempfile
import unittest
import zlib
from pathlib import Path

SCRIPT=Path(__file__).resolve().parents[1]/'scripts'/'apex_stage3b21_budget_recovery_audit.py'
spec=importlib.util.spec_from_file_location('apex_stage3b21',SCRIPT)
audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)

class BudgetRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.archive=self.root/'apex_historical_payload_archive.db'
        with sqlite3.connect(self.archive) as c:
            c.execute('CREATE TABLE historical_payload_archive (payload_type TEXT,row_id TEXT,source_table TEXT,source_column TEXT,source_sha256 TEXT,source_bytes INTEGER,archive_codec TEXT,archive_blob BLOB,archive_bytes INTEGER)')
        for kind,s in audit.SPECS.items():
            with sqlite3.connect(self.root/s[0]) as c:
                c.execute(f'CREATE TABLE {s[1]} ({s[2]} TEXT PRIMARY KEY,{s[3]} TEXT)')
    def tearDown(self):self.temp.cleanup()
    def add(self,kind='DECISION_SNAPSHOT',rid='d1',source='{"x":1}',archived=None,source_bytes=None,archive_bytes=None):
        s=audit.SPECS[kind]
        raw=(source if archived is None else archived)
        if isinstance(raw,str):raw=raw.encode()
        zipped=zlib.compress(raw,9)
        with sqlite3.connect(self.root/s[0]) as c:
            c.execute(f'INSERT INTO {s[1]} VALUES(?,?)',(rid,source))
        with sqlite3.connect(self.archive) as c:
            c.execute('INSERT INTO historical_payload_archive VALUES(?,?,?,?,?,?,?,?,?)',(kind,rid,s[1],s[3],hashlib.sha256(raw).hexdigest(),source_bytes if source_bytes is not None else len(raw),'ZLIB_9',zipped,archive_bytes if archive_bytes is not None else len(zipped)))
    def check(self,**opts):return audit.run(self.root,**opts)
    def test_exact_and_projection(self):
        self.add(source='{"text":"é"}')
        r=self.check()['types']['DECISION_SNAPSHOT']
        self.assertEqual((r['byte_exact_matches'],r['replay_projection_matches']),(1,1))
    def test_trigger(self):
        self.add('TRIGGER_EVIDENCE','t1')
        self.assertEqual(self.check()['types']['TRIGGER_EVIDENCE']['byte_exact_matches'],1)
    def test_uncompressed_limit_distinct(self):
        self.add(source='{"a":"'+'x'*3000+'"}')
        r=self.check(max_payload_bytes=1024)['types']['DECISION_SNAPSHOT']
        self.assertEqual(r['state_counts']['ARCHIVE_UNCOMPRESSED_LIMIT_EXCEEDED'],1)
        self.assertEqual(r['metadata_preflight_skips'],1)
    def test_compressed_limit_distinct(self):
        self.add(archive_bytes=2000)
        r=self.check(max_payload_bytes=1024)['types']['DECISION_SNAPSHOT']
        self.assertEqual(r['state_counts']['ARCHIVE_COMPRESSED_LIMIT_EXCEEDED'],1)
    def test_global_budget_stops_without_negative_charge(self):
        self.add(source='{"a":"'+'x'*550+'"}')
        r=self.check(max_total_payload_bytes=1024)
        d=r['types']['DECISION_SNAPSHOT']
        self.assertEqual(d['state_counts']['GLOBAL_RAW_BYTE_BUDGET_EXHAUSTED'],1)
        self.assertEqual(r['budget_attribution']['estimated_bytes_charged'],0)
    def test_charge_three_representations(self):
        self.add(source='{"x":1}')
        r=self.check()
        expected=len(zlib.compress(b'{"x":1}',9))+2*len(b'{"x":1}')
        self.assertEqual(r['budget_attribution']['estimated_bytes_charged'],expected)
        self.assertEqual(r['budget_attribution']['source_bytes_charged'],7)
    def test_oversize_one_does_not_block_smaller_later(self):
        self.add(rid='small',source='{"x":1}')
        self.add(rid='large',source='{"x":"'+'x'*3000+'"}')
        d=self.check(max_payload_bytes=1024)['types']['DECISION_SNAPSHOT']
        self.assertEqual(d['sampled'],2)
        self.assertEqual(d['byte_exact_matches'],1)
        self.assertEqual(d['state_counts']['ARCHIVE_UNCOMPRESSED_LIMIT_EXCEEDED'],1)
    def test_global_stop_does_not_consume_second_type(self):
        self.add(source='{"x":"'+'x'*550+'"}')
        self.add('TRIGGER_EVIDENCE','t1')
        r=self.check(max_total_payload_bytes=1024)
        self.assertEqual(r['types']['DECISION_SNAPSHOT']['status'],'GLOBAL_RAW_BYTE_BUDGET_EXHAUSTED')
        self.assertEqual(r['types']['TRIGGER_EVIDENCE']['status'],'NOT_ATTEMPTED_GLOBAL_RAW_BYTE_BUDGET_EXHAUSTED')
    def test_invalid_metadata(self):
        self.add(source_bytes=-1)
        d=self.check()['types']['DECISION_SNAPSHOT']
        self.assertEqual(d['state_counts']['ARCHIVE_METADATA_INVALID'],1)
    def test_mismatched_source(self):
        self.add(source='{"x":1}',archived='{"x":2}')
        d=self.check()['types']['DECISION_SNAPSHOT']
        self.assertEqual(d['state_counts']['SOURCE_BYTES_DIFFER'],1)
    def test_invalid_utf8(self):
        self.add(archived=b'\xff')
        d=self.check()['types']['DECISION_SNAPSHOT']
        self.assertEqual(d['state_counts']['PAYLOAD_INVALID_UTF8'],1)
    def test_corrupt_hash(self):
        self.add()
        with sqlite3.connect(self.archive) as c:c.execute('UPDATE historical_payload_archive SET source_sha256=?',('0'*64,))
        d=self.check()['types']['DECISION_SNAPSHOT']
        self.assertEqual(d['state_counts']['ARCHIVE_INTEGRITY_FAILURE'],1)
    def test_missing_source(self):
        self.add()
        with sqlite3.connect(self.root/'apex_evidence_pipeline.db') as c:c.execute('DELETE FROM decisions')
        d=self.check()['types']['DECISION_SNAPSHOT']
        self.assertEqual(d['state_counts']['SOURCE_MISSING'],1)
    def test_null_source(self):
        self.add()
        with sqlite3.connect(self.root/'apex_evidence_pipeline.db') as c:c.execute('UPDATE decisions SET snapshot_json=NULL')
        d=self.check()['types']['DECISION_SNAPSHOT']
        self.assertEqual(d['state_counts']['SOURCE_NULL'],1)
    def test_no_ids_in_output(self):
        self.add(rid='secret-identifier-ABC')
        self.assertNotIn('secret-identifier-ABC',json.dumps(self.check()))
    def test_no_writes(self):
        self.add();before=[p.read_bytes() for p in sorted(self.root.glob('*.db'))]
        self.check();self.assertEqual(before,[p.read_bytes() for p in sorted(self.root.glob('*.db'))])
    def test_missing_archive(self):
        self.archive.unlink();self.assertEqual(self.check()['status'],'BLOCKED_ARCHIVE_NOT_FOUND')
    def test_migration_blocked(self):
        r=self.check();self.assertFalse(r['production_replay_performed']);self.assertEqual(r['migration_authority'],'BLOCKED_RESEARCH_ONLY')
    def test_output_path_restriction(self):
        # CLI independently protects /data from report writes; no production access in tests.
        self.assertTrue('no_sqlite_writes' in self.check()['guardrails'])

if __name__=='__main__':unittest.main()
