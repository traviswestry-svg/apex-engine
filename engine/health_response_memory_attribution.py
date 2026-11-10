"""Read-only bounded /health construction and JSON serialization attribution.

One-request-lag reporting: a request cannot truthfully report its own completed
serialization inside the same JSON response without encoding again. No payloads
or response bodies are retained. Does not activate tracemalloc or call GC.
"""
from __future__ import annotations

from collections import deque
import os
from pathlib import Path
import threading
import time

SCHEMA = 'apex.health_response_memory_attribution.v1'
_EVENTS = deque(maxlen=8)
_LOCK = threading.Lock()


def rss_kib(pid=None):
    """Bounded read of current process RSS; no tree walking."""
    target = os.getpid() if pid is None else pid
    try:
        with Path(f'/proc/{target}/status').open(encoding='ascii') as handle:
            for line in handle:
                if line.startswith('VmRSS:'):
                    return max(0, int(line.split()[1]))
    except (OSError, ValueError, IndexError):
        pass
    return None


def begin(*, monotonic_ns=None, rss=None):
    return {'started_ns': time.perf_counter_ns() if monotonic_ns is None else monotonic_ns,
            'rss_before_kib': rss_kib() if rss is None else rss,
            'pid': os.getpid()}


def _difference(after, before):
    return after - before if after is not None and before is not None else None


def prior_completed():
    """Return small immutable-by-copy scalar summary. No bodies or full histories."""
    with _LOCK:
        last = dict(_EVENTS[-1]) if _EVENTS else None
        count = len(_EVENTS)
    return {'schema': SCHEMA,
            'status': 'PRIOR_COMPLETED_REQUEST' if last else 'NO_PRIOR_COMPLETED_REQUEST',
            'reporting_lag': 'COMPLETED_REQUEST_VISIBLE_ON_SUBSEQUENT_HEALTH_RESPONSE',
            'completed_requests_observed': count, 'last_completed': last,
            'read_only': True, 'db_reads': False, 'execution_authority': False,
            'decision_authority': False, 'changes_trade_decisions': False,
            'does_not_retain_response_body': True,
            'does_not_run_gc_or_tracemalloc': True,
            'limitations': ['RSS deltas can include unrelated concurrent work',
                            'post-jsonify RSS includes current response buffer until released',
                            'request-time RSS does not prove retained memory or a leak',
                            'history is process-local and resets after restart']}


def completed(start, *, construction_end_ns, construction_end_rss_kib,
              response, end_ns=None, end_rss_kib=None):
    """Record one already-built Flask response; do not reserialize or copy body."""
    stop_ns = time.perf_counter_ns() if end_ns is None else end_ns
    stop_rss = rss_kib() if end_rss_kib is None else end_rss_kib
    before = start.get('rss_before_kib')
    content_bytes = response.calculate_content_length()  # length of existing buffer
    record = {
        'pid': start['pid'],
        'payload_construction_ms': round(max(0, construction_end_ns - start['started_ns']) / 1e6, 3),
        'jsonify_serialization_ms': round(max(0, stop_ns - construction_end_ns) / 1e6, 3),
        'total_measured_ms': round(max(0, stop_ns - start['started_ns']) / 1e6, 3),
        'response_bytes': content_bytes,
        'rss_before_kib': before,
        'rss_after_construction_kib': construction_end_rss_kib,
        'rss_after_jsonify_kib': stop_rss,
        'construction_rss_delta_kib': _difference(construction_end_rss_kib, before),
        'serialization_rss_delta_kib': _difference(stop_rss, construction_end_rss_kib),
        'total_rss_delta_kib': _difference(stop_rss, before),
    }
    with _LOCK:
        _EVENTS.append(record)
    return record
