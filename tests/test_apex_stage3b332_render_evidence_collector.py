import importlib.util
from pathlib import Path
import json
import os
import tempfile
import unittest
from unittest.mock import patch

SRC=Path(__file__).resolve().parents[1]/'scripts'/'apex_stage3b332_render_evidence_collector.py'
spec=importlib.util.spec_from_file_location('collector',SRC)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
SERVICE='srv-d7p3u2navr4c73d2q0jg'
SHA='a'*40

def dep(id='dep-abc123',status='deactivated',sha=SHA):
 return {'id':id,'status':status,'commit':{'id':sha},'startedAt':'2026-10-01T12:00:00Z','finishedAt':'2026-10-01T12:02:00Z'}

def ev(status='succeeded',id='evt-abc123',did='dep-abc123',kind='deploy_ended',timestamp='2026-10-01T12:02:00Z'):
 return {'id':id,'type':kind,'timestamp':timestamp,'serviceId':SERVICE,'details':{'deployId':did,'deployStatus':status}}

class CollectorTests(unittest.TestCase):
 def compile(self,ds=None,es=None,acq='OPERATOR_SUPPLIED_PROVIDER_JSON_UNAUTHENTICATED'):
  return m.compile_evidence(ds if ds is not None else [dep()],es if es is not None else [ev()],SERVICE,acq,False,{})
 def test_deployment_native_fields(self):
  d=m.normalize_deploy(dep(),SERVICE)
  self.assertEqual(d['status'],'deactivated');self.assertEqual(d['commit_sha'],SHA)
 def test_deactivated_success_claim(self):
  x,p=self.compile();self.assertEqual(x['events'][0]['event_type'],'deploy_activated');self.assertFalse(p['historical_runtime_gamma_activation_verified'])
 def test_failed_event_is_not_promoted(self):
  x,p=self.compile(es=[ev('failed')]);self.assertEqual(x['events'],[])
 def test_started_event_not_promoted(self):
  x,p=self.compile(es=[ev(kind='deploy_started')]);self.assertEqual(x['events'],[])
 def test_wrong_deploy_not_promoted(self):
  x,p=self.compile(es=[ev(did='dep-other')]);self.assertEqual(x['events'],[])
 def test_before_start_not_promoted(self):
  x,p=self.compile(es=[ev(timestamp='2026-09-30T12:02:00Z')]);self.assertEqual(x['events'],[])
 def test_bad_sha_dropped(self):
  x,p=self.compile(ds=[dep(sha='not-a-sha')]);self.assertEqual(x['deployments'],[])
 def test_bad_deployment_time_dropped(self):
  d=dep();d['startedAt']='2026-10-01T12:04:00Z';x,p=self.compile(ds=[d]);self.assertEqual(x['deployments'],[])
 def test_wrong_service_event_dropped(self):
  e=ev();e['serviceId']='srv-other';x,p=self.compile(es=[e]);self.assertEqual(x['events'],[])
 def test_duplicate_events_no_repeat(self):
  x,p=self.compile(es=[ev(),ev()]);self.assertEqual(len(x['events']),1)
 def test_conflicting_deployment_first_kept_counted(self):
  x,p=self.compile(ds=[dep(),dep(status='live')]);self.assertEqual(len(x['deployments']),0);self.assertEqual(p['collector_counts']['deployment_rejections']['CONFLICTING_DUPLICATE_DEPLOYMENT'],1)
 def test_bad_timestamp(self):self.assertIsNone(m.stamp('2026-10-01T12:00:00'))
 def test_api_requires_key(self):
  with tempfile.TemporaryDirectory() as t,patch.dict(os.environ,{},clear=True):
   with self.assertRaises(SystemExit):m.main(['--mode','api','--out-dir',t])
 def test_offline_writes_mode_600(self):
  with tempfile.TemporaryDirectory() as t:
   a=Path(t)/'ds.json';b=Path(t)/'es.json';a.write_text(json.dumps([dep()]));b.write_text(json.dumps([ev()]));out=Path(t)/'out'
   m.main(['--mode','offline','--raw-deployments',str(a),'--raw-events',str(b),'--out-dir',str(out)])
   self.assertEqual(json.loads((out/'deployment-history.json').read_text())['events'][0]['outcome'],'succeeded')
   self.assertEqual((out/'deployment-history.json').stat().st_mode&0o777,0o600)
   self.assertFalse(json.loads((out/'render-native-evidence.json').read_text())['api_transport_authenticated_at_collection'])
 def test_direct_api_flag_not_attestation(self):
  _,p=self.compile(acq='DIRECT_RENDER_API_HTTPS_GET');self.assertTrue(p['api_transport_authenticated_at_collection']);self.assertFalse(p['provider_export_is_cryptographically_signed'])
 def test_invalid_raw_schema(self):
  with self.assertRaises(ValueError):m.unwrap({'abc':[]})
 def test_file_size_cap(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'oversize';p.write_bytes(b'x'*(m.MAX_INPUT+1))
   with self.assertRaises(ValueError):m.load_document(p)
 def test_output_size_cap(self):
  with tempfile.TemporaryDirectory() as t:
   with self.assertRaises(ValueError):m.atomic_json(Path(t)/'out',{'x':'A'*100},limit=20)
 def test_no_payload_in_native_summaries(self):
  e=ev();e['details']['apiToken']='SECRET';_,p=self.compile(es=[e]);self.assertNotIn('SECRET',json.dumps(p))
 def test_no_mutating_http_method(self):
  class Resp:
   status=200
   def __enter__(self):return self
   def __exit__(self,*args):pass
   def read(self,n):return b'[]'
  with patch.object(m.urllib.request,'urlopen',return_value=Resp()) as mock:
   m.render_get('https://api.render.com/v1/services/'+SERVICE+'/deploys','test-key')
   self.assertEqual(mock.call_args.args[0].get_method(),'GET')
 def test_reject_untrusted_hostname(self):
  with self.assertRaises(ValueError):m.render_get('https://evil.example/v1/deploys','secret')

if __name__=='__main__':unittest.main()

class PreviousAuditCompatibility(unittest.TestCase):
 def test_stage3b331_accepts_generated_export(self):
  import importlib.util
  script=Path('/mnt/data/apex_stage3b332_dependency/scripts/apex_stage3b331_render_lifecycle_gamma_audit.py')
  if not script.exists():self.skipTest('prior audit test dependency not available')
  s=importlib.util.spec_from_file_location('prior331',script);prior331=importlib.util.module_from_spec(s);s.loader.exec_module(prior331)
  class LocalPolicy:
   @staticmethod
   def timestamp(s):return m.stamp(s)
   @staticmethod
   def git_validate(repo,sha):return {'code_contract_verified':False}
  raw=[dep()]; events=[ev()]
  out,_=m.compile_evidence(raw,events,SERVICE,'OPERATOR_SUPPLIED_PROVIDER_JSON_UNAUTHENTICATED',False,{})
  r=prior331.reconcile(LocalPolicy(),Path('/tmp'),out['deployments'],out['events'],SERVICE)
  self.assertEqual(r['validated_unique_deployments'],1)
  self.assertEqual(r['event_counts']['DEPLOY_LINKED_SUCCESSFUL_ACTIVATION_CLAIM'],1)
  self.assertFalse(r['runtime_gamma_feature_activation_verified'])
