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

_DB_PATH = os.getenv("DB_PATH", "apex_tracking.db")
_LOCK = threading.Lock()
_DB_READY = False

STORE_VERSION = "9.4.0_FLOW_PL_STORE"


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def init_db() -> bool:
    """Create/upgrade the tracking table. Non-fatal: disables tracking on error."""
    global _DB_READY
    try:
        d = os.path.dirname(_DB_PATH)
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
            c.commit()
        _DB_READY = True
    except Exception as e:  # pragma: no cover
        _DB_READY = False
        print(f"Flow P/L tracking DISABLED — DB init failed at '{_DB_PATH}': {e}", flush=True)
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
        print(f"flow_pl_store.get_excursions failed (non-fatal): {e}", flush=True)
        return {}


def health() -> Dict[str, Any]:
    info: Dict[str, Any] = {"ready": _DB_READY, "store_version": STORE_VERSION,
                            "db_path": _DB_PATH, "tracked_events": None}
    if _DB_READY:
        try:
            with _conn() as c:
                info["tracked_events"] = c.execute(
                    "SELECT COUNT(*) n FROM flow_pl_tracking").fetchone()["n"]
                info["total_samples"] = c.execute(
                    "SELECT COALESCE(SUM(samples),0) s FROM flow_pl_tracking").fetchone()["s"]
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
        print(f"flow_pl_store.get_cluster_excursions failed (non-fatal): {e}", flush=True)
        return {}
