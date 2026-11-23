import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from engine.forward_provenance_phase4e import assess_phase4e, GATES


def manifest(gates=None):
    return {'schema_version':'4E.1','mode':'READ_ONLY','gates':gates or {}}

class Phase4ETests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        (self.root/'deployment.json').write_text('{"provider":"test"}',encoding='utf-8')
        self.record={'path':'deployment.json','sha256':hashlib.sha256((self.root/'deployment.json').read_bytes()).hexdigest()}

    def call(self,**kw):
        return assess_phase4e(evidence_dir=self.root,manifest=manifest(),**kw)

    def test_empty_fails_closed(self):
        r=self.call();self.assertEqual(r['overall_verdict'],'NO_GO');self.assertFalse(r['production_activation_authorized'])
    def test_missing_infrastructure_blockers(self):
        r=self.call();self.assertEqual(len(r['hard_blockers']),5)
    def test_claims_cannot_force_go(self):
        a={g:{field:self.record for field in fields} for g,fields in GATES.items()}
        r=assess_phase4e(evidence_dir=self.root,manifest=manifest(a))
        self.assertEqual(r['overall_verdict'],'NO_GO')
        self.assertEqual(len(r['gates']['code_integrity']['local_hash_matches']),3)
    def test_hash_mismatch_detected(self):
        a={'code_integrity':{'deployment_sha':{'path':'deployment.json','sha256':'a'*64}}}
        r=assess_phase4e(evidence_dir=self.root,manifest=manifest(a))
        self.assertEqual(r['gates']['code_integrity']['verdict'],'NO_GO')
        self.assertEqual(r['gates']['code_integrity']['invalid_evidence'][0]['reason'],'EVIDENCE_HASH_MISMATCH')
    def test_symlink_rejected(self):
        (self.root/'alias').symlink_to(self.root/'deployment.json')
        a={'code_integrity':{'deployment_sha':{'path':'alias','sha256':self.record['sha256']}}}
        r=assess_phase4e(evidence_dir=self.root,manifest=manifest(a))
        self.assertEqual(r['gates']['code_integrity']['invalid_evidence'][0]['reason'],'MISSING_OR_UNSAFE_EVIDENCE_COPY')
    def test_path_traversal_rejected(self):
        a={'code_integrity':{'deployment_sha':{'path':'../deployment.json','sha256':self.record['sha256']}}}
        r=assess_phase4e(evidence_dir=self.root,manifest=manifest(a))
        self.assertEqual(r['gates']['code_integrity']['invalid_evidence'][0]['reason'],'UNSAFE_REFERENCE_PATH')
    def test_not_reclassified_from_staging(self):
        p={'phase':'4D','authentication':'STAGING_SIGNATURE_AND_CHECKPOINT_CONSISTENCY_ONLY','verdict':'NO_GO'}
        r=self.call(phase4d_report=p)
        self.assertEqual(r['authentication'],'NOT_REAL_WORLD_AUTHENTICATION')
    def test_fake_verified_rejected(self):
        p={'phase':'4D','authentication':'REAL_WORLD','status':'VERIFIED','verdict':'GO','production_activation_authorized':True}
        r=self.call(phase4d_report=p)
        self.assertIn('UNSUPPORTED_PHASE4D_AUTHENTICATION_CLAIM',r['validation_errors'])
    def test_untrusted_gate_rejected(self):
        m=manifest({'made_up':{}})
        r=assess_phase4e(evidence_dir=self.root,manifest=m)
        self.assertIn('UNKNOWN_GATE',r['validation_errors'])
    def test_invalid_manifest_rejected(self):
        r=assess_phase4e(evidence_dir=self.root,manifest={'mode':'PRODUCTION'})
        self.assertIn('INVALID_OR_MISSING_MANIFEST',r['validation_errors'])
    def test_no_mutation(self):
        before=(self.root/'deployment.json').read_bytes()
        self.call()
        self.assertEqual(before,(self.root/'deployment.json').read_bytes())
    def test_naive_time_rejected(self):
        r=self.call(as_of_utc='2026-11-23T10:00:00')
        self.assertIn('NAIVE_TIME',r['validation_errors'])
    def test_cli_exit_two(self):
        p=subprocess.run([sys.executable,'-m','scripts.apex_forward_phase4e_readiness'],capture_output=True,text=True)
        self.assertEqual(p.returncode,2,p.stderr)
        self.assertEqual(json.loads(p.stdout)['overall_verdict'],'NO_GO')
    def test_cli_invalid_manifest(self):
        p=subprocess.run([sys.executable,'-m','scripts.apex_forward_phase4e_readiness','--evidence-dir',str(self.root),'--manifest',str(self.root/'missing.json')],capture_output=True,text=True)
        self.assertEqual(p.returncode,2)
        self.assertIn('UNREADABLE_OR_INVALID_MANIFEST',json.loads(p.stdout)['validation_errors'])

if __name__=='__main__': unittest.main()
