"""engine/flow_pl_store.py — APEX 9 Step 4 persistence for MFE/MAE.

MFE and MAE are the only Step 4 metrics that cannot be computed from a single
observation: they need the P/L sampled over time. This module owns that state.

WHY A STORE AT ALL
------------------
Steps 2 and 3 are stateless by design — classification and clustering are pure
functions of the current tape, which is what makes replay exact. Step 4 breaks
that only where it must: an excursion is a fact about history, not about now.

WHAT IS RECORDED — AND THE CAVEAT THAT MATTERS
----------------------------------------------
`entry_mark` is the print's observed execution price (a fact). But `entry_spot`
and `entry_iv` are captured at **first observation**, which is whenever the
scanner first sampled this print — seconds to minutes after it traded. We never
had spot or IV at trade time. So excursions are measured from first observation,
and every derived field says so rather than implying tick-zero precision.

MFE/MAE are recorded in dollars using the same conservative mark as live P/L, so
a "best" excursion is one you could plausibly have exited into — not a midpoint
mirage on a 0.05 x 5.00 market.

Failure is always non-fatal: a store that cannot open degrades to no-tracking,
never to a broken pipeline.
"""
from __future__ import annotations

import datetime as dt
import os
import sqlite3
import threading
from typing import Any, Dict, List, Optional

from .canonical_persistence import connect as canonical_connect
from .silent_degradation_observability import record_degradation

_DB_PATH = None

def _db_path() -> str:
    """Resolve canonical DB authority at call time.

    APEX 69.10.17: scanner/web processes may inject DB_PATH after module import.
    Freezing the path at import can split feature and excursion evidence across
    different SQLite files while both stores individually report healthy.
    Explicit _DB_PATH overrides remain supported for tests and controlled tools.
    """
    return _DB_PATH or os.getenv("DB_PATH", "apex_tracking.db")

def active_db_path() -> str:
    return _db_path()
_LOCK = threading.Lock()
_DB_READY = False

STORE_VERSION = "69.10.21_CANONICAL_SETTLEMENT_COHORT_IDENTITY_RECONCILIATION"


def _conn() -> sqlite3.Connection:
    return canonical_connect(_db_path(), timeout=10)


