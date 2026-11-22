"""Phase 3E: readiness must never grant authority from operator assertions."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from engine.forward_provenance_readiness import assess, REQUIRED

class Phase3EReadinessTests(unittest.TestCase):
    def test_absent_evidence_fails_closed(self):
        r=assess()
        self.assertEqual(r['overall_verdict'],'NO_GO')
        self.assertFalse(r['production_activation_authorized'])
        self.assertEqual(r['gates']['code_integrity']['verdict'],'INSUFFICIENT_EVIDENCE')
        self.assertEqual(r['gates']['infrastructure']['verdict'],'NO_GO')
    def test_all_operator_claims_cannot_force_go(self):
        claims={k:{item:{'reference':'operator://claimed-'+item} for item in items} for k,items in REQUIRED.items()}
        r=assess(evidence=claims)
        self.assertFalse(r['production_activation_authorized'])
        self.assertEqual(r['overall_verdict'],'NO_GO')
        self.assertTrue(all(g['verdict']=='NO_GO' for g in r['gates'].values()))
    def test_staging_corroboration_not_production(self):
        r=assess(operational_report={'ok':True,'status':'STAGING_CORROBORATED_OPERATOR_FACTS','authentication':'NOT_REAL_WORLD_AUTHENTICATION','promotion_authority':'NONE'})
        self.assertEqual(r['overall_verdict'],'NO_GO')
    def test_fake_verified_status_rejected(self):
        r=assess(operational_report={'status':'VERIFIED','authentication':'REAL_WORLD_AUTHENTICATED','promotion_authority':'LIVE'})
        self.assertEqual(r['gates']['runtime']['reason'],'UNSUPPORTED_REAL_WORLD_AUTHENTICATION_OR_PROMOTION_CLAIM')
    def test_malformed_claims_are_insufficient(self):
        r=assess(evidence={'code_integrity':{'deployment_sha':{'reference':''}, 'source_sha':'foo'}})
        self.assertIn('deployment_sha',r['gates']['code_integrity']['missing_evidence'])
    def test_unknown_fields_have_no_authority(self):
        r=assess(evidence={'authorization':'GO','production_activation_authorized':True})
        self.assertFalse(r['production_activation_authorized'])
    def test_no_historical_reclassification(self):
        r=assess()
        self.assertEqual(r['historical_3569_population'],'EXCLUDED_FROM_RETROACTIVE_PROMOTION')
    def test_cli_no_input_returns_code_2(self):
        p=subprocess.run([sys.executable,'-m','scripts.apex_forward_phase3e_readiness'],capture_output=True,text=True)
        self.assertEqual(p.returncode,2,p.stderr)
        self.assertEqual(json.loads(p.stdout)['overall_verdict'],'NO_GO')
    def test_cli_self_claiming_input_returns_code_2(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'claim.json';path.write_text(json.dumps({'infrastructure':{'collector':{'reference':'self-attested'}}}))
            p=subprocess.run([sys.executable,'-m','scripts.apex_forward_phase3e_readiness','--evidence',str(path)],capture_output=True,text=True)
            self.assertEqual(p.returncode,2,p.stderr)
    def test_cli_invalid_json_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'invalid.json';path.write_text('{bad')
            p=subprocess.run([sys.executable,'-m','scripts.apex_forward_phase3e_readiness','--evidence',str(path)],capture_output=True,text=True)
            self.assertEqual(p.returncode,2,p.stderr)
            self.assertEqual(json.loads(p.stdout)['overall_verdict'],'NO_GO')

if __name__=='__main__': unittest.main()
