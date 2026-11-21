import importlib.util
import pathlib
import tempfile
import zipfile
import json
import hashlib
import unittest
import subprocess

SCRIPT=pathlib.Path(__file__).resolve().parents[1]/'scripts'/'apex_stage3b311_semantic_replay.py'
spec=importlib.util.spec_from_file_location('stage311',SCRIPT)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class SemanticReplayTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  root=pathlib.Path(__file__).resolve().parents[1]
  cls.source=(root/'engine/evidence_eligibility.py').read_text()
  cls.hist=(root/'engine/historical_evidence_lifecycle.py').read_text()
 def test_candidate_fixture_behavior(self):
  n=m.eligibility_namespace(self.source)
  f=n['evaluate_evidence_eligibility']
  for name,op,ds,expected,reasons in m.fixtures():
   with self.subTest(name=name):
    res=f('dealer',op,ds)
    self.assertEqual(res['state'],expected)
    self.assertTrue(set(reasons).issubset(set(res['reasons'])))
    self.assertEqual(res,f('dealer',op,ds))
 def test_unknown_missing_integrity_behavior(self):
  n=m.eligibility_namespace(self.source)
  f=n['evaluate_evidence_eligibility']
  o={'direction':'BULLISH','freshness_state':'CURRENT'}
  # Integrity available true but no ID -> unknown freshness fails closed
  d={'gamma_transition':{'evidence_integrity_available':True}}
  self.assertEqual(f('dealer',o,d)['state'],'INELIGIBLE')
 def test_no_arbitrary_package_import(self):
  self.assertNotIn('__import__',m.eligibility_namespace(self.source)['__builtins__'])
 def test_missing_function_fails(self):
  with self.assertRaises(ValueError):m.eligibility_namespace('def foo(): return 1')
 def test_invalid_bundle_hash(self):
  with tempfile.TemporaryDirectory() as t:
   fn=pathlib.Path(t)/'b.zip'
   man={'candidate':m.CANDIDATE,'parent':m.PARENT,'files':{}}
   for ver in ('candidate','parent'):
    for name in m.FILES:
     p=f'{ver}/{name}'; data=(self.source if name.endswith('eligibility.py') else self.hist).encode();man['files'][p]={'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}
   with zipfile.ZipFile(fn,'w') as z:
    z.writestr('manifest.json',json.dumps(man))
    for p in man['files']:z.writestr(p,b'bad')
   with self.assertRaises(ValueError):m.bundle_load(fn)
 def test_complete_offline_run(self):
  with tempfile.TemporaryDirectory() as t:
   fn=pathlib.Path(t)/'b.zip';out=pathlib.Path(t)/'out.json'
   man={'candidate':m.CANDIDATE,'parent':m.PARENT,'files':{}}
   content={}
   for ver in ('candidate','parent'):
    for name in m.FILES:
     p=f'{ver}/{name}'; data=(self.source if name.endswith('eligibility.py') else self.hist).encode();content[p]=data
     man['files'][p]={'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}
   with zipfile.ZipFile(fn,'w') as z:
    z.writestr('manifest.json',json.dumps(man))
    for p,data in content.items():z.writestr(p,data)
   self.assertEqual(m.run_validate(fn,out),0)
   d=json.loads(out.read_text())
   self.assertEqual(d['fixture_count'],15)
   self.assertEqual(d['fixture_failed'],[])
   self.assertFalse(d['coverage']['production_runtime_activation_verified'])
   with self.assertRaises(ValueError):m.run_validate(fn,out)
 def test_tampered_commit_identity(self):
  with tempfile.TemporaryDirectory() as t:
   fn=pathlib.Path(t)/'b.zip'
   with zipfile.ZipFile(fn,'w') as z:z.writestr('manifest.json',json.dumps({'candidate':'wrong','parent':m.PARENT,'files':{}}))
   with self.assertRaises(ValueError):m.bundle_load(fn)
 def test_reject_directory(self):
  with tempfile.TemporaryDirectory() as t:
   with self.assertRaises(ValueError):m.collect(pathlib.Path(t)/'missing',pathlib.Path(t)/'out.zip')

if __name__=='__main__':unittest.main()
