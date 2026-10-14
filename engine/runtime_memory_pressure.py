"""Read-only cgroup v2 memory classification for APEX operational health.

Raw usage includes reclaimable file cache. Estimated non-inactive-file usage
is a heuristic, not a promise of available memory. PSI and events are reported
separately. No allocation, cache clearing, or execution authority.
"""
from __future__ import annotations
import pathlib
from typing import Any, Dict

VERSION = "69.10.38-runtime-observability-candidate"


def _read_int(path: pathlib.Path):
    try:
        value = path.read_text().strip()
        return None if value == "max" else int(value)
    except (OSError, ValueError):
        return None


def _read_kv(path: pathlib.Path) -> Dict[str, int]:
    try:
        return {k: int(v) for line in path.read_text().splitlines()
                if len(parts := line.split()) == 2
                for k, v in [parts]}
    except (OSError, ValueError):
        return {}


def classify_memory(*, current: int | None, limit: int | None,
                    inactive_file: int = 0, events: dict | None = None,
                    psi_some_avg10: float | None = None,
                    psi_full_avg10: float | None = None) -> Dict[str, Any]:
    events = events or {}
    raw_pct = round(current / limit * 100, 2) if current is not None and limit and limit > 0 else None
    inactive = min(max(0, inactive_file), current or 0)
    estimated_noninactive = max(0, current - inactive) if current is not None else None
    estimated_pct = round(estimated_noninactive / limit * 100, 2) if estimated_noninactive is not None and limit and limit > 0 else None
    # Event counters are cumulative since cgroup creation: report, do not infer a new event.
    oom = int(events.get("oom", 0)) + int(events.get("oom_kill", 0))
    if raw_pct is None:
        severity = "UNKNOWN"
    elif oom > 0 or (psi_full_avg10 is not None and psi_full_avg10 >= 1.0):
        severity = "CRITICAL"
    elif (estimated_pct is not None and estimated_pct >= 90) or (psi_some_avg10 is not None and psi_some_avg10 >= 5.0):
        severity = "HIGH_PRESSURE"
    elif raw_pct >= 90:
        severity = "HIGH_RAW_USAGE_NO_CONFIRMED_PRESSURE"
    else:
        severity = "NORMAL"
    return {
        "version": VERSION, "severity": severity,
        "raw_usage_pct": raw_pct, "estimated_noninactive_file_usage_pct": estimated_pct,
        "current_bytes": current, "limit_bytes": limit,
        "inactive_file_bytes": inactive,
        "estimated_noninactive_file_bytes": estimated_noninactive,
        "psi_some_avg10": psi_some_avg10, "psi_full_avg10": psi_full_avg10,
        "cgroup_events_cumulative": events,
        "note": "Inactive file cache is often reclaimable; this is not a guaranteed free-memory estimate. OOM counters are cumulative.",
        "read_only": True, "execution_authority": False, "decision_authority": False,
    }


def _psi_avg10(path: pathlib.Path, category: str):
    try:
        for line in path.read_text().splitlines():
            parts = line.split()
            if parts and parts[0] == category:
                return float(next(p.split("=", 1)[1] for p in parts[1:] if p.startswith("avg10=")))
    except (OSError, ValueError, StopIteration):
        pass
    return None


def memory_pressure_status(root: str = "/sys/fs/cgroup") -> Dict[str, Any]:
    base = pathlib.Path(root)
    stat = _read_kv(base / "memory.stat")
    return classify_memory(
        current=_read_int(base / "memory.current"),
        limit=_read_int(base / "memory.max"),
        inactive_file=stat.get("inactive_file", 0),
        events=_read_kv(base / "memory.events"),
        psi_some_avg10=_psi_avg10(base / "memory.pressure", "some"),
        psi_full_avg10=_psi_avg10(base / "memory.pressure", "full"),
    )
