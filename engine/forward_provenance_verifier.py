"""Read-only off-host corroboration for forward provenance receipts.

Never writes a source database, updates an evidence class, or authorizes trading.
A trusted verifier must supply a pinned Ed25519 key and independently obtained
signed DEPLOY, BOOT, and CHECKPOINT statements. Ledger-sourced statements are
not acceptable as independent evidence.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import sqlite3
from pathlib import Path
from typing import Any, Mapping

from .forward_provenance import verify_chain, _canonical

DOMAIN = 'APEX_FORWARD_PROVENANCE_ATTESTATION_V1'
KINDS = {'DEPLOY', 'BOOT', 'CHECKPOINT'}


def _time(v: Any) -> dt.datetime:
    if not isinstance(v, str):
        raise ValueError('missing ISO timestamp')
    out = dt.datetime.fromisoformat(v.replace('Z', '+00:00'))
    if out.tzinfo is None:
        raise ValueError('timezone is required')
    return out.astimezone(dt.timezone.utc)


def _verify_signature(statement: Mapping[str, Any], pinned_public_key: bytes) -> dict:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    if set(statement) != {'body', 'signature'}:
        raise ValueError('statement must contain only body and signature')
    body = statement['body']
    if not isinstance(body, dict) or body.get('domain') != DOMAIN or body.get('kind') not in KINDS:
        raise ValueError('invalid statement domain/kind')
    sig = base64.b64decode(statement['signature'], validate=True)
    Ed25519PublicKey.from_public_bytes(pinned_public_key).verify(sig, _canonical(body).encode())
    return body


def verify_external_receipts(*, ledger_path: str | Path, statements: list[Mapping[str, Any]],
                             pinned_public_key: bytes, decision_id: str,
                             as_of: str | None = None) -> dict[str, Any]:
    """Corroborate one decision with externally signed deploy, boot and chain head.

    The external collector must verify boot identity independently; a signed
    transcription of app-provided env vars alone is not sufficient.
    This function checks signatures and consistency, not collector honesty or
    real vendor event times. No promotion or source-database mutation occurs.
    """
    failed = lambda reason: {'ok': False, 'status': 'UNVERIFIED', 'reason': reason}
    try:
        if not pinned_public_key or len(pinned_public_key) != 32:
            return failed('NO_PINNED_PUBLIC_KEY')
        if not isinstance(statements, list) or len(statements) != 3:
            return failed('REQUIRE_THREE_INDEPENDENT_STATEMENTS')
        bodies = [_verify_signature(s, pinned_public_key) for s in statements]
        grouped = {b['kind']: b for b in bodies}
        if set(grouped) != KINDS:
            return failed('MISSING_OR_DUPLICATE_STATEMENT_KIND')
        deploy, boot, cp = (grouped[k] for k in ('DEPLOY','BOOT','CHECKPOINT'))
        if any(b.get('schema') != 1 for b in bodies):
            return failed('UNKNOWN_ATTESTATION_SCHEMA')
        chain = verify_chain(path=ledger_path)
        if not chain.get('ok'):
            return failed('LEDGER_CHAIN_INVALID')
        if int(cp['sequence']) != chain['rows'] or cp['head_hash'] != chain['head_hash']:
            return failed('CHECKPOINT_HEAD_OR_LENGTH_MISMATCH')
        if cp.get('ledger_id') != boot.get('ledger_id') or cp.get('ledger_id') != deploy.get('ledger_id'):
            return failed('LEDGER_ID_MISMATCH')
        if any(b.get('service_id') != deploy.get('service_id') for b in (boot, cp)):
            return failed('SERVICE_ID_MISMATCH')
        if boot.get('git_sha') != deploy.get('git_sha') or boot.get('release') != deploy.get('release'):
            return failed('DEPLOY_BOOT_MISMATCH')
        sha = deploy.get('git_sha')
        if not isinstance(sha, str) or len(sha) != 40 or any(x not in '0123456789abcdef' for x in sha.lower()):
            return failed('INVALID_COMMIT_SHA')
        if not all(isinstance(b.get('service_id'), str) and b['service_id'] for b in bodies):
            return failed('MISSING_SERVICE_ID')
        d_from, d_to = _time(deploy['valid_from']), _time(deploy['valid_until'])
        b_from, b_to = _time(boot['valid_from']), _time(boot['valid_until'])
        cp_at = _time(cp['captured_at'])
        now = _time(as_of) if as_of else dt.datetime.now(dt.timezone.utc)
        if not (d_from < d_to and b_from < b_to and cp_at <= now):
            return failed('INVALID_ATTESTATION_INTERVAL')
        if cp_at < b_from:
            return failed('CHECKPOINT_PREDATES_BOOT')
        if not isinstance(boot.get('boot_id'), str) or not boot['boot_id'] or not isinstance(boot.get('pid'), int):
            return failed('INVALID_BOOT_IDENTITY')
        path = Path(ledger_path)
        if not path.is_file():
            return failed('LEDGER_MISSING')
        uri = path.resolve().as_uri() + '?mode=ro'
        with sqlite3.connect(uri, uri=True) as db:
            db.row_factory = sqlite3.Row
            events = db.execute('SELECT * FROM forward_provenance_events ORDER BY sequence').fetchall()
        decision = [r for r in events if r['kind'] == 'DECISION_PERSISTED' and r['entity_id'] == decision_id]
        if len(decision) != 1:
            return failed('DECISION_RECEIPT_NOT_UNIQUE')
        dr = decision[0]
        ep = json.loads(dr['payload_json'])
        ev = ep['evidence']
        if ev.get('linkage_class') != 'SAME_PROCESS_RECEIPT_CLAIM':
            return failed('DECISION_GAMMA_LINK_UNVERIFIED')
        gamma = [r for r in events if r['kind'] == 'GAMMA_PERSISTED' and
                 r['event_id'] == ev.get('gamma_receipt_event_id') and
                 r['entity_id'] == ev.get('canonical_gamma_snapshot_id') and
                 r['execution_id'] == dr['execution_id']]
        calc = [r for r in events if r['kind'] == 'GAMMA_CALCULATED' and
                r['entity_id'] == dr['execution_id'] and r['execution_id'] == dr['execution_id']]
        if len(gamma) != 1 or len(calc) != 1 or not dr['execution_id']:
            return failed('EXACT_GAMMA_EXECUTION_CHAIN_MISSING')
        cr, gr = calc[0], gamma[0]
        if not (cr['sequence'] < gr['sequence'] < dr['sequence'] <= int(cp['sequence'])):
            return failed('RECEIPT_ORDER_INVALID')
        for r in (cr, gr, dr):
            runtime = json.loads(r['payload_json'])['runtime']
            if (runtime.get('boot_id') != boot['boot_id'] or runtime.get('pid') != boot['pid'] or
                runtime.get('git_sha_claim') != sha or runtime.get('service_id_claim') != deploy['service_id'] or
                runtime.get('release') != deploy['release']):
                return failed('RUNTIME_CLAIMS_CONFLICT_WITH_ATTESTATION')
            stamp = _time(r['inserted_at'])
            if not (d_from <= stamp <= d_to and b_from <= stamp <= b_to and stamp <= cp_at):
                return failed('RECEIPT_OUTSIDE_ATTESTED_INTERVAL')
        return {'ok': True, 'status': 'EXTERNALLY_CORROBORATED_RECEIPTS',
                'decision_id': decision_id, 'gamma_snapshot_id': gr['entity_id'],
                'gamma_execution_id': dr['execution_id'], 'git_sha': sha,
                'checkpoint_hash': cp['head_hash'],
                'caveat': 'No source-row authentication or trading/promotion authority'}
    except (KeyError, TypeError, ValueError, OSError, sqlite3.Error, ImportError, Exception) as exc:
        return failed('VERIFICATION_ERROR_' + type(exc).__name__)
