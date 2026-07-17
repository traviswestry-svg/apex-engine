"""engine/feature_store_db.py — APEX 9 Step 5a persistence.

TWO TABLES, DELIBERATELY
------------------------
`flow_features` and `flow_labels` are separate tables sharing only `sample_id`.
This is not normalization for its own sake — it is the two-record rule made
physical. There is no view, no join helper, and no `SELECT *` convenience that
returns a flat row containing both a feature and an outcome, because the moment
such a thing exists someone will train on it.

Reading them back together goes through `load_training_pairs()`, which demands an
explicit train/eval session split and refuses overlap.

IMMUTABILITY
------------
`write_features` refuses to overwrite an existing sample. A flow cluster mutates
as late prints arrive (Step 3, by design), so re-deriving and re-writing features
later would rewrite history with knowledge the original decision never had.
Labels, by contrast, are expected to be updated as excursions widen — that is
what a label *is*.

Failure is non-fatal everywhere: a store that cannot open degrades to
no-persistence, never to a broken pipeline.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
import threading
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .feature_store import (
    FEATURE_SCHEMA_VERSION,
    LABEL_SCHEMA_VERSION,
    LeakageError,
    assert_chronological_split,
    assert_disjoint_sessions,
)

_DB_PATH = os.getenv("DB_PATH", "apex_tracking.db")
_LOCK = threading.Lock()
_DB_READY = False

STORE_VERSION = "9.5.0_FEATURE_STORE_DB"


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def init_db() -> bool:
    """Create/upgrade both tables. Non-fatal."""
    global _DB_READY
    try:
        d = os.path.dirname(_DB_PATH)
        if d:
            os.makedirs(d, exist_ok=True)
        with _conn() as c:
            c.execute(
                """CREATE TABLE IF NOT EXISTS flow_features (
                       sample_id        TEXT PRIMARY KEY,
                       session_date     TEXT NOT NULL,
                       ticker           TEXT,
                       decision_time    TEXT NOT NULL,
                       features_json    TEXT NOT NULL,
                       availability_json TEXT NOT NULL,
                       max_feature_lag_seconds REAL,
                       feature_count    INTEGER,
                       schema_version   TEXT,
                       written_at       TEXT NOT NULL
                   )"""
            )
            # Separate table. No FK to flow_features and no view joining them:
            # the separation is the safety property.
            c.execute(
                """CREATE TABLE IF NOT EXISTS flow_labels (
                       sample_id        TEXT PRIMARY KEY,
                       session_date     TEXT NOT NULL,
                       decision_time    TEXT NOT NULL,
                       settled_at       TEXT NOT NULL,
                       labels_json      TEXT NOT NULL,
                       label_basis      TEXT,
                       schema_version   TEXT,
                       written_at       TEXT NOT NULL,
                       updated_at       TEXT
                   )"""
            )
            c.execute("CREATE INDEX IF NOT EXISTS idx_ff_session ON flow_features(session_date)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_fl_session ON flow_labels(session_date)")
            c.commit()
        _DB_READY = True
    except Exception as e:  # pragma: no cover
        _DB_READY = False
        print(f"Feature store DISABLED — DB init failed at '{_DB_PATH}': {e}", flush=True)
    return _DB_READY


def is_ready() -> bool:
    return _DB_READY


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def write_features(vector: Dict[str, Any]) -> bool:
    """Persist a pre-decision vector. Refuses to overwrite an existing sample.

    Immutability is the point: see module docstring.
    """
    if not _DB_READY or not vector:
        return False
    try:
        with _LOCK, _conn() as c:
            exists = c.execute("SELECT 1 FROM flow_features WHERE sample_id=?",
                               (vector["sample_id"],)).fetchone()
            if exists:
                return False        # already frozen; not an error, just refused
            c.execute(
                """INSERT INTO flow_features
                   (sample_id, session_date, ticker, decision_time, features_json,
                    availability_json, max_feature_lag_seconds, feature_count,
                    schema_version, written_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (vector["sample_id"], vector["session_date"], vector.get("ticker"),
                 vector["decision_time"], json.dumps(vector["features"]),
                 json.dumps(vector["feature_availability"]),
                 vector.get("max_feature_lag_seconds"), vector.get("feature_count"),
                 vector.get("schema_version", FEATURE_SCHEMA_VERSION), _now()),
            )
            c.commit()
        return True
    except Exception as e:  # pragma: no cover
        print(f"feature_store_db.write_features failed (non-fatal): {e}", flush=True)
        return False


