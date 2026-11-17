import importlib.util
import hashlib
import json
import sqlite3
import tempfile
import unittest
import zlib
from pathlib import Path

MODULE=Path(__file__).resolve().parents[1]/'scripts/apex_stage3b23_large_payload_provenance_audit.py'
spec=importlib.util.spec_from_file_location('stage3b23',MODULE)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class StageB23(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name)
  a=sqlite3.connect(self.root/'apex_historical_payload_archive.db')
  a.execute('''CREATE TABLE historical_payload_archive(payload_type TEXT,row_id TEXT,source_table TEXT,source_column TEXT,
     observed_at TEXT, source_sha256 TEXT,source_bytes INTEGER,archive_codec TEXT,archive_blob BLOB,
     archive_bytes INTEGER,apex_version TEXT,schema_version TEXT,integrity_status TEXT)''')
  a.execute('CREATE INDEX archive_kind ON historical_payload_archive(payload_type)')
  a.commit();a.close()
  for kind,(file,table,key,col,timestamp) in m.SPECS.items():
   c=sqlite3.connect(self.root/file)
   c.execute(f'CREATE TABLE "{table}" ("{key}" TEXT PRIMARY KEY,"{timestamp}" TEXT,"{col}" TEXT)')
   c.commit();c.close()
 def populate(self,kind,payload,*,tamper=False,source_change=False,archive_codec='ZLIB_9',time_change=False,declared_override=None):
  file,table,key,col,timestamp=m.SPECS[kind]
  source=sqlite3.connect(self.root/file)
  source.execute(f'INSERT INTO "{table}" VALUES (?,?,?)',('internal-id','2026-09-01',('changed' if source_change else payload)))
  source.commit();source.close()
  raw=payload.encode();blob=zlib.compress(raw,9)
  if tamper:blob=blob[:-3]+b'xyz'
  arc=sqlite3.connect(self.root/'apex_historical_payload_archive.db')
  arc.execute('INSERT INTO historical_payload_archive VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(
   kind,'internal-id',table,col,'2026-09-02' if time_change else '2026-09-01',
   hashlib.sha256(raw).hexdigest(),len(raw) if declared_override is None else declared_override,
   archive_codec,blob,len(blob),'69.10.11','1','HASH_VERIFIED'))
  arc.commit();arc.close()
 def result(self,**kw):return m.run(self.root,**kw)
 def test_decision_large_exact(self):
  self.populate('DECISION_SNAPSHOT',json.dumps({'data':'a'*400000}))
  r=self.result()
  t=r['types']['DECISION_SNAPSHOT']
  self.assertEqual(t['byte_exact_matches'],1)
  self.assertEqual(t['payload_projection_matches'],1)
  self.assertEqual(t['states']['ARCHIVE_VERIFIED_SOURCE_EXACT'],1)
 def test_trigger_large_exact(self):
  self.populate('TRIGGER_EVIDENCE',json.dumps({'data':'a'*700000}))
  self.assertEqual(self.result()['types']['TRIGGER_EVIDENCE']['byte_exact_matches'],1)
 def test_metadata_cap_blocks_read(self):
  self.populate('DECISION_SNAPSHOT',json.dumps({'data':'a'*100000}),declared_override=2000000)
  t=self.result()['types']['DECISION_SNAPSHOT']
  self.assertEqual(t['metadata_over_cap'],1);self.assertEqual(t['evaluated'],0)
 def test_global_budget_respected(self):
  self.populate('DECISION_SNAPSHOT',json.dumps({'data':'a'*100000}))
  r=self.result(budget=1024)
  self.assertEqual(r['types']['DECISION_SNAPSHOT']['status'],'GLOBAL_BYTE_BUDGET_EXHAUSTED')
  self.assertEqual(r['budget']['reserved_bytes'],0)
 def test_corrupted_archive(self):
  self.populate('DECISION_SNAPSHOT',json.dumps({'data':'a'*400000}),tamper=True)
  t=self.result()['types']['DECISION_SNAPSHOT']
  self.assertEqual(t['byte_exact_matches'],0)
  self.assertTrue(t['states'].get('ARCHIVE_DECODE_FAILURE',0) or t['states'].get('ARCHIVE_SHA256_MISMATCH',0))
 def test_source_mismatch(self):
  self.populate('DECISION_SNAPSHOT',json.dumps({'data':'a'*100000}),source_change=True)
  t=self.result()['types']['DECISION_SNAPSHOT']
  self.assertEqual(t['states']['SOURCE_BYTES_DIFFER'],1)
 def test_no_payload_or_identity_in_report(self):
  self.populate('TRIGGER_EVIDENCE',json.dumps({'private_identifier':'secret-payload-value'}))
  report=json.dumps(self.result())
  for secret in ['internal-id','private_identifier','secret-payload-value']:
   self.assertNotIn(secret,report)
 def test_source_timestamp_difference(self):
  self.populate('DECISION_SNAPSHOT','{}',time_change=True)
  t=self.result()['types']['DECISION_SNAPSHOT']
  self.assertEqual(t['states']['SOURCE_TIME_DIFFERENCE'],1)
 def test_unsupported_codec(self):
  self.populate('DECISION_SNAPSHOT','{}',archive_codec='OTHER')
  t=self.result()['types']['DECISION_SNAPSHOT']
  self.assertEqual(t['states']['UNSUPPORTED_CODEC'],1)
 def test_declared_length_mismatch(self):
  self.populate('DECISION_SNAPSHOT','{}',declared_override=999)
  t=self.result()['types']['DECISION_SNAPSHOT']
  self.assertEqual(t['states']['ARCHIVE_DECLARED_LENGTH_MISMATCH'],1)
 def test_missing_database(self):
  (self.root/'apex_historical_payload_archive.db').unlink()
  self.assertEqual(self.result()['status'],'ARCHIVE_DATABASE_NOT_FOUND')
 def test_bounded_inflation(self):
  raw=b'A'*2000000
  actual,state=m.inflate(zlib.compress(raw),len(raw),1572864)
  self.assertIsNone(actual);self.assertEqual(state,'ACTUAL_INFLATED_LIMIT_EXCEEDED')
 def test_trailing_bytes_rejected(self):
  blob=zlib.compress(b'{}')+b'EXTRA'
  _,state=m.inflate(blob,2,1024)
  self.assertEqual(state,'ARCHIVE_DECODE_FAILURE')
 def test_invalid_utf8_handled(self):
  raw=b'\xff';blob=zlib.compress(raw)
  meta={'archive_bytes':len(blob),'source_bytes':1,'source_sha256':hashlib.sha256(raw).hexdigest()}
  state,ex,proj,fmt=m.check(meta,{'archive_blob':blob},{'canonical':raw},1024)
  self.assertEqual(state,'ARCHIVE_VERIFIED_SOURCE_EXACT');self.assertTrue(ex);self.assertFalse(proj)
  self.assertEqual(fmt,'INVALID_JSON_OR_UTF8')
 def test_schema_and_cutover_flags(self):
  r=self.result()
  self.assertEqual(r['migration_authority'],'BLOCKED_RESEARCH_ONLY')
  self.assertFalse(r['production_reader_cutover'])
  self.assertFalse(r['production_engine_replay_performed'])
 def test_reader_index_gate(self):
  fn,table,key,col,stamp=m.SPECS['DECISION_SNAPSHOT']
  c=sqlite3.connect(self.root/fn);c.execute(f'DROP TABLE "{table}"');c.execute(f'CREATE TABLE "{table}" ("{key}" TEXT,"{stamp}" TEXT,"{col}" TEXT)');c.commit();c.close()
  t=self.result()['types']['DECISION_SNAPSHOT']
  self.assertEqual(t['status'],'SOURCE_INDEX_NOT_VERIFIED')

if __name__=='__main__':unittest.main()
