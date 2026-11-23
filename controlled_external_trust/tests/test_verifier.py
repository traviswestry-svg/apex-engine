import base64
import hashlib
import unittest
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import ec
from verify_provider_attestation import verify,canonical
SERVICE='srv-d7p3u2navr4c73d2q0jg';KEY='arn:aws:kms:us-east-1:123:key/test'
class VerifierTests(unittest.TestCase):
 def setUp(self):
    self.k=ec.generate_private_key(ec.SECP256R1())
    self.pub=self.k.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)
    self.obs={'scope':'RENDER_DEPLOYMENT_ONLY','service_id':SERVICE,'deploy_id':'dep-abc123',
              'commit_sha':'a'*40,'process_pid':None,'process_boot_id':None,'production_activation_authorized':False}
    self.st={'scope':'PROVIDER_DEPLOYMENT_ONLY','service_id':SERVICE,'deploy_id':'dep-abc123',
             'commit_sha':'a'*40,'kms_key_arn':KEY,'process_identity':'NOT_AUTHENTICATED',
             'production_activation_authorized':False,'observation_sha256':hashlib.sha256(canonical(self.obs)).hexdigest()}
    self.env={'statement':self.st,'algorithm':'ECDSA_SHA_256','signature_b64':base64.b64encode(self.k.sign(canonical(self.st),ec.ECDSA(hashes.SHA256()))).decode()}
 def check(self):return verify(self.obs,self.env,self.pub,expected_service_id=SERVICE,expected_kms_key_arn=KEY)
 def test_good_still_no_go(self):
    x=self.check();self.assertTrue(x['ok']);self.assertEqual(x['verdict'],'NO_GO')
 def test_wrong_service(self):
    self.assertFalse(verify(self.obs,self.env,self.pub,expected_service_id='srv-other',expected_kms_key_arn=KEY)['ok'])
 def test_tampered_commit(self):
    self.obs['commit_sha']='b'*40;self.assertFalse(self.check()['ok'])
 def test_bad_signature(self):
    self.env['signature_b64']=base64.b64encode(b'bad').decode();self.assertFalse(self.check()['ok'])
 def test_false_process_claim(self):
    self.obs['process_pid']=123;self.assertFalse(self.check()['ok'])
 def test_wrong_trust_key(self):
    x=ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)
    self.assertFalse(verify(self.obs,self.env,x,expected_service_id=SERVICE,expected_kms_key_arn=KEY)['ok'])
if __name__=='__main__':unittest.main()
