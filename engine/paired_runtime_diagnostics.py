"""APEX read-only paired memory and scanner coverage diagnostics.
No scanner scheduling, decisions, or execution behavior is changed.
"""
from __future__ import annotations
import datetime as dt
import os
import time
import uuid
from pathlib import Path
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
        stat = Path(f"/proc/{int(pid)}/stat").read_text(encoding="ascii")
        _, separator, fields = stat.rpartition(")")
        if not separator:
            return None
        values = fields.split()
        return int(values[19])
    except (OSError, ValueError, IndexError):
        return None

def _safe_write(path, record):
    try:
        append_bounded(os.getenv("APEX_MEMORY_PAIR_PATH", MEMORY_PATH) if path == MEMORY_PATH else os.getenv("APEX_SCAN_COVERAGE_PATH", SCAN_PATH), record)
    except (OSError, ValueError) as exc:
        print(f"[APEX DIAGNOSTICS] write unavailable: {type(exc).__name__}", flush=True)

def begin_stage(cycle_id, stage):
    try:
        pid = os.getpid()
        return (time.monotonic(), snapshot(scanner_pid=pid, stage=f"{stage}_START"),
                pid, _process_start_ticks(pid))
    except (OSError, ValueError):
        return (time.monotonic(), {}, os.getpid(), None)

def end_stage(cycle_id, stage, started, outcome="COMPLETED"):
    if len(started) == 2:
        start_time, before = started
        pid, start_ticks = os.getpid(), None
    else:
        start_time, before, pid, start_ticks = started
    try:
        after = snapshot(scanner_pid=pid, stage=f"{stage}_END")
        a, b = _rss(before), _rss(after)
        deltas = {key: (b[key] - a[key]) for key in ("rss_kib", "pss_kib", "private_dirty_kib") if isinstance(a.get(key), int) and isinstance(b.get(key), int)}
        end_ticks = _process_start_ticks(pid)
        identity = ("PROCESS_START_UNAVAILABLE" if start_ticks is None or end_ticks is None else
                    "VERIFIED" if start_ticks == end_ticks else "PROCESS_IDENTITY_CHANGED")
        _safe_write(MEMORY_PATH, {"schema":"apex.memory_pair.v1", "cycle_id":cycle_id, "stage":stage,
          "observed_at":dt.datetime.now(dt.timezone.utc).isoformat(), "elapsed_ms":round((time.monotonic()-start_time)*1000,1),
          "outcome":outcome,"before":a,"after":b,"delta_kib":deltas,
          "cgroup_before":before.get("cgroup"),"cgroup_after":after.get("cgroup"),
          "process_pid":pid,"process_start_ticks":start_ticks,
          "process_identity_verified":identity == "VERIFIED","identity_diagnostic":identity,
          "decision_authority":False,"execution_authority":False})
    except (OSError, ValueError, TypeError) as exc:
        print(f"[APEX DIAGNOSTICS] stage unavailable: {type(exc).__name__}", flush=True)

def scan_event(cycle_id, event, *, reason=None, details=None):
    _safe_write(SCAN_PATH, {"schema":"apex.scan_coverage.v1", "cycle_id":cycle_id,
      "event":event,"reason":reason,"details":details or {},
      "observed_at":dt.datetime.now(dt.timezone.utc).isoformat(),
      "decision_authority":False,"execution_authority":False})
