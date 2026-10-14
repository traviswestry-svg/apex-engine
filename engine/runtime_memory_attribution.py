"""APEX runtime memory attribution, observation-only, Linux /proc + cgroup v2.

No trading, database, or scanner controls. Designed to run as a small sidecar.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import time
from datetime import datetime, timezone


def _read_int(path):
    try:
        value = Path(path).read_text().strip()
        return int(value) if value.isdecimal() else None
    except (OSError, ValueError):
        return None


def _smaps(pid):
    try:
        lines = Path(f"/proc/{int(pid)}/smaps_rollup").read_text().splitlines()
    except (OSError, ValueError):
        return None
    values = {}
    for line in lines:
        key, _, rest = line.partition(":")
        if key in {"Rss", "Pss", "Private_Dirty", "Private_Clean", "Shared_Dirty"}:
            try:
                values[key.lower() + "_kib"] = int(rest.strip().split()[0])
            except (ValueError, IndexError):
                pass
    return values


def _cgroup():
    root = Path(os.getenv("APEX_MEMORY_CGROUP_PATH", "/sys/fs/cgroup"))
    current = _read_int(root / "memory.current")
    maximum = _read_int(root / "memory.max")
    peak = _read_int(root / "memory.peak")
    events = {}
    try:
        for line in (root / "memory.events").read_text().splitlines():
            key, _, value = line.partition(" ")
            if key in {"oom", "oom_kill", "high", "max"}:
                events[key] = int(value)
    except (OSError, ValueError):
        pass
    return {"current_bytes": current, "limit_bytes": maximum, "peak_bytes": peak,
            "usage_pct": round(100 * current / maximum, 2) if current is not None and maximum else None,
            "events": events}


def snapshot(scanner_pid=None, web_pid=None, stage="PERIODIC"):
    processes = {}
    for name, pid in (("scanner", scanner_pid), ("gunicorn_master", web_pid)):
        if pid is not None:
            processes[name] = {"pid": int(pid), "memory": _smaps(pid)}
    return {"schema": "apex.runtime_memory.v1", "observed_at": datetime.now(timezone.utc).isoformat(),
            "stage": stage, "cgroup": _cgroup(), "processes": processes,
            "execution_authority": False, "decision_authority": False}


def append_bounded(path, record, max_bytes=2_000_000):
    """Bound disk usage; rotate at size limit. No database writes."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size >= max_bytes:
        target.replace(target.with_suffix(target.suffix + ".previous"))
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, separators=(",", ":"), default=str) + "\n")


def monitor(scanner_pid, web_pid, *, interval=15, output="/data/apex_runtime_memory.jsonl",
            warn_pct=80.0, critical_pct=92.0, iterations=None, sleep=time.sleep):
    interval = max(5, int(interval))
    count = 0
    previous_oom_kills = None
    while iterations is None or count < iterations:
        record = snapshot(scanner_pid, web_pid)
        pct = record["cgroup"]["usage_pct"]
        kills = record["cgroup"]["events"].get("oom_kill")
        record["severity"] = ("CRITICAL" if pct is not None and pct >= critical_pct else
                              "WARN" if pct is not None and pct >= warn_pct else "NORMAL")
        if kills is not None and previous_oom_kills is not None and kills > previous_oom_kills:
            record["severity"] = "OOM_KILL_DETECTED"
        if kills is not None:
            previous_oom_kills = kills
        try:
            append_bounded(output, record)
        except OSError as exc:
            print(f"[APEX MEMORY] telemetry write unavailable: {type(exc).__name__}", flush=True)
        if record["severity"] != "NORMAL":
            print(f"[APEX MEMORY] {record['severity']} cgroup_usage_pct={pct} "
                  f"scanner_pid={scanner_pid} web_pid={web_pid}", flush=True)
        count += 1
        if iterations is None or count < iterations:
            sleep(interval)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--scanner-pid", type=int, required=True)
    parser.add_argument("--web-pid", type=int, required=True)
    args = parser.parse_args()
    monitor(args.scanner_pid, args.web_pid,
            interval=int(os.getenv("APEX_MEMORY_SAMPLE_SECONDS", "15")),
            output=os.getenv("APEX_MEMORY_TELEMETRY_PATH", "/data/apex_runtime_memory.jsonl"))
