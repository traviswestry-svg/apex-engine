"""Phase 4B research: restricted, externally supplied collector-envelope signer.

Staging-only. Does not authenticate scanner boot/PID, operate KMS, retain a
production anti-replay register, or grant production/evidence promotion.
Signer private keys are injected by the external caller, never loaded from APEX.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import re
from typing import Any, Callable, Mapping
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.exceptions import InvalidSignature
<<<<<<< Updated upstream
from .forward_provenance_render_observer import ObservationError, canonical, utc_time as observer_utc_time
=======
from .forward_provenance_render_observer import canonical, utc_time
>>>>>>> Stashed changes

COLLECTOR_DOMAIN = 'APEX_PHASE4B_COLLECTOR_OBSERVATION_V1'
SIGNER_DOMAIN = 'APEX_PHASE4B_DEPLOYMENT_ATTESTATION_V1'
HEX64 = re.compile(r'^[0-9a-f]{64}$')
KEY_ID = re.compile(r'^[a-zA-Z0-9_.-]{3,80}$')

class SignerRefusal(ValueError):
    pass


<<<<<<< Updated upstream
def utc_time(value: Any) -> str:
    try:
        return observer_utc_time(value)
    except ObservationError as exc:
        raise SignerRefusal(str(exc)) from None


=======
>>>>>>> Stashed changes
def _refuse(reason: str):
    raise SignerRefusal(reason)


def _key_from_policy(policy: Mapping[str, Any], key_id: str, role: str, at: str) -> bytes:
    if not KEY_ID.fullmatch(str(key_id)):
        _refuse('INVALID_KEY_ID')
    if policy.get('environment') != 'ISOLATED_STAGING':
        _refuse('PRODUCTION_SIGNING_NOT_SUPPORTED')
    item = (policy.get('keys') or {}).get(key_id)
    if not isinstance(item, dict) or item.get('role') != role:
        _refuse('UNPINNED_KEY')
    if item.get('revoked') is True or key_id in policy.get('revoked_key_ids', []):
        _refuse('REVOKED_KEY')
    try:
        if not (utc_time(item['valid_from']) <= at < utc_time(item['valid_until'])):
            _refuse('KEY_OUTSIDE_VALIDITY')
        raw = base64.b64decode(item['public_key_b64'], validate=True)
        if len(raw) != 32:
            _refuse('INVALID_PUBLIC_KEY')
        return raw
    except (KeyError, ValueError, TypeError) as exc:
        if isinstance(exc, SignerRefusal):
            raise
        _refuse('INVALID_TRUST_POLICY')


def _verify(public_key: bytes, body: dict, signature_b64: str):
    try:
        signature = base64.b64decode(signature_b64, validate=True)
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, canonical(body))
    except (InvalidSignature, ValueError, TypeError):
        _refuse('INVALID_SIGNATURE')


def _capture_observation(envelope: Mapping[str, Any], policy: Mapping[str, Any], as_of: str):
    if not isinstance(envelope, Mapping) or set(envelope) != {'body', 'signature'}:
        _refuse('INVALID_COLLECTOR_ENVELOPE')
    body = envelope['body']
    if not isinstance(body, dict) or set(body) != {
        'domain', 'collector_key_id', 'observation', 'nonce', 'collected_at_utc'
    } or body['domain'] != COLLECTOR_DOMAIN:
        _refuse('INVALID_COLLECTOR_BODY')
    nonce = body['nonce']
    if not isinstance(nonce, str) or not HEX64.fullmatch(nonce):
        _refuse('INVALID_NONCE')
    try:
        captured = utc_time(body['collected_at_utc'])
        public_key = _key_from_policy(policy, body['collector_key_id'], 'collector', captured)
        _verify(public_key, body, envelope['signature'])
        observation = body['observation']
        if not isinstance(observation, dict) or observation.get('phase') != '4A' or observation.get('capture_mode') != 'RENDER_API_READ_ONLY_RESPONSE' or observation.get('ok') is not True:
            _refuse('NOT_LIVE_COLLECTOR_OBSERVATION')
        evidence = observation.get('evidence')
        if not isinstance(evidence, dict) or observation.get('sha256_evidence') != hashlib.sha256(canonical(evidence)).hexdigest():
            _refuse('OBSERVATION_HASH_MISMATCH')
        if evidence.get('provider_deployment_observation') != 'SINGLE_LIVE_DEPLOY_OBSERVED' or len(evidence.get('live_deploy_ids', [])) != 1:
            _refuse('AMBIGUOUS_DEPLOYMENT')
        matches = [d for d in evidence.get('deploys', []) if d.get('deploy_id') == evidence['live_deploy_ids'][0] and d.get('status') == 'live']
        if len(matches) != 1 or not re.fullmatch(r'[0-9a-f]{40}', str(matches[0].get('commit_sha') or '')):
            _refuse('MISSING_LIVE_DEPLOY_SHA')
        if evidence.get('process_boot_id') is not None or evidence.get('process_pid') is not None or evidence.get('independent_runtime_authentication') != 'NOT_ESTABLISHED':
            _refuse('FORBIDDEN_PROCESS_ATTESTATION')
        if observation.get('production_activation_authorized') is not False or observation.get('promotion_authority') != 'NONE':
            _refuse('FORBIDDEN_ACTIVATION_CLAIM')
        if utc_time(evidence['observed_at_utc']) != captured:
            _refuse('OBSERVATION_CAPTURE_MISMATCH')
        now = dt.datetime.fromisoformat(utc_time(as_of))
        when = dt.datetime.fromisoformat(captured)
        if not (dt.timedelta(0) <= now - when <= dt.timedelta(minutes=10)):
            _refuse('STALE_OR_FUTURE_OBSERVATION')
        return body, matches[0], evidence
    except SignerRefusal:
        raise
    except (ValueError, TypeError, KeyError, AttributeError):
        _refuse('INVALID_OBSERVATION')


def issue_staging_deployment_attestation(*, envelope: Mapping[str, Any], policy: Mapping[str, Any],
                                          signer_key_id: str, signer: Any, as_of: str,
                                          reserve_nonce: Callable[[str], bool]) -> dict:
    """Sign only deployment observation from *signed* collector data.

    reserve_nonce must be independently owned, atomic, and reject repeats.
    This demo's ephemeral reserve is NOT durable replay protection. Never
    invoke with production key custody or interpret as runtime authentication.
    """
    now = utc_time(as_of)
    collector_body, live, evidence = _capture_observation(envelope, policy, now)
    key = _key_from_policy(policy, signer_key_id, 'signer', now)
    from cryptography.hazmat.primitives import serialization
    try:
        presented = signer.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw)
    except (AttributeError, ValueError, TypeError):
        _refuse('SIGNER_KEY_UNAVAILABLE')
    if presented != key:
        _refuse('SIGNER_KEY_MISMATCH')
    nonce = collector_body['nonce']
    if not callable(reserve_nonce) or reserve_nonce(nonce) is not True:
        _refuse('REPLAY_OR_NO_ATOMIC_RESERVATION')
    body = {
        'domain': SIGNER_DOMAIN, 'schema': '4B.1', 'environment': 'ISOLATED_STAGING',
        'kind': 'DEPLOYMENT_OBSERVATION_ONLY',
        'collector_key_id': collector_body['collector_key_id'],
        'signer_key_id': signer_key_id,
        'collector_observation_sha256': hashlib.sha256(canonical(envelope)).hexdigest(),
        'nonce': nonce, 'signed_at_utc': now,
        'service_id': evidence['service_id'],
        'deploy_id': live['deploy_id'], 'commit_sha': live['commit_sha'],
        'process_identity': 'NOT_OBSERVED', 'runtime_authentication': 'NOT_ESTABLISHED',
        'checkpoint': 'NOT_IMPLEMENTED', 'production_activation_authorized': False,
        'promotion_authority': 'NONE', 'historical_3569_population': 'EXCLUDED',
    }
    return {'body': body, 'signature': base64.b64encode(signer.sign(canonical(body))).decode('ascii'),
            'authentication': 'STAGING_COLLECTOR_SIGNATURE_CORROBORATION_ONLY', 'verdict': 'NO_GO'}


def verify_staging_attestation(*, envelope: Mapping[str, Any], attestation: Mapping[str, Any],
                                policy: Mapping[str, Any], as_of: str) -> dict:
    fail = lambda code: {'ok': False, 'status': 'UNVERIFIED', 'reason': code, 'verdict': 'NO_GO'}
    try:
        now = utc_time(as_of)
        collector_body, live, evidence = _capture_observation(envelope, policy, now)
        if not isinstance(attestation, dict) or set(attestation) != {'body', 'signature', 'authentication', 'verdict'}:
            _refuse('INVALID_ATTESTATION')
        body = attestation['body']
        if not isinstance(body, dict) or body.get('domain') != SIGNER_DOMAIN or body.get('schema') != '4B.1' or body.get('kind') != 'DEPLOYMENT_OBSERVATION_ONLY':
            _refuse('INVALID_ATTESTATION_BODY')
        signer_key = _key_from_policy(policy, body.get('signer_key_id'), 'signer', body.get('signed_at_utc', ''))
        _verify(signer_key, body, attestation['signature'])
        if body.get('environment') != 'ISOLATED_STAGING' or attestation.get('authentication') != 'STAGING_COLLECTOR_SIGNATURE_CORROBORATION_ONLY' or attestation.get('verdict') != 'NO_GO':
            _refuse('UNAUTHORIZED_CONTEXT')
        expected = {
            'collector_key_id': collector_body['collector_key_id'],
            'collector_observation_sha256': hashlib.sha256(canonical(envelope)).hexdigest(),
            'nonce': collector_body['nonce'], 'service_id': evidence['service_id'],
            'deploy_id': live['deploy_id'], 'commit_sha': live['commit_sha'],
            'process_identity': 'NOT_OBSERVED', 'runtime_authentication': 'NOT_ESTABLISHED',
            'checkpoint': 'NOT_IMPLEMENTED', 'production_activation_authorized': False,
            'promotion_authority': 'NONE', 'historical_3569_population': 'EXCLUDED'
        }
        if any(body.get(k) != v for k, v in expected.items()) or set(body) != set(expected) | {
            'domain','schema','environment','kind','signer_key_id','signed_at_utc'}:
            _refuse('ATTESTATION_FACT_MISMATCH')
        stamp = dt.datetime.fromisoformat(utc_time(body['signed_at_utc']))
        if not (dt.timedelta(0) <= dt.datetime.fromisoformat(now) - stamp <= dt.timedelta(minutes=10)):
            _refuse('STALE_SIGNATURE')
        return {'ok': True, 'status': 'STAGING_DEPLOYMENT_OBSERVATION_CORROBORATED',
                'authentication': 'NOT_REAL_WORLD_PROCESS_AUTHENTICATION',
                'promotion_authority': 'NONE', 'verdict': 'NO_GO'}
    except SignerRefusal as e:
        return fail(str(e))
    except (KeyError, ValueError, TypeError, AttributeError):
        return fail('INVALID_INPUT')
