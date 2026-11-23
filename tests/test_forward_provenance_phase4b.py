import base64
import copy
import datetime as dt
import hashlib
import unittest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from engine.forward_provenance_render_observer import canonical, collect
from engine.forward_provenance_signer import (
    COLLECTOR_DOMAIN, SignerRefusal, issue_staging_deployment_attestation,
    verify_staging_attestation,
)

AT = '2026-11-23T12:00:00+00:00'

def raw_public(key):
    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)

class Phase4BTests(unittest.TestCase):
    def setUp(self):
        self.collector = Ed25519PrivateKey.generate()
        self.signer = Ed25519PrivateKey.generate()
        self.used = set()
        self.policy = {'environment':'ISOLATED_STAGING','keys':{
            'collector-1': {'role':'collector','public_key_b64':base64.b64encode(raw_public(self.collector)).decode(),
                            'valid_from':'2026-11-01T00:00:00Z','valid_until':'2026-12-01T00:00:00Z'},
            'signer-1': {'role':'signer','public_key_b64':base64.b64encode(raw_public(self.signer)).decode(),
                         'valid_from':'2026-11-01T00:00:00Z','valid_until':'2026-12-01T00:00:00Z'}}}
        service='srv-example123'
        def get(path, params):
            if path.endswith('/deploys'):
                return [{'deploy':{'id':'dep-example123','status':'live',
                    'commit':{'id':'a'*40},'createdAt':'2026-11-23T11:55:00Z',
                    'finishedAt':'2026-11-23T11:56:00Z'}}]
            return {'id':service,'type':'web_service'}
        self.report=collect(service,get,observed_at=AT)
        self.report.update({'capture_mode':'RENDER_API_READ_ONLY_RESPONSE',
                            'independent_collector_identity':'NOT_ATTESTED',
                            'production_activation_authorized':False,
                            'promotion_authority':'NONE'})
        self.envelope=self.wrap(self.report)

    def wrap(self, report):
        body={'domain':COLLECTOR_DOMAIN,'collector_key_id':'collector-1',
              'observation':report,'nonce':hashlib.sha256(b'unique-test-request').hexdigest(),
              'collected_at_utc':AT}
        return {'body':body,'signature':base64.b64encode(self.collector.sign(canonical(body))).decode()}

    def reserve(self, nonce):
        if nonce in self.used: return False
        self.used.add(nonce)
        return True

    def issue(self, **kw):
        args={'envelope':self.envelope,'policy':self.policy,'signer_key_id':'signer-1',
              'signer':self.signer,'as_of':AT,'reserve_nonce':self.reserve}
        args.update(kw)
        return issue_staging_deployment_attestation(**args)

    def test_staging_issue_verify_no_go(self):
        result=self.issue()
        verified=verify_staging_attestation(envelope=self.envelope,attestation=result,policy=self.policy,as_of=AT)
        self.assertTrue(verified['ok']);self.assertEqual(verified['verdict'],'NO_GO')
        self.assertEqual(result['body']['process_identity'],'NOT_OBSERVED')
    def test_replay_rejected(self):
        self.issue()
        with self.assertRaisesRegex(SignerRefusal,'REPLAY'): self.issue()
    def test_unsigned_mutation_refused(self):
        bad=copy.deepcopy(self.envelope);bad['body']['observation']['evidence']['service_id']='srv-evil1'
        with self.assertRaisesRegex(SignerRefusal,'INVALID_SIGNATURE'):self.issue(envelope=bad)
    def test_fixture_refused_even_signed(self):
        report=copy.deepcopy(self.report);report['capture_mode']='OFFLINE_FIXTURE_NOT_OBSERVED'
        with self.assertRaisesRegex(SignerRefusal,'NOT_LIVE_COLLECTOR'):self.issue(envelope=self.wrap(report))
    def test_process_claim_refused(self):
        report=copy.deepcopy(self.report);report['evidence']['process_boot_id']='fake'
        report['sha256_evidence']=hashlib.sha256(canonical(report['evidence'])).hexdigest()
        with self.assertRaisesRegex(SignerRefusal,'FORBIDDEN_PROCESS'):self.issue(envelope=self.wrap(report))
    def test_tampered_observation_hash(self):
        report=copy.deepcopy(self.report);report['sha256_evidence']='f'*64
        with self.assertRaisesRegex(SignerRefusal,'OBSERVATION_HASH'):self.issue(envelope=self.wrap(report))
    def test_revoked_collector(self):
        self.policy['revoked_key_ids']=['collector-1']
        with self.assertRaisesRegex(SignerRefusal,'REVOKED_KEY'):self.issue()
    def test_revoked_signer(self):
        self.policy['revoked_key_ids']=['signer-1']
        with self.assertRaisesRegex(SignerRefusal,'REVOKED_KEY'):self.issue()
    def test_rotated_signer_requires_matching_pin(self):
        with self.assertRaisesRegex(SignerRefusal,'SIGNER_KEY_MISMATCH'):
            self.issue(signer=Ed25519PrivateKey.generate())
    def test_expired_key(self):
        self.policy['keys']['collector-1']['valid_until']='2026-11-23T11:00:00Z'
        with self.assertRaisesRegex(SignerRefusal,'KEY_OUTSIDE_VALIDITY'):self.issue()
    def test_production_policy_refused(self):
        self.policy['environment']='PRODUCTION'
        with self.assertRaisesRegex(SignerRefusal,'PRODUCTION_SIGNING'):self.issue()
    def test_bogus_signer_attestation_rejected(self):
        result=self.issue()
        result['body']['process_identity']='REAL_BOOT'
        self.assertFalse(verify_staging_attestation(envelope=self.envelope,attestation=result,policy=self.policy,as_of=AT)['ok'])
    def test_unknown_key_fails_closed(self):
        with self.assertRaisesRegex(SignerRefusal,'UNPINNED_KEY'):self.issue(signer_key_id='random-key')
    def test_stale_collector_refused(self):
        with self.assertRaisesRegex(SignerRefusal,'STALE_OR_FUTURE'):
            self.issue(as_of='2026-11-23T12:30:00Z')
    def test_missing_replay_callback_refused(self):
        with self.assertRaisesRegex(SignerRefusal,'REPLAY_OR_NO_ATOMIC'):
            self.issue(reserve_nonce=None)
<<<<<<< Updated upstream
    def test_invalid_timestamps_fail_closed(self):
        with self.assertRaisesRegex(SignerRefusal,'INVALID_TIMESTAMP'):
            self.issue(as_of='invalid')
        self.assertEqual(
            verify_staging_attestation(envelope=self.envelope,attestation={},policy=self.policy,as_of='invalid')['reason'],
            'INVALID_TIMESTAMP',
        )
        self.policy['keys']['collector-1']['valid_from']='invalid'
        with self.assertRaisesRegex(SignerRefusal,'INVALID_TIMESTAMP'):
            self.issue()
=======
>>>>>>> Stashed changes

if __name__ == '__main__': unittest.main()