def write_label(record: Dict[str, Any]) -> bool:
    """Persist / update a label record. Updates are expected as excursions widen."""
    if not _DB_READY or not record:
        return False
    try:
        with _LOCK, _conn() as c:
            c.execute(
                """INSERT INTO flow_labels
                   (sample_id, session_date, decision_time, settled_at, labels_json,
                    label_basis, schema_version, written_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(sample_id) DO UPDATE SET
                     settled_at=excluded.settled_at,
                     labels_json=excluded.labels_json,
                     updated_at=excluded.updated_at""",
                (record["sample_id"], record["session_date"], record["decision_time"],
                 record["settled_at"], json.dumps(record["labels"]),
                 record.get("label_basis"),
                 record.get("schema_version", LABEL_SCHEMA_VERSION), _now(), _now()),
            )
            c.commit()
        return True
    except Exception as e:  # pragma: no cover
        print(f"feature_store_db.write_label failed (non-fatal): {e}", flush=True)
        return False


def get_features(sample_id: str) -> Optional[Dict[str, Any]]:
    if not _DB_READY:
        return None
    try:
        with _conn() as c:
            r = c.execute("SELECT * FROM flow_features WHERE sample_id=?",
                          (sample_id,)).fetchone()
        if not r:
            return None
        return {"sample_id": r["sample_id"], "session_date": r["session_date"],
                "ticker": r["ticker"], "decision_time": r["decision_time"],
                "features": json.loads(r["features_json"]),
                "feature_availability": json.loads(r["availability_json"]),
                "max_feature_lag_seconds": r["max_feature_lag_seconds"],
                "feature_count": r["feature_count"],
                "schema_version": r["schema_version"]}
    except Exception:  # pragma: no cover
        return None


def sessions(kind: str = "features") -> List[str]:
    """Distinct session dates present, oldest first."""
    if not _DB_READY:
        return []
    table = "flow_features" if kind == "features" else "flow_labels"
    try:
        with _conn() as c:
            return [r[0] for r in c.execute(
                f"SELECT DISTINCT session_date FROM {table} ORDER BY session_date")]
    except Exception:  # pragma: no cover
        return []


def load_training_pairs(*, train_sessions: Sequence[str], eval_sessions: Sequence[str],
                        require_chronological: bool = True
                        ) -> Dict[str, List[Dict[str, Any]]]:
    """The ONLY way to read features and labels together.

    Enforces the session split before a single row is read. Returns
    {"train": [...], "eval": [...]}, each item {"sample_id", "features", "labels",
    "decision_time", "session_date"} — features and labels stay in named
    sub-objects rather than a flattened row, so a caller cannot accidentally
    sweep a label into a feature matrix with `list(row.values())`.
    """
    if not _DB_READY:
        return {"train": [], "eval": []}
    if require_chronological:
        assert_chronological_split(train_sessions, eval_sessions)
    else:
        assert_disjoint_sessions(train_sessions, eval_sessions)

    def _load(sess: Sequence[str]) -> List[Dict[str, Any]]:
        if not sess:
            return []
        out: List[Dict[str, Any]] = []
        with _conn() as c:
            for i in range(0, len(sess), 400):
                chunk = list(sess[i:i + 400])
                q = ",".join("?" * len(chunk))
                rows = c.execute(
                    f"""SELECT f.sample_id, f.session_date, f.decision_time,
                               f.features_json, l.labels_json, l.settled_at
                        FROM flow_features f
                        JOIN flow_labels l ON l.sample_id = f.sample_id
                        WHERE f.session_date IN ({q})
                        ORDER BY f.decision_time""", chunk).fetchall()
                for r in rows:
                    out.append({
                        "sample_id": r["sample_id"],
                        "session_date": r["session_date"],
                        "decision_time": r["decision_time"],
                        "features": json.loads(r["features_json"]),
                        "labels": json.loads(r["labels_json"]),
                        "settled_at": r["settled_at"],
                    })
        return out

    return {"train": _load(train_sessions), "eval": _load(eval_sessions)}


