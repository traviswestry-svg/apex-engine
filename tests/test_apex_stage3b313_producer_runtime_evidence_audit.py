"""Offline synthetic-only regression tests. No production data, network or database."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

S = Path(__file__).resolve().parents[1] / 'scripts' / 'apex_stage3b313_producer_runtime_evidence_audit.py'
spec = importlib.util.spec_from_file_location('apex313', S)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
SHA = 'a' * 40
D = {'schema': m.EVENT_SCHEMA, 'kind': 'decision', 'decision_id': 'd-1', 'snapshot_id': 'g-1', 'boot_id': 'b-1', 'producer_commit': SHA, 'decision_at': '2026-09-20T13:35:00Z'}
B = {'schema': m.EVENT_SCHEMA, 'kind': 'boot', 'boot_id': 'b-1', 'commit_sha': SHA, 'boot_at': '2026-09-20T13:25:00Z'}
G = {'schema': m.EVENT_SCHEMA, 'kind': 'gamma_execution', 'decision_id': 'd-1', 'snapshot_id': 'g-1', 'boot_id': 'b-1', 'executed_at': '2026-09-20T13:34:00Z', 'feature_enabled': True}
P = {'schema': m.EVENT_SCHEMA, 'kind': 'provider_capture', 'snapshot_id': 'g-1', 'received_at': '2026-09-20T13:32:00Z', 'persisted_at': '2026-09-20T13:33:00Z'}
PREV = {'schema':m.PREVIOUS_SCHEMA, 'status':'LINKAGE_POPULATION_RECONCILED_RUNTIME_NOT_ATTESTED', 'migration_authority':'BLOCKED_RESEARCH_ONLY', 'semantic_gate': {'passed':True}, 'population_gate': {'reconciled':True, 'scanned':5767, 'total':5767, 'decision_time_gamma_correlated':3569, 'linkage_exceptions':{'GAMMA_ID_MISSING_LEGACY_OR_UNKNOWN':53}}}


def calc(changes=None, previous=PREV):
    e = {'decision':[m.normalize(D,'decision')], 'boot':[m.normalize(B,'boot')], 'gamma_execution':[m.normalize(G,'gamma_execution')], 'provider_capture':[m.normalize(P,'provider_capture')]}
    for k,v in (changes or {}).items(): e[k]=v
    return m.evaluate(previous,e, {'stage3b312':'READ_AND_SCHEMA_CHECKED', **{k:'READ_AND_SCHEMA_CHECKED' for k in m.KINDS}}, {})


class Stage313Tests(unittest.TestCase):
    def test_three_way_claims_not_attestation(self):
        r=calc()
        self.assertEqual(r['trace_correlations']['three_way_claim_matches'],1)
        self.assertEqual(r['status'],'FIRST_PARTY_TRACES_CORRELATED_NOT_INDEPENDENTLY_ATTESTED')
        self.assertTrue(all(x == 'UNVERIFIED' for k,x in r['attestation_gates'].items() if k != 'historical_population_gate'))
        self.assertEqual(r['migration_authority'],'BLOCKED_RESEARCH_ONLY')

    def test_boot_commit_mismatch(self):
        b=dict(B,commit_sha='b'*40)
        r=calc({'boot':[m.normalize(b,'boot')]})
        self.assertEqual(r['trace_correlations']['origin_exact_boot_commit_claim_matches'],0)
        self.assertEqual(r['trace_correlations']['three_way_claim_matches'],0)

    def test_runtime_disabled(self):
        r=calc({'gamma_execution':[m.normalize(dict(G,feature_enabled=False),'gamma_execution')]})
        self.assertEqual(r['trace_correlations']['runtime_execution_exact_identity_time_claim_matches'],0)

    def test_runtime_wrong_snapshot(self):
        r=calc({'gamma_execution':[m.normalize(dict(G,snapshot_id='g-2'),'gamma_execution')]})
        self.assertEqual(r['trace_correlations']['runtime_execution_exact_identity_time_claim_matches'],0)

    def test_provider_claim_after_decision(self):
        r=calc({'provider_capture':[m.normalize(dict(P,persisted_at='2026-09-20T13:40:00Z'),'provider_capture')]})
        self.assertEqual(r['trace_correlations']['provider_capture_predecision_claim_matches'],0)
        self.assertEqual(r['trace_correlations']['predecision_provider_capture_claim_mismatches'],1)

    def test_ambiguous_identifiers_fail_closed(self):
        r=calc({'boot':[m.normalize(B,'boot'),m.normalize(B,'boot')]})
        self.assertEqual(r['status'],'AMBIGUOUS_TRACE_IDENTITIES_FAIL_CLOSED')
        self.assertEqual(r['trace_correlations']['three_way_claim_matches'],0)

    def test_missing_traces(self):
        r=calc({'provider_capture':None})
        self.assertEqual(r['status'],'TRACE_INPUTS_INCOMPLETE_RUNTIME_UNVERIFIED')

    def test_invalid_trace_fails_closed(self):
        r=m.evaluate(PREV,{}, {'stage3b312':'READ_AND_SCHEMA_CHECKED','decision':'INVALID_OR_UNREADABLE'}, {})
        self.assertEqual(r['status'],'INVALID_EVIDENCE_FAIL_CLOSED')

    def test_missing_prior_reconciliation(self):
        r=calc(previous=None)
        self.assertEqual(r['previous_reconciliation'],'UNVERIFIED')
        self.assertEqual(r['status'],'PREVIOUS_RECONCILIATION_UNVERIFIED')
        self.assertEqual(r['attestation_gates']['historical_population_gate'],'UNVERIFIED')

    def test_no_raw_identifiers_times_or_payload(self):
        r=calc()
        wire=json.dumps(r)
        for secret in ['d-1','g-1','b-1','2026-09-20T','aaaaaaaaaaaaaaaa']:
            self.assertNotIn(secret,wire)

    def test_invalid_timestamps_and_timezone(self):
        with self.assertRaisesRegex(ValueError,'INVALID_EVENT_TIME'):
            m.normalize(dict(D,decision_at='2026-09-20T13:35:00'),'decision')

    def test_jsonl_reader_and_digest(self):
        with tempfile.TemporaryDirectory() as temp:
            f=Path(temp)/'input.jsonl'
            f.write_text(json.dumps(D)+'\n')
            rows, state, digest=m.read_events(f,'decision',100)
            self.assertEqual(state,'READ_AND_SCHEMA_CHECKED')
            self.assertEqual(len(rows),1)
            self.assertEqual(len(digest),64)

    def test_overbudget_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            f=Path(temp)/'input.jsonl'
            f.write_text((json.dumps(D)+'\n')*2)
            rows,state,_=m.read_events(f,'decision',1)
            self.assertIsNone(rows)
            self.assertEqual(state,'INVALID_OR_UNREADABLE')

    def test_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)
            (p/'real').write_text(json.dumps(D)+'\n')
            (p/'alias').symlink_to(p/'real')
            rows,state,_=m.read_events(p/'alias','decision',20)
            self.assertIsNone(rows)
            self.assertEqual(state,'INVALID_OR_UNREADABLE')

    def test_protected_output_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError,'OUTPUT_INSIDE_PRODUCTION_DATA_REJECTED'):
                m.save_report(Path(temp)/'output.json',{},protected_root=temp)

    def test_previous_report_migration_authority(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'prev.json'
            p.write_text(json.dumps(dict(PREV,migration_authority='LIVE')))
            report,state,_=m.read_previous(p)
            self.assertIsNone(report)
            self.assertEqual(state,'UNSAFE_AUTHORITY')

    def test_prior_report_counts_not_replayed(self):
        r=calc()
        self.assertEqual(r['population_reference']['historical_population_reconciled'],5767)
        self.assertEqual(r['trace_counts']['decision'],1)
        self.assertEqual(r['trace_correlations']['decision_samples_examined'],1)


if __name__ == '__main__':
    unittest.main()
