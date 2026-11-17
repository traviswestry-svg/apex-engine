#!/usr/bin/env python3
"""APEX 3B.2.2: bounded metadata-only archive size/provenance audit.

No archive BLOB or canonical JSON is selected. Only fixed-source indexed identity
lookups and bounded archive metadata samples. NOT a full population survey, integrity
verification, replay, or migration permission. No imports from runtime APEX modules.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import time
from pathlib import Path

SCHEMA = "apex.stage3b22_archive_size_identity_provenance.v1"
ARCHIVE = "apex_historical_payload_archive.db"
# From engine/historical_payload_archive.py PAYLOAD_TYPES (2026-11-12 source snapshot)
SPECS = {
    "DECISION_SNAPSHOT": ("apex_evidence_pipeline.db", "decisions", "decision_id", "snapshot_json", "observed_at"),
    "TRIGGER_EVIDENCE": ("apex_trigger_observatory.db", "observed_trade_triggers", "trigger_id", "evidence_json", "triggered_at"),
}
BINS = ((16384, "under_16KiB"), (65536, "16_to_64KiB"),
        (262144, "64_to_256KiB"), (1048576, "256KiB_to_1MiB"),
        (4194304, "1_to_4MiB"), (None, "over_4MiB"))
META_QUERY = """SELECT rowid AS probe_rowid, payload_type, row_id, source_table,
source_column, observed_at, archived_at, source_bytes, archive_bytes,
archive_codec, apex_version, schema_version, integrity_status
FROM historical_payload_archive WHERE payload_type=? ORDER BY rowid {order} LIMIT ?"""


def connect_readonly(path: Path):
    if not path.is_file():
        return None
    con = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=0.20)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=ON")
    return con


def bounded(con, sql, params, deadline, query_ms, *, many=False):
    if time.monotonic() >= deadline:
        return None, "GLOBAL_TIME_BUDGET_EXCEEDED"
    stop = min(deadline, time.monotonic() + query_ms / 1000.0)
    ticks = [0]
    def callback():
        ticks[0] += 1
        return 1 if ticks[0] > 20000 or time.monotonic() >= stop else 0
    con.set_progress_handler(callback, 100)
    try:
        cursor = con.execute(sql, params)
        return (cursor.fetchall() if many else cursor.fetchone()), None
    except sqlite3.Error as exc:
        if "interrupted" in str(exc).lower():
            return None, "QUERY_BUDGET_EXCEEDED"
        return None, "SQLITE_READ_UNAVAILABLE"
    finally:
        con.set_progress_handler(None, 0)


def bucket(n):
    for upper, label in BINS:
        if upper is None or n < upper:
            return label
    raise AssertionError("unreachable")


def size_summary(values):
    if not values:
        return {"samples": 0}
    ordered = sorted(values)
    return {"samples": len(values), "min_bytes": ordered[0],
            "median_bytes": ordered[(len(values) - 1)//2], "max_bytes": ordered[-1],
            "mean_bytes": round(sum(values)/len(values), 2),
            "over_256KiB": sum(x > 262144 for x in values),
            "buckets": {label: sum(bucket(x)==label for x in values)
                        for _, label in BINS}}


def tally(d, key):
    d[key] = d.get(key, 0) + 1


def safe_version(value):
    # Version text may be output only when it matches a short, known-safe token.
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,32}", value) else "OTHER_OR_MISSING"


def safe_month(value):
    if isinstance(value, str) and re.match(r"^\d{4}-(0[1-9]|1[0-2])-", value):
        return value[:7]
    return "UNKNOWN_OR_INVALID"


def index_plan_supported(con, table, column, deadline, query_ms):
    rows, error = bounded(con,
        f'EXPLAIN QUERY PLAN SELECT "{column}" FROM "{table}" WHERE "{column}"=? LIMIT 1',
        ("__APEX_PROBE_NONEXISTENT__",), deadline, query_ms, many=True)
    if error or not rows:
        return False
    detail = " ".join(str(r[3]).upper() for r in rows)
    return "SEARCH " in detail and "SCAN " not in detail


def run(root: Path, *, sample_rows=16, query_ms=400, total_ms=8000):
    sample_rows = max(1, min(int(sample_rows), 32))
    query_ms = max(20, min(int(query_ms), 1000))
    total_ms = max(100, min(int(total_ms), 15000))
    report = {
        "schema": SCHEMA, "mode": "READ_ONLY_METADATA_FIRST", "migration_authority": "BLOCKED_RESEARCH_ONLY",
        "production_replay_performed": False, "archive_blob_read": False, "source_payload_read": False,
        "population_size_distribution_established": False,
        "limits": {"max_rows_per_type_per_edge": sample_rows, "max_unique_rows_per_type": sample_rows * 2,
                   "query_budget_ms": query_ms, "total_budget_ms": total_ms},
        "guardrails": {"no_sqlite_writes": True, "no_checkpoint": True, "no_vacuum": True,
                       "no_deletion": True, "no_payload_or_identifiers_exported": True,
                       "no_decompression": True, "source_lookup_requires_index": True,
                       "no_trade_execution_authority": True},
        "types": {}, "remaining_gates": ["real_archive_payload_integrity", "archive_source_byte_correspondence",
            "production_replay_equivalence", "canonical_gamma_and_decision_identity", "reader_cutover_coverage",
            "exhaustive_historical_correspondence", "external_backup_restore", "isolated_restore_rollback",
            "stage3b1_reader_utf8_failure_fix_verified"],
    }
    deadline = time.monotonic() + total_ms / 1000
    archive = connect_readonly(root / ARCHIVE)
    if archive is None:
        report["status"] = "ARCHIVE_DATABASE_NOT_FOUND"
        return report
    try:
        for kind, (filename, table, key, field, timestamp) in SPECS.items():
            result = {"status": "NOT_STARTED", "sampled_unique": 0, "oldest_sample_size": 0,
                "newest_sample_size": 0, "overlapping_window_rows": 0,
                "metadata_state_counts": {}, "source_lookup_counts": {}, "time_agreement_counts": {},
                "format_state_counts": {}, "archive_version_counts": {},
                "archive_schema_counts": {}, "archive_integrity_label_counts": {},
                "sampled_archived_months": {}, "archive_metadata_not_payload_verified": True,
                "size_distributions_are_sample_only": True, "identity_values_exported": False}
            report["types"][kind] = result
            if time.monotonic() >= deadline:
                result["status"] = "GLOBAL_TIME_BUDGET_EXCEEDED"; continue
            cohorts = {}
            for label, order in (("oldest", "ASC"), ("newest", "DESC")):
                rows, err = bounded(archive, META_QUERY.format(order=order), (kind, sample_rows), deadline, query_ms, many=True)
                if err:
                    tally(result["metadata_state_counts"], err)
                    cohorts[label] = []
                else:
                    cohorts[label] = rows
            result["oldest_sample_size"] = len(cohorts["oldest"])
            result["newest_sample_size"] = len(cohorts["newest"])
            seen = set()
            unique_rows = []
            for edge in ("oldest", "newest"):
                for item in cohorts[edge]:
                    if item["probe_rowid"] not in seen:
                        seen.add(item["probe_rowid"])
                        unique_rows.append(item)
                    else:
                        result["overlapping_window_rows"] += 1
            result["sampled_unique"] = len(unique_rows)
            for edge in ("oldest", "newest"):
                values = [int(x["source_bytes"]) for x in cohorts[edge]
                          if type(x["source_bytes"]) is int and x["source_bytes"] >= 0]
                compressed = [int(x["archive_bytes"]) for x in cohorts[edge]
                              if type(x["archive_bytes"]) is int and x["archive_bytes"] >= 0]
                result[edge + "_source_bytes"] = size_summary(values)
                result[edge + "_archive_bytes"] = size_summary(compressed)
            source = connect_readonly(root / filename)
            indexed = False
            if source is not None:
                indexed = index_plan_supported(source, table, key, deadline, query_ms)
            result["source_identity_access"] = "INDEXED_LOOKUP" if indexed else ("NO_SOURCE_DB" if source is None else "NO_VERIFIED_INDEX_PLAN")
            try:
                for item in unique_rows:
                    tally(result["archive_version_counts"], safe_version(item["apex_version"]))
                    tally(result["archive_schema_counts"], safe_version(item["schema_version"]))
                    tally(result["archive_integrity_label_counts"], safe_version(item["integrity_status"]))
                    tally(result["sampled_archived_months"], safe_month(item["archived_at"]))
                    if time.monotonic() >= deadline:
                        tally(result["metadata_state_counts"], "GLOBAL_TIME_BUDGET_EXCEEDED")
                        result["status"] = "PARTIAL_GLOBAL_TIME_BUDGET_EXCEEDED"
                        break
                    if item["payload_type"] != kind or item["source_table"] != table or item["source_column"] != field:
                        tally(result["metadata_state_counts"], "TYPE_TABLE_COLUMN_CONFLICT")
                        continue
                    sb, ab = item["source_bytes"], item["archive_bytes"]
                    if type(sb) is not int or type(ab) is not int or sb < 0 or ab < 0:
                        tally(result["metadata_state_counts"], "INVALID_DECLARED_SIZE")
                        continue
                    tally(result["metadata_state_counts"], "EXPECTED_TYPE_TABLE_COLUMN")
                    if item["archive_codec"] != "ZLIB_9":
                        tally(result["format_state_counts"], "UNSUPPORTED_CODEC")
                    else:
                        tally(result["format_state_counts"], "ZLIB_9_DECLARED")
                    # These are metadata-only plausibility states, NOT integrity checks.
                    if sb > 0 and ab == 0:
                        tally(result["format_state_counts"], "ZERO_COMPRESSED_SIZE_WITH_SOURCE_BYTES")
                    if sb > 0 and ab > 0:
                        tally(result["format_state_counts"], "NONZERO_SIZES_DECLARED")
                    if not indexed:
                        tally(result["source_lookup_counts"], "SKIPPED_NO_VERIFIED_INDEX")
                        continue
                    row, err = bounded(source,
                        f'SELECT "{key}" AS source_identity,"{timestamp}" AS source_time FROM "{table}" WHERE "{key}"=? LIMIT 1',
                        (item["row_id"],), deadline, query_ms)
                    if err:
                        tally(result["source_lookup_counts"], err)
                    elif row is None:
                        tally(result["source_lookup_counts"], "SOURCE_ID_NOT_FOUND")
                    else:
                        tally(result["source_lookup_counts"], "SOURCE_ID_FOUND")
                        a, b = item["observed_at"], row["source_time"]
                        if a is None or b is None:
                            tally(result["time_agreement_counts"], "MISSING_TIMESTAMP")
                        elif a == b:
                            tally(result["time_agreement_counts"], "EXACT_TEXT_AGREEMENT")
                        else:
                            tally(result["time_agreement_counts"], "TEXT_DIFFERENCE_NOT_PROOF_OF_WRONG_IDENTITY")
                else:
                    result["status"] = "SAMPLED_METADATA_ONLY"
                if not unique_rows and result["status"] == "NOT_STARTED":
                    result["status"] = "NO_ROWS_OR_METADATA_QUERY_UNAVAILABLE"
            finally:
                if source is not None:
                    source.close()
        report["status"] = "METADATA_PROVENANCE_SAMPLED_MIGRATION_BLOCKED"
        return report
    finally:
        archive.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="/data")
    parser.add_argument("--output", required=True)
    parser.add_argument("--sample-rows", type=int, default=16)
    parser.add_argument("--query-budget-ms", type=int, default=400)
    parser.add_argument("--total-budget-ms", type=int, default=8000)
    args = parser.parse_args()
    root = Path(args.root).resolve(); output = Path(args.output).resolve()
    if root == output or root in output.parents:
        parser.error("report output must be outside production SQLite root")
    result = run(root, sample_rows=args.sample_rows, query_ms=args.query_budget_ms, total_ms=args.total_budget_ms)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f'Stage 3B.2.2 report: {output} | migration={result["migration_authority"]} | status={result["status"]}')

if __name__ == "__main__":
    main()
