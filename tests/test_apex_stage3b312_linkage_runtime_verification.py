import importlib.util
from pathlib import Path
import json
import tempfile
import unittest

P=Path(__file__).resolve().parents[1]/'scripts/apex_stage3b312_linkage_runtime_verification.py'
spec=importlib.util.spec_from_file_location('b312',P)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def population(*, good=3,missing=1, complete=True):
    return {'migration_authority':'BLOCKED_RESEARCH_ONLY',
     'coverage':{'population_coverage_verified':complete,'count_reconciled':complete,
                 'decision_table_exhausted':complete,'scanned_rows':5,'decision_total':5},
     'observations':{'linkage_counts':{'PRE_REFERENCE_NO_RETROACTIVE_POLICY':1,
                       'GAMMA_ID_SYMBOL_TIME_CONSISTENT':good,
                       'GAMMA_ID_MISSING_LEGACY_OR_UNKNOWN':missing},
                  'time_partition_counts':{'PRE_REFERENCE':1,'POST_REFERENCE':4}},
     'deployment_provenance':{'deployment_completion_correlated':True}}

def semantic():return {'migration_authority':'BLOCKED_RESEARCH_ONLY',
    'status':'SELECTED_SEMANTIC_FIXTURES_PASSED_OTHER_GATES_UNVERIFIED',
    'fixture_passed':15,'fixture_failed':[],
    'snapshot_freeze_selected_execution':{'passed':6}}

class Tests(unittest.TestCase):
    def test_happy_path_never_attests_runtime(self):
        r=m.evaluate(population(),semantic())
        self.assertEqual(r['status'],'LINKAGE_POPULATION_RECONCILED_RUNTIME_NOT_ATTESTED')
        self.assertEqual(r['population_gate']['linked_share_of_post_reference'],0.75)
        self.assertFalse(r['runtime_gate']['runtime_activation_attested'])
        self.assertEqual(r['migration_authority'],'BLOCKED_RESEARCH_ONLY')
    def test_no_semantic_proof(self):
        r=m.evaluate(population(),None)
        self.assertFalse(r['semantic_gate']['passed'])
    def test_missing_population(self):
        r=m.evaluate(None,semantic())
        self.assertEqual(r['status'],'SEMANTIC_FIXTURES_PASSED_LINKAGE_NOT_RECONCILED')
    def test_bad_count_invariant_fails_closed(self):
        p=population();p['observations']['linkage_counts']['GAMMA_ID_SYMBOL_TIME_CONSISTENT']=4
        r=m.evaluate(p,semantic());self.assertFalse(r['population_gate']['reconciled'])
    def test_partial_fails_closed(self):
        r=m.evaluate(population(complete=False),semantic());self.assertFalse(r['population_gate']['reconciled'])
    def test_schema_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x.json';p.write_text('{"schema":"wrong"}')
            self.assertEqual(m.load_report(p,'expected')[1],'SCHEMA_MISMATCH')
    def test_protected_output_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):m.save(Path(d)/'report.json',{},protected_root=d)
    def test_no_raw_identifiers_in_report(self):
        raw=json.dumps(m.evaluate(population(),semantic()))
        self.assertNotIn('decision_id',raw)
        self.assertNotIn('snapshot_json',raw)

if __name__=='__main__':unittest.main()