def unlabelled_samples(session_date: Optional[str] = None) -> List[str]:
    """Feature rows with no label yet — the normal state for a live session."""
    if not _DB_READY:
        return []
    try:
        with _conn() as c:
            if session_date:
                rows = c.execute(
                    """SELECT f.sample_id FROM flow_features f
                       LEFT JOIN flow_labels l ON l.sample_id=f.sample_id
                       WHERE l.sample_id IS NULL AND f.session_date=?""",
                    (session_date,)).fetchall()
            else:
                rows = c.execute(
                    """SELECT f.sample_id FROM flow_features f
                       LEFT JOIN flow_labels l ON l.sample_id=f.sample_id
                       WHERE l.sample_id IS NULL""").fetchall()
        return [r[0] for r in rows]
    except Exception:  # pragma: no cover
        return []


def health() -> Dict[str, Any]:
    info: Dict[str, Any] = {"ready": _DB_READY, "store_version": STORE_VERSION,
                            "db_path": _DB_PATH,
                            "feature_schema": FEATURE_SCHEMA_VERSION,
                            "label_schema": LABEL_SCHEMA_VERSION}
    if _DB_READY:
        try:
            with _conn() as c:
                info["feature_rows"] = c.execute(
                    "SELECT COUNT(*) n FROM flow_features").fetchone()["n"]
                info["label_rows"] = c.execute(
                    "SELECT COUNT(*) n FROM flow_labels").fetchone()["n"]
                info["feature_sessions"] = c.execute(
                    "SELECT COUNT(DISTINCT session_date) n FROM flow_features").fetchone()["n"]
                info["unlabelled"] = len(unlabelled_samples())
        except Exception as e:  # pragma: no cover
            info["error"] = str(e)
    info["note"] = ("Features and labels are stored in separate tables and can only be read "
                    "together via load_training_pairs(), which enforces the session split.")
    return info


# ── Inspection reads ──────────────────────────────────────────────────────
# A human reading one record is not the leak; a bulk FLAT export fed to a trainer
# is. So these return features and labels in named sub-objects, never merged, and
# there is still no endpoint or function handing back a flat row with both.

def list_features(*, session_date: Optional[str] = None, limit: int = 50,
                  offset: int = 0) -> List[Dict[str, Any]]:
    """Feature vectors only — labels are not read here at all."""
    if not _DB_READY:
        return []
    limit = max(1, min(int(limit or 50), 500))
    try:
        with _conn() as c:
            if session_date:
                rows = c.execute(
                    """SELECT sample_id, session_date, ticker, decision_time,
                              features_json, availability_json, max_feature_lag_seconds,
                              feature_count, schema_version
                       FROM flow_features WHERE session_date=?
                       ORDER BY decision_time DESC LIMIT ? OFFSET ?""",
                    (session_date, limit, int(offset or 0))).fetchall()
            else:
                rows = c.execute(
                    """SELECT sample_id, session_date, ticker, decision_time,
                              features_json, availability_json, max_feature_lag_seconds,
                              feature_count, schema_version
                       FROM flow_features
                       ORDER BY session_date DESC, decision_time DESC
                       LIMIT ? OFFSET ?""", (limit, int(offset or 0))).fetchall()
        return [{"sample_id": r["sample_id"], "session_date": r["session_date"],
                 "ticker": r["ticker"], "decision_time": r["decision_time"],
                 "features": json.loads(r["features_json"]),
                 "feature_availability": json.loads(r["availability_json"]),
                 "max_feature_lag_seconds": r["max_feature_lag_seconds"],
                 "feature_count": r["feature_count"],
                 "schema_version": r["schema_version"]} for r in rows]
    except Exception:  # pragma: no cover
        return []


