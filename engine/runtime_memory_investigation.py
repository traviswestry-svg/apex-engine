"""Bounded, read-only cgroup v2 and process memory attribution for /health.

Observational only. No filesystem writes, proc enumeration, memory reclamation,
SQLite connections, thread creation, or execution/scanner authority.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import os
from pathlib import Path
import threading
import time

SCHEMA = 'apex.runtime_memory_investigation.v1'
_SAMPLES = deque(maxlen=12)
_LOCK = threading.Lock()


def _integer(path):
    try:
        value = Path(path).read_text(encoding='ascii').strip()
        return None if value == 'max' else max(0, int(value))
    except (OSError, ValueError):
        return None


def _key_values(path):
    result = {}
    try:
        with Path(path).open(encoding='ascii') as handle:
            for line in handle:
                parts = line.split()
                if len(parts) == 2:
                    try:
                        result[parts[0]] = max(0, int(parts[1]))
                    except ValueError:
                        pass
    except OSError:
        pass
    return result


def _process_status(pid):
    """Read only six /proc/<pid>/status fields; never walk process trees."""
    result = {'pid': pid, 'available': False}
    wanted = {'VmRSS': 'rss_kib', 'VmHWM': 'peak_rss_kib',
              'RssAnon': 'anonymous_rss_kib', 'RssFile': 'file_rss_kib',
              'RssShmem': 'shared_rss_kib', 'VmSize': 'virtual_size_kib'}
    try:
        with Path(f'/proc/{pid}/status').open(encoding='ascii') as handle:
            for line in handle:
                key, _, text = line.partition(':')
                if key in wanted:
                    try:
                        result[wanted[key]] = int(text.split()[0])
                    except (ValueError, IndexError):
                        pass
    except (OSError, ValueError):
        return result
    result['available'] = 'rss_kib' in result
    return result


def _delta(current, previous):
    if current is None or previous is None or current < previous:
        return None
    return current - previous


def inspect(*, cgroup_root='/sys/fs/cgroup', pid=None, monotonic=None):
    """Sample current cgroup/process using bounded reads; no guessed root cause."""
    root = Path(cgroup_root)
    now = time.monotonic() if monotonic is None else float(monotonic)
    stat = _key_values(root / 'memory.stat')
    events = _key_values(root / 'memory.events')
    current = _integer(root / 'memory.current')
    limit = _integer(root / 'memory.max')
    peak = _integer(root / 'memory.peak')
    # These are cgroup accounting categories, not independent additive totals.
    keys = ('anon', 'file', 'inactive_file', 'active_file', 'shmem', 'file_mapped',
            'file_dirty', 'file_writeback', 'slab', 'slab_reclaimable',
            'slab_unreclaimable', 'kernel', 'sock', 'pagetables', 'anon_thp')
    breakdown = {key + '_bytes': stat.get(key) for key in keys}
    process = _process_status(os.getpid() if pid is None else int(pid))
    sample = {'monotonic': now, 'current': current,
              'anon': stat.get('anon'), 'file': stat.get('file'),
              'rss_kib': process.get('rss_kib'),
              'max': events.get('max'), 'oom': events.get('oom'),
              'oom_kill': events.get('oom_kill')}
    with _LOCK:
        # This is process-local history; after restart no trend continuity is inferred.
        if _SAMPLES and now < _SAMPLES[-1]['monotonic']:
            _SAMPLES.clear()
        previous = _SAMPLES[-1] if _SAMPLES else None
        if not previous or now - previous['monotonic'] >= 30:
            _SAMPLES.append(sample)
        oldest = _SAMPLES[0]
        count = len(_SAMPLES)
    changes = {
        'sample_count': count,
        'span_seconds': round(max(0, now - oldest['monotonic']), 1),
        'cgroup_current_delta_bytes': (current - oldest['current'] if current is not None and oldest['current'] is not None else None),
        'cgroup_anon_delta_bytes': (stat['anon'] - oldest['anon'] if 'anon' in stat and oldest['anon'] is not None else None),
        'cgroup_file_delta_bytes': (stat['file'] - oldest['file'] if 'file' in stat and oldest['file'] is not None else None),
        'process_rss_delta_kib': (process['rss_kib'] - oldest['rss_kib'] if 'rss_kib' in process and oldest['rss_kib'] is not None else None),
        'max_events_since_previous_sample': _delta(events.get('max'), previous.get('max')) if previous else None,
        'oom_events_since_previous_sample': _delta(events.get('oom'), previous.get('oom')) if previous else None,
        'oom_kills_since_previous_sample': _delta(events.get('oom_kill'), previous.get('oom_kill')) if previous else None,
        'max_events_since_first_sample': _delta(events.get('max'), oldest.get('max')),
        'oom_kills_since_first_sample': _delta(events.get('oom_kill'), oldest.get('oom_kill')),
    }
    observed = current is not None and bool(stat)
    if not observed:
        state = 'MEASUREMENTS_UNAVAILABLE'
    elif events.get('oom_kill', 0) > 0 and (changes['oom_kills_since_first_sample'] or 0) > 0:
        state = 'NEW_OOM_KILL_OBSERVED'
    elif (changes['max_events_since_first_sample'] or 0) > 0:
        state = 'MEMORY_LIMIT_EVENTS_INCREASING'
    elif count < 2:
        state = 'SINGLE_SAMPLE_NO_CAUSAL_ATTRIBUTION'
    else:
        state = 'TREND_OBSERVED_CAUSE_NOT_PROVEN'
    return {
        'schema': SCHEMA, 'status': state,
        'observed_at': datetime.now(timezone.utc).isoformat(),
        'cgroup': {'current_bytes': current, 'limit_bytes': limit,
                   'peak_bytes': peak, 'events_cumulative': events,
                   'accounting': breakdown},
        'web_process': process, 'bounded_trend': changes,
        'stage_trace': {'source': 'existing paired_runtime_diagnostics JSONL',
                        'read_by_endpoint': False,
                        'note': 'Inspect scanner/settlement phase checkpoints separately; no file scan is performed here.'},
        'sqlite': {'measurement': 'NOT_SAMPLED',
                   'note': 'SQLite heap/cache attribution requires profiled connections; database size is not process RSS.'},
        'limitations': ['cgroup stat categories can overlap; do not sum them',
                        'web RSS is one process and is not total container memory',
                        'cgroup max counters are cumulative; deltas only apply within this process',
                        'no memory leak or database root cause established from these samples'],
        'read_only': True, 'decision_authority': False,
        'execution_authority': False, 'changes_trade_decisions': False,
        'automatic_reclamation': False, 'db_reads': False,
    }
