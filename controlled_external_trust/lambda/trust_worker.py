"""APEX external-trust research deployment: two Lambda entrypoints.

NOT a production-authentication authority: signs provider deployment facts only,
never a scanner boot/PID, gamma execution, or historical decision.
"""
from __future__ import annotations
import base64
import datetime as dt
import hashlib
import json
import os
import re
from .render_observer import canonical, collect, render_http_get

SERVICE_PATTERN = re.compile(r'^srv-[A-Za-z0-9]+$')

class TrustFailure(Exception):
    pass


def _aws(service, client=None):
    if client is not None:
        return client
    import boto3
    return boto3.client(service)


def _required_env(name):
    v = os.getenv(name, '').strip()
    if not v:
        raise TrustFailure('MISSING_CONFIGURATION_' + name)
    return v


def _get_render_token(secrets, secret_arn):
    value = secrets.get_secret_value(SecretId=secret_arn)
    if 'SecretString' not in value or not isinstance(value['SecretString'], str):
        raise TrustFailure('INVALID_RENDER_SECRET')
    token = value['SecretString'].strip()
    if len(token) < 8:
        raise TrustFailure('INVALID_RENDER_SECRET')
    return token


def _observe(service_id, token, *, now=None, get=None):
    if not SERVICE_PATTERN.fullmatch(service_id):
        raise TrustFailure('INVALID_SERVICE_ID')
    data = collect(service_id, get or render_http_get(token), observed_at=now)
    evidence = data['evidence']
    # Never accept an ambiguous live deploy, missing SHA, or process claims.
    if len(evidence['live_deploy_ids']) != 1:
        raise TrustFailure('AMBIGUOUS_LIVE_DEPLOY')
    live = [x for x in evidence['deploys'] if x['deploy_id'] == evidence['live_deploy_ids'][0]]
    if len(live) != 1 or not re.fullmatch('[a-f0-9]{40}', str(live[0]['commit_sha'])):
        raise TrustFailure('NO_VALID_DEPLOY_SHA')
    return {'schema_version':'4EXT.1', 'scope':'RENDER_DEPLOYMENT_ONLY',
            'capture_mode':'AUTHENTICATED_RENDER_API_RESPONSE_NOT_PROCESS_AUTHENTICATION',
            'service_id':service_id, 'observed_at_utc':evidence['observed_at_utc'],
            'deploy_id':live[0]['deploy_id'], 'commit_sha':live[0]['commit_sha'],
            'process_boot_id':None,'process_pid':None,
            'runtime_process_authentication':'NOT_ESTABLISHED',
            'historical_3569_population':'EXCLUDED',
            'production_activation_authorized':False,'promotion_authority':'NONE'}


def _put_immutable(s3, bucket, key, payload):
    # Conditional put blocks normal replay; S3 Object Lock must independently be enabled.
    return s3.put_object(Bucket=bucket, Key=key, Body=canonical(payload),
                         ContentType='application/json', IfNoneMatch='*',
                         ServerSideEncryption='AES256')


def observer_handler(event, context, *, clients=None, get=None):
    """Runs in an independent AWS account, not in the APEX Render process."""
    clients = clients or {}
    secrets = _aws('secretsmanager', clients.get('secretsmanager'))
    s3 = _aws('s3', clients.get('s3'))
    token = _get_render_token(secrets, _required_env('OBSERVER_RENDER_SECRET_ARN'))
    service_id = _required_env('APEX_RENDER_SERVICE_ID')
    observed = _observe(service_id, token, get=get)
    digest = hashlib.sha256(canonical(observed)).hexdigest()
    key = f'observations/{service_id}/{digest}.json'
    _put_immutable(s3, _required_env('EVIDENCE_BUCKET'), key, observed)
    return {'status':'OBSERVATION_STORED','key':key,'sha256':digest,
            'production_activation_authorized':False}


