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

def _process_start_ticks(pid):
    try:
        stat = Path(f"/proc/{int(pid)}/stat").read_text(encoding="ascii")
        _, _, fields = stat.rpartition(")")
        value = int(fields.split()[19])
        return value if value > 0 else None
    except (OSError, ValueError, IndexError):
        return None

def _rss(record):
    return ((record.get("processes") or {}).get("scanner") or {}).get("memory") or {}

def _process_start_ticks(pid):
    try:
        stat = Path(f"/proc/{int(pid)}/stat").read_text()
        ticks = int(stat.rsplit(")", 1)[1].split()[19])
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
    start_ticks = _process_start_ticks(pid)
    try:
        return (time.monotonic(), snapshot(scanner_pid=pid, stage=f"{stage}_START"), pid, start_ticks)
    except (OSError, ValueError):
        return (time.monotonic(), {}, pid, start_ticks)
        pid = os.getpid()
        return (time.monotonic(), snapshot(scanner_pid=pid, stage=f"{stage}_START"),
                pid, _process_start_ticks(pid))
    except (OSError, ValueError):
        return (time.monotonic(), {}, os.getpid(), None)

def end_stage(cycle_id, stage, started, outcome="COMPLETED"):
    start_time, before, pid, start_ticks = started
    try:
        end_pid = os.getpid()
        end_ticks = _process_start_ticks(end_pid)
        verified = pid == end_pid and start_ticks is not None and start_ticks == end_ticks
        identity = ("VERIFIED" if verified else "PROCESS_START_UNAVAILABLE"
                    if start_ticks is None or end_ticks is None else "PROCESS_IDENTITY_CHANGED")
        after = snapshot(scanner_pid=end_pid, stage=f"{stage}_END")
        a, b = _rss(before), _rss(after)
        deltas = {key: (b[key] - a[key]) for key in ("rss_kib", "pss_kib", "private_dirty_kib") if isinstance(a.get(key), int) and isinstance(b.get(key), int)}
        end_ticks = _process_start_ticks(pid)
        valid_start = type(start_ticks) is int and start_ticks > 0
        valid_end = type(end_ticks) is int and end_ticks > 0
        identity_verified = valid_start and valid_end and start_ticks == end_ticks
        identity_diagnostic = ("VERIFIED" if identity_verified else
                               "PROCESS_IDENTITY_CHANGED" if valid_start and valid_end else
                               "PROCESS_START_UNAVAILABLE")
        _safe_write(MEMORY_PATH, {"schema":"apex.memory_pair.v1", "cycle_id":cycle_id, "stage":stage,
          "observed_at":dt.datetime.now(dt.timezone.utc).isoformat(), "elapsed_ms":round((time.monotonic()-start_time)*1000,1),
          "outcome":outcome,"before":a,"after":b,"delta_kib":deltas,
          "process_pid":pid,"process_start_ticks":start_ticks,
          "process_identity_verified":verified,"identity_diagnostic":identity,
          "cgroup_before":before.get("cgroup"),"cgroup_after":after.get("cgroup"),
          "process_pid":pid,"process_start_ticks":start_ticks,
          "process_identity_verified":identity_verified,"identity_diagnostic":identity_diagnostic,
          "decision_authority":False,"execution_authority":False})
    except (OSError, ValueError, TypeError) as exc:
        print(f"[APEX DIAGNOSTICS] stage unavailable: {type(exc).__name__}", flush=True)

def scan_event(cycle_id, event, *, reason=None, details=None):
    _safe_write(SCAN_PATH, {"schema":"apex.scan_coverage.v1", "cycle_id":cycle_id,
      "event":event,"reason":reason,"details":details or {},
      "observed_at":dt.datetime.now(dt.timezone.utc).isoformat(),
      "decision_authority":False,"execution_authority":False})
