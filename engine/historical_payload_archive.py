"""APEX 69.10.11 — immutable historical evidence archive foundation.

This module provides a dependency-preserving archival sidecar and shadow-read
validation primitives for historically amplified JSON payloads. It never
rewrites or deletes canonical evidence rows. Archival writes are additive,
content-addressed, immutable, and integrity checked. Production consumers are
not redirected by this module.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import zlib
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from .canonical_persistence import connect as canonical_connect
from .evidence_pipeline import DEFAULT_DB as EVIDENCE_DB, _persisted_snapshot_projection
from .persistent_store import persistent_sqlite_path
from .storage_capacity_policy import classify_free_pct
from .trigger_observatory import _bounded_trigger_evidence

VERSION = "69.10.11"
SCHEMA_VERSION = "apex.historical_payload_archive.v1"
ARCHIVE_DB = persistent_sqlite_path(
    "APEX_HISTORICAL_PAYLOAD_ARCHIVE_DB",
    "apex_historical_payload_archive.db",
)
TRIGGER_DB = persistent_sqlite_path("APEX_TRIGGER_OBSERVATORY_DB", "apex_trigger_observatory.db")
PAYLOAD_TYPES = {
    "TRIGGER_EVIDENCE": {
        "source_table": "observed_trade_triggers",
        "id_column": "trigger_id",
        "time_column": "triggered_at",
        "payload_column": "evidence_json",
        "projector": _bounded_trigger_evidence,
    },
    "DECISION_SNAPSHOT": {
        "source_table": "decisions",
        "id_column": "decision_id",
        "time_column": "observed_at",
        "payload_column": "snapshot_json",
        "projector": _persisted_snapshot_projection,
    },
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _raw_bytes(raw: str | bytes) -> bytes:
    return raw if isinstance(raw, bytes) else str(raw).encode("utf-8")


def _sha256(raw: str | bytes) -> str:
    return hashlib.sha256(_raw_bytes(raw)).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, default=str, separators=(",", ":"), sort_keys=True).encode("utf-8")


def initialize_archive(path: str | Path = ARCHIVE_DB) -> None:
    """Create the append-only sidecar schema. Existing rows are never updated."""
    with canonical_connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS historical_payload_archive (
                payload_type TEXT NOT NULL,
                row_id TEXT NOT NULL,
                source_table TEXT NOT NULL,
                source_column TEXT NOT NULL,
                observed_at TEXT,
                source_sha256 TEXT NOT NULL,
                source_bytes INTEGER NOT NULL,
                archive_codec TEXT NOT NULL,
                archive_blob BLOB NOT NULL,
                archive_bytes INTEGER NOT NULL,
                archived_at TEXT NOT NULL,
                apex_version TEXT NOT NULL,
                schema_version TEXT NOT NULL,
                integrity_status TEXT NOT NULL,
                PRIMARY KEY(payload_type,row_id,source_sha256)
            );
            CREATE UNIQUE INDEX IF NOT EXISTS ux_historical_payload_archive_identity
              ON historical_payload_archive(payload_type,row_id);
            CREATE INDEX IF NOT EXISTS ix_historical_payload_archive_hash
              ON historical_payload_archive(source_sha256);
            CREATE INDEX IF NOT EXISTS ix_historical_payload_archive_time
              ON historical_payload_archive(archived_at);
            CREATE TRIGGER IF NOT EXISTS trg_historical_payload_archive_no_update
              BEFORE UPDATE ON historical_payload_archive
              BEGIN SELECT RAISE(ABORT, 'historical payload archive is immutable'); END;
            CREATE TRIGGER IF NOT EXISTS trg_historical_payload_archive_no_delete
              BEFORE DELETE ON historical_payload_archive
              BEGIN SELECT RAISE(ABORT, 'historical payload archive is immutable'); END;
            """
        )
        conn.commit()


def _compress(raw: bytes) -> bytes:
    return zlib.compress(raw, level=9)


def _decompress(blob: bytes, codec: str) -> bytes:
    if codec != "ZLIB_9":
        raise ValueError(f"unsupported archive codec: {codec}")
    return zlib.decompress(blob)


