import pathlib, unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
class Guardrails(unittest.TestCase):
 def test_manual_activation_default_off(self):
  t=(ROOT/'terraform/main.tf').read_text()
  self.assertIn('variable "enable_deployment" { type = bool; default = false',t)
 def test_worm_compliance_and_no_force_destroy(self):
  t=(ROOT/'terraform/main.tf').read_text()
  self.assertIn('mode = "COMPLIANCE"',t)
  self.assertIn('object_lock_enabled = true',t)
  self.assertIn('force_destroy = false',t)
 def test_independent_roles_and_key(self):
  t=(ROOT/'terraform/main.tf').read_text()
  for phrase in ['aws_iam_role" "observer"','aws_iam_role" "attestor"','key_usage = "SIGN_VERIFY"','ECC_NIST_P256','kms:Sign']:
   self.assertIn(phrase,t)
 def test_no_apex_activation_mutation(self):
  t=(ROOT/'terraform/main.tf').read_text()
  self.assertNotIn('aws_render',t)
  self.assertNotIn('APEX_FORWARD_PROVENANCE_ENABLED',t)
  self.assertIn('output "production_activation_authorized" { value = false }',t)
if __name__=='__main__':unittest.main()
