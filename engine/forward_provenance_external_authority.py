"""Phase 3C: independently operated, staging-only offline checkpoint authority.

This module MUST NOT run in an APEX runtime process or use runtime supplied
claims as its own observation. Deployment and boot facts MUST be independently
obtained and operator-reviewed. This module validates a supplied evidence
record's structure and signs it, but cannot prove the observer's honesty.

No production deployment, network fetch, key generation, or evidence promotion.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Mapping

from .forward_provenance import _canonical, verify_chain
from .forward_provenance_verifier import DOMAIN

FACT_DOMAINS = {'RENDER_API_DEPLOY_RECORD', 'EXTERNAL_SUPERVISOR_BOOT_RECORD'}


def _time(value: str) -> dt.datetime:
    x = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if x.tzinfo is None:
        raise ValueError('naive timestamp')
    return x.astimezone(dt.timezone.utc)


def _statement(body: dict, private_key: Any) -> dict:
    sig = private_key.sign(_canonical(body).encode('ascii'))
    return {'body': body, 'signature': base64.b64encode(sig).decode('ascii')}


def read_ledger_head(copy_path: str | Path) -> dict:
    """Only from a transaction-consistent, off-host SQLite audit copy."""
    path = Path(copy_path).resolve(strict=True)
    if not path.is_file():
        raise ValueError('audit copy must be a file')
    if str(path).startswith('/data/') or str(path).startswith('/audit-copy/'):
        raise ValueError('use separate external staging workspace, not app mount or example path')
    verdict = verify_chain(path=path)
    if not verdict.get('ok') or verdict['rows'] <= 0:
        raise ValueError('audit ledger missing, empty, or corrupt')
    return {'sequence': verdict['rows'], 'head_hash': verdict['head_hash']}


def create_staging_bundle(*, audit_copy: str | Path, observed_facts: Mapping[str, Any],
                          operator_private_key: Any, observed_at: str,
                          previous_checkpoint: Mapping[str, Any] | None = None) -> dict:
    """Signs independently *supplied* facts; staging only and never self-attests.

    `observed_facts` must be imported by the offline operator from an external
    control-plane/supervisor, not copied from the ledger or APEX env vars.
    Authenticated source collection is a separate operational requirement.
    """
    if observed_facts.get('environment') != 'ISOLATED_STAGING':
        raise ValueError('production signing is not supported by this research tool')
    deploy = dict(observed_facts.get('deployment') or {})
    boot = dict(observed_facts.get('boot') or {})
    if deploy.get('evidence_source') != 'RENDER_API_DEPLOY_RECORD':
        raise ValueError('independent deployment evidence is required')
    if boot.get('evidence_source') != 'EXTERNAL_SUPERVISOR_BOOT_RECORD':
        raise ValueError('independent supervisor observation is required')
    for section in (deploy, boot):
        for field in ('service_id', 'ledger_id', 'git_sha', 'release', 'valid_from', 'valid_until'):
            if not section.get(field):
                raise ValueError('missing external fact ' + field)
        if not _time(section['valid_from']) < _time(section['valid_until']):
            raise ValueError('bad validity interval')
    if any(boot[x] != deploy[x] for x in ('service_id', 'ledger_id', 'git_sha', 'release')):
        raise ValueError('deploy and boot facts conflict')
    if not (isinstance(boot.get('boot_id'), str) and boot['boot_id'] and
            isinstance(boot.get('pid'), int) and boot['pid'] > 0):
        raise ValueError('invalid external boot facts')
    sha = deploy['git_sha']
    if not (isinstance(sha, str) and len(sha) == 40 and
            all(c in '0123456789abcdef' for c in sha.lower())):
        raise ValueError('invalid externally observed SHA')
    captured = _time(observed_at)
    if captured < _time(boot['valid_from']):
        raise ValueError('checkpoint predates boot')
    head = read_ledger_head(audit_copy)
    if previous_checkpoint is not None:
        prev_body = previous_checkpoint['body']
        if prev_body.get('kind') != 'CHECKPOINT':
            raise ValueError('invalid previous checkpoint')
        if prev_body.get('ledger_id') != deploy['ledger_id']:
            raise ValueError('previous ledger identity mismatch')
        if head['sequence'] <= prev_body['sequence']:
            raise ValueError('non-increasing checkpoint sequence')
        if captured <= _time(prev_body['captured_at']):
            raise ValueError('non-increasing checkpoint time')
        # Pin previous signed statement bytes as a *reference*, not proof of
        # prior verification; the independent verifier must validate it.
        prev_digest = hashlib.sha256(_canonical(previous_checkpoint).encode('ascii')).hexdigest()
    else:
        prev_digest = None
    template = {'domain': DOMAIN, 'schema': 1, 'service_id': deploy['service_id'],
                'ledger_id': deploy['ledger_id']}
    d_body = {**template, 'kind': 'DEPLOY', **{k: deploy[k] for k in (
        'git_sha', 'release', 'valid_from', 'valid_until')}}
    b_body = {**template, 'kind': 'BOOT', **{k: boot[k] for k in (
        'git_sha', 'release', 'valid_from', 'valid_until', 'boot_id', 'pid')}}
    cp_body = {**template, 'kind': 'CHECKPOINT', 'captured_at': captured.isoformat(),
               **head, 'previous_checkpoint_sha256': prev_digest}
    statements = [_statement(x, operator_private_key) for x in (d_body, b_body, cp_body)]
    return {'schema': 'apex.phase3c.staging.v1', 'environment': 'ISOLATED_STAGING',
            'authentication': 'OPERATOR_SUPPLIED_FACTS_NOT_AUTONOMOUSLY_AUTHENTICATED',
            'statements': statements,
            'evidence_source_claims': {
                'deployment': deploy['evidence_source'], 'boot': boot['evidence_source']}}


def verify_staging_bundle(*, audit_copy: str | Path, bundle: Mapping[str, Any],
                          pinned_public_key: bytes, decision_id: str,
                          trust_policy: Mapping[str, Any], as_of: str) -> dict:
    """Applies local trust policy and invokes the existing no-write verifier.

    Trust policy must be supplied from independently controlled storage, not
    from the same bundle or APEX process. Revocation wins over key pinning.
    """
    from .forward_provenance_verifier import verify_external_receipts, _verify_signature
    fail = lambda reason: {'ok': False, 'status': 'UNVERIFIED', 'reason': reason}
    try:
        if bundle.get('environment') != 'ISOLATED_STAGING' or bundle.get('schema') != 'apex.phase3c.staging.v1':
            return fail('UNSUPPORTED_BUNDLE_CONTEXT')
        fingerprint = hashlib.sha256(pinned_public_key).hexdigest()
        if fingerprint in trust_policy.get('revoked_key_fingerprints', []):
            return fail('SIGNING_KEY_REVOKED')
        if fingerprint not in trust_policy.get('allowed_key_fingerprints', []):
            return fail('SIGNING_KEY_NOT_PINNED_BY_POLICY')
        if trust_policy.get('environment') != 'ISOLATED_STAGING':
            return fail('UNTRUSTED_POLICY_CONTEXT')
        if not isinstance(as_of, str) or not _time(as_of):
            return fail('NO_VERIFICATION_TIME')
        bodies = [_verify_signature(x, pinned_public_key) for x in bundle['statements']]
        cp = next(b for b in bodies if b['kind'] == 'CHECKPOINT')
        if cp.get('previous_checkpoint_sha256') is not None:
            # To authenticate a successor checkpoint the verifier must be given
            # the complete signed predecessor trail; this simple single-bundle
            # endpoint intentionally fails closed until that is provided.
            return fail('PREDECESSOR_CHECKPOINT_REQUIRED')
        result = verify_external_receipts(
            ledger_path=audit_copy, statements=bundle['statements'],
            pinned_public_key=pinned_public_key, decision_id=decision_id, as_of=as_of)
        if result.get('ok'):
            result['status'] = 'STAGING_CORROBORATED_OPERATOR_FACTS'
            result['promotion_authority'] = 'NONE'
            result['authentication'] = 'NOT_REAL_WORLD_DEPLOYMENT_AUTHENTICATION'
        return result
    except Exception as exc:
        return fail('PHASE3C_VERIFICATION_ERROR_' + type(exc).__name__)


def export_bundle_atomic(bundle: Mapping[str, Any], destination: str | Path) -> None:
    """Create-only; cannot overwrite a prior external checkpoint or attestation."""
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (_canonical(bundle) + '\n').encode('utf-8')
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
