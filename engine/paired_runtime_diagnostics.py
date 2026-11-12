"""APEX read-only paired memory and scanner coverage diagnostics.
No scanner scheduling, decisions, or execution behavior is changed.
"""
from __future__ import annotations
import datetime as dt
import os
from pathlib import Path
import time
import uuid
from engine.runtime_memory_attribution import snapshot, append_bounded

MEMORY_PATH = "/data/apex_runtime_memory_pairs.jsonl"
SCAN_PATH = "/data/apex_scan_coverage.jsonl"

def new_cycle_id(prefix="cycle"):
    return f"{prefix}-{uuid.uuid4().hex}"

def _rss(record):
    return ((record.get("processes") or {}).get("scanner") or {}).get("memory") or {}

def _process_start_ticks(pid):
    """Read Linux process start time, tolerating spaces and parentheses in comm."""
    try:
        stat = Path(f"/proc/{int(pid)}/stat").read_text()
        _, separator, fields = stat.rpartition(")")
        if not separator:
            return None
        values = fields.split()
        ticks = int(values[19])
        return ticks if ticks > 0 else None
    except (OSError, ValueError, IndexError):
        return None

def _safe_write(path, record):
    try:
        append_bounded(os.getenv("APEX_MEMORY_PAIR_PATH", MEMORY_PATH) if path == MEMORY_PATH else os.getenv("APEX_SCAN_COVERAGE_PATH", SCAN_PATH), record)
    except (OSError, ValueError) as exc:
        print(f"[APEX DIAGNOSTICS] write unavailable: {type(exc).__name__}", flush=True)

def begin_stage(cycle_id, stage):
    pid = os.getpid()
    ticks = _process_start_ticks(pid)
    try:
        return (time.monotonic(), snapshot(scanner_pid=pid, stage=f"{stage}_START"), pid, ticks)
    except (OSError, ValueError):
        return (time.monotonic(), {}, pid, ticks)

def end_stage(cycle_id, stage, started, outcome="COMPLETED"):
    if len(started) == 2:
        start_time, before = started
        pid, ticks = os.getpid(), None
    else:
        start_time, before, pid, ticks = started
    try:
        after = snapshot(scanner_pid=pid, stage=f"{stage}_END")
        end_pid = os.getpid()
        end_ticks = _process_start_ticks(end_pid)
        verified = pid == end_pid and ticks is not None and ticks > 0 and ticks == end_ticks
        identity = ("VERIFIED" if verified else
                    "PROCESS_START_UNAVAILABLE" if ticks is None or end_ticks is None or ticks <= 0 or end_ticks <= 0 else
                    "PROCESS_IDENTITY_CHANGED")
        a, b = _rss(before), _rss(after)
        deltas = {key: (b[key] - a[key]) for key in ("rss_kib", "pss_kib", "private_dirty_kib") if isinstance(a.get(key), int) and isinstance(b.get(key), int)}
        _safe_write(MEMORY_PATH, {"schema":"apex.memory_pair.v1", "cycle_id":cycle_id, "stage":stage,
          "observed_at":dt.datetime.now(dt.timezone.utc).isoformat(), "elapsed_ms":round((time.monotonic()-start_time)*1000,1),
          "outcome":outcome,"before":a,"after":b,"delta_kib":deltas,
          "cgroup_before":before.get("cgroup"),"cgroup_after":after.get("cgroup"),
          "process_pid":pid,"process_start_ticks":ticks,
          "process_identity_verified":verified,"identity_diagnostic":identity,
          "decision_authority":False,"execution_authority":False})
    except (OSError, ValueError, TypeError) as exc:
        print(f"[APEX DIAGNOSTICS] stage unavailable: {type(exc).__name__}", flush=True)

def scan_event(cycle_id, event, *, reason=None, details=None):
    _safe_write(SCAN_PATH, {"schema":"apex.scan_coverage.v1", "cycle_id":cycle_id,
      "event":event,"reason":reason,"details":details or {},
      "observed_at":dt.datetime.now(dt.timezone.utc).isoformat(),
      "decision_authority":False,"execution_authority":False})