def attestor_handler(event, context, *, clients=None, get=None):
    """Independent role re-queries Render before it signs collector observations."""
    clients = clients or {}
    secrets = _aws('secretsmanager', clients.get('secretsmanager'))
    s3 = _aws('s3', clients.get('s3'))
    kms = _aws('kms', clients.get('kms'))
    bucket = _required_env('EVIDENCE_BUCKET')
    service_id = _required_env('APEX_RENDER_SERVICE_ID')
    token = _get_render_token(secrets, _required_env('ATTESTOR_RENDER_SECRET_ARN'))
    signing_key = _required_env('ATTESTATION_KMS_KEY_ARN')
    records = event.get('Records', []) if isinstance(event, dict) else []
    if len(records) != 1 or records[0].get('eventSource') != 'aws:s3':
        raise TrustFailure('INVALID_EVENT')
    rec = records[0]['s3']
    from urllib.parse import unquote_plus
    key = unquote_plus(rec['object']['key'])
    prefix = 'observations/' + service_id + '/'
    if not key.startswith(prefix) or not re.fullmatch(r'[a-f0-9]{64}\.json', key[len(prefix):]):
        raise TrustFailure('INVALID_SOURCE_KEY')
    if rec['bucket']['name'] != bucket:
        raise TrustFailure('BUCKET_MISMATCH')
    response = s3.get_object(Bucket=bucket, Key=key)
    blob = response['Body'].read(100_001)
    if len(blob) > 100_000:
        raise TrustFailure('OVERSIZED_EVIDENCE')
    evidence = json.loads(blob)
    digest = hashlib.sha256(canonical(evidence)).hexdigest()
    if key != prefix + digest + '.json' or canonical(evidence) != blob:
        raise TrustFailure('EVIDENCE_DIGEST_MISMATCH')
    if evidence.get('service_id') != service_id or evidence.get('scope') != 'RENDER_DEPLOYMENT_ONLY':
        raise TrustFailure('INVALID_EVIDENCE_SCOPE')
    if evidence.get('process_pid') is not None or evidence.get('process_boot_id') is not None:
        raise TrustFailure('UNSUPPORTED_PROCESS_CLAIM')
    observed_time = dt.datetime.fromisoformat(evidence['observed_at_utc'])
    if observed_time.tzinfo is None or abs((dt.datetime.now(dt.timezone.utc)-observed_time).total_seconds()) > 600:
        raise TrustFailure('STALE_OBSERVATION')
    # Independent provider re-query. Strictly compare deploy identity and SHA.
    actual = _observe(service_id, token, get=get)
    if (actual['deploy_id'], actual['commit_sha']) != (evidence['deploy_id'], evidence['commit_sha']):
        raise TrustFailure('PROVIDER_CORROBORATION_MISMATCH')
    statement = {'schema_version':'4EXT.1','scope':'PROVIDER_DEPLOYMENT_ONLY',
                 'observation_sha256':digest,'service_id':service_id,
                 'deploy_id':evidence['deploy_id'],'commit_sha':evidence['commit_sha'],
                 'kms_key_arn':signing_key,'process_identity':'NOT_AUTHENTICATED',
                 'production_activation_authorized':False,'promotion_authority':'NONE'}
    to_sign = canonical(statement)
    signature = kms.sign(KeyId=signing_key, Message=to_sign, MessageType='RAW',
                         SigningAlgorithm='ECDSA_SHA_256')
    if signature.get('KeyId') != signing_key:
        raise TrustFailure('KMS_KEY_MISMATCH')
    envelope = {'statement':statement, 'signature_b64':base64.b64encode(signature['Signature']).decode(),
                'algorithm':'ECDSA_SHA_256',
                'authentication':'DEPLOYMENT_CORROBORATED_NOT_SCANNER_PROCESS',
                'production_activation_authorized':False,'verdict':'NO_GO'}
    new_key = f'attestations/{service_id}/{digest}.json'
    _put_immutable(s3, bucket, new_key, envelope)
    return {'status':'SIGNED_DEPLOYMENT_ONLY','key':new_key,
            'production_activation_authorized':False,'verdict':'NO_GO'}
