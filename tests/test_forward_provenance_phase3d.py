"""Phase 3D: no-write aggregate diagnostics and staging attestation checks."""
import datetime as dt
import hashlib
import base64
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from engine import forward_provenance as fp
from engine.forward_provenance_external_authority import create_staging_bundle
from engine.forward_provenance_operational import report


class Phase3DTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='apex-phase3d-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.src = self.root/'origin.db'
        self.audit = self.root/'offhost-copy.db'
        self.now = dt.datetime.now(dt.timezone.utc)
        self.claims = {'boot_id':'synthetic-3d-boot','pid':92001,'release':'STAGING-3D',
                       'git_sha_claim':'d'*40,'service_id_claim':'synthetic-service',
                       'identity_class':'RUNTIME_CLAIM_UNVERIFIED'}
        self.patches = [patch.object(fp,'enabled',return_value=True),
                        patch.object(fp,'runtime_identity',return_value=self.claims),
                        patch.object(fp,'DEFAULT_DB',self.src)]
        for p in self.patches:
            p.start();self.addCleanup(p.stop)
        self.assertEqual(fp.record_calculation('e1',ticker='SPX',path_version='p1')['status'],'RECORDED')
        self.assertEqual(fp.record_gamma('g1','e1',inserted=True,
                           source_timestamp_provenance='APEX_DERIVED_PARSE_TIME')['status'],'RECORDED')
        self.assertEqual(fp.record_decision('d1','g1',inserted=True,observed_at=fp.utc_now())['status'],'RECORDED')
        with sqlite3.connect('file:'+str(self.src)+'?mode=ro',uri=True) as src:
            with sqlite3.connect(self.audit) as dst:
                src.backup(dst)
        self.now = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=2)
        self.key = Ed25519PrivateKey.generate()
        self.public = self.key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)
        self.policy = {'environment':'ISOLATED_STAGING','allowed_key_fingerprints':[hashlib.sha256(self.public).hexdigest()],
                       'revoked_key_fingerprints':[]}
        lo = (self.now-dt.timedelta(hours=1)).isoformat()
        hi = (self.now+dt.timedelta(hours=1)).isoformat()
        base = {'service_id':'synthetic-service','ledger_id':'staging-ledger-3d','git_sha':'d'*40,
                'release':'STAGING-3D','valid_from':lo,'valid_until':hi}
        self.facts = {'environment':'ISOLATED_STAGING',
                      'deployment':{**base,'evidence_source':'RENDER_API_DEPLOY_RECORD'},
                      'boot':{**base,'evidence_source':'EXTERNAL_SUPERVISOR_BOOT_RECORD',
                              'boot_id':'synthetic-3d-boot','pid':92001}}
        self.bundle = create_staging_bundle(audit_copy=self.audit,observed_facts=self.facts,
                                            operator_private_key=self.key,observed_at=self.now.isoformat())

    def check(self, **kw):
        return report(ledger_path=self.audit,decision_id='d1',as_of=self.now.isoformat(),**kw)

    def test_no_external_inputs_is_unverified_and_reports_coverage(self):
        r=self.check(source_decision_ids=['d1','d2'])
        self.assertEqual(r['status'],'UNVERIFIED')
        self.assertEqual(r['coverage']['missing_decision_receipt'],1)
        self.assertEqual(r['metrics']['reported_boots'],1)
        self.assertEqual(r['metrics']['incomplete_decision_execution_chains'],0)

    def test_missing_receipt(self):
        self.assertEqual(report(ledger_path=self.audit,decision_id='absent')['status'],'MISSING_RECEIPT')

    def test_staging_correlated_not_verified(self):
        r=self.check(bundle=self.bundle,pinned_public_key=self.public,trust_policy=self.policy)
        self.assertTrue(r['ok'],r)
        self.assertEqual(r['status'],'STAGING_CORROBORATED_OPERATOR_FACTS')
        self.assertEqual(r['authentication'],'NOT_REAL_WORLD_AUTHENTICATION')
        self.assertEqual(r['promotion_authority'],'NONE')

    def test_revoked_key(self):
        policy={**self.policy,'revoked_key_fingerprints':self.policy['allowed_key_fingerprints']}
        self.assertEqual(self.check(bundle=self.bundle,pinned_public_key=self.public,
                                    trust_policy=policy)['status'],'REVOKED_KEY')

    def test_stale_checkpoint(self):
        later=(self.now+dt.timedelta(hours=2)).isoformat()
        r=report(ledger_path=self.audit,decision_id='d1',bundle=self.bundle,
                 pinned_public_key=self.public,trust_policy=self.policy,as_of=later,
                 max_checkpoint_age_seconds=900)
        self.assertEqual(r['status'],'STALE_CHECKPOINT')

    def test_chain_corruption(self):
        with sqlite3.connect(self.audit) as db:
            db.execute('DROP TRIGGER forward_provenance_no_update')
            db.execute("UPDATE forward_provenance_events SET entity_id='tamper' WHERE sequence=2")
        self.assertEqual(self.check()['status'],'CHAIN_INTEGRITY_FAILURE')

    def test_signed_checkpoint_head_mismatch_is_unverified(self):
        modified=json.loads(json.dumps(self.bundle))
        body=modified['statements'][2]['body']
        body['head_hash']='0'*64
        modified['statements'][2]['signature']=base64.b64encode(
            self.key.sign(fp._canonical(body).encode())).decode()
        verdict=self.check(bundle=modified,pinned_public_key=self.public,trust_policy=self.policy)
        self.assertEqual(verdict['status'],'UNVERIFIED')
        self.assertEqual(verdict['reason'],'CHECKPOINT_DOES_NOT_MATCH_LEDGER')

    def test_signed_false_claim_is_never_verified(self):
        modified=json.loads(json.dumps(self.bundle))
        modified['statements'][1]['body']['boot_id']='forged'
        r=self.check(bundle=modified,pinned_public_key=self.public,trust_policy=self.policy)
        self.assertFalse(r['ok'])
        self.assertEqual(r['status'],'UNVERIFIED')

    def test_source_and_ledger_bytes_unchanged(self):
        before=self.audit.read_bytes()
        self.check()
        self.check(bundle=self.bundle,pinned_public_key=self.public,trust_policy=self.policy)
        self.assertEqual(before,self.audit.read_bytes())


if __name__=='__main__':unittest.main()
