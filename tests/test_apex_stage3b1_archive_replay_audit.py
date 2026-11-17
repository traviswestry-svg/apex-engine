import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1]/'scripts'/'apex_stage3b1_archive_replay_audit.py'
spec=importlib.util.spec_from_file_location('stage3b1', SCRIPT)
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
SOURCE_PATH=Path.cwd()/'engine'/'historical_payload_archive.py'
if not SOURCE_PATH.is_file():
    SOURCE_PATH=Path(__file__).resolve().parents[2]/'repo'/'apex-engine-main'/'engine'/'historical_payload_archive.py'

class TestStage3B1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=SOURCE_PATH.read_text()
        cls.reader=m.extract_functions(cls.source)

    def test_reader_extraction(self):
        self.assertTrue(callable(self.reader))

    def test_contract_expected_failure_visible(self):
        with tempfile.TemporaryDirectory() as td:
            db=Path(td)/'fixture.db'
            m.make_fixture_db(db)
            m.write_fixture(db,'DECISION_SNAPSHOT','invalid',b'\xff')
            with self.assertRaises(UnicodeDecodeError):
                type(self).reader('DECISION_SNAPSHOT','invalid',path=db)

    def test_valid_byte_exact(self):
        with tempfile.TemporaryDirectory() as td:
            db=Path(td)/'fixture.db';m.make_fixture_db(db)
            content=b'{"gamma":"g1","seq":[3,1]} '
            m.write_fixture(db,'DECISION_SNAPSHOT','s1',content)
            self.assertEqual(type(self).reader('DECISION_SNAPSHOT','s1',path=db)['payload'].encode(),content)

    def test_missing_database(self):
        with tempfile.TemporaryDirectory() as td:
            r=type(self).reader('DECISION_SNAPSHOT','s1',path=Path(td)/'missing.db')
            self.assertEqual(r['state'],'ARCHIVE_NOT_FOUND')

    def test_missing_row(self):
        with tempfile.TemporaryDirectory() as td:
            db=Path(td)/'fixture.db';m.make_fixture_db(db)
            self.assertEqual(type(self).reader('DECISION_SNAPSHOT','absent',path=db)['state'],'ROW_NOT_ARCHIVED')

    def test_fixture_suite_recognizes_unhandled(self):
        result=m.fixture_checks(type(self).reader)
        self.assertEqual(len(result),9)
        self.assertEqual(sum(x['passed'] for x in result),8)
        self.assertEqual([x['case'] for x in result if not x['passed']],['invalid_utf8'])

    def test_source_inventory(self):
        with tempfile.TemporaryDirectory() as td:
            e=Path(td)/'engine';e.mkdir()
            (e/'reader.py').write_text('snapshot_json = record["snapshot_json"]\n')
            inv=m.source_inventory(Path(td))
            self.assertIn('engine/reader.py',inv['by_type']['DECISION_SNAPSHOT']['candidate_reader_files'])
            self.assertTrue(inv['source_hints_only_not_verified_call_graph'])

    def test_no_data_sqlite_written(self):
        import inspect
        source=inspect.getsource(m.run)
        self.assertNotIn('/data',source)
        self.assertIn('fixture_checks',source)

    def test_failure_path_blocks_migration(self):
        repo=SOURCE_PATH.parents[1]
        r=m.run(repo)
        self.assertEqual(r['migration_authority'],'BLOCKED_RESEARCH_ONLY')
        self.assertEqual(r['status'],'BLOCKED_READER_FAILURE_PATHS')
        self.assertFalse(r['production_replay_performed'])

    def test_missing_source_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            r=m.run(Path(td))
            self.assertEqual(r['status'],'BLOCKED_ARCHIVE_SOURCE_MISSING_OR_OVERSIZED')

    def test_invalid_source_contract_blocks(self):
        with self.assertRaises(ValueError):m.extract_functions('def unrelated(): return 1')

    def test_optional_patch_fail_closed_behavior(self):
        import subprocess
        with tempfile.TemporaryDirectory() as td:
            repo=Path(td); p=repo/'engine'/'historical_payload_archive.py';p.parent.mkdir()
            p.write_text(self.source)
            patch=Path(__file__).resolve().parents[1]/'patches'/'OPTIONAL_ARCHIVE_INVALID_UTF8_FAIL_CLOSED.patch'
            applied=subprocess.run(['patch','-p1','-i',str(patch)],cwd=repo,capture_output=True,text=True)
            self.assertEqual(applied.returncode,0,applied.stderr)
            read=m.extract_functions(p.read_text())
            checks=m.fixture_checks(read)
            self.assertTrue(all(c['passed'] for c in checks),checks)

if __name__=='__main__':unittest.main()
