"""Phase 3D: read-only, non-authoritative forward-provenance health reporting.

Does NOT create evidence, sign attestations, backfill receipts, promote records,
change order execution, or claim real-world authentication. Only isolated staging
bundles may be corroborated by the existing Phase 3C verifier.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from .forward_provenance import verify_chain
from .forward_provenance_verifier import _verify_signature, _time
from .forward_provenance_external_authority import verify_staging_bundle

STATES = ('UNVERIFIED', 'MISSING_RECEIPT', 'STALE_CHECKPOINT', 'REVOKED_KEY',
          'CHAIN_INTEGRITY_FAILURE', 'STAGING_CORROBORATED_OPERATOR_FACTS')


def _fail(reason: str, state: str = 'UNVERIFIED') -> dict:
    return {'ok': False, 'status': state, 'reason': reason,
            'authentication': 'NOT_REAL_WORLD_AUTHENTICATION',
            'promotion_authority': 'NONE'}


def _ledger_rows(path: Path) -> list[sqlite3.Row]:
    # SQLite readonly avoids accidental database creation or journaling writes.
    conn = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    try:
        conn.execute('PRAGMA query_only=ON')
        conn.row_factory = sqlite3.Row
        return conn.execute('SELECT sequence,event_id,kind,entity_id,execution_id,inserted_at,payload_json '
                            'FROM forward_provenance_events ORDER BY sequence').fetchall()
    finally:
        conn.close()


def report(*, ledger_path: str | Path, decision_id: str | None = None,
           bundle: Mapping[str, Any] | None = None,
           pinned_public_key: bytes | None = None,
           trust_policy: Mapping[str, Any] | None = None,
           as_of: str | None = None,
           max_checkpoint_age_seconds: int = 900,
           source_decision_ids: list[str] | None = None) -> dict[str, Any]:
    """Inspect an existing audit copy; no database or evidence mutation.

    A provided source_decision_ids list is caller-owned *inventory*, not source
    row authentication. Never infer absence from mere failure to find a ledger ID.
    Real-world VERIFIED is intentionally unsupported by this staging-only module.
    """
    result: dict[str, Any] = {
        'phase': '3D', 'mode': 'READ_ONLY', 'promotion_authority': 'NONE',
        'authentication': 'NOT_REAL_WORLD_AUTHENTICATION',
        'ok': False, 'status': 'UNVERIFIED',
    }
    try:
        if not isinstance(max_checkpoint_age_seconds, int) or max_checkpoint_age_seconds < 0:
            return {**result, **_fail('INVALID_CHECKPOINT_AGE')}
        now = _time(as_of) if as_of is not None else dt.datetime.now(dt.timezone.utc)
        target = Path(ledger_path)
        if not target.is_file() or target.is_symlink():
            return {**result, **_fail('LEDGER_MISSING_OR_SYMLINK')}
        chain = verify_chain(path=target)
        if not chain.get('ok'):
            return {**result, **_fail('LEDGER_CHAIN_INVALID', 'CHAIN_INTEGRITY_FAILURE'),
                    'chain': chain}
        rows = _ledger_rows(target)
        kind_counts = Counter(r['kind'] for r in rows)
        decisions = Counter(r['entity_id'] for r in rows if r['kind'] == 'DECISION_PERSISTED')
        calc_ids = {(r['entity_id'],r['execution_id']) for r in rows if r['kind'] == 'GAMMA_CALCULATED'}
        gamma_receipts = {(r['event_id'],r['entity_id'],r['execution_id']) for r in rows if r['kind'] == 'GAMMA_PERSISTED'}
        boots = Counter()
        missing_boot_claims = 0
        orphan_decisions = 0
        for r in rows:
            try:
                body = json.loads(r['payload_json'])
                runtime = body.get('runtime') or {}
                identity = (runtime.get('boot_id'), runtime.get('pid'))
                if identity[0] and identity[1] is not None:
                    boots[str(identity[0]) + ' / ' + str(identity[1])] += 1
                else:
                    missing_boot_claims += 1
                if r['kind'] == 'DECISION_PERSISTED':
                    ev = body.get('evidence') or {}
                    if not (r['execution_id'] and
                            (r['execution_id'], r['execution_id']) in calc_ids and
                            (ev.get('gamma_receipt_event_id'), ev.get('canonical_gamma_snapshot_id'),
                             r['execution_id']) in gamma_receipts):
                        orphan_decisions += 1
            except (TypeError, ValueError, AttributeError):
                missing_boot_claims += 1
                if r['kind'] == 'DECISION_PERSISTED':
                    orphan_decisions += 1
        unique = set(decisions)
        if source_decision_ids is not None:
            if not isinstance(source_decision_ids, list) or any(not isinstance(x, str) or not x for x in source_decision_ids):
                return {**result, **_fail('INVALID_SOURCE_INVENTORY')}
            inventory = set(source_decision_ids)
            coverage = {'inventory_count': len(inventory),
                        'has_decision_receipt': len(inventory & unique),
                        'missing_decision_receipt': len(inventory - unique),
                        'receipt_ids_not_in_inventory': len(unique - inventory),
                        'inventory_is_externally_authenticated': False}
        else:
            coverage = {'inventory_count': None, 'has_decision_receipt': len(unique),
                        'missing_decision_receipt': None,
                        'inventory_is_externally_authenticated': False}
        result.update(chain={'ok': True, 'rows': chain['rows'], 'head_hash': chain['head_hash']},
                      metrics={'event_types': dict(sorted(kind_counts.items())),
                               'unique_decision_receipts': len(unique),
                               'duplicate_decision_ids': sum(n-1 for n in decisions.values() if n > 1),
                               'incomplete_decision_execution_chains': orphan_decisions,
                               'reported_boots': len(boots),
                               'events_without_boot_claim': missing_boot_claims,
                               'boot_event_counts': dict(sorted(boots.items()))},
                      coverage=coverage)
        if decision_id is not None and (not isinstance(decision_id,str) or not decision_id):
            return {**result, **_fail('INVALID_DECISION_ID')}
        if decision_id is not None and decisions[decision_id] != 1:
            return {**result, **_fail('DECISION_RECEIPT_MISSING_OR_DUPLICATE', 'MISSING_RECEIPT')}
        if not bundle or not pinned_public_key or not trust_policy:
            return {**result, **_fail('EXTERNAL_ATTESTATION_INPUTS_UNAVAILABLE')}
        # Revocation is enforced before any freshness or success classification.
        fingerprint = hashlib.sha256(pinned_public_key).hexdigest()
        if fingerprint in trust_policy.get('revoked_key_fingerprints', []):
            return {**result, **_fail('SIGNING_KEY_REVOKED', 'REVOKED_KEY')}
        if fingerprint not in trust_policy.get('allowed_key_fingerprints', []):
            return {**result, **_fail('SIGNING_KEY_NOT_PINNED')}
        if bundle.get('environment') != 'ISOLATED_STAGING' or trust_policy.get('environment') != 'ISOLATED_STAGING':
            return {**result, **_fail('NON_STAGING_ATTESTATION_REFUSED')}
        statements = bundle.get('statements')
        if not isinstance(statements,list) or len(statements) != 3:
            return {**result, **_fail('ATTESTATION_STATEMENTS_INCOMPLETE')}
        bodies = [_verify_signature(x,pinned_public_key) for x in statements]
        if sorted(b['kind'] for b in bodies) != ['BOOT','CHECKPOINT','DEPLOY']:
            return {**result, **_fail('ATTESTATION_STATEMENT_TYPES_INVALID')}
        cp = next(b for b in bodies if b['kind'] == 'CHECKPOINT')
        if cp.get('head_hash') != chain['head_hash'] or cp.get('sequence') != chain['rows']:
            return {**result, **_fail('CHECKPOINT_DOES_NOT_MATCH_LEDGER')}
        # Never treat independently unverified checkpoint data as a freshness fact.
        cp_at = _time(cp['captured_at'])
        age = (now - cp_at).total_seconds()
        result['checkpoint'] = {'age_seconds': age, 'maximum_age_seconds': max_checkpoint_age_seconds,
                                'signature_valid': True, 'externally_collected': False}
        if age < 0 or age > max_checkpoint_age_seconds:
            return {**result, **_fail('CHECKPOINT_OUTSIDE_FRESHNESS_WINDOW', 'STALE_CHECKPOINT')}
        if decision_id is None:
            return {**result, **_fail('DECISION_ID_REQUIRED_FOR_ATTESTATION')}
        verdict = verify_staging_bundle(audit_copy=target, bundle=bundle,
                                         pinned_public_key=pinned_public_key,
                                         trust_policy=trust_policy, decision_id=decision_id,
                                         as_of=now.isoformat())
        if not verdict.get('ok'):
            return {**result, **_fail(verdict.get('reason','ATTESTATION_REJECTED'))}
        return {**result, 'ok': True, 'status': 'STAGING_CORROBORATED_OPERATOR_FACTS',
                'reason': 'STAGING_ONLY_NOT_REAL_WORLD_AUTHENTICATION',
                'decision_id': decision_id,
                'gamma_execution_id': verdict.get('gamma_execution_id')}
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error, ImportError, Exception) as exc:
        return {**result, **_fail('OPERATIONAL_CHECK_ERROR_' + type(exc).__name__)}
