"""Phase 4C staging-only persistence and recovery checks."""
import concurrent.futures
import copy
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from tests import test_forward_provenance_phase4b as phase4b
AT = phase4b.AT
from engine.forward_provenance_checkpoint_store import StagingCheckpointStore, CheckpointRefusal
from engine.forward_provenance_signer import issue_staging_deployment_attestation

class Phase4CTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'external_simulated.db'
        self.store = StagingCheckpointStore(self.path)
        self.fixture = phase4b.Phase4BTests(methodName='test_staging_issue_verify_no_go')
        self.fixture.setUp()

    def issue(self, *, store=None, envelope=None):
        s = store or self.store
        env = envelope or self.fixture.envelope
        return issue_staging_deployment_attestation(
            envelope=env, policy=self.fixture.policy, signer_key_id='signer-1',
            signer=self.fixture.signer, as_of=AT,
            reserve_nonce=lambda nonce: s.reserve_nonce(nonce, at=AT))

    def append(self, att, *, store=None, predecessor='0'*64, envelope=None):
        s = store or self.store
        return s.publish(nonce=att['body']['nonce'],attestation=att,at=AT,
                         expected_predecessor=predecessor,
                         envelope=envelope or self.fixture.envelope,policy=self.fixture.policy)

    def test_reservation_survives_restart(self):
        self.assertTrue(self.store.reserve_nonce('a'*64, at=AT))
        opened=StagingCheckpointStore(self.path)
        self.assertFalse(opened.reserve_nonce('a'*64, at=AT))
        self.assertEqual(opened.audit()['uncheckpointed_reservations'],1)

    def test_concurrent_reservation_single_winner(self):
        def worker(_):
            return StagingCheckpointStore(self.path).reserve_nonce('c'*64,at=AT)
        with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
            answers=list(ex.map(worker,range(24)))
        self.assertEqual(sum(answers),1)

    def test_full_signed_checkpoint_and_restart(self):
        att=self.issue();res=self.append(att)
        check=StagingCheckpointStore(self.path).audit(expected_anchor=res['checkpoint_sha256'])
        self.assertTrue(check['ok']);self.assertEqual(check['checkpoint_count'],1)
        self.assertEqual(check['status'],'STAGING_CHAIN_CONSISTENT_NOT_AUTHENTICATED')
        self.assertEqual(check['verdict'],'NO_GO')

    def test_repeated_attestation_no_double_publish(self):
        att=self.issue();self.append(att)
        with self.assertRaisesRegex(CheckpointRefusal,'REPLAY_OR_DUPLICATE'):
            self.append(att,predecessor=self.store.audit()['head_sha256'])
        self.assertEqual(self.store.audit()['checkpoint_count'],1)

    def test_wrong_expected_head_fail_closed(self):
        att=self.issue()
        with self.assertRaisesRegex(CheckpointRefusal,'HEAD_CONFLICT'):
            self.append(att,predecessor='e'*64)
        self.assertEqual(self.store.audit()['checkpoint_count'],0)
        self.assertEqual(self.store.audit()['uncheckpointed_reservations'],1)

    def test_interrupted_signing_preserves_nonce_not_receipt(self):
        self.assertTrue(self.store.reserve_nonce('d'*64,at=AT))
        with self.assertRaisesRegex(Exception,'REPLAY'):
            self.store.reserve_nonce('d'*64,at=AT) or (_ for _ in ()).throw(CheckpointRefusal('REPLAY'))
        self.assertEqual(self.store.audit()['uncheckpointed_reservations'],1)

    def test_unreserved_nonce_rejected(self):
        att=self.issue()
        fake=StagingCheckpointStore(Path(self.tmp.name)/'another.db')
        with self.assertRaisesRegex(CheckpointRefusal,'NONCE_NOT_RESERVED'):
            self.append(att,store=fake)

    def test_false_process_claim_rejected(self):
        att=self.issue(); forged=copy.deepcopy(att)
        forged['body']['process_identity']='PROCESS_REAL'
        with self.assertRaisesRegex(CheckpointRefusal,'ATTESTATION_UNVERIFIED'):
            self.append(forged)

    def test_chain_mutation_detected(self):
        att=self.issue();self.append(att)
        con=sqlite3.connect(self.path)
        try:
            con.execute('DROP TRIGGER checkpoint_no_update')
            con.execute("UPDATE checkpoints SET checkpoint_sha256=? WHERE seq=1",('f'*64,))
            con.commit()
        finally: con.close()
        self.assertEqual(self.store.audit()['status'],'CHAIN_INTEGRITY_FAILURE')

    def test_deleted_tail_detected_against_anchor(self):
        att=self.issue();head=self.append(att)['checkpoint_sha256']
        con=sqlite3.connect(self.path)
        try:
            con.execute('DROP TRIGGER checkpoint_no_delete')
            con.execute('DELETE FROM checkpoints WHERE seq=1')
            con.commit()
        finally: con.close()
        self.assertEqual(self.store.audit(expected_anchor=head)['status'],'EXTERNAL_ANCHOR_MISMATCH')

    def test_database_triggers_refuse_mutation(self):
        att=self.issue();self.append(att)
        con=sqlite3.connect(self.path)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                con.execute('DELETE FROM checkpoints WHERE seq=1')
            with self.assertRaises(sqlite3.IntegrityError):
                con.execute('DELETE FROM nonce_reservations')
        finally:con.close()

    def test_production_context_rejected(self):
        with self.assertRaisesRegex(CheckpointRefusal,'PRODUCTION_STORAGE'):
            StagingCheckpointStore(self.path,environment='PRODUCTION')

    def test_no_anchor_cannot_claim_external_verification(self):
        data=self.store.audit()
        self.assertFalse(data['external_anchor_provided']);self.assertEqual(data['verdict'],'NO_GO')

    def test_stale_expected_anchor_rejected(self):
        att=self.issue();self.append(att)
        self.assertEqual(self.store.audit(expected_anchor='0'*64)['status'],'EXTERNAL_ANCHOR_MISMATCH')

    def test_multi_checkpoint_continuity(self):
        att=self.issue();head=self.append(att)['checkpoint_sha256']
        self.fixture.envelope=copy.deepcopy(self.fixture.envelope)
        self.fixture.envelope['body']['nonce']='1'*64
        from engine.forward_provenance_render_observer import canonical
        import base64
        self.fixture.envelope['signature']=base64.b64encode(self.fixture.collector.sign(canonical(self.fixture.envelope['body']))).decode()
        second=self.issue()
        head2=self.append(second,predecessor=head)['checkpoint_sha256']
        self.assertNotEqual(head,head2)
        self.assertEqual(StagingCheckpointStore(self.path).audit(expected_anchor=head2)['checkpoint_count'],2)

if __name__=='__main__':unittest.main()
