import hashlib
import importlib.util
import json
import sqlite3
import tempfile
import unittest
import zlib
from pathlib import Path

script=Path(__file__).resolve().parents[1]/'scripts'/'apex_stage3b2_archive_source_replay_audit.py'
spec=importlib.util.spec_from_file_location('audit3b2',script)
audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)

class AuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.archive=self.root/'apex_historical_payload_archive.db'
        with sqlite3.connect(self.archive) as c:
            c.execute('CREATE TABLE historical_payload_archive (payload_type TEXT,row_id TEXT,source_table TEXT,source_column TEXT,source_sha256 TEXT,source_bytes INTEGER,archive_codec TEXT,archive_blob BLOB,archive_bytes INTEGER)')
        with sqlite3.connect(self.root/'apex_evidence_pipeline.db') as c:
            c.execute('CREATE TABLE decisions(decision_id TEXT PRIMARY KEY,snapshot_json TEXT)')
        with sqlite3.connect(self.root/'apex_trigger_observatory.db') as c:
            c.execute('CREATE TABLE observed_trade_triggers(trigger_id TEXT PRIMARY KEY,evidence_json TEXT)')
    def tearDown(self): self.tmp.cleanup()
    def add(self,kind='DECISION_SNAPSHOT',rid='d1',source_payload='{"x":1}',archive_payload=None,codec='ZLIB_9',hash_override=None,table_override=None):
        sp=audit.SPECS[kind]; raw=(source_payload if archive_payload is None else archive_payload).encode('utf-8') if isinstance((source_payload if archive_payload is None else archive_payload),str) else archive_payload
        b=zlib.compress(raw,9)
        with sqlite3.connect(self.root/sp[0]) as c:
            c.execute(f'INSERT INTO {sp[1]}({sp[2]},{sp[3]}) VALUES(?,?)',(rid,source_payload))
        with sqlite3.connect(self.archive) as c:
            c.execute('INSERT INTO historical_payload_archive VALUES(?,?,?,?,?,?,?,?,?)',(kind,rid,table_override or sp[1],sp[3],hash_override or hashlib.sha256(raw).hexdigest(),len(raw),codec,b,len(b)))
    def check(self,kind='DECISION_SNAPSHOT'):
        return audit.run(self.root,sample_rows=4,per_query_ms=800,total_ms=3000)['types'][kind]
    def test_byte_exact(self):
        self.add(source_payload='{"g":"\u03b2","order":[3,2,1]}')
        r=self.check();self.assertEqual(r['byte_exact_matches'],1);self.assertEqual(r['replay_projection_matches'],1)
    def test_trigger(self):
        self.add(kind='TRIGGER_EVIDENCE',rid='t1');self.assertEqual(self.check('TRIGGER_EVIDENCE')['byte_exact_matches'],1)
    def test_source_mismatch(self):
        self.add(archive_payload='{"x":2}');self.assertEqual(self.check()['state_counts']['SOURCE_BYTES_DIFFER'],1)
    def test_corrupt_hash(self):
        self.add(hash_override='0'*64);self.assertEqual(self.check()['state_counts']['ARCHIVE_INTEGRITY_FAILURE'],1)
    def test_unsupported_codec(self):
        self.add(codec='NO');self.assertEqual(self.check()['state_counts']['ARCHIVE_DECODE_FAILURE'],1)
    def test_source_missing(self):
        self.add();
        with sqlite3.connect(self.root/'apex_evidence_pipeline.db') as c: c.execute('DELETE FROM decisions')
        self.assertEqual(self.check()['state_counts']['SOURCE_MISSING'],1)
    def test_metadata_conflict(self):
        self.add(table_override='other');self.assertEqual(self.check()['state_counts']['ARCHIVE_METADATA_CONFLICT'],1)
    def test_archive_missing(self):
        self.archive.unlink();self.assertEqual(audit.run(self.root)['status'],'BLOCKED_ARCHIVE_NOT_FOUND')
    def test_caps(self):
        self.add(source_payload='{"x":"'+('a'*5000)+'"}')
        r=audit.run(self.root,max_payload_bytes=1024)['types']['DECISION_SNAPSHOT']
        self.assertEqual(r['state_counts']['PAYLOAD_BUDGET_EXCEEDED'],1)
    def test_invalid_utf8_archive_fails_closed(self):
        self.add(archive_payload=b'\xff\xfe')
        self.assertEqual(self.check()['state_counts']['PAYLOAD_INVALID_UTF8'],1)
    def test_non_json_exact_fails_replay_projection(self):
        self.add(source_payload='not json')
        r=self.check()
        self.assertEqual(r['byte_exact_matches'],1)
        self.assertEqual(r['replay_projection_matches'],0)
        self.assertEqual(r['state_counts']['JSON_PARSE_FAILURE'],1)
    def test_truncated_archive(self):
        self.add()
        with sqlite3.connect(self.archive) as c:
            c.execute('UPDATE historical_payload_archive SET archive_blob=?',(zlib.compress(b'{"x":1}')[:4],))
        self.assertEqual(self.check()['state_counts']['ARCHIVE_DECODE_FAILURE'],1)
    def test_global_payload_budget(self):
        self.add(source_payload='{"x":"'+'a'*4000+'"}')
        r=audit.run(self.root,max_total_payload_bytes=1024)
        self.assertEqual(r['types']['DECISION_SNAPSHOT']['sampled'],1)
    def test_no_archive_mutation(self):
        self.add()
        before=self.archive.read_bytes()
        self.check()
        self.assertEqual(self.archive.read_bytes(),before)
    def test_no_ids_exported(self):
        self.add(rid='private-sensitive-id')
        self.assertNotIn('private-sensitive-id',json.dumps(audit.run(self.root)))
    def test_no_production_replay_claim(self):
        self.assertFalse(audit.run(self.root)['production_replay_performed'])
    def test_migration_blocked(self):
        self.assertEqual(audit.run(self.root)['migration_authority'],'BLOCKED_RESEARCH_ONLY')

if __name__=='__main__':unittest.main()
