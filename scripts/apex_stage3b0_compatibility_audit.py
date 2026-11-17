#!/usr/bin/env python3
"""APEX Stage 3B.0: OFFLINE, NON-MUTATING evidence compression feasibility.

No production SQLite connection, no import of application modules, no migrations.
Inspects local source text and performs synthetic in-memory round-trip benchmarks.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
import time
import tracemalloc
import zlib
from pathlib import Path

SCHEMA = "apex.stage3b0_offline_compression_compatibility.v1"
TARGETS = {
    "decisions.snapshot_json": "CANONICAL_DECISION_EVIDENCE",
    "observed_trade_triggers.evidence_json": "TRIGGER_EVIDENCE",
    "observed_trade_triggers.blocker_codes_json": "TRIGGER_BLOCKERS",
    "observed_trade_triggers.etrade_handoff_json": "EXECUTION_HANDOFF_EVIDENCE",
    "observed_trade_triggers.canonical_grade_json": "CANONICAL_TRIGGER_GRADE",
    "flow_features.features_json": "FEATURE_PROVENANCE",
    "flow_features.availability_json": "FEATURE_AVAILABILITY",
    "gamma_observational_snapshots.snapshot_json": "CANONICAL_GAMMA_EVIDENCE",
    "gamma_observational_snapshots.lineage_json": "GAMMA_LINEAGE",
    "level_transition_observations.target_cluster_json": "CALIBRATION_HISTORY",
}
# Synthetic sizes are illustrative, not samples or extrapolations from the live data.
FIXTURES = {
    "synthetic_decision": {"snapshot": {f"feature_{i:03d}": {"available": True, "value": i/17, "description": "source_evidence"} for i in range(260)}, "gamma_id": "synthetic-id", "observed_at": "synthetic-time"},
    "synthetic_feature_availability": {f"feature_{i:03d}": {"available": True, "reason": "synthetic_available", "source": "synthetic"} for i in range(84)},
    "synthetic_trigger": {"blockers": [], "evidence": {"source": "synthetic", "sequence": [i for i in range(64)]}, "handoff": {"paper": True, "execution_authority": False}},
    "synthetic_gamma": {"identity": "synthetic-gamma", "lineage": [{"source": "synthetic", "time": i} for i in range(12)]},
    "synthetic_calibration": {"target_cluster": [{"level": i, "distance": i/8} for i in range(24)]},
}


def strict_zlib_decode(blob: bytes, *, max_output_bytes: int = 1_048_576) -> bytes:
    """Defensive fixture decoder: fail closed on expansion/trailing bytes/truncation."""
    if max_output_bytes < 1 or len(blob) > max_output_bytes:
        raise ValueError("input_limit")
    dec = zlib.decompressobj()
    raw = dec.decompress(blob, max_output_bytes + 1)
    if len(raw) > max_output_bytes:
        raise ValueError("output_limit")
    if dec.unconsumed_tail or not dec.eof or dec.unused_data:
        raise ValueError("invalid_or_trailing_stream")
    tail = dec.flush(max_output_bytes - len(raw) + 1)
    if len(raw) + len(tail) > max_output_bytes:
        raise ValueError("output_limit")
    return raw + tail


def roundtrip(raw: bytes, level: int) -> dict:
    compressed = zlib.compress(raw, level)
    recovered = strict_zlib_decode(compressed)
    if recovered != raw or hashlib.sha256(recovered).digest() != hashlib.sha256(raw).digest():
        raise AssertionError("not_byte_exact")
    return {"codec": f"ZLIB_{level}", "raw_bytes": len(raw), "compressed_bytes": len(compressed),
            "ratio": round(len(compressed)/len(raw), 5) if raw else None, "byte_exact": True}


def benchmark_fixture(name: str, obj: object, *, repetitions: int = 15) -> dict:
    raw = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    stats = []
    for level in (6, 9):
        compressed = zlib.compress(raw, level)
        strict_zlib_decode(compressed)
        c_ms, d_ms = [], []
        tracemalloc.start()
        try:
            for _ in range(repetitions):
                start = time.perf_counter_ns()
                blob = zlib.compress(raw, level)
                c_ms.append((time.perf_counter_ns() - start)/1e6)
                start = time.perf_counter_ns()
                restored = strict_zlib_decode(blob)
                d_ms.append((time.perf_counter_ns() - start)/1e6)
                assert restored == raw
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        stats.append({**roundtrip(raw, level), "compress_median_ms": round(statistics.median(c_ms), 5),
                      "decompress_median_ms": round(statistics.median(d_ms), 5),
                      "peak_traced_bytes": peak})
    return {"fixture": name, "synthetic_only": True, "no_source_payloads": True, "benchmarks": stats}


def source_inventory(repo: Path, *, file_limit: int = 1200, line_limit: int = 100_000) -> dict:
    root = repo / "engine"
    if not root.is_dir():
        return {"state": "ENGINE_SOURCE_MISSING", "files_scanned": 0, "references": {}, "complete": False}
    found = {target: [] for target in TARGETS}
    count = total_lines = 0
    all_files = sorted(root.rglob("*.py"))
    capped = len(all_files) > file_limit
    for path in all_files[:file_limit]:
        if total_lines >= line_limit:
            capped = True
            break
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            capped = True
            continue
        count += 1
        for i, line in enumerate(lines):
            total_lines += 1
            if total_lines > line_limit:
                capped = True
                break
            for target in TARGETS:
                column = target.split(".", 1)[1]
                if not re.search(r"\b" + re.escape(column) + r"\b", line):
                    continue
                # Only bounded contextual hints, never claim definitive use/ownership.
                context = " ".join(lines[max(0, i-2): min(len(lines), i+3)]).lower()
                category = "REFERENCE_UNCLASSIFIED"
                if re.search(r"json\.loads|json\.load\(|select\b|\[.[a-z_]+_json.\]|\.get\(", context):
                    category = "POTENTIAL_READER"
                if re.search(r"\binsert\b|\bupdate\b|json\.dumps|_json\(", context):
                    category = "POTENTIAL_WRITER_OR_TRANSFORMER" if category == "REFERENCE_UNCLASSIFIED" else "POTENTIAL_READ_WRITE"
                if len(found[target]) < 60:
                    found[target].append({"path": str(path.relative_to(repo)), "line": i+1, "kind_hint": category})
    return {"state": "BOUNDED_SOURCE_INVENTORY", "files_scanned": count, "lines_scanned": total_lines,
            "complete": not capped, "references": {k: {"count_capped": len(v) >= 60, "sample": v, "classification_verified": False} for k,v in found.items()}}


def check_existing_contracts(repo: Path) -> dict:
    files = {
        "archive": repo / "engine/historical_payload_archive.py",
        "compaction": repo / "engine/historical_payload_compaction.py",
        "evidence_pipeline": repo / "engine/evidence_pipeline.py",
        "trigger_observatory": repo / "engine/trigger_observatory.py",
    }
    contents = {key: p.read_text(encoding="utf-8") if p.is_file() else "" for key,p in files.items()}
    archive = contents["archive"]
    compaction = contents["compaction"]
    return {
        "historical_archive_source_present": bool(archive),
        "existing_archive_versioned_codec_ZLIB_9": bool(re.search(r'ZLIB_9', archive)),
        "existing_archive_source_sha256": "source_sha256" in archive,
        "existing_archive_immutable_triggers": "trg_historical_payload_archive_no_delete" in archive and "trg_historical_payload_archive_no_update" in archive,
        "existing_archive_reader": "def retrieve_archived_payload(" in archive,
        "existing_archive_applicable_payload_types": [s for s in ("TRIGGER_EVIDENCE", "DECISION_SNAPSHOT") if f'"{s}"' in archive],
        "existing_compaction_dependency_contracts": "DECISION_SNAPSHOT_DEPENDENCIES" in compaction and "TRIGGER_EVIDENCE_DEPENDENCIES" in compaction,
        "inline_decision_json_reader_detected": 'json.loads(row["snapshot_json"])' in contents["evidence_pipeline"] or "json.loads(row['snapshot_json'])" in contents["evidence_pipeline"],
        "compatibility_verified": False,
        "code_review_not_production_behavior_proof": True,
    }


def produce(repo: Path, *, files: int = 1200, lines: int = 100_000, iterations: int = 15) -> dict:
    if iterations < 1 or iterations > 50:
        raise ValueError("iterations must be 1..50")
    inventory = source_inventory(repo, file_limit=files, line_limit=lines)
    existing = check_existing_contracts(repo)
    fixtures = [benchmark_fixture(k,v,repetitions=iterations) for k,v in FIXTURES.items()]
    blockers = [
        "SOURCE_REFERENCE_HINTS_ARE_NOT_EXHAUSTIVE_READER_WRITER_PROOF",
        "PRODUCTION_READERS_NOT_SHADOW_VALIDATED",
        "HISTORICAL_BYTE_EXACT_REPLAY_NOT_PROVEN",
        "CANONICAL_GAMMA_AND_SETTLEMENT_IDENTITY_NOT_RECONCILED",
        "CROSS_DATABASE_DEPENDENCIES_NOT_VERIFIED",
        "EXTERNAL_BACKUP_AND_RESTORE_NOT_VERIFIED",
        "PRODUCTION_CPU_MEMORY_AND_LATENCY_NOT_BENCHMARKED",
        "NO_PRODUCTION_MIGRATION_ROLLBACK_EXERCISE",
        "DISK_RECLAIM_NOT_ESTABLISHED",
    ]
    if not existing["historical_archive_source_present"]:
        blockers.append("EXISTING_ARCHIVE_MODULE_NOT_PRESENT")
    return {
        "schema": SCHEMA, "mode": "OFFLINE_SOURCE_AND_SYNTHETIC_FIXTURES_ONLY",
        "target_columns": TARGETS, "existing_capabilities": existing,
        "source_reference_inventory": inventory, "synthetic_codec_benchmarks": fixtures,
        "migration_feasibility": {"status": "BLOCKED_RESEARCH_ONLY", "blockers": blockers,
            "recommendation": "Assess existing immutable ZLIB_9 archive and reader contracts before any new codec or storage migration",
            "production_migration_authorized": False, "retention_or_deletion_authorized": False,
            "shadow_reader_cutover_authorized": False, "backup_restore_verified": False,
            "disk_savings_estimated": False},
        "guardrails": {"sqlite_connections": 0, "source_payloads_loaded": False, "canonical_rows_mutated": False,
            "archives_created": False, "compressed_data_persisted": False,
            "live_execution_authority_changed": False, "no_deletion_vacuum_checkpoint": True},
        "limits": {"source_files_max": files, "source_lines_max": lines, "benchmark_iterations": iterations},
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo-root", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    p.add_argument("--source-file-limit", type=int, default=1200)
    p.add_argument("--source-line-limit", type=int, default=100000)
    p.add_argument("--benchmark-iterations", type=int, default=15)
    args = p.parse_args(argv)
    if not (1 <= args.source_file_limit <= 3000 and 100 <= args.source_line_limit <= 300000):
        p.error("source scan limits out of bounds")
    if not args.repo_root.is_dir():
        p.error("repo-root does not exist")
    if args.output.suffix.lower() != ".json":
        p.error("output must be a JSON report")
    # Safety: report cannot be placed inside repository or persistent /data.
    resolved = args.output.resolve()
    if resolved == args.repo_root.resolve() or args.repo_root.resolve() in resolved.parents or Path('/data') == resolved or Path('/data') in resolved.parents:
        p.error("output cannot be within repo or /data")
    report = produce(args.repo_root.resolve(), files=args.source_file_limit, lines=args.source_line_limit, iterations=args.benchmark_iterations)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Stage 3B.0 OFFLINE report: {args.output} | migration={report['migration_feasibility']['status']}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