def get_label(sample_id: str) -> Optional[Dict[str, Any]]:
    if not _DB_READY:
        return None
    try:
        with _conn() as c:
            r = c.execute("SELECT * FROM flow_labels WHERE sample_id=?",
                          (sample_id,)).fetchone()
        if not r:
            return None
        return {"sample_id": r["sample_id"], "settled_at": r["settled_at"],
                "labels": json.loads(r["labels_json"]),
                "label_basis": r["label_basis"], "schema_version": r["schema_version"]}
    except Exception:  # pragma: no cover
        return None


def get_sample(sample_id: str) -> Optional[Dict[str, Any]]:
    """One record for inspection: features and labels stay in named sub-objects.

    Single-row inspection, not a training path. `labels` is None until settled,
    which is the normal state during a live session.
    """
    f = get_features(sample_id)
    if not f:
        return None
    lab = get_label(sample_id)
    return {
        "sample_id": sample_id,
        "session_date": f["session_date"],
        "ticker": f["ticker"],
        "decision_time": f["decision_time"],
        "pre_decision": {
            "features": f["features"],
            "feature_availability": f["feature_availability"],
            "max_feature_lag_seconds": f["max_feature_lag_seconds"],
        },
        "post_outcome": lab,
        "note": ("pre_decision and post_outcome are stored in separate tables and shown "
                 "separately here. Only pre_decision was knowable at decision_time."),
    }


# ── Neighbourhood coverage (aggregates only — no flat row escapes) ─────────
_NEIGHBOURHOOD_DEFAULT = ("gamma_regime", "auction_state",
                          "cluster_directional_interpretation", "premium_band")


def _premium_band(features: Dict[str, Any]) -> str:
    """Bucket by the CLASSIFIER's own premium thresholds, not new ones."""
    try:
        from .flow_classifier import _INSTITUTIONAL_PREMIUM, _RETAIL_PREMIUM
        p = float(features.get("cluster_total_premium") or 0)
    except Exception:  # pragma: no cover
        return "UNKNOWN"
    if p >= _INSTITUTIONAL_PREMIUM:
        return "INSTITUTIONAL_SIZE"
    if p <= _RETAIL_PREMIUM:
        return "RETAIL_SIZE"
    return "MID_SIZE"


_DERIVED_DIMS = {"premium_band": _premium_band}


