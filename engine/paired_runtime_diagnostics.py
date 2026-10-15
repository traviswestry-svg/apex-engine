"""APEX read-only paired memory and scanner coverage diagnostics.
No scanner scheduling, decisions, or execution behavior is changed.
"""
from __future__ import annotations
import datetime as dt
import os
import time
import uuid
from engine.runtime_memory_attribution import snapshot, append_bounded

MEMORY_PATH = "/data/apex_runtime_memory_pairs.jsonl"
SCAN_PATH = "/data/apex_scan_coverage.jsonl"

def new_cycle_id(prefix="cycle"):
    return f"{prefix}-{uuid.uuid4().hex}"

def _rss(record):
    return ((record.get("processes") or {}).get("scanner") or {}).get("memory") or {}

def _safe_write(path, record):
    try:
        append_bounded(os.getenv("APEX_MEMORY_PAIR_PATH", MEMORY_PATH) if path == MEMORY_PATH else os.getenv("APEX_SCAN_COVERAGE_PATH", SCAN_PATH), record)
    except (OSError, ValueError) as exc:
        print(f"[APEX DIAGNOSTICS] write unavailable: {type(exc).__name__}", flush=True)

def begin_stage(cycle_id, stage):
    try:
        return (time.monotonic(), snapshot(scanner_pid=os.getpid(), stage=f"{stage}_START"))
    except (OSError, ValueError):
        return (time.monotonic(), {})

def end_stage(cycle_id, stage, started, outcome="COMPLETED"):
    start_time, before = started
    try:
        after = snapshot(scanner_pid=os.getpid(), stage=f"{stage}_END")
        a, b = _rss(before), _rss(after)
        deltas = {key: (b[key] - a[key]) for key in ("rss_kib", "pss_kib", "private_dirty_kib") if isinstance(a.get(key), int) and isinstance(b.get(key), int)}
        _safe_write(MEMORY_PATH, {"schema":"apex.memory_pair.v1", "cycle_id":cycle_id, "stage":stage,
          "observed_at":dt.datetime.now(dt.timezone.utc).isoformat(), "elapsed_ms":round((time.monotonic()-start_time)*1000,1),
          "outcome":outcome,"before":a,"after":b,"delta_kib":deltas,
          "cgroup_before":before.get("cgroup"),"cgroup_after":after.get("cgroup"),
          "decision_authority":False,"execution_authority":False})
    except (OSError, ValueError, TypeError) as exc:
        print(f"[APEX DIAGNOSTICS] stage unavailable: {type(exc).__name__}", flush=True)

def scan_event(cycle_id, event, *, reason=None, details=None):
    _safe_write(SCAN_PATH, {"schema":"apex.scan_coverage.v1", "cycle_id":cycle_id,
      "event":event,"reason":reason,"details":details or {},
      "observed_at":dt.datetime.now(dt.timezone.utc).isoformat(),
      "decision_authority":False,"execution_authority":False})
