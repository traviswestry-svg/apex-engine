"""Bounded, read-only cgroup v2 memory-limit event investigation.

A `memory.events.max` event indicates an allocation encountered the cgroup limit;
it is not an OOM kill. Samples are web-worker-local and must share the same
boot/cgroup inode identity. Phase records are temporal context, never causation.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from pathlib import Path
import os
import threading
import time
from typing import Any

SCHEMA = 'apex.container_memory_limit_event_investigation.v1'
_HISTORY = deque(maxlen=16)
_INTERVALS = deque(maxlen=8)
_LOCK = threading.Lock()
_KEYS = ('low', 'high', 'max', 'oom', 'oom_kill', 'oom_group_kill')
_STAT_KEYS = ('anon', 'file', 'active_file', 'inactive_file', 'kernel', 'slab')


def _integer_file(path: Path):
    try:
        value = path.read_text().strip()
        return None if value == 'max' else int(value)
    except (OSError, ValueError):
        return None


def _pairs(path: Path):
    try:
        result = {}
        for line in path.read_text().splitlines():
            parts = line.split()
            if len(parts) == 2:
                result[parts[0]] = int(parts[1])
        return result
    except (OSError, ValueError):
        return {}


def _pressure(path: Path):
    output = {}
    try:
        for line in path.read_text().splitlines():
            parts = line.split()
            if parts and parts[0] in ('some', 'full'):
                for part in parts[1:]:
                    if part.startswith('avg10='):
                        output[parts[0] + '_avg10'] = float(part.split('=', 1)[1])
    except (OSError, ValueError):
        pass
    return output


def sample(root='/sys/fs/cgroup', *, timestamp=None, monotonic=None):
    """Acquire one small, cgroup-scoped snapshot, never mutate the cgroup."""
    base = Path(root)
    try:
        identity = f'{Path("/proc/sys/kernel/random/boot_id").read_text().strip()}:{base.stat().st_dev}:{base.stat().st_ino}'
    except OSError:
        identity = None
    events = _pairs(base / 'memory.events')
    stat = _pairs(base / 'memory.stat')
    current = _integer_file(base / 'memory.current')
    if identity is None or current is None or not all(k in events for k in ('max', 'oom', 'oom_kill')):
        return None
    return {
        'at': timestamp or datetime.now(timezone.utc).isoformat(),
        'monotonic': time.monotonic() if monotonic is None else monotonic,
        'cgroup_identity': identity,
        'events': {k: events.get(k) for k in _KEYS},
        'current_bytes': current,
        'peak_bytes': _integer_file(base / 'memory.peak'),
        'limit_bytes': _integer_file(base / 'memory.max'),
        'stat': {k: stat.get(k) for k in _STAT_KEYS},
        'psi': _pressure(base / 'memory.pressure'),
    }


def compare(before, after):
    """Only compute counter deltas inside the same verified cgroup lifetime."""
    if not before or not after or before.get('cgroup_identity') != after.get('cgroup_identity'):
        return {'status': 'CGROUP_IDENTITY_CHANGED_OR_UNAVAILABLE'}
    if after['monotonic'] <= before['monotonic']:
        return {'status': 'NONMONOTONIC_SAMPLE'}
    events_a, events_b = before['events'], after['events']
    if any(events_a.get(k) is None or events_b.get(k) is None for k in ('max', 'oom', 'oom_kill')):
        return {'status': 'COUNTERS_UNAVAILABLE'}
    if any(events_b.get(k, 0) < events_a.get(k, 0) for k in ('max', 'oom', 'oom_kill')):
        return {'status': 'COUNTER_RESET_OR_REPLACED'}
    deltas = {k: events_b[k] - events_a[k] if events_a.get(k) is not None and events_b.get(k) is not None else None for k in _KEYS}
    stat_deltas = {k: after['stat'][k] - before['stat'][k] if after['stat'].get(k) is not None and before['stat'].get(k) is not None else None for k in _STAT_KEYS}
    return {
        'status': 'NEW_MAX_EVENTS_OBSERVED' if deltas['max'] > 0 else 'NO_NEW_MAX_EVENTS',
        'from_at': before['at'], 'to_at': after['at'],
        'span_seconds': round(after['monotonic'] - before['monotonic'], 2),
        'event_deltas': deltas,
        'current_delta_bytes': after['current_bytes'] - before['current_bytes'],
        'anon_delta_bytes': stat_deltas['anon'],
        'file_delta_bytes': stat_deltas['file'],
        'active_file_delta_bytes': stat_deltas['active_file'],
        'inactive_file_delta_bytes': stat_deltas['inactive_file'],
        'end_current_bytes': after['current_bytes'],
        'end_peak_bytes': after['peak_bytes'],
        'end_limit_bytes': after['limit_bytes'],
        'end_psi': after['psi'],
        'interpretation': 'TIME_BRACKET_ONLY_NO_CAUSAL_ATTRIBUTION',
    }


def _parse_timestamp(raw):
    try:
        parsed = datetime.fromisoformat(str(raw).replace('Z', '+00:00'))
        return parsed if parsed.tzinfo else None
    except (ValueError, TypeError):
        return None


def phase_context(interval, phase_summary):
    """Return bounded, *noncausal* coincidence of verified phase completion timestamps.

    Only look at last-completed verified phase records already summarized by
    the bounded phase reader. No further file reads and no implied absence of
    other phase records if a completion falls outside its one-record window.
    """
    if interval.get('status') != 'NEW_MAX_EVENTS_OBSERVED':
        return {'status': 'NO_NEW_MAX_EVENT_BRACKET'}
    start, end = _parse_timestamp(interval.get('from_at')), _parse_timestamp(interval.get('to_at'))
    if not start or not end:
        return {'status': 'INVALID_INTERVAL_TIMESTAMP'}
    matches = []
    for proc in (phase_summary or {}).get('processes', [])[:3]:
        for stage, data in (proc.get('phases') or {}).items():
            rec = (data or {}).get('last_completed') or {}
            when = _parse_timestamp(rec.get('observed_at'))
            if when is not None and start <= when <= end:
                matches.append({'stage': stage, 'pid': proc.get('pid'),
                                'process_start_ticks': proc.get('process_start_ticks'),
                                'completed_at': rec.get('observed_at'),
                                'rss_delta_kib': rec.get('rss_delta_kib')})
    return {'status': 'VERIFIED_PHASE_COMPLETIONS_IN_INTERVAL' if matches else 'NO_LAST_COMPLETION_IN_INTERVAL',
            'matching_last_completions': matches[:6],
            'scope': 'ONLY_LAST_COMPLETED_VERIFIED_PHASE_PER_PROCESS_AND_STAGE',
            'causation_established': False}


def observe(*, root='/sys/fs/cgroup', phase_summary=None, timestamp=None, monotonic=None):
    """Sample once per health call, report new max events only after a baseline.

    Fail-open. Keeps 16 small snapshots and 8 event brackets in process-local
    memory. Workers do not share state; deployment/restart resets the baseline.
    """
    try:
        current = sample(root, timestamp=timestamp, monotonic=monotonic)
        with _LOCK:
            if current is None:
                status = 'CGROUP_SAMPLE_UNAVAILABLE'
            elif not _HISTORY:
                _HISTORY.append(current)
                status = 'BASELINE_ESTABLISHED_NO_EVENT_TIME_INFERRED'
            elif _HISTORY[-1]['cgroup_identity'] != current['cgroup_identity']:
                _HISTORY.clear()
                _INTERVALS.clear()
                _HISTORY.append(current)
                status = 'CGROUP_IDENTITY_CHANGED_BASELINE_RESET'
            else:
                interval = compare(_HISTORY[-1], current)
                if interval['status'] in ('COUNTER_RESET_OR_REPLACED', 'NONMONOTONIC_SAMPLE'):
                    _HISTORY.clear()
                    _INTERVALS.clear()
                    _HISTORY.append(current)
                    status = 'COUNTER_OR_CLOCK_RESET_BASELINE_RESET'
                else:
                    _HISTORY.append(current)
                    status = interval['status']
                    if status == 'NEW_MAX_EVENTS_OBSERVED':
                        interval['phase_context'] = phase_context(interval, phase_summary)
                        _INTERVALS.append(interval)
            recent = list(_INTERVALS)
            baseline = _HISTORY[0] if _HISTORY else None
            last = _HISTORY[-1] if _HISTORY else None
            valid = baseline is not None and last is not None and baseline['cgroup_identity'] == last['cgroup_identity']
            return {
                'schema': SCHEMA, 'status': status,
                'observed_at': current['at'] if current else None,
                'cgroup_identity_verified': bool(current),
                'web_worker_pid': os.getpid(),
                'sample_count': len(_HISTORY),
                'cumulative_events_at_last_sample': dict(last['events']) if last else None,
                'baseline_cumulative_max': baseline['events'].get('max') if valid else None,
                'max_events_since_process_local_baseline': last['events']['max'] - baseline['events']['max'] if valid else None,
                'new_max_event_intervals': recent,
                'bounded_intervals': 8, 'bounded_samples': 16,
                'read_only': True, 'db_reads': False, 'execution_authority': False,
                'decision_authority': False, 'changes_trade_decisions': False,
                'automatic_reclamation': False,
                'limitations': [
                    'Cgroup memory.events counters are cumulative; historical events are not assigned timestamps',
                    'Sampling brackets an event between requests; it does not timestamp an individual allocation',
                    'The cgroup includes other processes; phase coincidence does not prove causation',
                    'State is web-worker local and resets on restart or worker change',
                    'Only the latest verified phase completion per stage/process is considered for temporal context',
                    'Raw memory.current includes potentially reclaimable file-backed cache',
                ],
            }
    except (OSError, ValueError, KeyError, TypeError):
        return {'schema': SCHEMA, 'status': 'DIAGNOSTIC_UNAVAILABLE',
                'read_only': True, 'db_reads': False,
                'execution_authority': False, 'decision_authority': False}
