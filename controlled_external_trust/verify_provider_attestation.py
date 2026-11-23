"""Offline P-256 AWS KMS signature verifier for deployment-only evidence.

Requires PEM obtained and pinned OUTSIDE the collection/signing environment.
Never authenticates scanner/gamma/decision producer identity or returns GO.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
import re
from pathlib import Path
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def verify(observation, envelope, trusted_public_key_pem, *, expected_service_id, expected_kms_key_arn):
    try:
        statement = envelope['statement']
        if envelope['algorithm'] != 'ECDSA_SHA_256':
            raise ValueError('UNSUPPORTED_ALGORITHM')
        if statement['scope'] != 'PROVIDER_DEPLOYMENT_ONLY' or observation['scope'] != 'RENDER_DEPLOYMENT_ONLY':
            raise ValueError('BAD_SCOPE')
        if statement['service_id'] != expected_service_id or observation['service_id'] != expected_service_id:
            raise ValueError('SERVICE_MISMATCH')
        if statement['kms_key_arn'] != expected_kms_key_arn:
            raise ValueError('KMS_KEY_IDENTITY_MISMATCH')
        if statement['deploy_id'] != observation['deploy_id'] or statement['commit_sha'] != observation['commit_sha']:
            raise ValueError('DEPLOYMENT_BINDING_MISMATCH')
        if statement['observation_sha256'] != hashlib.sha256(canonical(observation)).hexdigest():
            raise ValueError('DIGEST_MISMATCH')
        if statement.get('process_identity') != 'NOT_AUTHENTICATED' or observation.get('process_boot_id') is not None or observation.get('process_pid') is not None:
            raise ValueError('PROCESS_CLAIM_NOT_ALLOWED')
        if statement.get('production_activation_authorized') is not False or observation.get('production_activation_authorized') is not False:
            raise ValueError('UNAUTHORIZED_PROMOTION_CLAIM')
        if not re.fullmatch('[a-f0-9]{40}', observation['commit_sha']):
            raise ValueError('INVALID_SHA')
        key = serialization.load_pem_public_key(trusted_public_key_pem)
        if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, ec.SECP256R1):
            raise ValueError('WRONG_PUBLIC_KEY_TYPE')
        key.verify(base64.b64decode(envelope['signature_b64'], validate=True),canonical(statement),ec.ECDSA(hashes.SHA256()))
        return {'ok':True, 'scope':'SIGNED_DEPLOYMENT_OBSERVATION_ONLY',
                'process_identity':'NOT_AUTHENTICATED', 'production_activation_authorized':False,
                'verdict':'NO_GO'}
    except (KeyError, TypeError, ValueError, InvalidSignature) as err:
        return {'ok':False,'reason':type(err).__name__,'scope':'UNVERIFIED',
                'production_activation_authorized':False,'verdict':'NO_GO'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--observation',required=True)
    p.add_argument('--attestation',required=True)
    p.add_argument('--pinned-public-key',required=True)
    p.add_argument('--service-id',required=True)
    p.add_argument('--kms-key-arn',required=True)
    args=p.parse_args()
    result=verify(json.loads(Path(args.observation).read_text()),json.loads(Path(args.attestation).read_text()),
                  Path(args.pinned_public_key).read_bytes(), expected_service_id=args.service_id,
                  expected_kms_key_arn=args.kms_key_arn)
    print(json.dumps(result,indent=2,sort_keys=True))
    return 0 if result['ok'] else 2
if __name__=='__main__':raise SystemExit(main())
