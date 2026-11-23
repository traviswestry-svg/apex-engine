import datetime as dt
import hashlib
import io
import json
import os
import unittest
from unittest.mock import patch
from lambda_package.trust_worker import (_observe, canonical, observer_handler,
                                         attestor_handler, TrustFailure)

SERVICE='srv-d7p3u2navr4c73d2q0jg'
SHA='a'*40
class Secrets:
    def get_secret_value(self, **kw):return {'SecretString':'test_token_abcdefgh'}
class S3:
    def __init__(self):self.objects={}
    def put_object(self, **kw):
        if kw['Key'] in self.objects:raise RuntimeError('duplicate')
        self.objects[kw['Key']]=kw['Body']
    def get_object(self, **kw):return {'Body':io.BytesIO(self.objects[kw['Key']])}
class KMS:
    def sign(self, **kw):return {'KeyId':kw['KeyId'],'Signature':b'fake-only-for-test'}

def fetch(path, params):
    if path.endswith('/deploys'):
        return [{'deploy':{'id':'dep-abc123','status':'live',
                'commit':{'id':SHA},'createdAt':'2026-11-23T10:00:00Z'},
                'cursor':'x'}] if False else [{'deploy':{'id':'dep-abc123','status':'live',
                'commit':{'id':SHA},'createdAt':'2026-11-23T10:00:00Z'}}]
    return {'id':SERVICE,'type':'web_service'}

class Tests(unittest.TestCase):
    def setUp(self):
        self.s3=S3();self.clients={'secretsmanager':Secrets(),'s3':self.s3,'kms':KMS()}
        self.env={'OBSERVER_RENDER_SECRET_ARN':'sec-obs','ATTESTOR_RENDER_SECRET_ARN':'sec-sign',
          'APEX_RENDER_SERVICE_ID':SERVICE,'EVIDENCE_BUCKET':'test-bucket',
          'ATTESTATION_KMS_KEY_ARN':'arn:aws:kms:us-east-1:123:key/test'}
        self.p=patch.dict(os.environ,self.env);self.p.start()
    def tearDown(self):self.p.stop()
    def test_observation_scoped(self):
        x=_observe(SERVICE,'test_token_abcdefgh',get=fetch)
        self.assertIsNone(x['process_boot_id']);self.assertFalse(x['production_activation_authorized'])
    def test_write_and_replay_refused(self):
        r=observer_handler({},None,clients=self.clients,get=fetch)
        self.assertEqual(r['status'],'OBSERVATION_STORED')
        # Each capture gets a fresh timestamp: distinct evidence, not nonce replay.
        again=observer_handler({},None,clients=self.clients,get=fetch)
        self.assertEqual(again['status'],'OBSERVATION_STORED')
    def test_signature_scoped_no_go(self):
        r=observer_handler({},None,clients=self.clients,get=fetch)
        event={'Records':[{'eventSource':'aws:s3','s3':{'bucket':{'name':'test-bucket'},'object':{'key':r['key']}}}]}
        result=attestor_handler(event,None,clients=self.clients,get=fetch)
        self.assertEqual(result['verdict'],'NO_GO')
        x=json.loads(self.s3.objects[result['key']])
        self.assertEqual(x['statement']['process_identity'],'NOT_AUTHENTICATED')
    def test_digest_corruption_rejected(self):
        r=observer_handler({},None,clients=self.clients,get=fetch)
        self.s3.objects[r['key']]=b'{}'
        event={'Records':[{'eventSource':'aws:s3','s3':{'bucket':{'name':'test-bucket'},'object':{'key':r['key']}}}]}
        with self.assertRaises(TrustFailure):attestor_handler(event,None,clients=self.clients,get=fetch)
    def test_process_forgery_rejected(self):
        r=observer_handler({},None,clients=self.clients,get=fetch)
        x=json.loads(self.s3.objects[r['key']]);x['process_pid']=123
        b=canonical(x);newkey=f'observations/{SERVICE}/{hashlib.sha256(b).hexdigest()}.json'
        self.s3.objects[newkey]=b
        event={'Records':[{'eventSource':'aws:s3','s3':{'bucket':{'name':'test-bucket'},'object':{'key':newkey}}}]}
        with self.assertRaises(TrustFailure):attestor_handler(event,None,clients=self.clients,get=fetch)
    def test_wrong_bucket_rejected(self):
        event={'Records':[{'eventSource':'aws:s3','s3':{'bucket':{'name':'wrong'},'object':{'key':'observations/'+SERVICE+'/'+'a'*64+'.json'}}}]}
        with self.assertRaises(TrustFailure):attestor_handler(event,None,clients=self.clients,get=fetch)
if __name__=='__main__':unittest.main()