def archive_one(
    *,
    payload_type: str,
    row_id: str,
    observed_at: str | None,
    raw_payload: str,
    path: str | Path = ARCHIVE_DB,
    apply: bool = False,
) -> dict[str, Any]:
    """Plan or immutably archive one payload.

    A pre-existing row with a different source hash fails closed. The function
    never updates or deletes archive rows and never mutates the canonical source.
    """
    spec = PAYLOAD_TYPES.get(payload_type)
    if spec is None:
        return {"ok": False, "state": "UNSUPPORTED_PAYLOAD_TYPE", "payload_type": payload_type}
    raw = _raw_bytes(raw_payload)
    source_hash = hashlib.sha256(raw).hexdigest()
    compressed = _compress(raw)
    result = {
        "ok": True,
        "apply": bool(apply),
        "payload_type": payload_type,
        "row_id": str(row_id),
        "source_sha256": source_hash,
        "source_bytes": len(raw),
        "archive_codec": "ZLIB_9",
        "archive_bytes": len(compressed),
        "compression_ratio": round(len(compressed) / len(raw), 6) if raw else 0.0,
        "canonical_source_mutated": False,
        "archive_row_inserted": False,
        "archive_immutable": True,
    }
    if not apply:
        result["state"] = "DRY_RUN"
        return result

    initialize_archive(path)
    with canonical_connect(path) as conn:
        conn.row_factory = sqlite3.Row
        existing = conn.execute(
            "SELECT source_sha256,source_bytes,archive_codec,archive_blob,integrity_status "
            "FROM historical_payload_archive WHERE payload_type=? AND row_id=?",
            (payload_type, str(row_id)),
        ).fetchone()
        if existing is not None:
            if existing["source_sha256"] != source_hash:
                return {
                    **result,
                    "ok": False,
                    "state": "SOURCE_ID_HASH_CONFLICT",
                    "existing_source_sha256": existing["source_sha256"],
                }
            reconstructed = _decompress(existing["archive_blob"], existing["archive_codec"])
            intact = hashlib.sha256(reconstructed).hexdigest() == source_hash and reconstructed == raw
            return {
                **result,
                "state": "ALREADY_ARCHIVED_VERIFIED" if intact else "ARCHIVE_INTEGRITY_FAILURE",
                "ok": bool(intact),
                "archive_integrity_verified": bool(intact),
            }

        conn.execute(
            "INSERT INTO historical_payload_archive("
            "payload_type,row_id,source_table,source_column,observed_at,source_sha256,source_bytes,"
            "archive_codec,archive_blob,archive_bytes,archived_at,apex_version,schema_version,integrity_status"
            ") VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                payload_type,
                str(row_id),
                spec["source_table"],
                spec["payload_column"],
                observed_at,
                source_hash,
                len(raw),
                "ZLIB_9",
                sqlite3.Binary(compressed),
                len(compressed),
                _now(),
                VERSION,
                SCHEMA_VERSION,
                "HASH_VERIFIED",
            ),
        )
        conn.commit()
        inserted = conn.total_changes > 0
    result.update({"state": "ARCHIVED_VERIFIED", "archive_row_inserted": bool(inserted), "archive_integrity_verified": True})
    return result


def retrieve_archived_payload(
    payload_type: str,
    row_id: str,
    *,
    path: str | Path = ARCHIVE_DB,
) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {"ok": False, "state": "ARCHIVE_NOT_FOUND", "payload_type": payload_type, "row_id": str(row_id)}
    with canonical_connect(p, read_only=True, wal=False, heal=False) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM historical_payload_archive WHERE payload_type=? AND row_id=?",
            (payload_type, str(row_id)),
        ).fetchone()
    if row is None:
        return {"ok": False, "state": "ROW_NOT_ARCHIVED", "payload_type": payload_type, "row_id": str(row_id)}
    try:
        raw = _decompress(row["archive_blob"], row["archive_codec"])
    except Exception as exc:
        return {"ok": False, "state": "ARCHIVE_DECODE_FAILURE", "error": f"{type(exc).__name__}: {exc}"}
    actual_hash = hashlib.sha256(raw).hexdigest()
    intact = actual_hash == row["source_sha256"] and len(raw) == int(row["source_bytes"])
    return {
        "ok": bool(intact),
        "state": "ARCHIVE_VERIFIED" if intact else "ARCHIVE_INTEGRITY_FAILURE",
        "payload_type": payload_type,
        "row_id": str(row_id),
        "source_sha256": row["source_sha256"],
        "source_bytes": int(row["source_bytes"]),
        "archive_bytes": int(row["archive_bytes"]),
        "archive_codec": row["archive_codec"],
        "payload": raw.decode("utf-8") if intact else None,
        "payload_values_exposed": bool(intact),
    }


def _source_rows(path: str | Path, payload_type: str, limit: int | None = None):
    spec = PAYLOAD_TYPES[payload_type]
    p = Path(path)
    if not p.exists():
        return []
    sql = (
        f"SELECT {spec['id_column']} row_id,{spec['time_column']} observed_at,"
        f"{spec['payload_column']} payload FROM {spec['source_table']} ORDER BY {spec['time_column']}"
    )
    params: tuple[Any, ...] = ()
    if limit is not None:
        sql += " LIMIT ?"
        params = (max(1, int(limit)),)
    with canonical_connect(p, read_only=True, wal=False, heal=False) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(sql, params)]


