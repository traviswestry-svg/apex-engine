"""Phase 4D external-evidence rehearsal verifier, read-only and fail-closed.

Research-only. Validates staging 4A/4B signatures, 4C checkpoint content,
and an independently pinned *synthetic* anchor signature. This cannot establish
actual collector independence, managed key custody, external WORM retention,
scanner-process origin or production authorization. Never returns VERIFIED/GO.
"""
from __future__ import annotations
import base64
import datetime as dt
import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from .forward_provenance_signer import verify_staging_attestation
from .forward_provenance_checkpoint_store import sha, canonical, DOMAIN, _time

ANCHOR_DOMAIN = 'APEX_PHASE4D_INDEPENDENT_ANCHOR_REHEARSAL_V1'
HEX64 = re.compile(r'^[0-9a-f]{64}$')


def _fail(reason: str, *, status: str = 'UNVERIFIED') -> dict:
    return {'phase':'4D','ok':False,'status':status,'reason':reason,
            'authentication':'NOT_REAL_WORLD_AUTHENTICATION',
            'runtime_process_authentication':'NOT_ESTABLISHED',
            'production_activation_authorized':False,'promotion_authority':'NONE',
            'historical_3569_population':'EXCLUDED','verdict':'NO_GO'}


def _check_anchor(anchor: Mapping[str, Any], policy: Mapping[str, Any], *, as_of: str) -> dict:
    if not isinstance(anchor, dict) or set(anchor) != {'body','signature'}:
        raise ValueError('INVALID_ANCHOR_ENVELOPE')
    body = anchor['body']
    required = {'domain','environment','anchor_key_id','service_id','checkpoint_count',
                'checkpoint_head_sha256','attestation_sha256','anchored_at_utc',
                'external_store_identity','retention_mode','runtime_authentication'}
    if not isinstance(body, dict) or set(body) != required:
        raise ValueError('INVALID_ANCHOR_BODY')
    if body['domain'] != ANCHOR_DOMAIN or body['environment'] != 'ISOLATED_STAGING' or body['runtime_authentication'] != 'NOT_ESTABLISHED':
        raise ValueError('UNAUTHORIZED_ANCHOR_DOMAIN')
    if body['retention_mode'] != 'STAGING_SIMULATION_NOT_WORM' or body['external_store_identity'] != 'SYNTHETIC_OPERATOR_SUPPLIED':
        raise ValueError('UNSUPPORTED_REAL_WORLD_ANCHOR_CLAIM')
    if not isinstance(body['checkpoint_count'],int) or isinstance(body['checkpoint_count'],bool) or body['checkpoint_count'] < 1:
        raise ValueError('INVALID_ANCHOR_COUNT')
    if not isinstance(body['checkpoint_head_sha256'],str) or not HEX64.fullmatch(body['checkpoint_head_sha256']):
        raise ValueError('INVALID_ANCHOR_HEAD')
    if not isinstance(body['attestation_sha256'],str) or not HEX64.fullmatch(body['attestation_sha256']):
        raise ValueError('INVALID_ATTESTATION_DIGEST')
    at = dt.datetime.fromisoformat(_time(as_of))
    when = dt.datetime.fromisoformat(_time(body['anchored_at_utc']))
    if not dt.timedelta(0) <= (at-when) <= dt.timedelta(minutes=10):
        raise ValueError('ANCHOR_STALE_OR_FUTURE')
    if not isinstance(policy,dict) or policy.get('environment') != 'ISOLATED_STAGING':
        raise ValueError('UNTRUSTED_ANCHOR_POLICY')
    key_id = body['anchor_key_id']
    keys = policy.get('keys',{})
    item = keys.get(key_id) if isinstance(keys,dict) and isinstance(key_id,str) else None
    if not isinstance(item,dict) or item.get('role') != 'anchor':
        raise ValueError('UNPINNED_ANCHOR_KEY')
    if item.get('revoked') is True or key_id in policy.get('revoked_key_ids',[]):
        raise ValueError('REVOKED_ANCHOR_KEY')
    if not (dt.datetime.fromisoformat(_time(item['valid_from'])) <= when < dt.datetime.fromisoformat(_time(item['valid_until']))):
        raise ValueError('ANCHOR_KEY_EXPIRED')
    raw = base64.b64decode(item['public_key_b64'],validate=True)
    if len(raw) != 32:
        raise ValueError('INVALID_ANCHOR_KEY')
    collector_keys = {k for k,v in keys.items() if isinstance(v,dict) and v.get('role') in ('collector','signer')}
    if key_id in collector_keys:
        raise ValueError('ANCHOR_NOT_SEPARATE')
    signature = base64.b64decode(anchor['signature'],validate=True)
    Ed25519PublicKey.from_public_bytes(raw).verify(signature,canonical(body))
    return body


