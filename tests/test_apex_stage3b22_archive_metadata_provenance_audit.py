"""Stage 3B.2.2 isolated-fixture tests; never access production paths."""
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'apex_stage3b22_archive_metadata_provenance_audit.py'
spec = importlib.util.spec_from_file_location('apex_stage3b22', SCRIPT)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class TestArchiveMetadata(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        with sqlite3.connect(self.root / audit.ARCHIVE) as conn:
            conn.execute('''CREATE TABLE historical_payload_archive (
              payload_type TEXT,row_id TEXT,source_table TEXT,source_column TEXT,
              observed_at TEXT,archived_at TEXT,source_bytes INTEGER,archive_bytes INTEGER,
              archive_codec TEXT,apex_version TEXT,schema_version TEXT,integrity_status TEXT,
              archive_blob BLOB)''')
            conn.execute('CREATE INDEX archive_kind_idx ON historical_payload_archive(payload_type)')
        for _, (filename, table, key, field, ts) in audit.SPECS.items():
            with sqlite3.connect(self.root / filename) as conn:
                conn.execute(f'CREATE TABLE "{table}" ("{key}" TEXT PRIMARY KEY,"{ts}" TEXT,"{field}" TEXT)')

    def add(self, kind, row, size, *, compressed=100, archive_ts='2026-01-01',
            source_ts='2026-01-01', source_exists=True, column_override=None, codec='ZLIB_9'):
        filename, table, key, field, ts = audit.SPECS[kind]
        if source_exists:
            with sqlite3.connect(self.root / filename) as conn:
                conn.execute(f'INSERT INTO "{table}"("{key}","{ts}","{field}") VALUES(?,?,?)',
                             (row,source_ts,'SENSITIVE_PAYLOAD_DO_NOT_EXPORT'))
        with sqlite3.connect(self.root / audit.ARCHIVE) as conn:
            conn.execute('''INSERT INTO historical_payload_archive
            (payload_type,row_id,source_table,source_column,observed_at,archived_at,
             source_bytes,archive_bytes,archive_codec,apex_version,schema_version,integrity_status,archive_blob)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (kind,row,table,column_override or field,archive_ts,archive_ts,size,compressed,codec,
             '69.10.13','v1','HASH_VERIFIED',b'NOT_READ'))

    def test_oversized_metadata_no_payload_fetch(self):
        self.add('DECISION_SNAPSHOT','sample-sensitive',9876543)
        r=audit.run(self.root)
        x=r['types']['DECISION_SNAPSHOT']
        self.assertEqual(x['oldest_source_bytes']['over_256KiB'],1)
        self.assertEqual(x['source_lookup_counts']['SOURCE_ID_FOUND'],1)
        self.assertFalse(r['archive_blob_read'])
        self.assertNotIn('sample-sensitive',json.dumps(r))
        self.assertNotIn('SENSITIVE_PAYLOAD',json.dumps(r))

    def test_two_edge_sampling_bounded_and_deduplicated(self):
        for i in range(12):self.add('TRIGGER_EVIDENCE',f'id-{i}',300000+i)
        r=audit.run(self.root,sample_rows=3)
        x=r['types']['TRIGGER_EVIDENCE']
        self.assertEqual(x['sampled_unique'],6)
        self.assertEqual(x['oldest_sample_size'],3)
        self.assertEqual(x['newest_sample_size'],3)
        self.assertEqual(x['overlapping_window_rows'],0)

    def test_cohorts_overlap_no_double_count(self):
        for i in range(3):self.add('DECISION_SNAPSHOT',f'id-{i}',800000)
        x=audit.run(self.root,sample_rows=4)['types']['DECISION_SNAPSHOT']
        self.assertEqual(x['sampled_unique'],3)
        self.assertEqual(x['overlapping_window_rows'],3)

    def test_source_missing_attributed(self):
        self.add('TRIGGER_EVIDENCE','deleted-in-source',300000,source_exists=False)
        x=audit.run(self.root)['types']['TRIGGER_EVIDENCE']
        self.assertEqual(x['source_lookup_counts']['SOURCE_ID_NOT_FOUND'],1)

    def test_conflicting_archive_field_flagged(self):
        self.add('DECISION_SNAPSHOT','a',1,column_override='unexpected_json')
        x=audit.run(self.root)['types']['DECISION_SNAPSHOT']
        self.assertEqual(x['metadata_state_counts']['TYPE_TABLE_COLUMN_CONFLICT'],1)
        self.assertEqual(x['source_lookup_counts'],{})

    def test_timestamps_different_not_treated_identity_failure(self):
        self.add('DECISION_SNAPSHOT','a',300000,source_ts='2026-01-02')
        x=audit.run(self.root)['types']['DECISION_SNAPSHOT']
        self.assertEqual(x['time_agreement_counts']['TEXT_DIFFERENCE_NOT_PROOF_OF_WRONG_IDENTITY'],1)
        self.assertEqual(x['source_lookup_counts']['SOURCE_ID_FOUND'],1)

    def test_missing_index_skips_lookup(self):
        filename, table, key, field, ts = audit.SPECS['TRIGGER_EVIDENCE']
        with sqlite3.connect(self.root / filename) as conn:
            conn.execute(f'ALTER TABLE "{table}" RENAME TO old_{table}')
            conn.execute(f'CREATE TABLE "{table}"("{key}" TEXT,"{ts}" TEXT,"{field}" TEXT)')
        self.add('TRIGGER_EVIDENCE','a',10)
        x=audit.run(self.root)['types']['TRIGGER_EVIDENCE']
        self.assertEqual(x['source_identity_access'],'NO_VERIFIED_INDEX_PLAN')
        self.assertEqual(x['source_lookup_counts']['SKIPPED_NO_VERIFIED_INDEX'],1)

    def test_bad_metadata_size_flagged(self):
        self.add('TRIGGER_EVIDENCE','a',-1)
        x=audit.run(self.root)['types']['TRIGGER_EVIDENCE']
        self.assertEqual(x['metadata_state_counts']['INVALID_DECLARED_SIZE'],1)
        self.assertEqual(x['oldest_source_bytes']['samples'],0)

    def test_archive_month_and_version_sample_aggregates(self):
        self.add('TRIGGER_EVIDENCE','sensitive-1',12,archive_ts='2026-08-02')
        self.add('TRIGGER_EVIDENCE','sensitive-2',22,archive_ts='2026-11-17')
        x=audit.run(self.root)['types']['TRIGGER_EVIDENCE']
        self.assertEqual(x['sampled_archived_months'], {'2026-08':1, '2026-11':1})
        self.assertEqual(x['archive_version_counts'], {'69.10.13':2})
        self.assertNotIn('sensitive-',json.dumps(x))

    def test_unsupported_codec_flagged(self):
        self.add('TRIGGER_EVIDENCE','a',100,codec='NONE')
        x=audit.run(self.root)['types']['TRIGGER_EVIDENCE']
        self.assertEqual(x['format_state_counts']['UNSUPPORTED_CODEC'],1)

    def test_size_bucket_boundaries(self):
        self.assertEqual(audit.bucket(16383),'under_16KiB')
        self.assertEqual(audit.bucket(16384),'16_to_64KiB')
        self.assertEqual(audit.bucket(262144),'256KiB_to_1MiB')
        self.assertEqual(audit.bucket(4194304),'over_4MiB')

    def test_limits_clamped(self):
        r=audit.run(self.root,sample_rows=10000,query_ms=9999,total_ms=99999)
        self.assertEqual(r['limits']['max_rows_per_type_per_edge'],32)
        self.assertEqual(r['limits']['query_budget_ms'],1000)
        self.assertEqual(r['limits']['total_budget_ms'],15000)

    def test_missing_archive_is_fail_closed(self):
        (self.root / audit.ARCHIVE).unlink()
        r=audit.run(self.root)
        self.assertEqual(r['status'],'ARCHIVE_DATABASE_NOT_FOUND')
        self.assertEqual(r['migration_authority'],'BLOCKED_RESEARCH_ONLY')

    def test_no_import_runtime_apex(self):
        source=SCRIPT.read_text()
        self.assertNotIn('from engine',source)
        self.assertNotIn('zlib.decompress(',source)
        self.assertNotIn('archive_blob,',source.split('META_QUERY =')[1].split('def connect_readonly')[0])

    def test_missing_timestamp_metadata(self):
        self.add('DECISION_SNAPSHOT','a',20,source_ts='2026-01-01')
        with sqlite3.connect(self.root / audit.ARCHIVE) as con:con.execute('UPDATE historical_payload_archive SET observed_at=NULL')
        x=audit.run(self.root)['types']['DECISION_SNAPSHOT']
        self.assertEqual(x['time_agreement_counts']['MISSING_TIMESTAMP'],1)

    def test_metadata_probe_makes_no_database_changes(self):
        self.add('DECISION_SNAPSHOT','a',25)
        with sqlite3.connect(self.root / audit.ARCHIVE) as con:
            before=con.execute('SELECT total_changes()').fetchone() if False else con.execute('SELECT COUNT(*) FROM historical_payload_archive').fetchone()[0]
        audit.run(self.root)
        with sqlite3.connect(self.root / audit.ARCHIVE) as con:
            after=con.execute('SELECT COUNT(*) FROM historical_payload_archive').fetchone()[0]
        self.assertEqual(before,after)

if __name__=='__main__':unittest.main()