def init_db() -> bool:
    """Create/upgrade the tracking table. Non-fatal: disables tracking on error."""
    global _DB_READY
    try:
        d = os.path.dirname(_db_path())
        if d:
            os.makedirs(d, exist_ok=True)
        with _conn() as c:
            c.execute(
                """CREATE TABLE IF NOT EXISTS flow_pl_tracking (
                       event_id        TEXT PRIMARY KEY,
                       cluster_key     TEXT,
                       session_date    TEXT,
                       ticker          TEXT,
                       contract_type   TEXT,
                       strike          REAL,
                       expiration      TEXT,
                       position_side   TEXT,
                       contracts       INTEGER,
                       multiplier      REAL,
                       entry_time_et   TEXT,
                       entry_mark      REAL,
                       entry_spot      REAL,
                       entry_iv        REAL,
                       first_seen      TEXT,
                       last_seen       TEXT,
                       last_mark       REAL,
                       last_pl         REAL,
                       mfe_dollars     REAL,
                       mfe_at          TEXT,
                       mae_dollars     REAL,
                       mae_at          TEXT,
                       samples         INTEGER DEFAULT 0,
                       mark_methodology TEXT
                   )"""
            )
            # Forward-compatible migration (mirrors the 7.6 ALTER TABLE pattern).
            existing = {r["name"] for r in c.execute("PRAGMA table_info(flow_pl_tracking)")}
            for col, decl in (
                ("cluster_key", "TEXT"), ("entry_spot", "REAL"), ("entry_iv", "REAL"),
                ("mark_methodology", "TEXT"), ("last_pl", "REAL"),
            ):
                if col not in existing:
                    c.execute(f"ALTER TABLE flow_pl_tracking ADD COLUMN {col} {decl}")
            c.execute("CREATE INDEX IF NOT EXISTS idx_fpl_cluster "
                      "ON flow_pl_tracking(cluster_key)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_fpl_session "
                      "ON flow_pl_tracking(session_date)")
            # Cluster-level excursions. Per-event MFE/MAE cannot be summed into a
            # cluster figure: members do not peak simultaneously, so a sum is an
            # upper bound, not the cluster's excursion. Step 5 samples ARE
            # clusters, so their labels must be measured on the cluster's own
            # aggregate P/L — tracked here in its own envelope.
            c.execute(
                """CREATE TABLE IF NOT EXISTS flow_pl_cluster_tracking (
                       cluster_key     TEXT NOT NULL,
                       session_date    TEXT NOT NULL,
                       ticker          TEXT,
                       first_seen      TEXT,
                       last_seen       TEXT,
                       cost_basis      REAL,
                       last_pl         REAL,
                       mfe_dollars     REAL,
                       mfe_at          TEXT,
                       mae_dollars     REAL,
                       mae_at          TEXT,
                       samples         INTEGER DEFAULT 0,
                       PRIMARY KEY (cluster_key, session_date)
                   )"""
            )
            c.execute("CREATE INDEX IF NOT EXISTS idx_fplc_session "
                      "ON flow_pl_cluster_tracking(session_date)")
            # APEX 69.1: canonical sample-scoped excursion ledger. The previous
            # cluster_key is intentionally retained above as lineage only; it is
            # too coarse to identify one immutable feature sample.
            c.execute(
                """CREATE TABLE IF NOT EXISTS flow_sample_excursions (
                       sample_id        TEXT PRIMARY KEY,
                       session_date     TEXT NOT NULL,
                       ticker           TEXT,
                       legacy_cluster_key TEXT,
                       decision_time    TEXT,
                       first_seen       TEXT,
                       last_seen        TEXT,
                       cost_basis       REAL,
                       last_pl          REAL,
                       mfe_dollars      REAL,
                       mfe_at           TEXT,
                       mae_dollars      REAL,
                       mae_at           TEXT,
                       samples          INTEGER DEFAULT 0
                   )"""
            )
            c.execute("CREATE INDEX IF NOT EXISTS idx_fse_session "
                      "ON flow_sample_excursions(session_date)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_fse_legacy "
                      "ON flow_sample_excursions(legacy_cluster_key, session_date)")
            # APEX 69.4.1: authoritative identity bridge from the exact persisted
            # feature sample to the live flow cluster lineage. The live P/L path
            # must resolve this map; it may not reconstruct sample_id independently.
            c.execute(
                """CREATE TABLE IF NOT EXISTS flow_sample_identity_map (
                       session_date TEXT NOT NULL,
                       legacy_cluster_key TEXT NOT NULL,
                       decision_time TEXT NOT NULL,
                       sample_id TEXT NOT NULL UNIQUE,
                       registered_at TEXT NOT NULL,
                       PRIMARY KEY(session_date, legacy_cluster_key, decision_time)
                   )"""
            )
            c.execute("CREATE INDEX IF NOT EXISTS idx_fsim_lookup "
                      "ON flow_sample_identity_map(session_date, legacy_cluster_key)")
            # APEX 69.10.19: durable observational lifecycle for exact canonical
            # feature-sample P/L linkage. This table records why a registered sample
            # does or does not have an excursion; it never manufactures P/L.
            c.execute(
                """CREATE TABLE IF NOT EXISTS flow_sample_pl_lifecycle (
                       sample_id TEXT PRIMARY KEY,
                       session_date TEXT NOT NULL,
                       legacy_cluster_key TEXT NOT NULL,
                       decision_time TEXT NOT NULL,
                       state TEXT NOT NULL,
                       reason TEXT,
                       first_registered_at TEXT NOT NULL,
                       last_observed_at TEXT NOT NULL,
                       pl_observations INTEGER DEFAULT 0,
                       excursion_writes INTEGER DEFAULT 0
                   )"""
            )
            c.execute("CREATE INDEX IF NOT EXISTS idx_fspl_state "
                      "ON flow_sample_pl_lifecycle(session_date, state)")
            # APEX 69.3: durable capture audit. This is observability only; it
            # never manufactures excursion evidence and never participates in
            # label selection.
            c.execute(
                """CREATE TABLE IF NOT EXISTS flow_excursion_capture_audit (
                       id INTEGER PRIMARY KEY CHECK (id=1),
                       capture_attempts INTEGER DEFAULT 0,
                       excursions_inserted INTEGER DEFAULT 0,
                       excursions_updated INTEGER DEFAULT 0,
                       missing_feature_sample INTEGER DEFAULT 0,
                       missing_pl INTEGER DEFAULT 0,
                       capture_errors INTEGER DEFAULT 0,
                       last_attempt_at TEXT,
                       last_success_at TEXT,
                       last_sample_id TEXT,
                       canonical_capture_attempts INTEGER DEFAULT 0,
                       canonical_missing_feature_sample INTEGER DEFAULT 0,
                       identity_registration_failures INTEGER DEFAULT 0
                   )"""
            )
            # APEX 69.10.5 adds post-persistence-only counters without rewriting
            # the historical aggregate. ``missing_feature_sample`` may include the
            # pre-69.10.5 source-stage false attempts; the canonical counters start
            # at zero on upgrade and measure only exact feature-sample targets.
            audit_cols = {r["name"] for r in c.execute(
                "PRAGMA table_info(flow_excursion_capture_audit)")}
            for col, decl in (
                ("canonical_capture_attempts", "INTEGER DEFAULT 0"),
                ("canonical_missing_feature_sample", "INTEGER DEFAULT 0"),
                ("identity_registration_failures", "INTEGER DEFAULT 0"),
            ):
                if col not in audit_cols:
                    c.execute(f"ALTER TABLE flow_excursion_capture_audit ADD COLUMN {col} {decl}")
            c.execute("INSERT OR IGNORE INTO flow_excursion_capture_audit(id) VALUES (1)")
            # APEX 69.10.20: prove that every canonical excursion counted as a
            # successful write is immediately retrievable through the exact same
            # public read contract used by settlement. Observability only.
            c.execute(
                """CREATE TABLE IF NOT EXISTS flow_excursion_write_readback_audit (
                       id INTEGER PRIMARY KEY CHECK (id=1),
                       write_commits INTEGER DEFAULT 0,
                       readback_attempts INTEGER DEFAULT 0,
                       readback_verified INTEGER DEFAULT 0,
                       readback_missing INTEGER DEFAULT 0,
                       readback_identity_mismatch INTEGER DEFAULT 0,
                       last_sample_id TEXT,
                       last_session_date TEXT,
                       last_db_path TEXT,
                       last_table TEXT,
                       last_write_mode TEXT,
                       last_rows_affected INTEGER,
                       last_readback_found INTEGER,
                       last_verified_at TEXT
                   )"""
            )
            c.execute("INSERT OR IGNORE INTO flow_excursion_write_readback_audit(id) VALUES (1)")
            c.commit()
        _DB_READY = True
    except Exception as e:  # pragma: no cover
        _DB_READY = False
        record_degradation(
            component="flow_pl_store", operation="init_db", exc=e,
            fallback="FLOW_PL_TRACKING_DISABLED", decision_authority_suppressed=False,
            source=__name__, context={"db_path": _db_path()},
        )
        print(f"Flow P/L tracking DISABLED — DB init failed at '{_db_path()}': {e}", flush=True)
    return _DB_READY


