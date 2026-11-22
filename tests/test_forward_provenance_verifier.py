"""Offline verification tests with independently generated test-only signing keys."""
import base64
import datetime as dt
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from engine import forward_provenance as fp
from engine import forward_provenance_verifier as v


class VerifierTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'ledger.db'
        self.key = Ed25519PrivateKey.generate()
        self.pub = self.key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.env = patch.dict(os.environ, {
            'APEX_FORWARD_PROVENANCE_ENABLED': '1',
            'RENDER_GIT_COMMIT': 'a'*40,
            'RENDER_SERVICE_ID': 'srv-test',
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.patchdb = patch.object(fp, 'DEFAULT_DB', str(self.path))
        self.patchdb.start()
        self.addCleanup(self.patchdb.stop)
        self.identity = patch.object(fp, 'runtime_identity', return_value={
            'boot_id': 'boot-abc', 'pid': 777, 'release': '69.10.47',
            'git_sha_claim': 'a'*40, 'service_id_claim': 'srv-test',
            'identity_class': 'RUNTIME_CLAIM_UNVERIFIED',
        })
        self.identity.start()
        self.addCleanup(self.identity.stop)
        x = 'execution-test'
        self.assertEqual(fp.record_calculation(x, ticker='SPX', path_version='abc')['status'], 'RECORDED')
        self.assertEqual(fp.record_gamma('gamma-test', x, inserted=True,
            source_timestamp_provenance='APEX_DERIVED_PARSE_TIME')['status'], 'RECORDED')
        self.assertEqual(fp.record_decision('decision-test', 'gamma-test', inserted=True,
            observed_at='2026-11-22T10:00:00+00:00')['status'], 'RECORDED')
        self.now = dt.datetime.now(dt.timezone.utc)

    def sign(self, kind, **kw):
        body = {'domain': v.DOMAIN, 'kind':kind,'schema':1,
                'ledger_id':'externally-inventoried-ledger-1',
                'service_id':'srv-test', **kw}
        return {'body': body, 'signature': base64.b64encode(
            self.key.sign(v._canonical(body).encode())).decode()}

    def docs(self):
        first = (self.now - dt.timedelta(minutes=5)).isoformat()
        last = (self.now + dt.timedelta(minutes=5)).isoformat()
        checkpoint_at = (self.now + dt.timedelta(seconds=5)).isoformat()
        head = fp.verify_chain(path=self.path)
        return [
            self.sign('DEPLOY', release='69.10.47', git_sha='a'*40, valid_from=first, valid_until=last),
            self.sign('BOOT', release='69.10.47', git_sha='a'*40, boot_id='boot-abc', pid=777,
                      valid_from=first, valid_until=last),
            self.sign('CHECKPOINT', sequence=head['rows'], head_hash=head['head_hash'], captured_at=checkpoint_at),
        ]

    def check(self, docs=None, **kwargs):
        return v.verify_external_receipts(ledger_path=self.path, statements=docs or self.docs(),
                                         pinned_public_key=self.pub, decision_id='decision-test',
                                         as_of=(self.now + dt.timedelta(seconds=10)).isoformat(), **kwargs)

    def test_correlated_receipts_with_signed_independent_statements(self):
        self.assertEqual(self.check()['status'], 'EXTERNALLY_CORROBORATED_RECEIPTS')

    def test_wrong_public_key_rejected(self):
        k = Ed25519PrivateKey.generate().public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        res = v.verify_external_receipts(ledger_path=self.path, statements=self.docs(),
            pinned_public_key=k, decision_id='decision-test')
        self.assertFalse(res['ok'])

    def test_truncated_chain_not_accepted_by_checkpoint(self):
        docs = self.docs()
        with sqlite3.connect(self.path) as db:
            db.execute('DROP TRIGGER forward_provenance_no_delete')
            db.execute('DELETE FROM forward_provenance_events WHERE sequence=3')
        self.assertEqual(self.check(docs)['reason'], 'CHECKPOINT_HEAD_OR_LENGTH_MISMATCH')

    def test_forged_boot_rejected(self):
        docs = self.docs()
        docs[1] = self.sign('BOOT', release='69.10.47', git_sha='a'*40,
                            boot_id='wrong',pid=777,
                            valid_from=docs[1]['body']['valid_from'],
                            valid_until=docs[1]['body']['valid_until'])
        self.assertEqual(self.check(docs)['reason'], 'RUNTIME_CLAIMS_CONFLICT_WITH_ATTESTATION')

    def test_no_checkpoint_rejected(self):
        self.assertEqual(self.check(self.docs()[:2])['reason'], 'REQUIRE_THREE_INDEPENDENT_STATEMENTS')

    def test_modified_claims_rejected_even_when_signed(self):
        docs = self.docs()
        docs[0]['body']['git_sha'] = 'b'*40
        self.assertFalse(self.check(docs)['ok'])

    def test_empty_key_fails_closed(self):
        res = v.verify_external_receipts(ledger_path=self.path, statements=self.docs(),
                                         pinned_public_key=b'', decision_id='decision-test')
        self.assertEqual(res['reason'], 'NO_PINNED_PUBLIC_KEY')

if __name__ == '__main__':
    unittest.main()
