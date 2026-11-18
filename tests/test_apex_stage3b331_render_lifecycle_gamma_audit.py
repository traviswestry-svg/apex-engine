import importlib.util,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/'scripts'/'apex_stage3b331_render_lifecycle_gamma_audit.py'
spec=importlib.util.spec_from_file_location('stage3b331',SCRIPT)
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)
SERVICE='srv-d7p3u2navr4c73d2q0jg'
SHA='a'*40

def dep(**kw):
 d={'deploy_id':'dep-test123','service_id':SERVICE,'commit_sha':SHA,'status':'deactivated','started_at':'2026-10-01T12:00:00Z','live_at':'2026-10-01T12:02:00Z'}
 d.update(kw);return d

def evt(**kw):
 e={'deploy_id':'dep-test123','service_id':SERVICE,'event_type':'deploy_activated','outcome':'succeeded','occurred_at':'2026-10-01T12:02:00Z'}
 e.update(kw);return e

class TestStage(unittest.TestCase):
 def setUp(self):
  tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
  self.repo=Path(tmp.name);(self.repo/'scripts').mkdir()
  self.repo.joinpath('scripts','apex_stage3b33_deployment_gamma_contract_audit.py').write_bytes((ROOT/'tests'/'_stage3b33_test_dependency.py').read_bytes())
  self.prior=a.load_prior(self.repo)
 def rec(self,d,e):return a.reconcile(self.prior,self.repo,d,e,SERVICE)
 def test_no_export_remains_blocked(self):
  r=a.build_report(self.repo);self.assertFalse(r['historical_gamma_effective_date_verified']);self.assertEqual(r['migration_authority'],'BLOCKED_RESEARCH_ONLY')
 def test_replaced_without_event_unverified(self):
  r=self.rec([dep()],[]);self.assertEqual(r['counts']['HISTORICALLY_DEACTIVATED_ACTIVATION_UNVERIFIED'],1);self.assertEqual(r['git_unique_commits_checked'],0)
 def test_replaced_with_linked_event_candidate(self):
  r=self.rec([dep()],[evt()]);self.assertEqual(r['counts']['HISTORICALLY_DEACTIVATED_WITH_LINKED_ACTIVATION_EVENT'],1);self.assertEqual(r['git_unique_commits_checked'],1);self.assertFalse(r['historical_gamma_effective_date_verified'])
 def test_event_wrong_deploy_ignored(self):self.assertEqual(self.rec([dep()],[evt(deploy_id='dep-wrong')])['event_counts']['UNMATCHED_DEPLOY_ID'],1)
 def test_event_wrong_service_ignored(self):self.assertEqual(self.rec([dep()],[evt(service_id='srv-other')])['event_counts']['OTHER_SERVICE'],1)
 def test_failed_event_not_activation(self):self.assertEqual(self.rec([dep()],[evt(outcome='failed')])['event_counts']['ACTIVATION_OUTCOME_NOT_SUCCEEDED'],1)
 def test_deploy_ended_is_not_activation(self):self.assertEqual(self.rec([dep()],[evt(event_type='deploy_ended')])['event_counts']['NON_ACTIVATION_EVENT'],1)
 def test_unqualified_other_status_not_activated(self):self.assertEqual(self.rec([dep(status='failed')],[evt()])['counts']['OTHER_OR_FAILED_DEPLOYMENT_STATE'],1)
 def test_event_before_start_invalid(self):self.assertEqual(self.rec([dep()],[evt(occurred_at='2026-10-01T11:00:00Z')])['event_counts']['EVENT_BEFORE_DEPLOY_START'],1)
 def test_event_after_deactivation_invalid(self):self.assertEqual(self.rec([dep(deactivated_at='2026-10-01T12:03:00Z')],[evt(occurred_at='2026-10-01T12:04:00Z')])['event_counts']['EVENT_AFTER_DEACTIVATION'],1)
 def test_duplicate_deploy_rejected(self):self.assertEqual(self.rec([dep(),dep()],[evt()])['validated_unique_deployments'],0)
 def test_nonexistent_sha_rejected(self):self.assertEqual(self.rec([dep(commit_sha='abc')],[])['counts']['MISSING_OR_INVALID_COMMIT'],1)
 def test_missing_deploy_id_rejected(self):self.assertEqual(self.rec([dep(deploy_id=None)],[])['counts']['MISSING_OR_INVALID_DEPLOY_ID'],1)
 def test_naive_timestamp_rejected(self):self.assertEqual(self.rec([dep()],[evt(occurred_at='2026-10-01T12:02:00')])['event_counts']['INVALID_EVENT_TIMESTAMP'],1)
 def test_export_file_not_authenticated(self):
  path=self.repo/'dep.json';path.write_text(json.dumps({'deployments':[dep()],'events':[evt()]}))
  r=a.build_report(self.repo,path);self.assertFalse(r['deployment_reconciliation']['event_claims_are_authenticated']);self.assertEqual(r['deployment_reconciliation']['export_status'],'EXPORT_PROVIDED_NOT_AUTHENTICATED')
 def test_bad_schema_rejected(self):
  path=self.repo/'dep.json';path.write_text(json.dumps({'events':[]}));self.assertEqual(a.read_export(path,128,256)[2],'EXPORT_INVALID_SCHEMA')
 def test_limits_enforced(self):
  path=self.repo/'dep.json';path.write_text(json.dumps({'deployments':[dep()]*2,'events':[]}));self.assertEqual(a.read_export(path,1,256)[2],'EXPORT_EXCEEDS_CONFIGURED_LIMITS')
 def test_git_markers_not_proof(self):
  with patch.object(self.prior,'git_validate',return_value={'code_contract_verified':True,'state':'GIT_POLICY_CONTRACT_MARKERS_PRESENT'}):
   r=self.rec([dep()],[evt()]);self.assertEqual(r['counts']['CANDIDATE_ACTIVATION_WITH_GIT_POLICY_MARKERS'],1);self.assertFalse(r['runtime_gamma_feature_activation_verified'])
 def test_conflicting_marker_not_transition_proof(self):
  with patch.object(self.prior,'git_validate',return_value={'code_contract_verified':True,'state':'GIT_POLICY_CONTRACT_MARKERS_PRESENT'}):
   r=self.rec([dep(),dep(deploy_id='dep-bbbbb',commit_sha='b'*40)],[evt(),evt(deploy_id='dep-bbbbb')]);self.assertTrue(r['conflicting_candidate_activation_markers']);self.assertFalse(r['candidate_transition_interval_seen'])
 def test_no_db_mutation(self):self.assertTrue(a.build_report(self.repo)['guardrails']['no_sqlite_writes'])

if __name__=='__main__':unittest.main()
