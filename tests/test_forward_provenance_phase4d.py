"""Phase 4D synthetic external-evidence verification, never production authority."""
import base64
import copy
import json
import sqlite3
import unittest
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from tests import test_forward_provenance_phase4c as phase4c
AT = phase4c.AT
from tests.test_forward_provenance_phase4b import raw_public
from engine.forward_provenance_checkpoint_store import sha, canonical
from engine.forward_provenance_realworld_verifier import verify_phase4d, ANCHOR_DOMAIN

class Phase4DTests(unittest.TestCase):
    def setUp(self):
        self.base = phase4c.Phase4CTests(methodName='test_full_signed_checkpoint_and_restart')
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)
        self.att = self.base.issue()
        self.head = self.base.append(self.att)['checkpoint_sha256']
        self.policy = copy.deepcopy(self.base.fixture.policy)
        self.anchor_key = Ed25519PrivateKey.generate()
        self.policy['keys']['anchor-1'] = {
            'role':'anchor', 'public_key_b64':base64.b64encode(raw_public(self.anchor_key)).decode(),
            'valid_from':'2026-11-01T00:00:00Z','valid_until':'2026-12-01T00:00:00Z'}
        self.anchor = self.sign_anchor({
            'domain':ANCHOR_DOMAIN,'environment':'ISOLATED_STAGING','anchor_key_id':'anchor-1',
            'service_id':'srv-example123','checkpoint_count':1,
            'checkpoint_head_sha256':self.head,'attestation_sha256':sha(self.att),
            'anchored_at_utc':AT,'external_store_identity':'SYNTHETIC_OPERATOR_SUPPLIED',
            'retention_mode':'STAGING_SIMULATION_NOT_WORM',
            'runtime_authentication':'NOT_ESTABLISHED'})

    def sign_anchor(self,body):
        return {'body':body,'signature':base64.b64encode(self.anchor_key.sign(canonical(body))).decode()}

    def verify(self,**changes):
        args={'observer_envelope':self.base.fixture.envelope, 'signer_attestation':self.att,
              'trust_policy':self.policy,'signed_anchor':self.anchor,
              'checkpoint_copy':self.base.path,'as_of_utc':AT}
        args.update(changes)
        return verify_phase4d(**args)

    def test_valid_synthetic_chain_no_go(self):
        r=self.verify();self.assertTrue(r['ok']);self.assertEqual(r['verdict'],'NO_GO')
        self.assertEqual(r['status'],'STAGING_CORROBORATED_NO_PROCESS_ATTESTATION')
        self.assertFalse(r['production_activation_authorized'])

    def test_invalid_anchor_signature(self):
        bad=copy.deepcopy(self.anchor);bad['signature']='AA=='
        self.assertEqual(self.verify(signed_anchor=bad)['reason'],'INVALID_ANCHOR_SIGNATURE')

    def test_signed_wrong_anchor_head(self):
        bad=self.sign_anchor({**self.anchor['body'],'checkpoint_head_sha256':'f'*64})
        self.assertEqual(self.verify(signed_anchor=bad)['reason'],'SIGNED_ANCHOR_CHECKPOINT_MISMATCH')

    def test_revoked_anchor_key(self):
        self.policy['revoked_key_ids']=['anchor-1']
        self.assertEqual(self.verify()['reason'],'REVOKED_ANCHOR_KEY')

    def test_unknown_anchor_key(self):
        self.policy['keys'].pop('anchor-1')
        self.assertEqual(self.verify()['reason'],'UNPINNED_ANCHOR_KEY')

    def test_anchor_cannot_claim_worm(self):
        bad=self.sign_anchor({**self.anchor['body'],'retention_mode':'REAL_WORM'})
        self.assertEqual(self.verify(signed_anchor=bad)['reason'],'UNSUPPORTED_REAL_WORLD_ANCHOR_CLAIM')

    def test_process_claim_cannot_upgrade(self):
        self.assertEqual(self.verify(process_evidence={'pid':123,'boot_id':'fake'})['reason'],
                         'INDEPENDENT_PROCESS_ATTESTATION_PROTOCOL_NOT_IMPLEMENTED')

    def test_observer_signature_mutation(self):
        bad=copy.deepcopy(self.base.fixture.envelope);bad['body']['nonce']='f'*64
        self.assertFalse(self.verify(observer_envelope=bad)['ok'])

    def test_stale_anchor(self):
        self.assertEqual(self.verify(as_of_utc='2026-11-23T12:31:00+00:00')['reason'],
                         'DEPLOYMENT_ATTESTATION_STALE_OR_FUTURE_OBSERVATION')

    def test_checkpoint_corruption_detected(self):
        con=sqlite3.connect(self.base.path)
        try:
            con.execute('DROP TRIGGER checkpoint_no_update')
            con.execute('UPDATE checkpoints SET checkpoint_sha256=? WHERE seq=1',('f'*64,))
            con.commit()
        finally:con.close()
        self.assertEqual(self.verify()['reason'],'CHAIN_INTEGRITY_FAILURE')

    def test_no_source_or_ledger_mutations(self):
        before=Path(self.base.path).read_bytes()
        self.assertTrue(self.verify()['ok'])
        self.assertEqual(before,Path(self.base.path).read_bytes())

    def test_wrong_attestation_binding(self):
        bad=self.sign_anchor({**self.anchor['body'],'attestation_sha256':'e'*64})
        self.assertEqual(self.verify(signed_anchor=bad)['reason'],'ATTESTATION_CHAIN_BINDING_MISMATCH')

    def test_missing_checkpoint_copy(self):
        self.assertEqual(self.verify(checkpoint_copy=Path(self.base.tmp.name)/'missing.db')['reason'],
                         'UNSAFE_OR_MISSING_AUDIT_COPY')

    def test_readonly_path_blocks_production(self):
        self.assertEqual(self.verify(checkpoint_copy='/data/apex_forward_provenance.db')['reason'],
                         'UNSAFE_OR_MISSING_AUDIT_COPY')

if __name__=='__main__':unittest.main()