def neighbourhood_coverage(*, dims: Sequence[str] = _NEIGHBOURHOOD_DEFAULT,
                           sessions: Optional[Sequence[str]] = None
                           ) -> Dict[str, Any]:
    """Per-cell sample counts and outcome distribution. Returns AGGREGATES ONLY.

    This is the number that actually gates 5b: not how many rows exist, but how
    many exist in cells that resemble each other. Aggregation happens here so no
    caller ever holds a flat feature+label row.

    Outcome RATES are reported only for cells where `edge_claim_permitted` is
    true. Below that the counts are shown and the rate is withheld — a 3-sample
    cell has a win rate, and printing it is how a fictional edge gets believed.
    """
    from .feature_store import sample_quality, wilson_interval
    if not _DB_READY:
        return {"cells": [], "dims": list(dims), "total_samples": 0}
    try:
        with _conn() as c:
            if sessions:
                q = ",".join("?" * len(sessions))
                rows = c.execute(
                    f"""SELECT f.features_json, l.labels_json
                        FROM flow_features f
                        LEFT JOIN flow_labels l ON l.sample_id=f.sample_id
                        WHERE f.session_date IN ({q})""", list(sessions)).fetchall()
            else:
                rows = c.execute(
                    """SELECT f.features_json, l.labels_json
                       FROM flow_features f
                       LEFT JOIN flow_labels l ON l.sample_id=f.sample_id""").fetchall()

        cells: Dict[tuple, Dict[str, Any]] = {}
        for r in rows:
            feats = json.loads(r["features_json"])
            key = []
            for d in dims:
                if d in _DERIVED_DIMS:
                    key.append(str(_DERIVED_DIMS[d](feats)))
                else:
                    key.append(str(feats.get(d, "UNKNOWN")))
            k = tuple(key)
            cell = cells.setdefault(k, {"n": 0, "labelled": 0, "outcomes": {}})
            cell["n"] += 1
            if r["labels_json"]:
                lab = json.loads(r["labels_json"])
                oc = lab.get("final_outcome")
                if oc:
                    cell["labelled"] += 1
                    cell["outcomes"][oc] = cell["outcomes"].get(oc, 0) + 1

        out = []
        for k, v in sorted(cells.items(), key=lambda kv: -kv[1]["n"]):
            q = sample_quality(v["n"])
            entry = {
                "cell": dict(zip(dims, k)),
                "matched_sample_count": v["n"],
                "labelled_count": v["labelled"],
                "tier": q["tier"],
                "edge_claim_permitted": q["edge_claim_permitted"],
                "note": q["note"],
                "outcome_counts": v["outcomes"],
            }
            if q["edge_claim_permitted"] and v["labelled"]:
                hits = v["outcomes"].get("TARGET_FIRST", 0) + v["outcomes"].get("TARGET_ONLY", 0)
                entry["target_first_rate"] = wilson_interval(hits, v["labelled"])
            else:
                entry["target_first_rate"] = None
                entry["rate_withheld_because"] = (
                    f"{v['n']} matched sample(s) — below the threshold at which a rate "
                    f"means anything. Counts are shown; the rate is not.")
            out.append(entry)

        return {
            "dims": list(dims),
            "cells": out,
            "cell_count": len(out),
            "total_samples": sum(c["n"] for c in cells.values()),
            "cells_permitting_edge_claims": sum(1 for c in out if c["edge_claim_permitted"]),
            "basis": ("Counts are per MATCHED NEIGHBOURHOOD. A large store total spread thinly "
                      "across cells supports no claim in any of them. Correlated sessions are "
                      "also not independent observations, so even a full cell may overstate."),
        }
    except Exception as e:  # pragma: no cover
        return {"cells": [], "dims": list(dims), "total_samples": 0, "error": str(e)}


def load_similarity_candidates(*, decision_time: str, ticker: str = "SPX",
                               prior_sessions_only: bool = True,
                               exclude_sample_id: Optional[str] = None,
                               limit: int = 5000) -> List[Dict[str, Any]]:
    """Load leakage-safe candidates for similarity.

    This narrowly scoped join is not a training export. It guarantees that every
    candidate decision predates the query and every included label was settled by
    the query time. Feature and label objects remain separate.
    """
    if not _DB_READY or not decision_time:
        return []
    query_session = str(decision_time)[:10]
    clauses = ["f.decision_time < ?", "f.ticker = ?", "l.settled_at <= ?"]
    args: List[Any] = [decision_time, ticker, decision_time]
    if prior_sessions_only:
        clauses.append("f.session_date < ?")
        args.append(query_session)
    if exclude_sample_id:
        clauses.append("f.sample_id != ?")
        args.append(exclude_sample_id)
    args.append(max(1, min(int(limit or 5000), 20000)))
    try:
        with _conn() as c:
            rows = c.execute(
                f"""SELECT f.sample_id, f.session_date, f.ticker, f.decision_time,
                           f.features_json, l.labels_json, l.settled_at
                    FROM flow_features f
                    JOIN flow_labels l ON l.sample_id=f.sample_id
                    WHERE {' AND '.join(clauses)}
                    ORDER BY f.decision_time DESC LIMIT ?""", args).fetchall()
        return [{"sample_id": r["sample_id"], "session_date": r["session_date"],
                 "ticker": r["ticker"], "decision_time": r["decision_time"],
                 "features": json.loads(r["features_json"]),
                 "labels": json.loads(r["labels_json"]),
                 "settled_at": r["settled_at"]} for r in rows]
    except Exception:  # pragma: no cover
        return []