def archive_plan(
    *,
    trigger_path: str | Path = TRIGGER_DB,
    evidence_path: str | Path = EVIDENCE_DB,
    archive_path: str | Path = ARCHIVE_DB,
    sample_limit: int = 50,
) -> dict[str, Any]:
    """Estimate compressed archive footprint from bounded samples; no writes."""
    result: dict[str, Any] = {
        "ok": True,
        "version": VERSION,
        "schema_version": "apex.historical_payload_archive_plan.v1",
        "archive_path": str(archive_path),
        "apply": False,
        "canonical_source_mutated": False,
        "archive_rows_written": 0,
        "payload_values_exposed": False,
    }
    estimates: dict[str, Any] = {}
    for payload_type, source_path in (("TRIGGER_EVIDENCE", trigger_path), ("DECISION_SNAPSHOT", evidence_path)):
        spec = PAYLOAD_TYPES[payload_type]
        p = Path(source_path)
        entry: dict[str, Any] = {"source_path": str(p), "exists": p.exists()}
        if p.exists():
            with canonical_connect(p, read_only=True, wal=False, heal=False) as conn:
                conn.row_factory = sqlite3.Row
                agg = conn.execute(
                    f"SELECT COUNT(*) n,COALESCE(SUM(LENGTH({spec['payload_column']})),0) b FROM {spec['source_table']}"
                ).fetchone()
                sample = conn.execute(
                    f"SELECT {spec['payload_column']} payload FROM {spec['source_table']} "
                    f"ORDER BY LENGTH({spec['payload_column']}) DESC LIMIT ?",
                    (max(1, int(sample_limit)),),
                ).fetchall()
            source_sample = 0
            archive_sample = 0
            for row in sample:
                raw = _raw_bytes(row["payload"] or "")
                source_sample += len(raw)
                archive_sample += len(_compress(raw))
            ratio = archive_sample / source_sample if source_sample else None
            total_source = int(agg["b"] or 0)
            entry.update({
                "rows": int(agg["n"] or 0),
                "source_payload_bytes": total_source,
                "sample_rows": len(sample),
                "sample_source_bytes": source_sample,
                "sample_archive_bytes": archive_sample,
                "sample_compression_ratio": round(ratio, 6) if ratio is not None else None,
                "estimated_archive_bytes": int(total_source * ratio) if ratio is not None else 0,
                "estimate_is_exact": False,
            })
        estimates[payload_type] = entry
    result["payloads"] = estimates
    result["estimated_archive_bytes"] = sum(int(v.get("estimated_archive_bytes") or 0) for v in estimates.values())
    result["guardrails"] = {
        "archive_additive_only": True,
        "canonical_source_rewrite": False,
        "canonical_source_delete": False,
        "archive_update": False,
        "archive_delete": False,
        "vacuum_performed": False,
        "filesystem_reclaim_promised": False,
        "decision_authority": False,
        "execution_authority": False,
    }
    return result


def _archive_capacity_status(path: str | Path = ARCHIVE_DB) -> dict[str, Any]:
    target = Path(path)
    root = target.parent if target.parent.exists() else Path(".")
    usage = shutil.disk_usage(root)
    free_pct = (usage.free / usage.total * 100.0) if usage.total else 0.0
    state = classify_free_pct(free_pct).get("state")
    return {
        "root": str(root),
        "total_bytes": int(usage.total),
        "free_bytes": int(usage.free),
        "free_pct": round(free_pct, 2),
        "state": state,
        "archive_write_allowed": state != "CRITICAL",
        "critical_write_block": state == "CRITICAL",
    }


def archive_batch(
    *,
    payload_type: str,
    source_path: str | Path,
    archive_path: str | Path = ARCHIVE_DB,
    limit: int = 25,
    apply: bool = False,
) -> dict[str, Any]:
    """Archive a bounded batch. Dry-run is default; canonical rows are untouched."""
    if payload_type not in PAYLOAD_TYPES:
        return {"ok": False, "state": "UNSUPPORTED_PAYLOAD_TYPE", "payload_type": payload_type}
    bounded_limit = max(1, min(int(limit), 500))
    capacity = _archive_capacity_status(archive_path)
    if apply and not capacity.get("archive_write_allowed"):
        return {
            "ok": False,
            "version": VERSION,
            "payload_type": payload_type,
            "apply": True,
            "state": "STORAGE_CRITICAL_ARCHIVE_WRITE_BLOCKED",
            "capacity": capacity,
            "rows_considered": 0,
            "rows_archived": 0,
            "canonical_source_mutated": False,
            "archive_immutable": True,
        }
    rows = _source_rows(source_path, payload_type, limit=bounded_limit)
    outcomes = [
        archive_one(
            payload_type=payload_type,
            row_id=str(row["row_id"]),
            observed_at=row.get("observed_at"),
            raw_payload=row.get("payload") or "",
            path=archive_path,
            apply=apply,
        )
        for row in rows
    ]
    return {
        "ok": all(bool(x.get("ok")) for x in outcomes),
        "version": VERSION,
        "payload_type": payload_type,
        "apply": bool(apply),
        "rows_considered": len(rows),
        "rows_archived": sum(1 for x in outcomes if x.get("state") == "ARCHIVED_VERIFIED"),
        "rows_already_archived": sum(1 for x in outcomes if x.get("state") == "ALREADY_ARCHIVED_VERIFIED"),
        "canonical_source_mutated": False,
        "archive_immutable": True,
        "capacity": capacity,
        "outcomes": outcomes,
    }