def _checkpoint_readonly(path: str|Path) -> dict:
    target = Path(path).absolute()
    if (str(target).startswith(('/data/','/audit-copy/')) or target.is_symlink() or
        not target.is_file() or target.stat().st_size < 1):
        raise ValueError('UNSAFE_OR_MISSING_AUDIT_COPY')
    # 'mode=ro' plus query_only: never initializes, vacuums, or updates evidence.
    con = sqlite3.connect(target.as_uri() + '?mode=ro', uri=True, timeout=3)
    try:
        con.execute('PRAGMA query_only=ON')
        con.execute('BEGIN')
        rows = con.execute('SELECT seq, checkpoint_id, nonce, predecessor_sha256, attestation_sha256, checkpoint_sha256, created_at_utc, record_json FROM checkpoints ORDER BY seq').fetchall()
        reservations = {r[0] for r in con.execute('SELECT nonce FROM nonce_reservations').fetchall()}
    finally:
        con.close()
    previous = '0'*64
    used = set()
    for number, (seq, cid, nonce, predecessor, att_digest, head, stamp, raw) in enumerate(rows,1):
        record = json.loads(raw)
        if (seq != number or cid != f'checkpoint-{number:012d}' or nonce in used or nonce not in reservations
            or predecessor != previous or record.get('domain') != DOMAIN or record.get('schema') != '4C.1'
            or record.get('environment') != 'ISOLATED_STAGING' or record.get('seq') != seq
            or record.get('nonce') != nonce or record.get('predecessor_sha256') != predecessor
            or record.get('attestation_sha256') != att_digest or record.get('created_at_utc') != stamp
            or record.get('runtime_authentication') != 'NOT_ESTABLISHED'
            or record.get('production_activation_authorized') is not False or record.get('promotion_authority') != 'NONE'
            or sha(record) != head or not isinstance(att_digest,str) or not HEX64.fullmatch(att_digest)):
            raise ValueError('CHAIN_INTEGRITY_FAILURE')
        previous = head
        used.add(nonce)
    return {'count':len(rows),'head':previous,'tail_attestation_sha256':rows[-1][4] if rows else None,
            'tail_nonce':rows[-1][2] if rows else None, 'orphan_reservations':len(reservations-used)}


def verify_phase4d(*, observer_envelope:Mapping[str,Any], signer_attestation:Mapping[str,Any],
                    trust_policy:Mapping[str,Any], signed_anchor:Mapping[str,Any],
                    checkpoint_copy:str|Path, as_of_utc:str, process_evidence:Any=None) -> dict:
    """Verify evidence from *disposable staging audit copy* without mutation.

    Process evidence is purposely not accepted: Phase 4A-C have no supervised
    independently verified process-origin protocol. Caller-supplied facts do
    not become authentication. Likewise, a signature is not an external audit.
    """
    try:
        _time(as_of_utc)
        if process_evidence is not None:
            return _fail('INDEPENDENT_PROCESS_ATTESTATION_PROTOCOL_NOT_IMPLEMENTED')
        verified = verify_staging_attestation(envelope=observer_envelope,
                                              attestation=signer_attestation,
                                              policy=trust_policy,as_of=as_of_utc)
        if verified.get('ok') is not True:
            return _fail('DEPLOYMENT_ATTESTATION_' + str(verified.get('reason','UNVERIFIED')))
        body = _check_anchor(signed_anchor,trust_policy,as_of=as_of_utc)
        chain = _checkpoint_readonly(checkpoint_copy)
        att_body = signer_attestation['body']
        expected = sha(signer_attestation)
        if chain['count'] != body['checkpoint_count'] or chain['head'] != body['checkpoint_head_sha256']:
            return _fail('SIGNED_ANCHOR_CHECKPOINT_MISMATCH',status='CHAIN_INTEGRITY_FAILURE')
        if (chain['tail_attestation_sha256'] != expected or body['attestation_sha256'] != expected
            or chain['tail_nonce'] != att_body['nonce'] or body['service_id'] != att_body['service_id']):
            return _fail('ATTESTATION_CHAIN_BINDING_MISMATCH')
        return {'phase':'4D','ok':True,'status':'STAGING_CORROBORATED_NO_PROCESS_ATTESTATION',
                'authentication':'STAGING_SIGNATURE_AND_CHECKPOINT_CONSISTENCY_ONLY',
                'runtime_process_authentication':'NOT_ESTABLISHED',
                'checkpoint_count':chain['count'],'checkpoint_head_sha256':chain['head'],
                'uncheckpointed_reservations':chain['orphan_reservations'],
                'independent_storage_and_key_custody':'NOT_ESTABLISHED',
                'production_activation_authorized':False,'promotion_authority':'NONE',
                'historical_3569_population':'EXCLUDED','verdict':'NO_GO'}
    except (ValueError,TypeError,KeyError,AttributeError,sqlite3.Error,InvalidSignature,OverflowError) as exc:
        if isinstance(exc,InvalidSignature):
            reason = 'INVALID_ANCHOR_SIGNATURE'
        elif isinstance(exc,sqlite3.Error):
            reason = 'UNREADABLE_CHECKPOINT_COPY'
        else:
            reason = str(exc) if str(exc) in {
                'INVALID_ANCHOR_ENVELOPE','INVALID_ANCHOR_BODY','UNAUTHORIZED_ANCHOR_DOMAIN',
                'UNSUPPORTED_REAL_WORLD_ANCHOR_CLAIM','INVALID_ANCHOR_COUNT','INVALID_ANCHOR_HEAD',
                'INVALID_ATTESTATION_DIGEST','ANCHOR_STALE_OR_FUTURE','UNTRUSTED_ANCHOR_POLICY',
                'UNPINNED_ANCHOR_KEY','REVOKED_ANCHOR_KEY','ANCHOR_KEY_EXPIRED',
                'INVALID_ANCHOR_KEY','ANCHOR_NOT_SEPARATE','UNSAFE_OR_MISSING_AUDIT_COPY',
                'CHAIN_INTEGRITY_FAILURE'} else 'INVALID_OR_UNVERIFIED_EVIDENCE'
        return _fail(reason,status='CHAIN_INTEGRITY_FAILURE' if reason == 'CHAIN_INTEGRITY_FAILURE' else 'UNVERIFIED')
