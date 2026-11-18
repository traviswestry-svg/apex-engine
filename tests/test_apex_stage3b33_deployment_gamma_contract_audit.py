import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SCRIPT=Path(__file__).resolve().parents[1]/'scripts'/'apex_stage3b33_deployment_gamma_contract_audit.py'
spec=importlib.util.spec_from_file_location('stage3b33',SCRIPT)
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)
SHA='a'*40
SERVICE='srv-d7p3u2navr4c73d2q0jg'
def entry(**kw):
    x={'service_id':SERVICE,'commit_sha':SHA,'status':'live','started_at':'2026-10-01T12:00:00Z','live_at':'2026-10-01T12:01:00Z'}
    x.update(kw)
    return x
class StageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
    def test_no_export_never_establishes_effectivity(self):
        out=a.build_report(self.root)
        self.assertFalse(out['historical_gamma_effective_date_verified'])
        self.assertEqual(out['migration_authority'],'BLOCKED_RESEARCH_ONLY')
        self.assertEqual(out['deployment_reconciliation']['export_status'],'NO_DEPLOYMENT_EXPORT_SUPPLIED')
    def test_export_alone_untrusted(self):
        p=self.root/'deploy.json';p.write_text(json.dumps({'deployments':[entry()]}))
        out=a.build_report(self.root,p)
        self.assertFalse(out['deployment_reconciliation']['export_authenticity_verified'])
        self.assertFalse(out['record_level_eligibility_verified'])
    def test_bad_timestamp(self):
        r=a.reconcile(self.root,[entry(live_at='2026-10-01T11:00:00Z')],SERVICE,128)
        self.assertEqual(r['counts']['INVALID_OR_INCOMPLETE_UTC_DEPLOYMENT_TIMES'],1)
    def test_naive_time_rejected(self):self.assertIsNone(a.timestamp('2026-10-01T12:00:00'))
    def test_bad_sha_rejected(self):
        r=a.reconcile(self.root,[entry(commit_sha='abc')],SERVICE,128)
        self.assertIn('MISSING_SERVICE_OR_FULL_COMMIT',r['counts'])
    def test_foreign_service_ignored(self):
        r=a.reconcile(self.root,[entry(service_id='other')],SERVICE,128)
        self.assertEqual(r['counts']['OTHER_SERVICE'],1)
    def test_no_success_aliases(self):
        r=a.reconcile(self.root,[entry(status='success')],SERVICE,128)
        self.assertEqual(r['counts']['NOT_EXPLICITLY_LIVE'],1)
    def test_git_history_absent(self):
        r=a.reconcile(self.root,[entry()],SERVICE,128)
        self.assertEqual(r['counts']['EXPORTED_LIVE_GIT_HISTORY_UNAVAILABLE'],1)
    def test_malicious_path_safe(self):
        (self.root/'file').write_text('hi')
        self.assertIsNone(a.read_bounded(self.root,'../file'))
    def test_bad_export_schema(self):
        p=self.root/'bad.json';p.write_text('{}')
        self.assertEqual(a.read_export(p,128)[1],'EXPORT_INVALID_SCHEMA')
    def test_export_limit(self):
        p=self.root/'many.json';p.write_text(json.dumps({'deployments':[entry()]*3}))
        self.assertEqual(a.read_export(p,2)[1],'EXPORT_EXCEEDS_MAX_ITEMS')
    def test_source_not_deployment_proof(self):
        r=a.source_contract(self.root)
        self.assertFalse(r['source_is_deployment_attestation'])
        self.assertFalse(r['documentation_complete'])
    def test_conflict(self):
        r=a.reconcile(self.root,[entry(),entry(commit_sha='b'*40)],SERVICE,128)
        self.assertTrue(r['conflicting_live_timestamps'])
        self.assertFalse(r['effective_date_verified'])
    def test_mock_git_verified_still_unattested(self):
        with patch.object(a,'git_validate',return_value={'state':'GIT_POLICY_CONTRACT_MARKERS_PRESENT','code_contract_verified':True}):
            r=a.reconcile(self.root,[entry()],SERVICE,128)
        self.assertEqual(r['counts']['EXPORTED_LIVE_WITH_GIT_POLICY_MARKERS'],1)
        self.assertFalse(r['effective_date_verified'])
    def test_distinct_policy_transition_not_sufficient(self):
        with patch.object(a,'git_validate',side_effect=lambda root,sha:{'code_contract_verified':sha.startswith('b'),'state':'test'}):
            r=a.reconcile(self.root,[entry(),entry(commit_sha='b'*40,started_at='2026-10-02T12:00:00Z',live_at='2026-10-02T12:01:00Z')],SERVICE,128)
        self.assertTrue(r['potential_policy_transition_seen'])
        self.assertFalse(r['effective_date_verified'])
    def test_no_db_access_flag(self):self.assertTrue(a.build_report(self.root)['guardrails']['no_database_reads'])
if __name__=='__main__':unittest.main()
