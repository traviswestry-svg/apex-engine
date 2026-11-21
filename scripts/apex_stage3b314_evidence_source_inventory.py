#!/usr/bin/env python3
"""APEX 3B.3.14: bounded, metadata-only historical evidence source inventory.

No row reads, no log content reads, no source execution, no writes to inputs.
The output names only database table/column metadata and opaque file references.
Candidate sources are *not* evidence of historical events or runtime activation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys
import time

SCHEMA = "apex.stage3b314_evidence_source_inventory.v1"
CATEGORIES = {
    "producer_origin": ("producer", "commit", "git_sha", "build_sha", "boot_id", "process_boot", "runtime_version", "deployment_id"),
    "runtime_execution": ("gamma_execution", "gamma_eval", "gamma_feature", "feature_enabled", "execution_event", "runtime_activation", "gamma_runtime"),
    "provider_capture": ("provider_capture", "received_at", "ingested_at", "persisted_at", "capture_at", "receipt_at", "source_received"),
    "decision_linkage": ("decision_id", "canonical_gamma_snapshot_id", "gamma_snapshot_id", "snapshot_id", "decision_at", "decision_time"),
}
DB_EXTENSIONS = (".db", ".sqlite", ".sqlite3", ".db3")
TRACE_EXTENSIONS = (".jsonl", ".ndjson", ".log", ".json")
MAX_NAME_LENGTH = 120


def safe_ident(s: str) -> str:
    """Canonicalized schema identifier, sanitized for terminal/JSON use."""
    return re.sub(r"[^a-zA-Z0-9_]+", "_", str(s))[:MAX_NAME_LENGTH]


def opaque_id(relative: str) -> str:
    return hashlib.sha256(relative.encode("utf-8")).hexdigest()[:20]


def classify(parts: list[str]) -> dict[str, list[str]]:
    t = " ".join(parts).lower()
    # Only metadata signals; never classify as verified historical evidence.
    return {k: sorted(set(word for word in keywords if word in t)) for k, keywords in CATEGORIES.items()
            if any(word in t for word in keywords)}


def load_prior(path: Path | None):
    if path is None:
        return "NOT_SUPPLIED", None
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 2_000_000:
            return "INVALID", None
        data = json.loads(path.read_text(encoding="utf-8"))
        if (data.get("schema") != "apex.stage3b313_producer_origin_runtime_activation_evidence.v1"
                or data.get("migration_authority") != "BLOCKED_RESEARCH_ONLY"):
            return "INVALID", None
        return "READ_AND_SCHEMA_CHECKED", data.get("status")
    except (OSError, UnicodeError, ValueError, TypeError):
        return "INVALID", None


def inspect_sqlite(path: Path, root: Path, max_tables: int, deadline: float):
    """Connect only mode=ro/query_only and read sqlite_master/pragma_table_info metadata."""
    rel = str(path.relative_to(root))
    result = {"file_ref": opaque_id(rel), "kind": "SQLITE_SCHEMA", "signals": {},
              "tables_with_signals": [], "table_count_inspected": 0, "status": "UNINSPECTED"}
    conn = None
    try:
        # Reject links at the file and ancestor levels (root is also validated).
        if path.is_symlink() or not path.is_file():
            result["status"] = "NOT_REGULAR_OR_SYMLINK"; return result
        uri = "file:" + str(path) + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=0.15)
        conn.execute("PRAGMA query_only=ON")
        conn.execute("PRAGMA trusted_schema=OFF")
        # SQLite PRAGMA metadata only; never scan or select table rows.
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name LIMIT ?", (max_tables+1,)).fetchall()
        if len(tables) > max_tables:
            result["status"] = "TABLE_LIMIT_EXCEEDED"; return result
        for (tbl,) in tables:
            if time.monotonic() > deadline:
                result["status"] = "TIME_BUDGET_EXCEEDED"; return result
            if not isinstance(tbl, str):
                continue
            # table-valued PRAGMA, parameterized table name. No interpolated SQL identifiers.
            cols = conn.execute("SELECT name FROM pragma_table_info(?) LIMIT 256", (tbl,)).fetchall()
            names = [safe_ident(x[0]) for x in cols if isinstance(x[0], str)]
            signals = classify([safe_ident(tbl), *names])
            result["table_count_inspected"] += 1
            if signals:
                result["tables_with_signals"].append({"table": safe_ident(tbl),
                    "matched_columns": {cat: [c for c in names if any(k in c.lower() for k in CATEGORIES[cat])][:16]
                         for cat in signals}, "categories": sorted(signals)})
                for cat in signals:
                    result["signals"][cat] = result["signals"].get(cat, 0) + 1
        result["status"] = "METADATA_INSPECTED"
    except (sqlite3.DatabaseError, sqlite3.OperationalError, OSError, ValueError) as exc:
        result["status"] = "UNREADABLE_OR_INVALID_SQLITE"
        result["error_type"] = type(exc).__name__
    finally:
        if conn is not None:
            conn.close()
    return result


def inventory(root: Path, *, max_files: int = 250, max_depth: int = 3,
              max_tables: int = 400, budget_seconds: float = 20.0, prior: Path | None = None):
    if not root.is_dir() or root.is_symlink() or not root.is_absolute():
        raise ValueError("ROOT_MUST_BE_ABSOLUTE_DIRECTORY_NOT_SYMLINK")
    if not (1 <= max_files <= 1000 and 0 <= max_depth <= 5 and 1 <= max_tables <= 1000
            and 1 <= budget_seconds <= 120):
        raise ValueError("INVALID_BUDGET")
    prior_state, prior_status = load_prior(prior)
    deadline = time.monotonic() + budget_seconds
    sources = []
    total_seen = 0
    truncated = False
    stack = [(root, 0)]
    excluded_dirs = {".git", ".venv", "venv", "node_modules", "__pycache__", ".cache"}
    while stack:
        parent, depth = stack.pop()
        if time.monotonic() > deadline:
            truncated = True; break
        try:
            entries = sorted(os.scandir(parent), key=lambda e: e.name)
        except OSError:
            truncated = True; continue
        for entry in entries:
            if time.monotonic() > deadline:
                truncated = True; break
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if depth < max_depth and entry.name not in excluded_dirs:
                        stack.append((Path(entry.path), depth+1))
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                suffix = Path(entry.name).suffix.lower()
                if suffix not in DB_EXTENSIONS + TRACE_EXTENSIONS:
                    continue
                total_seen += 1
                if total_seen > max_files:
                    truncated = True; break
                p = Path(entry.path)
                rel = str(p.relative_to(root))
                size = entry.stat(follow_symlinks=False).st_size
                if suffix in DB_EXTENSIONS:
                    item = inspect_sqlite(p, root, max_tables, deadline)
                    item["size_band"] = "GT_1GB" if size > 1024**3 else "100MB_TO_1GB" if size > 100*1024**2 else "LT_100MB"
                else:
                    # Filename is only a discovery hint; do NOT open/read files.
                    signals = classify([entry.name]); item = {
                        "file_ref": opaque_id(rel), "kind": "POTENTIAL_TRACE_FILE_METADATA",
                        "extension": suffix, "size_band": "GT_16MB" if size > 16*1024**2 else "LTE_16MB",
                        "candidate_categories": sorted(signals),
                        "status": "FILENAME_ONLY_UNINSPECTED_CONTENT"}
                sources.append(item)
            except (OSError, ValueError):
                truncated = True
        if truncated:
            break
    return {
        "schema": SCHEMA, "mode": "METADATA_ONLY_READ_ONLY", "status": "PARTIAL_INVENTORY" if truncated else "BOUNDED_INVENTORY_COMPLETED",
        "migration_authority": "BLOCKED_RESEARCH_ONLY", "prior_stage3b313": {"state": prior_state, "status": prior_status},
        "inventory": {"candidate_files_inspected": len(sources), "truncated": truncated,
            "root_ref": opaque_id(str(root)), "max_files": max_files, "max_depth": max_depth,
            "max_tables_per_db": max_tables},
        "sources": sources,
        "attestation": {"producer_origin": "UNVERIFIED", "runtime_activation": "UNVERIFIED",
            "provider_availability": "UNVERIFIED", "historical_authenticity": "UNVERIFIED"},
        "guardrails": {"no_sqlite_rows_read": True, "no_log_contents_read": True,
            "no_production_writes": True, "no_backfill": True, "no_trades": True,
            "no_exports_of_decisions_or_events": True},
        "limitations": [
            "Inventory covers only files visible beneath the selected root and within configured bounds.",
            "Schema names and file-name signals indicate candidates, not real historical events or activation.",
            "No source provenance, event authenticity, timestamp order, or production runtime execution is attested.",
            "SQLite schema metadata may include tables created after the historical period.",
            "Files in external systems or missing containers are not discovered.",
        ]
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", required=True, type=Path)
    ap.add_argument("--stage3b313-report", type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--max-files", type=int, default=250)
    ap.add_argument("--max-depth", type=int, default=3)
    ap.add_argument("--max-tables", type=int, default=400)
    ap.add_argument("--budget-seconds", type=float, default=20)
    args = ap.parse_args(argv)
    root = args.root.absolute()
    out = args.output.absolute()
    if out.is_symlink() or out == root or root in out.parents or not (str(out).startswith('/tmp/') or str(out).startswith('/var/tmp/')):
        ap.error("OUTPUT_MUST_BE_OUTSIDE_ROOT_IN_TMP")
    report = inventory(root, max_files=args.max_files, max_depth=args.max_depth,
        max_tables=args.max_tables, budget_seconds=args.budget_seconds, prior=args.stage3b313_report)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Do not overwrite existing output: safe repeated execution via distinct names.
    with out.open('x', encoding='utf-8') as f:
        json.dump(report, f, indent=2, sort_keys=True)
        f.write('\n')
    print(f"Stage 3B.3.14: {report['status']} | {report['migration_authority']} | {len(report['sources'])} candidate files")
    return 0

if __name__ == "__main__":
    sys.exit(main())
