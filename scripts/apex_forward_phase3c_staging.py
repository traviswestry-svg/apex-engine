"""Phase 3C isolated staging rehearsal; NEVER run with real production keys.

No network access or on-host key custody. All evidence is synthetic operator
facts, not independently authenticated Render/OS records.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import tempfile
from pathlib import Path


def rehearse() -> dict:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from engine import forward_provenance as fp
    from engine.forward_provenance_external_authority import (
        create_staging_bundle, export_bundle_atomic, verify_staging_bundle)
    from engine.forward_provenance_verifier import DOMAIN

    cases = {}
    def check(name, predicate):
        if not predicate:
            raise AssertionError(name)
        cases[name] = 'PASS'

    original_enabled = fp.enabled
    original_identity = fp.runtime_identity
    original_default = fp.DEFAULT_DB
    try:
        with tempfile.TemporaryDirectory(prefix='apex-phase3c-synthetic-') as root:
            root = Path(root)
            ledger = root / 'apex_origin' / 'evidence.db'
            external = root / 'external_operator'
            external.mkdir()
            # Only synthetic runtime metadata; never reads Render production.
            claims = {'boot_id':'synthetic-boot-3c','pid':98765,
                      'release':'STAGING-3C','git_sha_claim':'a'*40,
                      'service_id_claim':'synthetic-service-3c',
                      'identity_class':'RUNTIME_CLAIM_UNVERIFIED'}
            fp.enabled = lambda: True
            fp.runtime_identity = lambda: dict(claims)
            fp.DEFAULT_DB = ledger
            calc = fp.record_calculation('synthetic-execution', ticker='SPX', path_version='synthetic-path')
            gamma = fp.record_gamma('synthetic-gamma','synthetic-execution',inserted=True,source_timestamp_provenance='APEX_DERIVED_PARSE_TIME')
            decision = fp.record_decision('synthetic-decision','synthetic-gamma',inserted=True,observed_at=fp.utc_now())
            check('three_stage_receipts_created', all(x['status']=='RECORDED' for x in (calc,gamma,decision)))
            # SQLite backup API yields a transaction-consistent staging copy.
            audit = external / 'audit-copy.db'
            source = sqlite3.connect('file:'+str(ledger)+'?mode=ro', uri=True)
            target = sqlite3.connect(audit)
            source.backup(target)
            source.close(); target.close()
            check('transaction_consistent_off_host_simulated_copy', audit.is_file())
            key = Ed25519PrivateKey.generate() # EPHEMERAL TEST-ONLY
            pub = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
            import datetime as dt
            now = dt.datetime.now(dt.timezone.utc)
            t0 = (now - dt.timedelta(hours=1)).isoformat()
            t1 = (now + dt.timedelta(hours=1)).isoformat()
            observed = now.isoformat()
            facts = {'environment':'ISOLATED_STAGING',
                     'deployment':{'evidence_source':'RENDER_API_DEPLOY_RECORD','service_id':claims['service_id_claim'],
                       'ledger_id':'synthetic-ledger-3c','git_sha':claims['git_sha_claim'],'release':claims['release'],
                       'valid_from':t0,'valid_until':t1},
                     'boot':{'evidence_source':'EXTERNAL_SUPERVISOR_BOOT_RECORD','service_id':claims['service_id_claim'],
                       'ledger_id':'synthetic-ledger-3c','git_sha':claims['git_sha_claim'],'release':claims['release'],
                       'valid_from':t0,'valid_until':t1,'boot_id':claims['boot_id'],'pid':claims['pid']}}
            bundle = create_staging_bundle(audit_copy=audit, observed_facts=facts, operator_private_key=key, observed_at=observed)
            bundle_path = external/'checkpoint-000001.json'
            export_bundle_atomic(bundle,bundle_path)
            check('off_host_copy_only_signed', bundle_path.is_file())
            try:
                export_bundle_atomic(bundle,bundle_path)
            except FileExistsError:
                check('checkpoint_cannot_be_overwritten',True)
            else:
                check('checkpoint_cannot_be_overwritten',False)
            policy = {'environment':'ISOLATED_STAGING','allowed_key_fingerprints':[__import__('hashlib').sha256(pub).hexdigest()],
                      'revoked_key_fingerprints':[]}
            def verify(b=bundle,p=policy,k=pub,a=audit):
                return verify_staging_bundle(audit_copy=a,bundle=b,pinned_public_key=k,
                                             decision_id='synthetic-decision',trust_policy=p,as_of=observed)
            good = verify()
            check('synthetic_operator_facts_validate',good.get('status')=='STAGING_CORROBORATED_OPERATOR_FACTS')
            check('no_real_world_authentication_claim',good.get('authentication')=='NOT_REAL_WORLD_DEPLOYMENT_AUTHENTICATION')
            check('no_promotion_authority',good.get('promotion_authority')=='NONE')
            rev = {**policy,'revoked_key_fingerprints':policy['allowed_key_fingerprints']}
            check('revoked_key_fails_closed',verify(p=rev)['reason']=='SIGNING_KEY_REVOKED')
            wrong = Ed25519PrivateKey.generate().public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)
            check('untrusted_key_fails_closed',not verify(k=wrong)['ok'])
            tampered = json.loads(json.dumps(bundle))
            tampered['statements'][1]['body']['pid'] += 1
            check('modified_signed_boot_rejected',not verify(b=tampered)['ok'])
            missing = json.loads(json.dumps(bundle))
            missing['statements'] = missing['statements'][:2]
            check('missing_checkpoint_fails_closed',not verify(b=missing)['ok'])
            truncated = external/'truncated.db'
            ss = sqlite3.connect(audit); dd = sqlite3.connect(truncated); ss.backup(dd); ss.close(); dd.close()
            conn=sqlite3.connect(truncated)
            conn.execute('DROP TRIGGER forward_provenance_no_delete')
            conn.execute('DELETE FROM forward_provenance_events WHERE sequence=3')
            conn.commit();conn.close()
            check('truncated_off_host_copy_rejected',not verify(a=truncated)['ok'])
            try:
                create_staging_bundle(audit_copy=audit,observed_facts={**facts,'environment':'PRODUCTION'},
                                      operator_private_key=key,observed_at=observed)
            except ValueError:
                check('production_context_refused',True)
            else:
                check('production_context_refused',False)
            try:
                create_staging_bundle(audit_copy=audit,observed_facts={**facts,'boot':{**facts['boot'],'git_sha':'b'*40}},
                                      operator_private_key=key,observed_at=observed)
            except ValueError:
                check('independent_claim_mismatch_refused',True)
            else:
                check('independent_claim_mismatch_refused',False)
            # Local state cannot validate a successor checkpoint without predecessor trail.
            successor = json.loads(json.dumps(bundle))
            successor['statements'][2]['body']['previous_checkpoint_sha256'] = 'a'*64
            successor['statements'][2]['signature'] = __import__('base64').b64encode(key.sign(fp._canonical(successor['statements'][2]['body']).encode())).decode()
            check('unverified_checkpoint_predecessor_rejected',verify(b=successor)['reason']=='PREDECESSOR_CHECKPOINT_REQUIRED')
            return {'ok':True,'phase':'3C','cases':cases,'total_passed':len(cases),
                    'authentication':'SYNTHETIC_OPERATOR_SUPPLIED_FACTS_NOT_REAL_WORLD_AUTHENTICATION',
                    'environment':'DISPOSABLE_SYNTHETIC_ONLY','production_data_accessed':False,
                    'promotion_authority':'NONE','historical_rows_modified':0}
    finally:
        fp.enabled=original_enabled;fp.runtime_identity=original_identity;fp.DEFAULT_DB=original_default


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--json',action='store_true')
    args=p.parse_args()
    try:
        report=rehearse()
    except Exception as exc:
        report={'ok':False,'phase':'3C','reason':type(exc).__name__+' '+str(exc),
                'promotion_authority':'NONE'}
    print(json.dumps(report,indent=2,sort_keys=True))
    return 0 if report['ok'] else 2

if __name__=='__main__':
    raise SystemExit(main())