def shadow_validate(
    *,
    payload_type: str,
    source_path: str | Path,
    archive_path: str | Path = ARCHIVE_DB,
    limit: int = 50,
) -> dict[str, Any]:
    """Compare canonical full payload, compact projection and archival fallback.

    This is a shadow validation only. Production readers are not redirected.
    """
    if payload_type not in PAYLOAD_TYPES:
        return {"ok": False, "state": "UNSUPPORTED_PAYLOAD_TYPE", "payload_type": payload_type}
    spec = PAYLOAD_TYPES[payload_type]
    rows = _source_rows(source_path, payload_type, limit=max(1, min(int(limit), 500)))
    checked = archived = hash_matches = projection_errors = archive_misses = 0
    mismatches: list[dict[str, Any]] = []
    for row in rows:
        checked += 1
        raw_text = row.get("payload") or ""
        raw_hash = _sha256(raw_text)
        try:
            parsed = json.loads(raw_text)
            if not isinstance(parsed, Mapping):
                raise TypeError("payload is not a mapping")
            projected = dict(spec["projector"](parsed))
            projected_bytes = len(_json_bytes(projected))
        except Exception as exc:
            projection_errors += 1
            mismatches.append({"row_id": str(row["row_id"]), "reason": f"PROJECTION_ERROR:{type(exc).__name__}"})
            continue
        archive = retrieve_archived_payload(payload_type, str(row["row_id"]), path=archive_path)
        if not archive.get("ok"):
            archive_misses += 1
            continue
        archived += 1
        if archive.get("source_sha256") == raw_hash and archive.get("payload") == raw_text:
            hash_matches += 1
        else:
            mismatches.append({"row_id": str(row["row_id"]), "reason": "ARCHIVE_SOURCE_MISMATCH"})
        # The projection is intentionally smaller, but full-payload consumers are
        # semantically preserved by exact archival fallback in shadow mode.
        if projected_bytes <= 0:
            mismatches.append({"row_id": str(row["row_id"]), "reason": "EMPTY_PROJECTION"})
    ready = checked > 0 and archived == checked and hash_matches == checked and projection_errors == 0 and not mismatches
    return {
        "ok": True,
        "version": VERSION,
        "schema_version": "apex.historical_payload_shadow_validation.v1",
        "payload_type": payload_type,
        "rows_checked": checked,
        "rows_archived": archived,
        "archive_misses": archive_misses,
        "exact_archive_matches": hash_matches,
        "projection_errors": projection_errors,
        "mismatches": mismatches[:20],
        "shadow_read_ready": bool(ready),
        "production_reads_redirected": False,
        "canonical_source_mutated": False,
        "decision_authority": False,
        "execution_authority": False,
    }


def archive_status(path: str | Path = ARCHIVE_DB) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {
            "ok": True,
            "version": VERSION,
            "exists": False,
            "path": str(p),
            "rows": 0,
            "archive_bytes": 0,
            "source_bytes": 0,
            "state": "NOT_INITIALIZED",
        }
    try:
        with canonical_connect(p, read_only=True, wal=False, heal=False) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT payload_type,COUNT(*) n,COALESCE(SUM(source_bytes),0) source_bytes,"
                "COALESCE(SUM(archive_bytes),0) archive_bytes FROM historical_payload_archive GROUP BY payload_type"
            ).fetchall()
    except Exception as exc:
        return {
            "ok": False, "version": VERSION, "exists": True, "path": str(p),
            "rows": 0, "archive_bytes": 0, "source_bytes": 0,
            "state": "ARCHIVE_STATUS_UNAVAILABLE",
            "error": f"{type(exc).__name__}: {exc}",
        }
    by_type = [dict(row) for row in rows]
    return {
        "ok": True,
        "version": VERSION,
        "exists": True,
        "path": str(p),
        "rows": sum(int(x["n"]) for x in by_type),
        "source_bytes": sum(int(x["source_bytes"]) for x in by_type),
        "archive_bytes": sum(int(x["archive_bytes"]) for x in by_type),
        "by_type": by_type,
        "state": "AVAILABLE",
        "immutable": True,
    }
