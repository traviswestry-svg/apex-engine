#!/usr/bin/env python3
"""Phase 3A synthetic, disposable verification rehearsal. NOT real attestation.

Creates its own temporary ledger and an SQLite-backup audit copy. Does not use
production SQLite, /data, external attestations, or secret signing material.
A test signer is deliberately in-process: any positive result proves only
signature/receipt plumbing, NEVER independent producer authentication.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

from engine import forward_provenance as fp
from engine import forward_provenance_verifier as verifier

FAKE_SHA = 'a' * 40
FAKE_ID = {
    'boot_id': 'PHASE3A-TEST-BOOT', 'pid': 424242,
    'release': '69.10.47', 'git_sha_claim': FAKE_SHA,
    'service_id_claim': 'srv-PHASE3A-SYNTHETIC',
    'identity_class': 'RUNTIME_CLAIM_UNVERIFIED',
}


def _signed(key, kind, **attrs):
    body = {
        'domain': verifier.DOMAIN, 'schema': 1, 'kind': kind,
        'ledger_id': 'PHASE3A-TEST-LEDGER',
        'service_id': FAKE_ID['service_id_claim'], **attrs,
    }
    signature = key.sign(fp._canonical(body).encode())
    return {'body': body, 'signature': base64.b64encode(signature).decode()}


def _attestations(key, head, now):
    earlier = (now - dt.timedelta(minutes=10)).isoformat()
    later = (now + dt.timedelta(minutes=10)).isoformat()
    captured = (now + dt.timedelta(seconds=1)).isoformat()
    common = {'release': FAKE_ID['release'], 'git_sha': FAKE_SHA,
              'valid_from': earlier, 'valid_until': later}
    return [
        _signed(key, 'DEPLOY', **common),
        _signed(key, 'BOOT', **common, boot_id=FAKE_ID['boot_id'], pid=FAKE_ID['pid']),
        _signed(key, 'CHECKPOINT', sequence=head['rows'],
                head_hash=head['head_hash'], captured_at=captured),
    ]


def _copy_database(src: Path, dst: Path):
    # SQLite's backup API includes committed WAL frames; never use shutil.copy
    # on a live WAL-mode SQLite database.
    with sqlite3.connect(src.resolve().as_uri() + '?mode=ro', uri=True) as a:
        with sqlite3.connect(dst) as b:
            a.backup(b)


def run_phase3a():
    """Raise AssertionError on any failed negative/control; return concise report."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    cases = {}
    with tempfile.TemporaryDirectory(prefix='apex-phase3a-synthetic-') as root:
        folder = Path(root)
        ledger = folder / 'runtime-ledger.sqlite'
        audit = folder / 'audit-copy.sqlite'
        with patch.dict(os.environ, {'APEX_FORWARD_PROVENANCE_ENABLED': '1'}, clear=False), \
             patch.object(fp, 'DEFAULT_DB', str(ledger)), \
             patch.object(fp, 'runtime_identity', return_value=dict(FAKE_ID)):
            execution = fp.new_execution_id()
            assert fp.record_calculation(execution, ticker='SPX-TEST', path_version='TEST-FINGERPRINT')['status'] == 'RECORDED'
            assert fp.record_gamma('GAMMA-PHASE3A', execution, inserted=True,
                source_timestamp_provenance='APEX_DERIVED_PARSE_TIME')['status'] == 'RECORDED'
            now = dt.datetime.now(dt.timezone.utc)
            assert fp.record_decision('DECISION-PHASE3A', 'GAMMA-PHASE3A',
                inserted=True, observed_at=now.isoformat())['status'] == 'RECORDED'
            head = fp.verify_chain(path=ledger)
            assert head['ok'] and head['rows'] == 3
            cases['three_stage_receipts_and_chain'] = 'PASS'

            with sqlite3.connect(ledger.resolve().as_uri() + '?mode=ro', uri=True) as conn:
                count_before = conn.execute('SELECT COUNT(*) FROM forward_provenance_events').fetchone()[0]
            assert fp.record_gamma('GAMMA-PHASE3A', execution, inserted=False,
                source_timestamp_provenance=None)['status'] == 'NOT_ELIGIBLE'
            assert fp.record_decision('DECISION-PHASE3A', 'GAMMA-PHASE3A',
                inserted=False, observed_at=now.isoformat())['status'] == 'NOT_ELIGIBLE'
            with sqlite3.connect(ledger.resolve().as_uri() + '?mode=ro', uri=True) as conn:
                assert conn.execute('SELECT COUNT(*) FROM forward_provenance_events').fetchone()[0] == count_before
            cases['duplicate_persistence_no_extra_receipts'] = 'PASS'

            # Snapshot ledger independently with SQLite's transaction-safe backup.
            _copy_database(ledger, audit)
            assert fp.verify_chain(path=audit)['ok']
            cases['transaction_consistent_audit_copy'] = 'PASS'

            key = Ed25519PrivateKey.generate()  # TEST-ONLY: never persisted or deployed.
            pub = key.public_key().public_bytes(serialization.Encoding.Raw,
                                                 serialization.PublicFormat.Raw)
            docs = _attestations(key, head, now)
            future = (now + dt.timedelta(seconds=10)).isoformat()

            def verify(statement_set, decision_id='DECISION-PHASE3A', key_bytes=pub, identity_path=audit):
                return verifier.verify_external_receipts(
                    ledger_path=identity_path, statements=statement_set,
                    pinned_public_key=key_bytes, decision_id=decision_id, as_of=future)

            result = verify(docs)
            assert result['ok'] and result['status'] == 'EXTERNALLY_CORROBORATED_RECEIPTS'
            cases['simulated_signature_consistency_only'] = 'PASS'

            assert verify(docs, decision_id='UNKNOWN-DECISION')['status'] == 'UNVERIFIED'
            cases['unknown_decision_fails_closed'] = 'PASS'

            assert verify(docs[:2])['status'] == 'UNVERIFIED'
            cases['missing_checkpoint_fails_closed'] = 'PASS'

            wrong_key = Ed25519PrivateKey.generate().public_key().public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw)
            assert verify(docs, key_bytes=wrong_key)['status'] == 'UNVERIFIED'
            cases['untrusted_key_fails_closed'] = 'PASS'

            # BOOT is freshly re-signed, but claims a different process.
            forged = list(docs)
            b = docs[1]['body']
            forged[1] = _signed(key, 'BOOT', release=b['release'], git_sha=b['git_sha'],
                boot_id='DIFFERENT-BOOT', pid=b['pid'], valid_from=b['valid_from'],
                valid_until=b['valid_until'])
            assert verify(forged)['status'] == 'UNVERIFIED'
            cases['different_boot_fails_closed'] = 'PASS'

            # Missing gamma receipt: new synthetic decision is explicitly unlinked.
            assert fp.record_decision('DECISION-NO-GAMMA', 'GAMMA-UNKNOWN',
                inserted=True, observed_at=now.isoformat())['status'] == 'RECORDED'
            latest = fp.verify_chain(path=ledger)
            _copy_database(ledger, folder / 'audit-with-missing-gamma.sqlite')
            docs_latest = _attestations(key, latest, now)
            assert verify(docs_latest, decision_id='DECISION-NO-GAMMA',
                identity_path=folder / 'audit-with-missing-gamma.sqlite')['status'] == 'UNVERIFIED'
            cases['missing_gamma_receipt_fails_closed'] = 'PASS'

            # A fresh ledger event renders the older signed checkpoint insufficient.
            assert verify(docs, identity_path=folder / 'audit-with-missing-gamma.sqlite')['status'] == 'UNVERIFIED'
            cases['stale_checkpoint_fails_closed'] = 'PASS'

            # SQLite-enforced immutability.
            with sqlite3.connect(audit) as db:
                try:
                    db.execute("UPDATE forward_provenance_events SET kind='DECISION_PERSISTED'")
                except sqlite3.DatabaseError:
                    pass
                else:
                    raise AssertionError('immutable update was accepted')
            cases['append_only_trigger_enforced'] = 'PASS'

        # Disabled mode, entirely independent from production feature setting.
        disabled_db = folder / 'disabled.sqlite'
        with patch.dict(os.environ, {'APEX_FORWARD_PROVENANCE_ENABLED': '0'}, clear=False), \
             patch.object(fp, 'DEFAULT_DB', str(disabled_db)):
            assert fp.record_calculation('DISABLED-EXE', ticker='TEST', path_version='X')['status'] == 'DISABLED'
            assert not disabled_db.exists()
        cases['disabled_creates_no_ledger'] = 'PASS'

    return {'ok': True, 'phase': '3A', 'environment': 'DISPOSABLE_SYNTHETIC_ONLY',
            'test_key': 'EPHEMERAL_IN_PROCESS_NOT_INDEPENDENT',
            'authentication': 'NOT_REAL_WORLD_AUTHENTICATION',
            'promotion_authority': 'NONE',
            'production_data_accessed': False,
            'cases': cases, 'total_passed': len(cases)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', action='store_true', help='Print JSON status report')
    args = parser.parse_args()
    try:
        result = run_phase3a()
    except Exception as exc:
        result = {'ok': False, 'phase': '3A', 'status': 'FAILED',
                  'reason': type(exc).__name__ + ': ' + str(exc)}
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print('Phase 3A:', 'PASS' if result['ok'] else 'FAIL')
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result['ok'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
