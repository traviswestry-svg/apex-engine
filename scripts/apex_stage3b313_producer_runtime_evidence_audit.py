#!/usr/bin/env python3
"""APEX Stage 3B.3.13 — bounded, read-only historical runtime evidence inventory.

Optional inputs are EXISTING local JSONL traces. Never synthesizes historic records,
executes engine code, opens SQLite, exports IDs/timestamps, or promotes first-party
trace correlation into independent runtime or provider attestation.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import time

SCHEMA = 'apex.stage3b313_producer_origin_runtime_activation_evidence.v1'
PREVIOUS_SCHEMA = 'apex.stage3b312_decision_time_linkage_runtime_evidence.v1'
EVENT_SCHEMA = 'apex.stage3b313_trace.v1'
KINDS = ('decision', 'boot', 'gamma_execution', 'provider_capture')
MAX_REPORT_BYTES = 4 * 1024 * 1024
MAX_EVENT_LINE = 16384
MAX_EVENT_FILE = 16 * 1024 * 1024
HEX_SHA = re.compile(r'^[0-9a-f]{40}(?:[0-9a-f]{24})?$')


def parse_timestamp(s):
    if not isinstance(s, str) or not s or len(s) > 48:
        return None
    try:
        value = datetime.fromisoformat(s.replace('Z', '+00:00'))
        if value.tzinfo is None:
            return None
        return value.astimezone(timezone.utc)
    except ValueError:
        return None


def safe_read(path, limit):
    """Reject symlinks and non-regular files; cap content before processing."""
    import stat
    p = Path(path)
    if p.is_symlink():
        raise ValueError('SYMLINK_INPUT_REJECTED')
    fd = os.open(p, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError('INPUT_NOT_REGULAR_OR_OVERSIZE')
        with os.fdopen(fd, 'rb', closefd=False) as fp:
            data = fp.read(limit + 1)
        if len(data) > limit:
            raise ValueError('INPUT_OVERSIZE')
        return data
    finally:
        os.close(fd)


def read_previous(path):
    if not path:
        return None, 'NOT_SUPPLIED', None
    try:
        raw = safe_read(path, MAX_REPORT_BYTES)
        obj = json.loads(raw)
    except (OSError, ValueError, UnicodeError):
        return None, 'MISSING_OR_INVALID', None
    if not isinstance(obj, dict) or obj.get('schema') != PREVIOUS_SCHEMA:
        return None, 'SCHEMA_MISMATCH', None
    if obj.get('migration_authority') != 'BLOCKED_RESEARCH_ONLY':
        return None, 'UNSAFE_AUTHORITY', None
    return obj, 'READ_AND_SCHEMA_CHECKED', hashlib.sha256(raw).hexdigest()


def valid_identifier(x):
    return isinstance(x, str) and 1 <= len(x) <= 128 and all(c.isalnum() or c in '-_:.|/' for c in x)


def valid_sha(x):
    return isinstance(x, str) and bool(HEX_SHA.fullmatch(x.lower()))


def normalize(event, kind):
    if not isinstance(event, dict) or event.get('schema') != EVENT_SCHEMA or event.get('kind') != kind:
        raise ValueError('EVENT_SCHEMA_OR_KIND_INVALID')
    required = {
        'decision': ('decision_id', 'decision_at', 'snapshot_id', 'boot_id', 'producer_commit'),
        'boot': ('boot_id', 'commit_sha', 'boot_at'),
        'gamma_execution': ('decision_id', 'snapshot_id', 'boot_id', 'executed_at', 'feature_enabled'),
        'provider_capture': ('snapshot_id', 'received_at', 'persisted_at'),
    }[kind]
    if any(key not in event for key in required):
        raise ValueError('MISSING_REQUIRED_FIELD')
    ids = ('decision_id', 'snapshot_id', 'boot_id')
    for k in ids:
        if k in event and not valid_identifier(event[k]):
            raise ValueError('INVALID_IDENTIFIER')
    if (kind == 'boot' and not valid_sha(event['commit_sha'])) or (kind == 'decision' and not valid_sha(event['producer_commit'])):
        raise ValueError('INVALID_COMMIT_SHA')
    if kind == 'gamma_execution' and type(event['feature_enabled']) is not bool:
        raise ValueError('INVALID_FEATURE_ENABLED')
    stamps = {
        'decision': ('decision_at',), 'boot': ('boot_at',),
        'gamma_execution': ('executed_at',),
        'provider_capture': ('received_at', 'persisted_at'),
    }[kind]
    parsed = {k: parse_timestamp(event[k]) for k in stamps}
    if any(v is None for v in parsed.values()):
        raise ValueError('INVALID_EVENT_TIME')
    # Only retain the explicitly allowed attributes; unknown fields are not exported.
    clean = {k: event[k] for k in required if k not in stamps}
    clean.update(parsed)
    return clean


def read_events(path, kind, max_events):
    if not path:
        return None, 'NOT_SUPPLIED', None
    try:
        raw = safe_read(path, MAX_EVENT_FILE)
        if len(raw) == 0:
            return [], 'EMPTY', hashlib.sha256(raw).hexdigest()
        lines = raw.splitlines()
        if len(lines) > max_events:
            raise ValueError('EVENT_BUDGET_EXCEEDED')
        events = []
        for line in lines:
            if len(line) > MAX_EVENT_LINE:
                raise ValueError('EVENT_LINE_OVERSIZE')
            if not line.strip():
                continue
            events.append(normalize(json.loads(line), kind))
        return events, 'READ_AND_SCHEMA_CHECKED', hashlib.sha256(raw).hexdigest()
    except (OSError, ValueError, UnicodeError, TypeError):
        return None, 'INVALID_OR_UNREADABLE', None


def index_unique(records, key):
    out = {}
    duplicates = set()
    for row in records:
        ident = row[key]
        if ident in out:
            duplicates.add(ident)
        else:
            out[ident] = row
    return out, duplicates


def evaluate(previous, traces, states, hashes):
    pop = (previous or {}).get('population_gate', {})
    prior_valid = bool(previous and previous.get('status') == 'LINKAGE_POPULATION_RECONCILED_RUNTIME_NOT_ATTESTED'
                       and pop.get('reconciled') is True
                       and type(pop.get('scanned')) is int and pop['scanned'] >= 0
                       and type(pop.get('total')) is int and pop['scanned'] == pop['total']
                       and type(pop.get('decision_time_gamma_correlated')) is int
                       and 0 <= pop['decision_time_gamma_correlated'] <= pop['total']
                       and previous.get('semantic_gate', {}).get('passed') is True)
    counts = {'historical_population_reconciled': int(pop['total']) if prior_valid else None,
              'post_reference_gamma_correlated': int(pop['decision_time_gamma_correlated']) if prior_valid else None,
              'previous_unresolved_post_reference': pop.get('linkage_exceptions', {}).get('GAMMA_ID_MISSING_LEGACY_OR_UNKNOWN') if prior_valid else None}
    result = {
      'schema': SCHEMA, 'status': 'NO_INDEPENDENT_RUNTIME_ATTESTATION',
      'migration_authority': 'BLOCKED_RESEARCH_ONLY', 'mode': 'READ_ONLY_EXISTING_TRACE_CORRELATION',
      'previous_reconciliation': 'PASS' if prior_valid else 'UNVERIFIED',
      'source_states': states, 'input_sha256': hashes,
      'population_reference': counts,
      'trace_counts': {k: len(traces[k]) if traces.get(k) is not None else None for k in KINDS},
      'trace_correlations': {
        'origin_exact_boot_commit_claim_matches': 0,
        'runtime_execution_exact_identity_time_claim_matches': 0,
        'provider_capture_predecision_claim_matches': 0,
        'three_way_claim_matches': 0,
        'decision_samples_examined': 0,
        'ambiguous_or_duplicate_evidence': 0,
        'unmatched_or_conflicting_samples': 0,
        'predecision_provider_capture_claim_mismatches': 0,
      },
      'attestation_gates': {
        'historical_population_gate': 'PASS_PREVIOUS_BOUNDED_RECONCILIATION' if prior_valid else 'UNVERIFIED',
        'producer_origin': 'UNVERIFIED', 'runtime_feature_executed': 'UNVERIFIED',
        'provider_available_at_decision': 'UNVERIFIED',
        'independent_source_authenticity': 'UNVERIFIED',
        'cross_database_point_in_time_consistency': 'UNVERIFIED',
        'full_historical_decision_replay': 'UNVERIFIED',
      },
      'guardrails': {
        'read_only': True, 'no_sqlite_access': True, 'no_writes_to_inputs': True,
        'no_identifiers_or_event_times_in_output': True, 'no_log_export': True,
        'no_replay_or_source_execution': True, 'no_history_reclassification': True,
        'no_gamma_backfill': True, 'no_latest_substitution': True,
        'no_trade_execution': True, 'no_cutover': True,
      },
      'limitations': [
        'Prior population totals derive from Stage 3B.3.12; no full historical population scan is repeated.',
        'Input hashes establish byte integrity only and not independent custody, trust, or historical authenticity.',
        'First-party records are untrusted claims: even exact joins cannot independently attest production execution.',
        'Provider received/persisted timestamps are claims, not independent proof data was available to a decision.',
        'No shared SQLite point-in-time transaction or full historical engine replay is performed.',
        'No invented producer, gamma execution, or provider traces; absent sources remain UNVERIFIED.',
      ],
    }
    if any(states.get(k) in ('INVALID_OR_UNREADABLE', 'SCHEMA_MISMATCH', 'UNSAFE_AUTHORITY', 'MISSING_OR_INVALID') for k in ('stage3b312',) + KINDS):
        result['status'] = 'INVALID_EVIDENCE_FAIL_CLOSED'
        return result
    if not prior_valid:
        result['status'] = 'PREVIOUS_RECONCILIATION_UNVERIFIED'
        return result
    if not all(traces.get(k) is not None for k in KINDS):
        result['status'] = 'TRACE_INPUTS_INCOMPLETE_RUNTIME_UNVERIFIED'
        return result
    decision, decision_dups = index_unique(traces['decision'], 'decision_id')
    boots, boot_dups = index_unique(traces['boot'], 'boot_id')
    gamma, gamma_dups = index_unique(traces['gamma_execution'], 'decision_id')
    captures, capture_dups = index_unique(traces['provider_capture'], 'snapshot_id')
    c = result['trace_correlations']
    c['decision_samples_examined'] = len(decision)
    duplicate_keys = len(decision_dups) + len(boot_dups) + len(gamma_dups) + len(capture_dups)
    c['ambiguous_or_duplicate_evidence'] = duplicate_keys
    if duplicate_keys:
        result['status'] = 'AMBIGUOUS_TRACE_IDENTITIES_FAIL_CLOSED'
        return result
    for did, d in decision.items():
        boot = boots.get(d['boot_id'])
        ex = gamma.get(did)
        capture = captures.get(d['snapshot_id'])
        origin = bool(boot and boot['commit_sha'].lower() == d['producer_commit'].lower()
                      and boot['boot_at'] <= d['decision_at'])
        runtime = bool(origin and ex and ex['snapshot_id'] == d['snapshot_id']
                       and ex['boot_id'] == d['boot_id'] and ex['feature_enabled'] is True
                       and boot['boot_at'] <= ex['executed_at'] <= d['decision_at'])
        provider = bool(capture and capture['received_at'] <= capture['persisted_at'] <= d['decision_at'])
        if origin: c['origin_exact_boot_commit_claim_matches'] += 1
        if runtime: c['runtime_execution_exact_identity_time_claim_matches'] += 1
        if provider: c['provider_capture_predecision_claim_matches'] += 1
        elif capture: c['predecision_provider_capture_claim_mismatches'] += 1
        if origin and runtime and provider: c['three_way_claim_matches'] += 1
        if not (origin and runtime and provider): c['unmatched_or_conflicting_samples'] += 1
    result['status'] = 'FIRST_PARTY_TRACES_CORRELATED_NOT_INDEPENDENTLY_ATTESTED'
    return result


def save_report(path, report, protected_root='/data'):
    dest = Path(path).resolve()
    root = Path(protected_root).resolve()
    if dest == root or root in dest.parents:
        raise ValueError('OUTPUT_INSIDE_PRODUCTION_DATA_REJECTED')
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.apex313-', dir=dest.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, sort_keys=True)
            f.write('\n')
        os.chmod(tmp, 0o600)
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--stage3b312-report', required=True)
    for kind in KINDS:
        p.add_argument('--' + kind.replace('_', '-') + '-events')
    p.add_argument('--max-events-per-file', type=int, default=10000)
    p.add_argument('--protected-root', default='/data')
    p.add_argument('--output', required=True)
    args = p.parse_args(argv)
    if not 1 <= args.max_events_per_file <= 50000:
        p.error('max-events-per-file must be 1..50000')
    inputs = [args.stage3b312_report] + [getattr(args, kind + '_events') for kind in KINDS]
    output_resolved = Path(args.output).resolve()
    if any(Path(src).resolve() == output_resolved for src in inputs if src):
        p.error('output cannot overwrite an evidence input')
    previous, state, digest = read_previous(args.stage3b312_report)
    states = {'stage3b312': state}
    hashes = {'stage3b312': digest} if digest else {}
    traces = {}
    for kind in KINDS:
        path = getattr(args, kind + '_events')
        events, state, sha = read_events(path, kind, args.max_events_per_file)
        traces[kind] = events
        states[kind] = state
        if sha: hashes[kind] = sha
    report = evaluate(previous, traces, states, hashes)
    save_report(args.output, report, protected_root=args.protected_root)
    print('Stage 3B.3.13:', report['status'], '|', report['migration_authority'])
    return 0 if report['status'] not in ('INVALID_EVIDENCE_FAIL_CLOSED', 'AMBIGUOUS_TRACE_IDENTITIES_FAIL_CLOSED', 'PREVIOUS_RECONCILIATION_UNVERIFIED') else 2


if __name__ == '__main__':
    raise SystemExit(main())
