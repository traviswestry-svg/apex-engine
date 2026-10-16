"""APEX 69.10.38 candidate: read-only settlement eligibility classification.

No evidence writes, no matching heuristics, no trading/label decisions. Uses only
persisted canonical sample IDs. Diagnostic totals are database-wide, unlike the
bounded per-session settlement scheduler cohort.
"""
from __future__ import annotations
import sqlite3
from typing import Any

VERSION = "69.10.38-candidate"

def audit(db_path: str, *, sample_limit: int = 10) -> dict[str, Any]:
    """Audit existing feature/label/excursion/lifecycle populations read-only."""
    result: dict[str, Any] = {
        "version": VERSION, "state": "UNAVAILABLE", "writes_evidence": False,
        "changes_trade_decisions": False, "execution_authority": False,
        "synthetic_pl": False, "fuzzy_matching": False,
        "identity_basis": "EXACT_CANONICAL_SAMPLE_ID",
    }
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5) as db:
            db.execute("PRAGMA query_only=ON")
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            required = {"flow_features", "flow_labels", "flow_sample_excursions", "flow_sample_pl_lifecycle"}
            if not required.issubset(tables):
                result.update(state="MISSING_TABLES", missing_tables=sorted(required-tables))
                return result
            # All relationships use exact canonical sample_id. Primary-key uniqueness
            # is part of the persisted schema contract, not inferred timestamps.
            row = db.execute("""
                SELECT COUNT(*) AS features,
                  SUM(CASE WHEN b.sample_id IS NOT NULL THEN 1 ELSE 0 END) AS labelled,
                  SUM(CASE WHEN b.sample_id IS NULL THEN 1 ELSE 0 END) AS unlabelled,
                  SUM(CASE WHEN e.sample_id IS NOT NULL THEN 1 ELSE 0 END) AS with_excursion,
                  SUM(CASE WHEN e.sample_id IS NOT NULL AND b.sample_id IS NOT NULL THEN 1 ELSE 0 END) AS excursion_labelled,
                  SUM(CASE WHEN e.sample_id IS NOT NULL AND b.sample_id IS NULL THEN 1 ELSE 0 END) AS excursion_unlabelled,
                  SUM(CASE WHEN e.sample_id IS NULL AND b.sample_id IS NOT NULL THEN 1 ELSE 0 END) AS label_without_excursion,
                  SUM(CASE WHEN b.sample_id IS NULL AND e.sample_id IS NULL AND l.sample_id IS NOT NULL THEN 1 ELSE 0 END) AS pending_with_lifecycle_no_excursion,
                  SUM(CASE WHEN b.sample_id IS NULL AND e.sample_id IS NULL AND l.sample_id IS NULL THEN 1 ELSE 0 END) AS pending_without_lifecycle_no_excursion
                FROM flow_features f
                LEFT JOIN flow_labels b ON f.sample_id=b.sample_id
                LEFT JOIN flow_sample_excursions e ON f.sample_id=e.sample_id
                LEFT JOIN flow_sample_pl_lifecycle l ON f.sample_id=l.sample_id
            """).fetchone()
            keys = ("features", "labelled", "unlabelled", "with_excursion", "excursion_labelled", "excursion_unlabelled", "label_without_excursion", "pending_with_lifecycle_no_excursion", "pending_without_lifecycle_no_excursion")
            counts = dict(zip(keys, (int(x or 0) for x in row)))
            counts["pending_without_exact_excursion"] = counts["pending_with_lifecycle_no_excursion"] + counts["pending_without_lifecycle_no_excursion"]
            counts["excursion_rows"] = db.execute("SELECT COUNT(*) FROM flow_sample_excursions").fetchone()[0]
            counts["label_rows"] = db.execute("SELECT COUNT(*) FROM flow_labels").fetchone()[0]
            counts["lifecycle_rows"] = db.execute("SELECT COUNT(*) FROM flow_sample_pl_lifecycle").fetchone()[0]
            counts["orphan_excursions"] = db.execute("SELECT COUNT(*) FROM flow_sample_excursions e LEFT JOIN flow_features f ON e.sample_id=f.sample_id WHERE f.sample_id IS NULL").fetchone()[0]
            counts["orphan_labels"] = db.execute("SELECT COUNT(*) FROM flow_labels b LEFT JOIN flow_features f ON b.sample_id=f.sample_id WHERE f.sample_id IS NULL").fetchone()[0]
            counts["orphan_lifecycle"] = db.execute("SELECT COUNT(*) FROM flow_sample_pl_lifecycle l LEFT JOIN flow_features f ON l.sample_id=f.sample_id WHERE f.sample_id IS NULL").fetchone()[0]
            # Exhaustive, mutually exclusive pending-evidence partition. These are
            # observations, NOT permission to settle or assertions of bad data.
            counts["pending_with_excursion"] = counts["excursion_unlabelled"]
            counts["pending_without_excursion"] = counts["pending_without_exact_excursion"]
            pending_partition = {
                "EXCURSION_PRESENT_UNLABELLED": counts["pending_with_excursion"],
                "NO_EXCURSION_LIFECYCLE_PRESENT": counts["pending_with_lifecycle_no_excursion"],
                "NO_EXCURSION_NO_LIFECYCLE": counts["pending_without_lifecycle_no_excursion"],
            }
            integrity = {
                "feature_label_partition_valid": counts["features"] == counts["labelled"] + counts["unlabelled"],
                "pending_evidence_partition_valid": counts["unlabelled"] == sum(pending_partition.values()),
                "excursion_feature_partition_valid": counts["with_excursion"] == counts["excursion_labelled"] + counts["excursion_unlabelled"],
            }
            states = [dict(state=r[0], reason=r[1], count=r[2]) for r in db.execute("""
                SELECT l.state,l.reason,COUNT(*) FROM flow_features f
                JOIN flow_sample_pl_lifecycle l ON l.sample_id=f.sample_id
                LEFT JOIN flow_labels b ON b.sample_id=f.sample_id
                LEFT JOIN flow_sample_excursions e ON e.sample_id=f.sample_id
                WHERE b.sample_id IS NULL AND e.sample_id IS NULL
                GROUP BY l.state,l.reason ORDER BY COUNT(*) DESC
            """)]
            limit = max(0, min(int(sample_limit), 50))
            anomalies = [dict(sample_id=r[0], session_date=r[1]) for r in db.execute("""
                SELECT f.sample_id,f.session_date FROM flow_features f
                JOIN flow_labels b ON b.sample_id=f.sample_id
                LEFT JOIN flow_sample_excursions e ON e.sample_id=f.sample_id
                WHERE e.sample_id IS NULL ORDER BY f.session_date DESC,f.sample_id LIMIT ?
            """, (limit,))]
            result.update(state="READY" if all(integrity.values()) else "INTEGRITY_MISMATCH",
                          counts=counts, pending_evidence_partition=pending_partition,
                          partition_integrity=integrity, pending_lifecycle_states=states,
                          label_without_excursion_examples=anomalies,
                          coverage_scope="ALL_PERSISTED_FEATURES_NOT_SETTLEMENT_SCHEDULER_WINDOW",
                          classification="OBSERVATIONAL_ONLY_NO_ELIGIBILITY_PROMOTION")
    except (sqlite3.Error, ValueError, OSError) as exc:
        result.update(state="ERROR", error=f"{type(exc).__name__}: {exc}")
    return result