def is_ready() -> bool:
    return _DB_READY


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def record_observation(pl: Dict[str, Any], *, cluster_key: Optional[str] = None,
                       session_date: Optional[str] = None,
                       spot: Optional[float] = None,
                       iv: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """Record one P/L sample and update the running MFE/MAE.

    First sight of an event inserts its baseline (and captures entry_spot/entry_iv
    at *first observation* — see module docstring). Subsequent samples only widen
    the excursion envelope; they never rewrite the baseline.
    """
    if not _DB_READY or not pl or not pl.get("event_id"):
        return None
    if not pl.get("markable"):
        return None
    try:
        eid = pl["event_id"]
        now = _now_iso()
        cur_pl = pl.get("estimated_pl_dollars")
        if cur_pl is None:
            return None
        with _LOCK, _conn() as c:
            row = c.execute("SELECT * FROM flow_pl_tracking WHERE event_id=?", (eid,)).fetchone()
            if row is None:
                c.execute(
                    """INSERT INTO flow_pl_tracking
                       (event_id, cluster_key, session_date, ticker, contract_type, strike,
                        expiration, position_side, contracts, multiplier, entry_time_et,
                        entry_mark, entry_spot, entry_iv, first_seen, last_seen, last_mark,
                        last_pl, mfe_dollars, mfe_at, mae_dollars, mae_at, samples,
                        mark_methodology)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (eid, cluster_key, session_date, pl.get("ticker"), pl.get("contract_type"),
                     pl.get("strike"), pl.get("expiration"), pl.get("position_side"),
                     pl.get("contracts"), pl.get("multiplier"), pl.get("entry_time_et"),
                     pl.get("entry_mark"), spot, iv, now, now, pl.get("current_mark"),
                     cur_pl, cur_pl, now, cur_pl, now, 1, pl.get("mark_methodology")),
                )
                c.commit()
                return {"event_id": eid, "samples": 1, "mfe_dollars": cur_pl,
                        "mae_dollars": cur_pl, "first_sample": True}

            mfe = row["mfe_dollars"] if row["mfe_dollars"] is not None else cur_pl
            mae = row["mae_dollars"] if row["mae_dollars"] is not None else cur_pl
            mfe_at, mae_at = row["mfe_at"], row["mae_at"]
            if cur_pl > mfe:
                mfe, mfe_at = cur_pl, now
            if cur_pl < mae:
                mae, mae_at = cur_pl, now
            c.execute(
                """UPDATE flow_pl_tracking
                   SET last_seen=?, last_mark=?, last_pl=?, mfe_dollars=?, mfe_at=?,
                       mae_dollars=?, mae_at=?, samples=samples+1, mark_methodology=?
                   WHERE event_id=?""",
                (now, pl.get("current_mark"), cur_pl, mfe, mfe_at, mae, mae_at,
                 pl.get("mark_methodology"), eid),
            )
            c.commit()
            return {"event_id": eid, "samples": (row["samples"] or 0) + 1,
                    "mfe_dollars": mfe, "mae_dollars": mae, "first_sample": False}
    except Exception as e:  # pragma: no cover
        record_degradation(
            component="flow_pl_store", operation="record_observation", exc=e,
            fallback="OBSERVATION_NOT_PERSISTED", decision_authority_suppressed=False,
            source=__name__, context={"db_path": _db_path()},
        )
        print(f"flow_pl_store.record_observation failed (non-fatal): {e}", flush=True)
        return None


def _secs_between(a: Optional[str], b: Optional[str]) -> Optional[int]:
    if not a or not b:
        return None
    try:
        da = dt.datetime.fromisoformat(a)
        db = dt.datetime.fromisoformat(b)
        return int((db - da).total_seconds())
    except (TypeError, ValueError):
        return None


def get_excursions(event_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """Return MFE/MAE + time-to-excursion per event_id. Empty dict if unavailable."""
    if not _DB_READY or not event_ids:
        return {}
    try:
        out: Dict[str, Dict[str, Any]] = {}
        with _conn() as c:
            # Chunk to stay under SQLite's variable limit on large tapes.
            for i in range(0, len(event_ids), 400):
                chunk = event_ids[i:i + 400]
                q = ",".join("?" * len(chunk))
                for r in c.execute(
                        f"SELECT * FROM flow_pl_tracking WHERE event_id IN ({q})", chunk):
                    out[r["event_id"]] = {
                        "mfe_dollars": r["mfe_dollars"],
                        "mae_dollars": r["mae_dollars"],
                        "time_to_mfe_seconds": _secs_between(r["first_seen"], r["mfe_at"]),
                        "time_to_mae_seconds": _secs_between(r["first_seen"], r["mae_at"]),
                        "samples": r["samples"],
                        "first_seen": r["first_seen"],
                        "last_seen": r["last_seen"],
                        "entry_spot_at_first_observation": r["entry_spot"],
                        "entry_iv_at_first_observation": r["entry_iv"],
                        "excursion_basis": ("Measured from first observation, not from the "
                                            "print — the quote at trade time was never available."),
                    }
        return out
    except Exception as e:  # pragma: no cover
        record_degradation(
            component="flow_pl_store", operation="get_excursions", exc=e,
            fallback="EMPTY_EXCURSION_HISTORY", decision_authority_suppressed=False,
            source=__name__, context={"db_path": _db_path()},
        )
        print(f"flow_pl_store.get_excursions failed (non-fatal): {e}", flush=True)
        return {}



def register_sample_identity(*, sample_id: str, session_date: str, legacy_cluster_key: str,
                             decision_time: str) -> bool:
    """Register and verify the exact immutable feature identity.

    ``INSERT OR IGNORE`` is retained for duplicate-safe replay, but success now
    means the persisted row actually matches all four identity fields. A uniqueness
    collision therefore fails closed instead of being reported as a successful
    lineage publication.
    """
    if not _DB_READY or not sample_id or not session_date or not legacy_cluster_key or not decision_time:
        return False
    try:
        with _LOCK, _conn() as c:
            c.execute(
                """INSERT OR IGNORE INTO flow_sample_identity_map
                   (session_date, legacy_cluster_key, decision_time, sample_id, registered_at)
                   VALUES (?,?,?,?,?)""",
                (session_date, legacy_cluster_key, decision_time, sample_id, _now_iso()),
            )
            row = c.execute(
                """SELECT session_date,legacy_cluster_key,decision_time,sample_id
                   FROM flow_sample_identity_map WHERE sample_id=?""",
                (sample_id,),
            ).fetchone()
            c.commit()
        return bool(row and row["session_date"] == session_date
                    and row["legacy_cluster_key"] == legacy_cluster_key
                    and row["decision_time"] == decision_time
                    and row["sample_id"] == sample_id)
    except Exception:
        return False


def record_sample_pl_lifecycle(*, sample_id: str, session_date: str,
                               legacy_cluster_key: str, decision_time: str,
                               state: str, reason: Optional[str] = None,
                               pl_observed: bool = False, excursion_written: bool = False) -> bool:
    """Record the exact canonical sample's real-P/L linkage state.

    APEX 69.10.19 observability only: callers must already possess the persisted
    canonical sample_id. This function never resolves, reconstructs, or substitutes
    identity and never creates P/L/excursion evidence.
    """
    if not _DB_READY or not all((sample_id, session_date, legacy_cluster_key, decision_time, state)):
        return False
    try:
        now = _now_iso()
        with _LOCK, _conn() as c:
            c.execute(
                """INSERT INTO flow_sample_pl_lifecycle
                   (sample_id,session_date,legacy_cluster_key,decision_time,state,reason,
                    first_registered_at,last_observed_at,pl_observations,excursion_writes)
                   VALUES (?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(sample_id) DO UPDATE SET
                     state=excluded.state, reason=excluded.reason,
                     last_observed_at=excluded.last_observed_at,
                     pl_observations=flow_sample_pl_lifecycle.pl_observations+excluded.pl_observations,
                     excursion_writes=flow_sample_pl_lifecycle.excursion_writes+excluded.excursion_writes""",
                (sample_id,session_date,legacy_cluster_key,decision_time,state,reason,now,now,
                 1 if pl_observed else 0, 1 if excursion_written else 0))
            c.commit()
        return True
    except Exception:
        return False


def sample_pl_lifecycle_health() -> Dict[str, Any]:
    out = {"version": "69.10.19", "identity_basis": "CANONICAL_FEATURE_SAMPLE_ID",
           "writes_evidence": False, "reconstructs_identity": False, "states": {},
           "registered_samples": 0, "pl_observations": 0, "excursion_writes": 0}
    if not _DB_READY:
        return out
    try:
        with _conn() as c:
            rows=c.execute("SELECT state,COUNT(*) n FROM flow_sample_pl_lifecycle GROUP BY state").fetchall()
            out["states"]={r["state"]: r["n"] for r in rows}
            r=c.execute("SELECT COUNT(*) n,COALESCE(SUM(pl_observations),0) p,COALESCE(SUM(excursion_writes),0) w FROM flow_sample_pl_lifecycle").fetchone()
            out.update({"registered_samples":r["n"],"pl_observations":r["p"],"excursion_writes":r["w"]})
    except Exception as exc:
        out["error"]=f"{type(exc).__name__}: {exc}"
    return out


def resolve_exact_sample_identity(*, session_date: str, legacy_cluster_key: str,
                                  decision_time: str) -> Optional[Dict[str, Any]]:
    """Resolve only an exact persisted feature identity tuple.

    APEX 69.10.16 uses this on later live cluster P/L observations.  It never
    reconstructs ``sample_id`` and never falls back to the newest sample for a
    coarse cluster key, because either behavior could attach an outcome to the
    wrong immutable feature vector.
    """
    if not _DB_READY or not session_date or not legacy_cluster_key or not decision_time:
        return None
    try:
        with _conn() as c:
            row = c.execute(
                """SELECT sample_id,decision_time,session_date,legacy_cluster_key
                   FROM flow_sample_identity_map
                   WHERE session_date=? AND legacy_cluster_key=? AND decision_time=?
                   LIMIT 1""",
                (session_date, legacy_cluster_key, decision_time),
            ).fetchone()
        return dict(row) if row else None
    except Exception:
        return None


def resolve_sample_identity(*, session_date: str, legacy_cluster_key: str) -> Optional[Dict[str, Any]]:
    """Resolve one canonical sample from persisted identity lineage.

    If more than one sample shares the coarse legacy key, return the most recent
    decision_time. That is safe for the live path because only sealed samples are
    registered and later observations belong to the latest sealed incarnation.
    """
    if not _DB_READY or not session_date or not legacy_cluster_key:
        return None
    try:
        with _conn() as c:
            row = c.execute(
                """SELECT sample_id,decision_time,session_date,legacy_cluster_key
                   FROM flow_sample_identity_map
                   WHERE session_date=? AND legacy_cluster_key=?
                   ORDER BY decision_time DESC LIMIT 1""",
                (session_date, legacy_cluster_key),
            ).fetchone()
        return dict(row) if row else None
    except Exception:
        return None

def record_capture_audit(*, attempted: int = 0, inserted: int = 0, updated: int = 0,
                         missing_feature: int = 0, missing_pl: int = 0,
                         errors: int = 0, sample_id: Optional[str] = None,
                         success: bool = False, canonical_attempted: int = 0,
                         canonical_missing_feature: int = 0,
                         identity_registration_failure: int = 0) -> None:
    """Persist scanner/web-process-neutral excursion capture telemetry.

    The legacy aggregate is preserved for backward compatibility. The canonical
    counters were introduced in 69.10.5 and only advance after a feature sample is
    expected to exist at the post-persistence writer boundary.
    """
    if not _DB_READY:
        return
    try:
        now = _now_iso()
        with _LOCK, _conn() as c:
            c.execute(
                """UPDATE flow_excursion_capture_audit SET
                     capture_attempts=capture_attempts+?,
                     excursions_inserted=excursions_inserted+?,
                     excursions_updated=excursions_updated+?,
                     missing_feature_sample=missing_feature_sample+?,
                     missing_pl=missing_pl+?,
                     capture_errors=capture_errors+?,
                     canonical_capture_attempts=canonical_capture_attempts+?,
                     canonical_missing_feature_sample=canonical_missing_feature_sample+?,
                     identity_registration_failures=identity_registration_failures+?,
                     last_attempt_at=CASE WHEN ?>0 THEN ? ELSE last_attempt_at END,
                     last_success_at=CASE WHEN ? THEN ? ELSE last_success_at END,
                     last_sample_id=COALESCE(?, last_sample_id)
                   WHERE id=1""",
                (attempted, inserted, updated, missing_feature, missing_pl, errors,
                 canonical_attempted, canonical_missing_feature,
                 identity_registration_failure,
                 attempted, now, 1 if success else 0, now, sample_id),
            )
            c.commit()
    except Exception:
        return


def _record_write_readback_audit(*, sample_id: str, session_date: str,
                                 write_mode: str, rows_affected: int,
                                 readback_found: bool, identity_match: bool) -> None:
    """Persist 69.10.20 write/read observability; never selects evidence."""
    if not _DB_READY:
        return
    try:
        verified = bool(readback_found and identity_match)
        with _LOCK, _conn() as c:
            c.execute(
                """UPDATE flow_excursion_write_readback_audit SET
                     write_commits=write_commits+1,
                     readback_attempts=readback_attempts+1,
                     readback_verified=readback_verified+?,
                     readback_missing=readback_missing+?,
                     readback_identity_mismatch=readback_identity_mismatch+?,
                     last_sample_id=?, last_session_date=?, last_db_path=?,
                     last_table='flow_sample_excursions', last_write_mode=?,
                     last_rows_affected=?, last_readback_found=?, last_verified_at=?
                   WHERE id=1""",
                (1 if verified else 0, 0 if readback_found else 1,
                 1 if readback_found and not identity_match else 0,
                 sample_id, session_date, os.path.abspath(_db_path()), write_mode,
                 int(rows_affected or 0), 1 if readback_found else 0, _now_iso()),
            )
            c.commit()
    except Exception:
        return


def excursion_write_readback_health() -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "version": "69.10.20", "identity_basis": "CANONICAL_FEATURE_SAMPLE_ID",
        "db_path": os.path.abspath(_db_path()), "table": "flow_sample_excursions",
        "reader": "get_sample_excursions", "write_commits": 0,
        "readback_attempts": 0, "readback_verified": 0, "readback_missing": 0,
        "readback_identity_mismatch": 0, "writes_evidence": False,
        "reconstructs_identity": False,
    }
    if not _DB_READY:
        return out
    try:
        with _conn() as c:
            r = c.execute("SELECT * FROM flow_excursion_write_readback_audit WHERE id=1").fetchone()
            if r:
                out.update({k: r[k] for k in r.keys() if k != "id"})
    except Exception as e:
        out["error"] = type(e).__name__
    return out


def record_sample_excursion(*, sample_id: str, session_date: str,
                            ticker: Optional[str], pl_dollars: Optional[float],
                            cost_basis: Optional[float], decision_time: Optional[str] = None,
                            legacy_cluster_key: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Persist MFE/MAE under the exact immutable feature ``sample_id``.

    APEX 69.3 keeps the immutable sample as the only label-selecting identity and
    records durable capture telemetry outside the database write lock.
    """
    if not _DB_READY or not sample_id or pl_dollars is None:
        return None
    try:
        now = _now_iso()
        audit_inserted = audit_updated = 0
        with _LOCK, _conn() as c:
            row = c.execute("SELECT * FROM flow_sample_excursions WHERE sample_id=?",
                            (sample_id,)).fetchone()
            if row is None:
                c.execute(
                    """INSERT INTO flow_sample_excursions
                       (sample_id, session_date, ticker, legacy_cluster_key, decision_time,
                        first_seen, last_seen, cost_basis, last_pl, mfe_dollars, mfe_at,
                        mae_dollars, mae_at, samples)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (sample_id, session_date, ticker, legacy_cluster_key, decision_time,
                     now, now, cost_basis, pl_dollars, pl_dollars, now, pl_dollars, now, 1))
                c.commit()
                result = {"sample_id": sample_id, "samples": 1, "first_sample": True}
                audit_inserted = 1
            else:
                mfe = row["mfe_dollars"] if row["mfe_dollars"] is not None else pl_dollars
                mae = row["mae_dollars"] if row["mae_dollars"] is not None else pl_dollars
                mfe_at, mae_at = row["mfe_at"], row["mae_at"]
                if pl_dollars > mfe:
                    mfe, mfe_at = pl_dollars, now
                if pl_dollars < mae:
                    mae, mae_at = pl_dollars, now
                c.execute(
                    """UPDATE flow_sample_excursions
                       SET last_seen=?, last_pl=?, mfe_dollars=?, mfe_at=?, mae_dollars=?,
                           mae_at=?, samples=samples+1, cost_basis=COALESCE(?, cost_basis),
                           legacy_cluster_key=COALESCE(?, legacy_cluster_key)
                       WHERE sample_id=?""",
                    (now, pl_dollars, mfe, mfe_at, mae, mae_at, cost_basis,
                     legacy_cluster_key, sample_id))
                c.commit()
                result = {"sample_id": sample_id, "samples": (row["samples"] or 0) + 1,
                          "first_sample": False, "mfe_dollars": mfe, "mae_dollars": mae}
                audit_updated = 1
        # APEX 69.10.20: post-commit exact read-after-write using the same
        # retrieval function settlement calls. A write is not reported successful
        # unless that exact canonical sample_id is visible through this contract.
        readback = get_sample_excursions([sample_id])
        rb = (readback or {}).get(sample_id)
        readback_found = rb is not None
        identity_match = bool(readback_found)  # dict key is the persisted exact sample_id
        _record_write_readback_audit(
            sample_id=sample_id, session_date=session_date,
            write_mode="INSERT" if audit_inserted else "UPDATE",
            rows_affected=1, readback_found=readback_found, identity_match=identity_match)
        if not readback_found:
            record_capture_audit(attempted=1, errors=1, sample_id=sample_id,
                                 canonical_attempted=1)
            return None
        result["readback_verified"] = True
        result["readback_db_path"] = os.path.abspath(_db_path())
        result["readback_table"] = "flow_sample_excursions"
        record_capture_audit(attempted=1, inserted=audit_inserted, updated=audit_updated,
                             sample_id=sample_id, success=True, canonical_attempted=1)
        return result
    except Exception as e:  # pragma: no cover
        record_capture_audit(attempted=1, errors=1, sample_id=sample_id,
                             canonical_attempted=1)
        record_degradation(
            component="flow_pl_store", operation="record_sample_excursion", exc=e,
            fallback="SAMPLE_EXCURSION_NOT_PERSISTED", decision_authority_suppressed=False,
            source=__name__, context={"db_path": _db_path(), "sample_id": sample_id},
        )
        return None


def audit_sample_identity_join(sample_ids: List[str], *, session_date: Optional[str] = None, sample_limit: int = 5) -> Dict[str, Any]:
    """Audit the persisted three-table canonical identity contract without repairing it.

    APEX 69.10.18 is diagnostic-first: feature sample IDs are compared directly
    with the identity bridge and sample excursion ledger.  No identity is
    reconstructed, no coarse key is substituted, and no evidence is written.
    """
    ids = sorted({str(x) for x in (sample_ids or []) if x})
    out: Dict[str, Any] = {
        "identity_basis": "CANONICAL_FEATURE_SAMPLE_ID",
        "release": "69.10.18",
        "feature_sample_ids": len(ids),
        "identity_map_matches": 0,
        "excursion_matches": 0,
        "registered_without_excursion": 0,
        "excursion_without_identity_map": 0,
        "identity_tuple_mismatches": 0,
        "feature_only_ids": 0,
        "exact_three_table_matches": 0,
        "diagnostic_samples": [],
        "writes_evidence": False,
        "reconstructs_identity": False,
    }
    if not _DB_READY or not ids:
        return out
    try:
        identity_rows: Dict[str, Dict[str, Any]] = {}
        excursion_rows: Dict[str, Dict[str, Any]] = {}
        with _conn() as c:
            for i in range(0, len(ids), 400):
                chunk = ids[i:i+400]
                q = ",".join("?" * len(chunk))
                args: List[Any] = list(chunk)
                sess_clause = ""
                if session_date:
                    sess_clause = " AND session_date=?"
                    args.append(session_date)
                for r in c.execute(
                    f"SELECT sample_id,session_date,legacy_cluster_key,decision_time FROM flow_sample_identity_map WHERE sample_id IN ({q}){sess_clause}", args):
                    identity_rows[str(r["sample_id"])] = dict(r)
                args2: List[Any] = list(chunk)
                if session_date:
                    args2.append(session_date)
                for r in c.execute(
                    f"SELECT sample_id,session_date,legacy_cluster_key,decision_time,samples FROM flow_sample_excursions WHERE sample_id IN ({q}){sess_clause}", args2):
                    excursion_rows[str(r["sample_id"])] = dict(r)
        im = set(identity_rows)
        ex = set(excursion_rows)
        fs = set(ids)
        out["identity_map_matches"] = len(fs & im)
        out["excursion_matches"] = len(fs & ex)
        out["registered_without_excursion"] = len((fs & im) - ex)
        out["excursion_without_identity_map"] = len((fs & ex) - im)
        out["feature_only_ids"] = len(fs - im - ex)
        out["exact_three_table_matches"] = len(fs & im & ex)
        mismatches = []
        for sid in sorted(fs & im & ex):
            a, b = identity_rows[sid], excursion_rows[sid]
            if (a.get("session_date") != b.get("session_date") or
                a.get("decision_time") != b.get("decision_time") or
                a.get("legacy_cluster_key") != b.get("legacy_cluster_key")):
                mismatches.append(sid)
        out["identity_tuple_mismatches"] = len(mismatches)
        sample_ids_diag = sorted(fs - ex)[:max(0, int(sample_limit))]
        for sid in sample_ids_diag:
            ir = identity_rows.get(sid)
            er = excursion_rows.get(sid)
            out["diagnostic_samples"].append({
                "sample_id": sid,
                "identity_map_present": bool(ir),
                "excursion_present": bool(er),
                "identity_session_date": ir.get("session_date") if ir else None,
                "identity_decision_time": ir.get("decision_time") if ir else None,
                "identity_legacy_cluster_key": ir.get("legacy_cluster_key") if ir else None,
            })
        return out
    except Exception as e:
        out["error"] = type(e).__name__
        return out

def reconcile_settlement_excursion_cohort(sample_ids: List[str], *, session_date: str, sample_limit: int = 10) -> Dict[str, Any]:
    """Compare settlement's exact requested IDs with the persisted excursion cohort.

    APEX 69.10.21 is diagnostic-only. It does not repair, reconstruct, remap,
    fuzzy-match, or write evidence. The comparison is exact sample_id equality
    within the explicitly requested session_date.
    """
    requested = sorted({str(x) for x in (sample_ids or []) if x})
    out: Dict[str, Any] = {
        "version": "69.10.21",
        "identity_basis": "CANONICAL_FEATURE_SAMPLE_ID",
        "session_date": str(session_date or "")[:10],
        "settlement_requested_ids": len(requested),
        "excursion_session_ids": 0,
        "requested_with_excursion": 0,
        "requested_without_excursion": 0,
        "excursion_not_requested": 0,
        "identity_map_only_requested": 0,
        "feature_only_requested": 0,
        "exact_requested_excursion_overlap_pct": 0.0,
        "requested_without_excursion_samples": [],
        "excursion_not_requested_samples": [],
        "writes_evidence": False,
        "reconstructs_identity": False,
        "fuzzy_matching": False,
        "historical_backfill": False,
    }
    if not _DB_READY:
        out["state"] = "FLOW_PL_STORE_NOT_READY"
        return out
    try:
        identity_rows: Dict[str, Dict[str, Any]] = {}
        excursion_rows: Dict[str, Dict[str, Any]] = {}
        with _conn() as c:
            for r in c.execute(
                "SELECT sample_id,session_date,legacy_cluster_key,decision_time,samples "
                "FROM flow_sample_excursions WHERE session_date=?", (out["session_date"],)):
                excursion_rows[str(r["sample_id"])] = dict(r)
            if requested:
                for i in range(0, len(requested), 400):
                    chunk = requested[i:i+400]
                    q = ",".join("?" * len(chunk))
                    args: List[Any] = list(chunk) + [out["session_date"]]
                    for r in c.execute(
                        f"SELECT sample_id,session_date,legacy_cluster_key,decision_time "
                        f"FROM flow_sample_identity_map WHERE sample_id IN ({q}) AND session_date=?", args):
                        identity_rows[str(r["sample_id"])] = dict(r)
        req, ex, im = set(requested), set(excursion_rows), set(identity_rows)
        overlap = req & ex
        missing = req - ex
        extra = ex - req
        out.update({
            "excursion_session_ids": len(ex),
            "requested_with_excursion": len(overlap),
            "requested_without_excursion": len(missing),
            "excursion_not_requested": len(extra),
            "identity_map_only_requested": len((req & im) - ex),
            "feature_only_requested": len(req - im - ex),
            "exact_requested_excursion_overlap_pct": round((len(overlap) / len(req) * 100.0), 4) if req else 0.0,
            "state": "EXACT_COHORT_ALIGNED" if req == ex else "EXACT_COHORT_DIVERGENCE",
        })
        lim=max(0,int(sample_limit))
        for sid in sorted(missing)[:lim]:
            ir=identity_rows.get(sid)
            out["requested_without_excursion_samples"].append({
                "sample_id": sid,
                "identity_map_present": bool(ir),
                "identity_session_date": ir.get("session_date") if ir else None,
                "identity_decision_time": ir.get("decision_time") if ir else None,
                "identity_legacy_cluster_key": ir.get("legacy_cluster_key") if ir else None,
            })
        for sid in sorted(extra)[:lim]:
            er=excursion_rows[sid]
            out["excursion_not_requested_samples"].append({
                "sample_id": sid,
                "excursion_session_date": er.get("session_date"),
                "excursion_decision_time": er.get("decision_time"),
                "excursion_legacy_cluster_key": er.get("legacy_cluster_key"),
                "samples": er.get("samples"),
            })
        return out
    except Exception as exc:
        out["state"] = "ERROR"
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out


def get_sample_excursions(sample_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """Return exact sample-scoped excursions. No legacy-key fallback is allowed."""
    if not _DB_READY or not sample_ids:
        return {}
    try:
        out: Dict[str, Dict[str, Any]] = {}
        with _conn() as c:
            for i in range(0, len(sample_ids), 400):
                chunk = sample_ids[i:i + 400]
                q = ",".join("?" * len(chunk))
                for r in c.execute(
                        f"SELECT * FROM flow_sample_excursions WHERE sample_id IN ({q})", chunk):
                    out[r["sample_id"]] = {
                        "mfe_dollars": r["mfe_dollars"], "mae_dollars": r["mae_dollars"],
                        "cost_basis": r["cost_basis"], "last_pl": r["last_pl"],
                        "time_to_mfe_seconds": _secs_between(r["first_seen"], r["mfe_at"]),
                        "time_to_mae_seconds": _secs_between(r["first_seen"], r["mae_at"]),
                        "samples": r["samples"], "first_seen": r["first_seen"],
                        "last_seen": r["last_seen"], "decision_time": r["decision_time"],
                        "legacy_cluster_key": r["legacy_cluster_key"],
                        "identity_basis": "CANONICAL_FEATURE_SAMPLE_ID",
                    }
        return out
    except Exception as e:  # pragma: no cover
        record_degradation(
            component="flow_pl_store", operation="get_sample_excursions", exc=e,
            fallback="EMPTY_SAMPLE_EXCURSION_HISTORY", decision_authority_suppressed=False,
            source=__name__, context={"db_path": _db_path()},
        )
        return {}


def sample_excursion_health() -> Dict[str, Any]:
    out = {"ok": _DB_READY, "version": "69.10.5", "sample_excursions": 0,
           "sessions": 0, "latest_at": None, "identity_basis": "CANONICAL_FEATURE_SAMPLE_ID",
           "capture_owner": "FEATURE_STORE_WRITER_POST_PERSISTENCE",
           "capture": {"capture_attempts": 0, "excursions_inserted": 0,
                       "excursions_updated": 0, "missing_feature_sample": 0,
                       "missing_pl": 0, "capture_errors": 0, "last_attempt_at": None,
                       "last_success_at": None, "last_sample_id": None,
                       "canonical_capture_attempts": 0,
                       "canonical_missing_feature_sample": 0,
                       "identity_registration_failures": 0}}
    if not _DB_READY:
        return out
    try:
        with _conn() as c:
            row = c.execute("""SELECT COUNT(*) n, COUNT(DISTINCT session_date) s,
                                MAX(last_seen) latest FROM flow_sample_excursions""").fetchone()
            out.update({"sample_excursions": row["n"], "sessions": row["s"],
                        "latest_at": row["latest"]})
            audit = c.execute("SELECT * FROM flow_excursion_capture_audit WHERE id=1").fetchone()
            if audit is not None:
                out["capture"] = {k: audit[k] for k in audit.keys() if k != "id"}
                out["capture"]["legacy_missing_feature_sample_includes_pre_69_10_5_source_stage"] = True
                out["capture"]["canonical_counter_start_release"] = "69.10.5"
                out["pl_excursion_linkage_lifecycle"] = sample_pl_lifecycle_health()
                out["excursion_write_readback"] = excursion_write_readback_health()
    except Exception as exc:  # pragma: no cover
        out.update({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
    return out


def health() -> Dict[str, Any]:
    info: Dict[str, Any] = {"ready": _DB_READY, "store_version": STORE_VERSION,
                            "db_path": _db_path(), "tracked_events": None}
    if _DB_READY:
        try:
            with _conn() as c:
                info["tracked_events"] = c.execute(
                    "SELECT COUNT(*) n FROM flow_pl_tracking").fetchone()["n"]
                info["total_samples"] = c.execute(
                    "SELECT COALESCE(SUM(samples),0) s FROM flow_pl_tracking").fetchone()["s"]
                info["canonical_sample_excursions"] = c.execute(
                    "SELECT COUNT(*) n FROM flow_sample_excursions").fetchone()["n"]
        except Exception as e:  # pragma: no cover
            info["error"] = str(e)
    return info


# ── Cluster-level excursions (the label surface for Step 5 samples) ────────
def record_cluster_observation(*, cluster_key: str, session_date: str,
                               ticker: Optional[str], pl_dollars: Optional[float],
                               cost_basis: Optional[float]) -> Optional[Dict[str, Any]]:
    """Record one cluster-aggregate P/L sample and widen its MFE/MAE envelope.

    Measured on the cluster's own aggregate P/L rather than summed member
    excursions: members peak at different moments, so a sum would report a peak
    the cluster never actually reached.
    """
    if not _DB_READY or not cluster_key or pl_dollars is None:
        return None
    try:
        now = _now_iso()
        with _LOCK, _conn() as c:
            row = c.execute(
                "SELECT * FROM flow_pl_cluster_tracking WHERE cluster_key=? AND session_date=?",
                (cluster_key, session_date)).fetchone()
            if row is None:
                c.execute(
                    """INSERT INTO flow_pl_cluster_tracking
                       (cluster_key, session_date, ticker, first_seen, last_seen, cost_basis,
                        last_pl, mfe_dollars, mfe_at, mae_dollars, mae_at, samples)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (cluster_key, session_date, ticker, now, now, cost_basis, pl_dollars,
                     pl_dollars, now, pl_dollars, now, 1))
                c.commit()
                return {"cluster_key": cluster_key, "samples": 1, "first_sample": True}

            mfe = row["mfe_dollars"] if row["mfe_dollars"] is not None else pl_dollars
            mae = row["mae_dollars"] if row["mae_dollars"] is not None else pl_dollars
            mfe_at, mae_at = row["mfe_at"], row["mae_at"]
            if pl_dollars > mfe:
                mfe, mfe_at = pl_dollars, now
            if pl_dollars < mae:
                mae, mae_at = pl_dollars, now
            c.execute(
                """UPDATE flow_pl_cluster_tracking
                   SET last_seen=?, last_pl=?, mfe_dollars=?, mfe_at=?, mae_dollars=?,
                       mae_at=?, samples=samples+1,
                       cost_basis=COALESCE(?, cost_basis)
                   WHERE cluster_key=? AND session_date=?""",
                (now, pl_dollars, mfe, mfe_at, mae, mae_at, cost_basis,
                 cluster_key, session_date))
            c.commit()
            return {"cluster_key": cluster_key, "samples": (row["samples"] or 0) + 1,
                    "first_sample": False}
    except Exception as e:  # pragma: no cover
        record_degradation(
            component="flow_pl_store", operation="record_cluster_observation", exc=e,
            fallback="CLUSTER_OBSERVATION_NOT_PERSISTED", decision_authority_suppressed=False,
            source=__name__, context={"db_path": _db_path()},
        )
        print(f"flow_pl_store.record_cluster_observation failed (non-fatal): {e}", flush=True)
        return None


def get_cluster_excursions(cluster_keys: List[str], session_date: str
                           ) -> Dict[str, Dict[str, Any]]:
    """Cluster MFE/MAE + time-to-excursion for one session."""
    if not _DB_READY or not cluster_keys:
        return {}
    try:
        out: Dict[str, Dict[str, Any]] = {}
        with _conn() as c:
            for i in range(0, len(cluster_keys), 400):
                chunk = cluster_keys[i:i + 400]
                q = ",".join("?" * len(chunk))
                for r in c.execute(
                        f"""SELECT * FROM flow_pl_cluster_tracking
                            WHERE session_date=? AND cluster_key IN ({q})""",
                        [session_date] + list(chunk)):
                    out[r["cluster_key"]] = {
                        "mfe_dollars": r["mfe_dollars"],
                        "mae_dollars": r["mae_dollars"],
                        "cost_basis": r["cost_basis"],
                        "last_pl": r["last_pl"],
                        "time_to_mfe_seconds": _secs_between(r["first_seen"], r["mfe_at"]),
                        "time_to_mae_seconds": _secs_between(r["first_seen"], r["mae_at"]),
                        "samples": r["samples"],
                        "first_seen": r["first_seen"],
                        "last_seen": r["last_seen"],
                    }
        return out
    except Exception as e:  # pragma: no cover
        record_degradation(
            component="flow_pl_store", operation="get_cluster_excursions", exc=e,
            fallback="EMPTY_CLUSTER_EXCURSION_HISTORY", decision_authority_suppressed=False,
            source=__name__, context={"db_path": _db_path()},
        )
        print(f"flow_pl_store.get_cluster_excursions failed (non-fatal): {e}", flush=True)
        return {}
