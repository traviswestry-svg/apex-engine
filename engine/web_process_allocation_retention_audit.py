"""Read-only, bounded web-process anonymous allocation/retention observations.

Samples at /health only. This module does NOT trace allocations, collect garbage,
inspect object graphs, query databases, walk /proc processes, or retain responses.
All trends are correlations within a verified Linux process instance, not leaks.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
import gc
import os
from pathlib import Path
import sys
import threading
import time

SCHEMA = "apex.web_process_allocation_retention_audit.v1"
_HISTORY = deque(maxlen=16)
_LOCK = threading.Lock()
MIN_SAMPLE_SECONDS = 30.0


def _integer(path):
    try:
        return int(Path(path).read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return None


def _fields(path, fields):
    values = {}
    try:
        with Path(path).open(encoding="ascii") as handle:
            for line in handle:
                key, _, val = line.partition(":")
                if key in fields:
                    try:
                        values[fields[key]] = int(val.strip().split()[0])
                    except (IndexError, ValueError):
                        pass
    except OSError:
        pass
    return values


def _process_start_ticks(pid, proc_root):
    """Linux /proc stat starttime field 22; handle spaces in comm safely."""
    try:
        stat = (Path(proc_root) / str(pid) / "stat").read_text(encoding="ascii")
        rparen = stat.rfind(")")
        if rparen < 0:
            return None
        # Tail starts with stat field 3 ('state'), so field 22 is offset 19.
        start = int(stat[rparen + 1:].split()[19])
        return start if start > 0 else None
    except (OSError, ValueError, IndexError):
        return None


def sample(*, proc_root="/proc", cgroup_root="/sys/fs/cgroup", pid=None, monotonic=None):
    pid = os.getpid() if pid is None else int(pid)
    proc = Path(proc_root) / str(pid)
    status = _fields(proc / "status", {"VmRSS": "rss_kib", "RssAnon": "rss_anon_kib",
                                      "VmData": "vm_data_kib", "Threads": "threads"})
    rollup = _fields(proc / "smaps_rollup", {"Private_Dirty": "private_dirty_kib",
                                                   "Private_Clean": "private_clean_kib",
                                                   "Pss_Anon": "pss_anon_kib"})
    cg = Path(cgroup_root)
    stat = {}
    try:
        with (cg / "memory.stat").open(encoding="ascii") as handle:
            for line in handle:
                parts = line.split()
                if len(parts) == 2 and parts[0] in ("anon", "file", "active_file", "inactive_file"):
                    try:
                        stat[parts[0]] = int(parts[1])
                    except ValueError:
                        pass
    except OSError:
        pass
    blocks = sys.getallocatedblocks() if hasattr(sys, "getallocatedblocks") else None
    return {"pid": pid, "start_ticks": _process_start_ticks(pid, proc_root),
            "monotonic": time.monotonic() if monotonic is None else float(monotonic),
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "process": {**status, **rollup, "allocated_blocks": blocks,
                        "gc_generation_counts": list(gc.get_count())},
            "cgroup": {"current_bytes": _integer(cg / "memory.current"),
                       "anon_bytes": stat.get("anon"), "file_bytes": stat.get("file"),
                       "active_file_bytes": stat.get("active_file"),
                       "inactive_file_bytes": stat.get("inactive_file")}}


def _difference(start, end, key):
    a, b = start.get(key), end.get(key)
    return (b-a) if isinstance(a, int) and isinstance(b, int) else None


def compare(before, after):
    if not before or not after or not before.get("start_ticks") or not after.get("start_ticks"):
        return {"status": "PROCESS_IDENTITY_UNVERIFIED", "comparable": False}
    if (before["pid"], before["start_ticks"]) != (after["pid"], after["start_ticks"]):
        return {"status": "PROCESS_CHANGED", "comparable": False}
    if after["monotonic"] < before["monotonic"]:
        return {"status": "NONMONOTONIC_SAMPLE", "comparable": False}
    proc_keys = ("rss_kib", "rss_anon_kib", "private_dirty_kib", "private_clean_kib",
                 "pss_anon_kib", "vm_data_kib", "allocated_blocks", "threads")
    cg_keys = ("current_bytes", "anon_bytes", "file_bytes", "active_file_bytes", "inactive_file_bytes")
    return {"status": "COMPARABLE_TREND_NOT_CAUSAL", "comparable": True,
            "span_seconds": round(after["monotonic"] - before["monotonic"], 2),
            "process_deltas": {k: _difference(before["process"], after["process"], k) for k in proc_keys},
            "cgroup_deltas": {k: _difference(before["cgroup"], after["cgroup"], k) for k in cg_keys}}


def observe(*, proc_root="/proc", cgroup_root="/sys/fs/cgroup", pid=None, monotonic=None):
    point = sample(proc_root=proc_root, cgroup_root=cgroup_root, pid=pid, monotonic=monotonic)
    identity = (point["pid"], point["start_ticks"])
    with _LOCK:
        if _HISTORY and (identity != (_HISTORY[-1]["pid"], _HISTORY[-1]["start_ticks"])
                         or point["monotonic"] < _HISTORY[-1]["monotonic"]):
            _HISTORY.clear()
        if not _HISTORY or point["monotonic"] - _HISTORY[-1]["monotonic"] >= MIN_SAMPLE_SECONDS:
            _HISTORY.append(point)
        first = _HISTORY[0]
        latest = _HISTORY[-1]
        count = len(_HISTORY)
    trend = compare(first, point) if count > 1 else None
    if not point["start_ticks"]:
        status = "PROCESS_IDENTITY_UNVERIFIED"
    elif "rss_kib" not in point["process"]:
        status = "PROCESS_SAMPLE_UNAVAILABLE"
    elif count == 1:
        status = "FIRST_PROCESS_SAMPLE"
    else:
        status = "BOUNDED_TREND_OBSERVED_CAUSE_NOT_PROVEN"
    return {"schema": SCHEMA, "status": status, "observed_at": point["observed_at"],
            "process_identity": {"pid": point["pid"], "start_ticks": point["start_ticks"],
                                 "verified": bool(point["start_ticks"])},
            "latest_process": point["process"], "latest_cgroup": point["cgroup"],
            "history_samples": count, "sample_min_interval_seconds": MIN_SAMPLE_SECONDS,
            "history_max_samples": _HISTORY.maxlen,
            "oldest_to_current": trend,
            "retention_assessment": "NOT_ESTABLISHED_BY_SNAPSHOTS",
            "limits": ["RSS/private dirty/allocated blocks can change due to concurrent requests and allocators",
                       "Python allocated blocks are not bytes or a heap ownership breakdown",
                       "GC generation counts do not indicate object retention by themselves",
                       "Only /health samples are observed; this does not trace every endpoint",
                       "No Python heap, cache-owner or SQLite allocation attribution is asserted",
                       "Process-local history resets on worker restart; same cgroup is shared by other processes"],
            "read_only": True, "db_reads": False, "automatic_reclamation": False,
            "uses_tracemalloc": False, "calls_gc_collect": False,
            "decision_authority": False, "execution_authority": False,
            "changes_trade_decisions": False}
