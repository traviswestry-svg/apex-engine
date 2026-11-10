"""Bounded read-only diagnostics for paired scanner and settlement phase memory.

Reads at most 128 KiB of the existing JSONL; never scans an entire file,
reads a database, samples additional processes, or infers a leak from a single event.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path

SCHEMA = "apex.scanner_settlement_phase_memory_attribution.v1"
DEFAULT_FILE = "/data/apex_runtime_memory_pairs.jsonl"
READ_BYTES = 131072
MAX_RECORDS = 64
VALID_STAGES = {"FULL_SCAN", "SETTLEMENT_PASS"}


def _int(value):
    return value if type(value) is int else None


def _difference(after, before):
    return after - before if after is not None and before is not None else None


def _record(raw):
    if not isinstance(raw, dict) or raw.get("stage") not in VALID_STAGES:
        return None
    pid, start = _int(raw.get("process_pid")), _int(raw.get("process_start_ticks"))
    if pid is None or start is None or raw.get("process_identity_verified") is not True:
        return None
    before = raw.get("before") or {}
    after = raw.get("after") or {}
    c0 = raw.get("cgroup_before") or {}
    c1 = raw.get("cgroup_after") or {}
    s0 = c0.get("memory_stat") or {}
    s1 = c1.get("memory_stat") or {}
    event0, event1 = c0.get("events") or {}, c1.get("events") or {}
    return {
        "process_pid": pid, "process_start_ticks": start,
        "stage": raw["stage"], "cycle_id": str(raw.get("cycle_id") or "")[:90],
        "observed_at": raw.get("observed_at"), "outcome": raw.get("outcome"),
        "elapsed_ms": raw.get("elapsed_ms"),
        "rss_before_kib": _int(before.get("rss_kib")),
        "rss_after_kib": _int(after.get("rss_kib")),
        "rss_delta_kib": _difference(_int(after.get("rss_kib")), _int(before.get("rss_kib"))),
        "private_dirty_delta_kib": _difference(_int(after.get("private_dirty_kib")), _int(before.get("private_dirty_kib"))),
        "cgroup_current_delta_bytes": _difference(_int(c1.get("current_bytes")), _int(c0.get("current_bytes"))),
        "cgroup_anon_delta_bytes": _difference(_int(s1.get("anon_bytes")), _int(s0.get("anon_bytes"))),
        "cgroup_file_delta_bytes": _difference(_int(s1.get("file_bytes")), _int(s0.get("file_bytes"))),
        "max_events_delta": _difference(_int(event1.get("max")), _int(event0.get("max"))),
        "oom_kill_events_delta": _difference(_int(event1.get("oom_kill")), _int(event0.get("oom_kill"))),
    }


def summarize(records):
    """Only compare records with the same verified Linux process start identity."""
    valid = [r for r in (_record(item) for item in records) if r is not None]
    grouped = defaultdict(list)
    for record in valid:
        grouped[(record["process_pid"], record["process_start_ticks"])].append(record)
    if not valid:
        return {"status": "NO_VERIFIED_PHASE_PAIRS", "verified_records": 0,
                "processes": [], "limitations": ["Legacy phase records lack verified process identity"]}
    # Preserve append order; choose newest observed process within bounded tail.
    keys = list(grouped)[-3:]
    processes = []
    for pid, ticks in reversed(keys):
        group = grouped[(pid, ticks)]
        phases = {}
        for stage in ("FULL_SCAN", "SETTLEMENT_PASS"):
            part = [r for r in group if r["stage"] == stage]
            rss = [r["rss_delta_kib"] for r in part if r["rss_delta_kib"] is not None]
            phases[stage] = {
                "sample_count": len(part), "last_completed": part[-1] if part else None,
                "max_observed_rss_increase_kib": max(rss) if rss else None,
                "max_observed_rss_decrease_kib": min(rss) if rss else None,
                "net_observed_phase_rss_delta_kib": sum(rss) if rss else None,
            }
        first = group[0]
        last = group[-1]
        processes.append({"pid": pid, "process_start_ticks": ticks,
                          "paired_records": len(group), "phases": phases,
                          "first_observed_at": first["observed_at"],
                          "last_observed_at": last["observed_at"],
                          "same_process_boundary_rss_delta_kib": _difference(last["rss_after_kib"], first["rss_before_kib"]),
                          "interpretation": "PHASE_CORRELATED_NOT_CAUSAL"})
    return {"status": "PHASE_PAIRS_AVAILABLE", "verified_records": len(valid),
            "processes": processes,
            "limitations": ["Per-stage delta includes concurrent work and retained allocations may occur outside the stage",
                            "Same-process phase boundaries do not isolate Python heap or SQLite cache",
                            "Records without verified process start time are excluded",
                            "Only a bounded tail of existing phase records is inspected"]}


def inspect(*, path=None):
    file_path = Path(path or os.getenv("APEX_MEMORY_PAIR_PATH", DEFAULT_FILE))
    try:
        with file_path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            offset = max(0, size - READ_BYTES)
            handle.seek(offset)
            data = handle.read(READ_BYTES)
        # If seeking into a record, discard that partial record.
        if offset:
            data = data.partition(b"\n")[2]
        # Discard incomplete trailing record, if any.
        if data and not data.endswith(b"\n"):
            data = data.rpartition(b"\n")[0] + b"\n"
        records = []
        for line in data.splitlines()[-MAX_RECORDS:]:
            try:
                records.append(json.loads(line))
            except (UnicodeError, ValueError, TypeError):
                continue
        summary = summarize(records)
        summary.update({"source": "existing_paired_runtime_diagnostics_jsonl",
                        "bounded_read_max_bytes": READ_BYTES, "max_records": MAX_RECORDS,
                        "source_bytes": size})
    except OSError:
        summary = {"status": "PHASE_TRACE_UNAVAILABLE", "verified_records": 0,
                   "processes": [], "source": "existing_paired_runtime_diagnostics_jsonl"}
    summary.update({"schema": SCHEMA, "observed_at": datetime.now(timezone.utc).isoformat(),
                    "read_only": True, "db_reads": False, "decision_authority": False,
                    "execution_authority": False, "changes_trade_decisions": False,
                    "automatic_reclamation": False})
    return summary
