"""Phase 4A: restricted read-only Render API observer.

Observations are NOT signed attestations. A Render deployment is NOT proof of
scanner PID/boot or that a specific decision was produced by that process.
Only allow GETs to explicit Render API endpoints and refuse malformed data.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Mapping

API_ORIGIN = 'https://api.render.com'
HEX40 = re.compile(r'^[0-9a-fA-F]{40}$')
SERVICE = re.compile(r'^srv-[a-zA-Z0-9]+$')
DEPLOY = re.compile(r'^dep-[a-zA-Z0-9]+$')

class ObservationError(Exception):
    """Explicit fail-closed status without secrets or raw HTTP bodies."""


def canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('utf-8')


def utc_time(text: Any) -> str:
    if not isinstance(text, str):
        raise ObservationError('INVALID_TIMESTAMP')
    try:
        value = dt.datetime.fromisoformat(text.replace('Z', '+00:00'))
    except ValueError:
        raise ObservationError('INVALID_TIMESTAMP') from None
    if value.tzinfo is None:
        raise ObservationError('NAIVE_TIMESTAMP')
    return value.astimezone(dt.timezone.utc).isoformat()


def sanitize_deploy(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict) or not DEPLOY.fullmatch(str(data.get('id', ''))):
        raise ObservationError('INVALID_DEPLOY_ID')
    status = data.get('status')
    if not isinstance(status, str) or status not in {
        'created','queued','build_in_progress','update_in_progress','live',
        'deactivated','build_failed','update_failed','canceled',
        'pre_deploy_in_progress','pre_deploy_failed'
    }:
        raise ObservationError('INVALID_DEPLOY_STATUS')
    commit = data.get('commit')
    if commit is not None and (not isinstance(commit, dict) or not HEX40.fullmatch(str(commit.get('id', '')))):
        raise ObservationError('INVALID_COMMIT_SHA')
    record = {
        'deploy_id': data['id'],
        'status': status,
        'commit_sha': commit['id'].lower() if commit else None,
        'trigger': data.get('trigger') if isinstance(data.get('trigger'), str) else None,
        'created_at_utc': utc_time(data.get('createdAt')),
    }
    for source_key, target in [('startedAt','started_at_utc'),('finishedAt','finished_at_utc')]:
        record[target] = utc_time(data[source_key]) if data.get(source_key) else None
    if record['finished_at_utc'] and record['finished_at_utc'] < record['created_at_utc']:
        raise ObservationError('IMPOSSIBLE_DEPLOY_CHRONOLOGY')
    return record


def render_http_get(token: str) -> Callable[[str, Mapping[str,str]], Any]:
    if not isinstance(token, str) or len(token.strip()) < 8 or '\n' in token or '\r' in token:
        raise ObservationError('MISSING_API_CREDENTIAL')
    def get(path: str, params: Mapping[str, str]) -> Any:
        # Only these GET paths are permitted. Never permit caller-supplied URLs.
        if not re.fullmatch(r'/v1/services/srv-[A-Za-z0-9]+(?:/deploys)?', path):
            raise ObservationError('UNAPPROVED_ENDPOINT')
        query = urllib.parse.urlencode(params)
        url = API_ORIGIN + path + (('?' + query) if query else '')
        request = urllib.request.Request(url, headers={
            'Authorization':'Bearer ' + token,
            'Accept':'application/json',
            'User-Agent':'APEX-independent-Render-observer/4A',
        }, method='GET')
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                if response.status != 200:
                    raise ObservationError('HTTP_NON_200')
                raw = response.read(2_000_001)
                if len(raw) > 2_000_000:
                    raise ObservationError('RESPONSE_TOO_LARGE')
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            # Do not reveal API error bodies or credentials.
            raise ObservationError('RENDER_HTTP_' + str(e.code)) from None
        except (urllib.error.URLError, TimeoutError):
            raise ObservationError('RENDER_TRANSPORT_FAILURE') from None
        except (ValueError, UnicodeDecodeError):
            raise ObservationError('INVALID_JSON_RESPONSE') from None
    return get


def collect(service_id: str, get: Callable[[str, Mapping[str,str]], Any],
            *, observed_at: str | None = None, max_pages: int = 10) -> dict[str, Any]:
    """Collect and normalize provider responses without verifying local runtime.

    GET injected for offline fixture tests or live authenticated Render API.
    Caller must make fixture provenance explicit in output.
    """
    if not SERVICE.fullmatch(str(service_id)):
        raise ObservationError('INVALID_SERVICE_ID')
    if not 1 <= max_pages <= 100:
        raise ObservationError('INVALID_PAGE_LIMIT')
    now = utc_time(observed_at or dt.datetime.now(dt.timezone.utc).isoformat())
    base = '/v1/services/' + service_id
    service = get(base, {})
    if not isinstance(service, dict) or service.get('id') != service_id:
        raise ObservationError('SERVICE_ID_MISMATCH')
    result: list[dict[str, Any]] = []
    seen_deploys: set[str] = set()
    seen_cursors: set[str] = set()
    cursor: str | None = None
    complete = False
    for page in range(max_pages):
        params = {'limit':'100'}
        if cursor is not None:
            params['cursor'] = cursor
        records = get(base + '/deploys', params)
        if not isinstance(records, list) or len(records) > 100:
            raise ObservationError('INVALID_DEPLOY_PAGE')
        if not records:
            complete = True
            break
        for entry in records:
            if not isinstance(entry, dict) or not isinstance(entry.get('deploy'), dict):
                raise ObservationError('INVALID_DEPLOY_WRAPPER')
            dep = sanitize_deploy(entry['deploy'])
            if dep['deploy_id'] in seen_deploys:
                raise ObservationError('DUPLICATE_DEPLOY')
            seen_deploys.add(dep['deploy_id'])
            result.append(dep)
        tail = records[-1].get('cursor')
        if len(records) < 100 and not tail:
            complete = True
            break
        if not isinstance(tail, str) or not tail or len(tail) > 1024 or tail in seen_cursors:
            raise ObservationError('MISSING_OR_REPEATED_CURSOR')
        seen_cursors.add(tail)
        cursor = tail
    if not complete:
        raise ObservationError('PAGINATION_INCOMPLETE')
    live = [x for x in result if x['status'] == 'live']
    # Do not guess which deployment was current if none/many are marked live.
    assessment = 'SINGLE_LIVE_DEPLOY_OBSERVED' if len(live) == 1 else 'LIVE_DEPLOY_AMBIGUOUS'
    evidence = {
        'schema_version': '4A.1',
        'service_id': service_id,
        'service_type': service.get('type') if isinstance(service.get('type'), str) else None,
        'observed_at_utc': now,
        'deploys': sorted(result, key=lambda x: (x['created_at_utc'], x['deploy_id'])),
        'deploy_records_count': len(result),
        'live_deploy_ids': [x['deploy_id'] for x in live],
        'provider_deployment_observation': assessment,
        'process_boot_id': None,
        'process_pid': None,
        'process_identity': 'NOT_INDEPENDENTLY_OBSERVED',
        'off_host_signature': 'NOT_IMPLEMENTED',
        'checkpoint': 'NOT_IMPLEMENTED',
        'independent_runtime_authentication': 'NOT_ESTABLISHED',
        'production_activation_authorized': False,
        'promotion_authority': 'NONE',
        'historical_3569_population': 'EXCLUDED',
    }
    return {
        'ok': True,
        'phase': '4A',
        'evidence': evidence,
        'sha256_evidence': hashlib.sha256(canonical(evidence)).hexdigest(),
        'verdict': 'NO_GO',
    }
