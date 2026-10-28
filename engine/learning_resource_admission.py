"""Conservative resource gate for scanner-owned optional flow learning.

No worker, queue, persistence mutation, or bypass of scanner deadlines.
Unknown memory measurements fail closed; cgroup max events are cumulative and
not used alone as a current-pressure signal.
"""
from __future__ import annotations


def assess_resource_admission(snapshot, *, max_noninactive_pct=75.0,
                              max_raw_pct=95.0, max_psi_some=2.0):
    if not isinstance(snapshot, dict):
        return 'DEFERRED_MEMORY_UNKNOWN'
    if snapshot.get('severity') in ('CRITICAL', 'HIGH_PRESSURE'):
        return 'DEFERRED_MEMORY_PRESSURE'
    raw = snapshot.get('raw_usage_pct')
    noninactive = snapshot.get('estimated_noninactive_file_usage_pct')
    psi = snapshot.get('psi_some_avg10')
    if raw is None or noninactive is None or psi is None:
        return 'DEFERRED_MEMORY_UNKNOWN'
    try:
        if float(raw) >= max_raw_pct or float(noninactive) >= max_noninactive_pct or float(psi) >= max_psi_some:
            return 'DEFERRED_MEMORY_PRESSURE'
    except (TypeError, ValueError):
        return 'DEFERRED_MEMORY_UNKNOWN'
    return 'ADMITTED'
