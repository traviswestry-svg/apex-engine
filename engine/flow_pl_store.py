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

STORE_VERSION = "69.10.27_DURABLE_BOUND_ORIGIN_REOBSERVATION_CLOSURE"


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
            # APEX 69.10.23: durable read-only provenance of the exact feature ->
            # genuine-P/L handoff.  A row records the P/L observation tuple and whether
            # that exact tuple resolved a persisted feature owner.  It never selects,
            # reconstructs, or substitutes an owner and never creates outcome evidence.
            c.execute(
                """CREATE TABLE IF NOT EXISTS flow_feature_pl_handoff_audit (
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       observed_at TEXT NOT NULL,
                       session_date TEXT NOT NULL,
                       legacy_cluster_key TEXT NOT NULL,
                       decision_time TEXT NOT NULL,
                       exact_owner_sample_id TEXT,
                       exact_owner_found INTEGER NOT NULL DEFAULT 0
                   )"""
            )
            c.execute("CREATE INDEX IF NOT EXISTS idx_ffpha_session "
                      "ON flow_feature_pl_handoff_audit(session_date)")
            # APEX 69.10.24: immutable transport of the exact persisted feature
            # origin through later rebuilt runtime clusters. Event IDs are the
            # identity of the originating market objects; no market attributes are
            # used to reconstruct ownership.
            c.execute(
                """CREATE TABLE IF NOT EXISTS flow_feature_origin_bindings (
                       event_id TEXT PRIMARY KEY,
                       sample_id TEXT NOT NULL,
                       session_date TEXT NOT NULL,
                       legacy_cluster_key TEXT NOT NULL,
                       decision_time TEXT NOT NULL,
                       bound_at TEXT NOT NULL
                   )"""
            )
            c.execute("CREATE INDEX IF NOT EXISTS idx_ffob_session "
                      "ON flow_feature_origin_bindings(session_date, sample_id)")
            c.execute(
                """CREATE TABLE IF NOT EXISTS flow_feature_origin_pl_audit (
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       observed_at TEXT NOT NULL,
                       observation_session_date TEXT NOT NULL,
                       observation_legacy_cluster_key TEXT NOT NULL,
                       observation_decision_time TEXT NOT NULL,
                       origin_sample_id TEXT,
                       origin_session_date TEXT,
                       origin_legacy_cluster_key TEXT,
                       origin_decision_time TEXT,
                       provenance_present INTEGER NOT NULL DEFAULT 0,
                       owner_validated INTEGER NOT NULL DEFAULT 0,
                       validation_failed INTEGER NOT NULL DEFAULT 0,
                       direction_evolved INTEGER NOT NULL DEFAULT 0,
                       uncertain_to_bullish INTEGER NOT NULL DEFAULT 0,
                       uncertain_to_bearish INTEGER NOT NULL DEFAULT 0,
                       excursion_written INTEGER NOT NULL DEFAULT 0,
                       excursion_updated INTEGER NOT NULL DEFAULT 0,
                       diagnostic_reason TEXT
                   )"""
            )
            c.execute("CREATE INDEX IF NOT EXISTS idx_ffopa_session "
                      "ON flow_feature_origin_pl_audit(observation_session_date)")
            # APEX 69.10.25: reason-coded transport coverage audit. Ownership is
            # resolved only from direct continuing event ancestry. Unbound new
            # members may coexist with a bound ancestor; conflicting bound
            # ancestors fail closed. No ticker/expiration/direction/time matching.
            c.execute(
                """CREATE TABLE IF NOT EXISTS flow_feature_origin_transport_audit (
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       observed_at TEXT NOT NULL,
                       observation_session_date TEXT NOT NULL,
                       observation_legacy_cluster_key TEXT NOT NULL,
                       observation_decision_time TEXT NOT NULL,
                       event_count INTEGER NOT NULL DEFAULT 0,
                       bound_event_count INTEGER NOT NULL DEFAULT 0,
                       unbound_event_count INTEGER NOT NULL DEFAULT 0,
                       distinct_bound_origins INTEGER NOT NULL DEFAULT 0,
                       transport_status TEXT NOT NULL,
                       resolved_sample_id TEXT,
                       owner_authorized INTEGER NOT NULL DEFAULT 0
                   )"""
            )
            c.execute("CREATE INDEX IF NOT EXISTS idx_ffota_session "
                      "ON flow_feature_origin_transport_audit(observation_session_date)")
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
                             decision_time: str, origin_event_ids: Optional[List[str]] = None) -> bool:
    """Register and verify the immutable feature identity and optional origin bindings.

    APEX 69.10.24 makes identity publication + origin transport atomic inside the
    canonical evidence store. Event bindings come only from the successfully
    persisted feature's originating runtime object. Conflicts fail closed.
    """
    if not _DB_READY or not sample_id or not session_date or not legacy_cluster_key or not decision_time:
        return False
    event_ids = [str(x) for x in (origin_event_ids or []) if x]
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
                   FROM flow_sample_identity_map WHERE sample_id=?""", (sample_id,)).fetchone()
            ok = bool(row and row["session_date"] == session_date
                      and row["legacy_cluster_key"] == legacy_cluster_key
                      and row["decision_time"] == decision_time
                      and row["sample_id"] == sample_id)
            if not ok:
                c.rollback(); return False
            now = _now_iso()
            for event_id in event_ids:
                c.execute(
                    """INSERT OR IGNORE INTO flow_feature_origin_bindings
                       (event_id,sample_id,session_date,legacy_cluster_key,decision_time,bound_at)
                       VALUES (?,?,?,?,?,?)""",
                    (event_id,sample_id,session_date,legacy_cluster_key,decision_time,now))
                b = c.execute(
                    """SELECT sample_id,session_date,legacy_cluster_key,decision_time
                       FROM flow_feature_origin_bindings WHERE event_id=?""", (event_id,)).fetchone()
                if not (b and b["sample_id"] == sample_id and b["session_date"] == session_date
                        and b["legacy_cluster_key"] == legacy_cluster_key
                        and b["decision_time"] == decision_time):
                    c.rollback(); return False
            c.commit()
        return True
    except Exception:
        return False


def get_bound_origin_repricing_candidates(session_date: str) -> List[Dict[str, Any]]:
    """Return durable, exact origin-bound events eligible for genuine re-observation.

    APEX 69.10.27 closes the source-window gap: once a persisted feature has
    atomically bound its originating event IDs, later repricing does not require
    those historical prints to remain in the provider's current tape window.
    Ownership comes only from ``flow_feature_origin_bindings`` and event facts
    come only from the previously observed ``flow_pl_tracking`` row.
    """
    if not _DB_READY or not session_date:
        return []
    try:
        with _conn() as c:
            rows = c.execute(
                """SELECT b.event_id,b.sample_id,b.session_date,b.legacy_cluster_key,
                          b.decision_time,t.ticker,t.contract_type,t.strike,t.expiration,
                          t.position_side,t.contracts,t.multiplier,t.entry_time_et,
                          t.entry_mark,t.entry_spot,t.entry_iv
                   FROM flow_feature_origin_bindings b
                   JOIN flow_pl_tracking t ON t.event_id=b.event_id
                   WHERE b.session_date=?
                   ORDER BY b.sample_id,b.event_id""", (session_date,)).fetchall()
        return [dict(r) for r in rows]
    except Exception as exc:
        record_degradation(
            component="flow_pl_store", operation="get_bound_origin_repricing_candidates",
            exc=exc, fallback="NO_DURABLE_ORIGIN_REPRICING",
            decision_authority_suppressed=False, source=__name__,
            context={"db_path": _db_path(), "session_date": session_date})
        return []


def resolve_feature_origin_transport(*, event_ids: List[str]) -> Dict[str, Any]:
    """Resolve provenance from direct event ancestry and explain every miss.

    FULL_EXACT_BINDING requires every current member event to be bound to the
    same persisted origin. PARTIAL_CONSISTENT_BINDING permits newly-added
    unbound members only when at least one continuing member is directly bound
    and every bound member names the identical immutable origin tuple. This is
    deterministic ancestry transport, not matching on market attributes. Any
    conflicting bound origins fail closed.
    """
    ids = list(dict.fromkeys(str(x) for x in (event_ids or []) if x))
    out = {
        "version": "69.10.25", "transport_status": "NO_EVENT_IDS",
        "event_count": len(ids), "bound_event_count": 0,
        "unbound_event_count": len(ids), "distinct_bound_origins": 0,
        "owner_authorized": False, "origin": None,
        "identity_basis": "DIRECT_EVENT_ANCESTRY",
        "fuzzy_matching": False, "reconstructs_identity": False,
        "uses_market_attributes": False, "latest_owner_substitution": False,
    }
    if not ids:
        return out
    if not _DB_READY:
        out["transport_status"] = "STORE_NOT_READY"
        return out
    try:
        with _conn() as c:
            q = ",".join("?" * len(ids))
            rows = c.execute(
                f"SELECT event_id,sample_id,session_date,legacy_cluster_key,decision_time "
                f"FROM flow_feature_origin_bindings WHERE event_id IN ({q})", ids).fetchall()
        out["bound_event_count"] = len(rows)
        out["unbound_event_count"] = len(ids) - len(rows)
        if not rows:
            out["transport_status"] = "NO_BOUND_EVENTS"
            return out
        tuples = {(r["sample_id"], r["session_date"], r["legacy_cluster_key"], r["decision_time"])
                  for r in rows}
        out["distinct_bound_origins"] = len(tuples)
        if len(tuples) != 1:
            out["transport_status"] = "CONFLICTING_BOUND_ORIGINS"
            return out
        sample_id, session_date, legacy_cluster_key, decision_time = next(iter(tuples))
        origin = {"sample_id": sample_id, "session_date": session_date,
                  "legacy_cluster_key": legacy_cluster_key, "decision_time": decision_time}
        out["origin"] = origin
        out["owner_authorized"] = True
        out["transport_status"] = ("FULL_EXACT_BINDING" if len(rows) == len(ids)
                                   else "PARTIAL_CONSISTENT_BINDING")
        return out
    except Exception as exc:
        out["transport_status"] = "RESOLVER_ERROR"
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out


def resolve_feature_origin_provenance(*, event_ids: List[str]) -> Optional[Dict[str, Any]]:
    """Compatibility surface returning only an authorized deterministic origin."""
    result = resolve_feature_origin_transport(event_ids=event_ids)
    return result.get("origin") if result.get("owner_authorized") else None


def record_feature_origin_transport_observation(*, observation_session_date: str,
        observation_legacy_cluster_key: str, observation_decision_time: str,
        transport: Dict[str, Any]) -> bool:
    if not _DB_READY or not all((observation_session_date, observation_legacy_cluster_key,
                                 observation_decision_time)):
        return False
    t = transport or {}
    origin = t.get("origin") or {}
    try:
        with _LOCK, _conn() as c:
            c.execute(
                """INSERT INTO flow_feature_origin_transport_audit
                   (observed_at,observation_session_date,observation_legacy_cluster_key,
                    observation_decision_time,event_count,bound_event_count,unbound_event_count,
                    distinct_bound_origins,transport_status,resolved_sample_id,owner_authorized)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (_now_iso(), observation_session_date, observation_legacy_cluster_key,
                 observation_decision_time, int(t.get("event_count") or 0),
                 int(t.get("bound_event_count") or 0), int(t.get("unbound_event_count") or 0),
                 int(t.get("distinct_bound_origins") or 0),
                 str(t.get("transport_status") or "UNKNOWN"), origin.get("sample_id"),
                 1 if t.get("owner_authorized") else 0))
            c.commit()
        return True
    except Exception:
        return False


def feature_origin_transport_coverage_health(session_date: Optional[str] = None) -> Dict[str, Any]:
    out = {
        "version":"69.10.25", "identity_basis":"DIRECT_EVENT_ANCESTRY",
        "transport_observations":0, "full_exact_bindings":0,
        "partial_consistent_bindings":0, "no_event_ids":0, "no_bound_events":0,
        "conflicting_bound_origins":0, "store_not_ready":0, "resolver_errors":0,
        "transport_owner_resolved":0, "transport_owner_missing":0,
        "transport_resolution_pct":0.0, "observations_with_any_bound_event":0,
        "bound_events":0, "unbound_events":0,
        "owner_authority":"DIRECT_CONTINUING_EVENT_ANCESTRY_ONLY",
        "writes_evidence":False, "reconstructs_identity":False, "fuzzy_matching":False,
        "uses_market_attributes":False, "latest_owner_substitution":False,
        "historical_backfill":False, "changes_trade_decisions":False,
        "execution_authority":False}
    if not _DB_READY:
        return out
    try:
        where = " WHERE observation_session_date=?" if session_date else ""
        args = (session_date,) if session_date else ()
        with _conn() as c:
            r = c.execute(
                "SELECT COUNT(*) n,"
                "COALESCE(SUM(CASE WHEN transport_status='FULL_EXACT_BINDING' THEN 1 ELSE 0 END),0) full_n,"
                "COALESCE(SUM(CASE WHEN transport_status='PARTIAL_CONSISTENT_BINDING' THEN 1 ELSE 0 END),0) partial_n,"
                "COALESCE(SUM(CASE WHEN transport_status='NO_EVENT_IDS' THEN 1 ELSE 0 END),0) noids,"
                "COALESCE(SUM(CASE WHEN transport_status='NO_BOUND_EVENTS' THEN 1 ELSE 0 END),0) nobound,"
                "COALESCE(SUM(CASE WHEN transport_status='CONFLICTING_BOUND_ORIGINS' THEN 1 ELSE 0 END),0) conflict,"
                "COALESCE(SUM(CASE WHEN transport_status='STORE_NOT_READY' THEN 1 ELSE 0 END),0) notready,"
                "COALESCE(SUM(CASE WHEN transport_status='RESOLVER_ERROR' THEN 1 ELSE 0 END),0) err,"
                "COALESCE(SUM(owner_authorized),0) resolved,"
                "COALESCE(SUM(CASE WHEN bound_event_count>0 THEN 1 ELSE 0 END),0) anybound,"
                "COALESCE(SUM(bound_event_count),0) bound,"
                "COALESCE(SUM(unbound_event_count),0) unbound "
                "FROM flow_feature_origin_transport_audit" + where, args).fetchone()
        vals = {k:int(r[k] or 0) for k in ("n","full_n","partial_n","noids","nobound","conflict","notready","err","resolved","anybound","bound","unbound")}
        out.update({
            "transport_observations":vals["n"], "full_exact_bindings":vals["full_n"],
            "partial_consistent_bindings":vals["partial_n"], "no_event_ids":vals["noids"],
            "no_bound_events":vals["nobound"], "conflicting_bound_origins":vals["conflict"],
            "store_not_ready":vals["notready"], "resolver_errors":vals["err"],
            "transport_owner_resolved":vals["resolved"],
            "transport_owner_missing":max(0, vals["n"]-vals["resolved"]),
            "transport_resolution_pct":round(vals["resolved"]/vals["n"]*100.0,2) if vals["n"] else 0.0,
            "observations_with_any_bound_event":vals["anybound"],
            "bound_events":vals["bound"], "unbound_events":vals["unbound"]})
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


def record_feature_origin_pl_observation(*, observation_session_date: str,
        observation_legacy_cluster_key: str, observation_decision_time: str,
        origin: Optional[Dict[str, Any]], owner_validated: bool,
        diagnostic_reason: str, excursion_written: bool = False,
        excursion_updated: bool = False) -> bool:
    if not _DB_READY or not all((observation_session_date, observation_legacy_cluster_key, observation_decision_time)):
        return False
    od = str(observation_legacy_cluster_key).rsplit("|",1)[-1]
    ok = origin or {}
    rd = str(ok.get("legacy_cluster_key") or "").rsplit("|",1)[-1]
    evolved = bool(origin and od != rd)
    try:
        with _LOCK, _conn() as c:
            c.execute(
                """INSERT INTO flow_feature_origin_pl_audit
                   (observed_at,observation_session_date,observation_legacy_cluster_key,
                    observation_decision_time,origin_sample_id,origin_session_date,
                    origin_legacy_cluster_key,origin_decision_time,provenance_present,
                    owner_validated,validation_failed,direction_evolved,uncertain_to_bullish,
                    uncertain_to_bearish,excursion_written,excursion_updated,diagnostic_reason)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (_now_iso(),observation_session_date,observation_legacy_cluster_key,observation_decision_time,
                 ok.get("sample_id"),ok.get("session_date"),ok.get("legacy_cluster_key"),ok.get("decision_time"),
                 1 if origin else 0,1 if owner_validated else 0,1 if origin and not owner_validated else 0,
                 1 if evolved else 0,1 if rd=="UNCERTAIN" and od=="BULLISH" else 0,
                 1 if rd=="UNCERTAIN" and od=="BEARISH" else 0,1 if excursion_written else 0,
                 1 if excursion_updated else 0,diagnostic_reason))
            c.commit()
        return True
    except Exception:
        return False


def feature_origin_provenance_health(session_date: Optional[str] = None) -> Dict[str, Any]:
    out = {"version":"69.10.25","identity_basis":"CANONICAL_FEATURE_SAMPLE_ID",
           "pl_handoff_observations":0,"origin_provenance_present":0,"origin_provenance_missing":0,
           "origin_owner_validated":0,"origin_owner_validation_failed":0,"origin_owned_pl_observations":0,
           "origin_owned_excursion_writes":0,"origin_owned_excursion_updates":0,
           "origin_direction_unchanged":0,"origin_direction_evolved":0,"origin_uncertain_to_bullish":0,
           "origin_uncertain_to_bearish":0,"provenance_resolution_pct":0.0,"ownership_integrity_failures":0,
           "writes_evidence":False,"reconstructs_identity":False,"fuzzy_matching":False,
           "historical_backfill":False,"changes_trade_decisions":False,"execution_authority":False}
    if not _DB_READY: return out
    try:
        where = " WHERE observation_session_date=?" if session_date else ""
        args = (session_date,) if session_date else ()
        with _conn() as c:
            r=c.execute("SELECT COUNT(*) n,COALESCE(SUM(provenance_present),0) p,COALESCE(SUM(owner_validated),0) v,"
                        "COALESCE(SUM(validation_failed),0) f,COALESCE(SUM(direction_evolved),0) de,"
                        "COALESCE(SUM(uncertain_to_bullish),0) ub,COALESCE(SUM(uncertain_to_bearish),0) ur,"
                        "COALESCE(SUM(excursion_written),0) ew,COALESCE(SUM(excursion_updated),0) eu "
                        "FROM flow_feature_origin_pl_audit"+where,args).fetchone()
        n,p,v,f,de,ub,ur,ew,eu=[int(r[k] or 0) for k in ("n","p","v","f","de","ub","ur","ew","eu")]
        legacy = feature_pl_handoff_health()
        out.update({"pl_handoff_observations":n,"origin_provenance_present":p,"origin_provenance_missing":n-p,
                    "origin_owner_validated":v,"origin_owner_validation_failed":f,"origin_owned_pl_observations":v,
                    "origin_owned_excursion_writes":ew,"origin_owned_excursion_updates":eu,
                    "origin_direction_evolved":de,"origin_direction_unchanged":max(0,p-de),
                    "origin_uncertain_to_bullish":ub,"origin_uncertain_to_bearish":ur,
                    "fallback_exact_owner_found":int(legacy.get("exact_feature_owner_found") or 0),
                    "fallback_exact_owner_missing":int(legacy.get("exact_feature_owner_missing") or 0),
                    "provenance_resolution_pct":round(v/n*100.0,2) if n else 0.0,
                    "ownership_integrity_failures":f})
    except Exception as exc: out["error"]=f"{type(exc).__name__}: {exc}"
    return out


def feature_origin_session_audit(session_date: str) -> Dict[str, Any]:
    out = feature_origin_provenance_health(session_date)
    out.update({"session_date":session_date,"persisted_feature_samples":0,"registered_feature_identities":0,
                "origin_owned_excursions":0,"pending_samples_awaiting_genuine_pl":0,"labels_created":0,
                "transport_coverage": feature_origin_transport_coverage_health(session_date)})
    if not _DB_READY: return out
    try:
        with _conn() as c:
            out["persisted_feature_samples"] = int(c.execute("SELECT COUNT(*) n FROM flow_features WHERE session_date=?",(session_date,)).fetchone()["n"])
            out["registered_feature_identities"] = int(c.execute("SELECT COUNT(*) n FROM flow_sample_identity_map WHERE session_date=?",(session_date,)).fetchone()["n"])
            out["origin_owned_excursions"] = int(c.execute(
                "SELECT COUNT(DISTINCT origin_sample_id) n FROM flow_feature_origin_pl_audit "
                "WHERE observation_session_date=? AND owner_validated=1 AND "
                "(excursion_written=1 OR excursion_updated=1)",(session_date,)).fetchone()["n"])
            out["pending_samples_awaiting_genuine_pl"] = int(c.execute("SELECT COUNT(*) n FROM flow_sample_pl_lifecycle WHERE session_date=? AND state IN ('REGISTERED_AWAITING_REAL_PL','AWAITING_REAL_PL')",(session_date,)).fetchone()["n"])
            out["labels_created"] = int(c.execute("SELECT COUNT(*) n FROM flow_labels WHERE session_date=?",(session_date,)).fetchone()["n"])
    except Exception as exc: out["error"]=f"{type(exc).__name__}: {exc}"
    return out


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


def record_feature_pl_handoff_observation(*, session_date: str, legacy_cluster_key: str,
                                                  decision_time: str,
                                                  exact_owner_sample_id: Optional[str]) -> bool:
    """Persist one exact feature-to-P/L ownership resolution attempt.

    APEX 69.10.23 observability only.  ``exact_owner_sample_id`` must come from the
    existing exact tuple resolver.  This function performs no lookup, matching,
    reconstruction, or evidence write of its own.
    """
    if not _DB_READY or not all((session_date, legacy_cluster_key, decision_time)):
        return False
    try:
        with _LOCK, _conn() as c:
            c.execute(
                """INSERT INTO flow_feature_pl_handoff_audit
                   (observed_at,session_date,legacy_cluster_key,decision_time,
                    exact_owner_sample_id,exact_owner_found)
                   VALUES (?,?,?,?,?,?)""",
                (_now_iso(), session_date, legacy_cluster_key, decision_time,
                 exact_owner_sample_id, 1 if exact_owner_sample_id else 0),
            )
            c.commit()
        return True
    except Exception:
        return False


def feature_pl_handoff_health() -> Dict[str, Any]:
    """Summarize exact feature-owner resolution at genuine P/L observation time."""
    out = {
        "version": "69.10.23",
        "identity_basis": "EXACT_PERSISTED_FEATURE_IDENTITY_TUPLE",
        "pl_handoff_observations": 0,
        "exact_feature_owner_found": 0,
        "exact_feature_owner_missing": 0,
        "exact_owner_resolution_pct": 0.0,
        "writes_evidence": False,
        "reconstructs_identity": False,
        "fuzzy_matching": False,
        "historical_backfill": False,
        "changes_trade_decisions": False,
        "execution_authority": False,
        "by_direction": {},
        "latest": None,
    }
    if not _DB_READY:
        return out
    try:
        with _conn() as c:
            row = c.execute(
                """SELECT COUNT(*) n, COALESCE(SUM(exact_owner_found),0) found
                   FROM flow_feature_pl_handoff_audit""").fetchone()
            n, found = int(row["n"] or 0), int(row["found"] or 0)
            out["pl_handoff_observations"] = n
            out["exact_feature_owner_found"] = found
            out["exact_feature_owner_missing"] = n - found
            out["exact_owner_resolution_pct"] = round(found / n * 100.0, 2) if n else 0.0
            rows = c.execute(
                """SELECT legacy_cluster_key, exact_owner_found
                   FROM flow_feature_pl_handoff_audit""").fetchall()
            dirs = {}
            for r in rows:
                direction = str(r["legacy_cluster_key"] or "").rsplit("|", 1)[-1] or "UNKNOWN"
                d = dirs.setdefault(direction, {"observations": 0, "owner_found": 0, "owner_missing": 0})
                d["observations"] += 1
                if int(r["exact_owner_found"] or 0): d["owner_found"] += 1
                else: d["owner_missing"] += 1
            out["by_direction"] = dirs
            latest = c.execute(
                """SELECT observed_at,session_date,legacy_cluster_key,decision_time,
                          exact_owner_sample_id,exact_owner_found
                   FROM flow_feature_pl_handoff_audit ORDER BY id DESC LIMIT 1""").fetchone()
            if latest: out["latest"] = dict(latest)
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
    return out


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



def verify_sample_identity_owner(*, sample_id: str, session_date: str,
                                 legacy_cluster_key: str, decision_time: str) -> bool:
    """Verify that an excursion write is owned by the exact persisted feature identity.

    APEX 69.10.22 is fail-closed: canonical callers may not write an excursion merely
    because they possess a sample_id.  The immutable sample_id and its complete
    persisted identity tuple must already agree in ``flow_sample_identity_map``.
    This never reconstructs or substitutes identity.
    """
    if not _DB_READY or not all((sample_id, session_date, legacy_cluster_key, decision_time)):
        return False
    try:
        with _conn() as c:
            row = c.execute(
                """SELECT sample_id,session_date,legacy_cluster_key,decision_time
                   FROM flow_sample_identity_map WHERE sample_id=? LIMIT 1""",
                (sample_id,),
            ).fetchone()
        return bool(row and row["sample_id"] == sample_id
                    and row["session_date"] == session_date
                    and row["legacy_cluster_key"] == legacy_cluster_key
                    and row["decision_time"] == decision_time)
    except Exception:
        return False

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
                            legacy_cluster_key: Optional[str] = None,
                            require_registered_owner: bool = False) -> Optional[Dict[str, Any]]:
    """Persist MFE/MAE under the exact immutable feature ``sample_id``.

    APEX 69.3 keeps the immutable sample as the only label-selecting identity and
    records durable capture telemetry outside the database write lock.
    """
    if not _DB_READY or not sample_id or pl_dollars is None:
        return None
    if require_registered_owner and not verify_sample_identity_owner(
            sample_id=sample_id, session_date=session_date,
            legacy_cluster_key=legacy_cluster_key or "", decision_time=decision_time or ""):
        record_capture_audit(attempted=1, errors=1, sample_id=sample_id,
                             canonical_attempted=1, identity_registration_failure=1)
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



def audit_pending_sample_outcome_eligibility(sample_ids: List[str], *,
                                             session_date: Optional[str] = None,
                                             sample_limit: int = 10) -> Dict[str, Any]:
    """Classify unlabelled feature samples by exact outcome-evidence state.

    This is read-only evidence observability.  A pending feature is not assumed to
    be broken merely because it lacks an excursion: genuine P/L may never have
    been observable.  Conversely, any persisted lifecycle claiming P/L/excursion
    activity without an exact excursion row is surfaced as an integrity failure.
    """
    ids = sorted({str(x) for x in (sample_ids or []) if x})
    out: Dict[str, Any] = {
        "version": "69.10.22",
        "identity_basis": "CANONICAL_FEATURE_SAMPLE_ID",
        "pending_sample_ids": len(ids),
        "registered_identity": 0,
        "exact_excursion_present": 0,
        "awaiting_real_pl": 0,
        "pl_observed_without_excursion": 0,
        "excursion_state_without_excursion": 0,
        "no_lifecycle_record": 0,
        "feature_only_unregistered": 0,
        "ownership_integrity_failures": 0,
        "reconstructs_identity": False,
        "fuzzy_matching": False,
        "writes_evidence": False,
        "samples": [],
    }
    if not _DB_READY or not ids:
        out["state"] = "NO_PENDING_SAMPLES" if not ids else "STORE_NOT_READY"
        return out
    try:
        q = ",".join("?" for _ in ids)
        with _conn() as c:
            identity = {r["sample_id"]: dict(r) for r in c.execute(
                f"SELECT sample_id,session_date,legacy_cluster_key,decision_time FROM flow_sample_identity_map WHERE sample_id IN ({q})", ids)}
            lifecycle = {r["sample_id"]: dict(r) for r in c.execute(
                f"SELECT sample_id,state,reason,pl_observations,excursion_writes FROM flow_sample_pl_lifecycle WHERE sample_id IN ({q})", ids)}
            excursions = {r["sample_id"]: dict(r) for r in c.execute(
                f"SELECT sample_id,session_date,legacy_cluster_key,decision_time FROM flow_sample_excursions WHERE sample_id IN ({q})", ids)}
        out["registered_identity"] = len(identity)
        out["exact_excursion_present"] = len(excursions)
        for sid in ids:
            ir, lr, er = identity.get(sid), lifecycle.get(sid), excursions.get(sid)
            if ir is None:
                out["feature_only_unregistered"] += 1
                cls = "FEATURE_ONLY_UNREGISTERED"
            elif er is not None:
                mismatch = (ir.get("session_date") != er.get("session_date") or
                            ir.get("legacy_cluster_key") != er.get("legacy_cluster_key") or
                            ir.get("decision_time") != er.get("decision_time"))
                if mismatch:
                    out["ownership_integrity_failures"] += 1
                    cls = "EXCURSION_OWNER_TUPLE_MISMATCH"
                else:
                    cls = "EXACT_EXCURSION_PRESENT"
            elif lr is None:
                out["no_lifecycle_record"] += 1
                cls = "NO_LIFECYCLE_RECORD"
            elif int(lr.get("excursion_writes") or 0) > 0 or str(lr.get("state") or "").startswith("PL_OBSERVED_EXCURSION_"):
                out["excursion_state_without_excursion"] += 1
                out["ownership_integrity_failures"] += 1
                cls = "EXCURSION_STATE_WITHOUT_ROW"
            elif int(lr.get("pl_observations") or 0) > 0:
                out["pl_observed_without_excursion"] += 1
                out["ownership_integrity_failures"] += 1
                cls = "PL_OBSERVED_WITHOUT_EXCURSION"
            else:
                out["awaiting_real_pl"] += 1
                cls = "AWAITING_GENUINE_REAL_PL"
            if len(out["samples"]) < max(0, int(sample_limit)):
                out["samples"].append({
                    "sample_id": sid, "classification": cls,
                    "identity_present": ir is not None,
                    "lifecycle_state": (lr or {}).get("state"),
                    "lifecycle_reason": (lr or {}).get("reason"),
                    "pl_observations": int((lr or {}).get("pl_observations") or 0),
                    "excursion_writes": int((lr or {}).get("excursion_writes") or 0),
                })
        out["state"] = ("OWNERSHIP_INTEGRITY_FAILURE" if out["ownership_integrity_failures"]
                        else "PENDING_AWAITING_EVIDENCE")
        return out
    except Exception as exc:
        out["state"] = "ERROR"
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out

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



def settlement_identity_alignment_diagnostic(sample_ids: List[str], *, session_date: str,
                                             sample_limit: int = 10) -> Dict[str, Any]:
    """APEX 69.10.35 exact settlement-cohort identity diagnostic.

    Partitions the settlement/feature population and canonical excursion population
    into four mutually exclusive sets using *only* exact canonical feature sample
    IDs.  This function is read-only: it never reconstructs an identity, performs a
    nearest-time/market-attribute join, backfills evidence, or changes eligibility.
    """
    requested = sorted({str(x) for x in (sample_ids or []) if x})
    day = str(session_date or "")[:10]
    out: Dict[str, Any] = {
        "version": "69.10.35",
        "identity_basis": "CANONICAL_FEATURE_SAMPLE_ID",
        "session_date": day,
        "invariant": (
            "settlement.requested_sample_id == feature.feature_sample_id == "
            "lifecycle.sample_id == excursion.sample_id"
        ),
        "sets": {
            "REQUESTED_AND_EXCURSION": {"count": 0, "samples": []},
            "REQUESTED_NO_EXCURSION": {"count": 0, "samples": []},
            "EXCURSION_NOT_REQUESTED": {"count": 0, "samples": []},
            "FEATURE_ONLY_UNREGISTERED": {"count": 0, "samples": []},
        },
        "identity_fork_stages": {
            "NONE": 0,
            "FEATURE_TO_LIFECYCLE": 0,
            "LIFECYCLE_TO_EXCURSION": 0,
            "EXCURSION_TO_SETTLEMENT": 0,
        },
        "writes_evidence": False,
        "reconstructs_identity": False,
        "fuzzy_matching": False,
        "nearest_time_matching": False,
        "historical_backfill": False,
        "synthetic_excursion": False,
        "synthetic_pl": False,
        "cross_sample_borrowing": False,
    }
    if not _DB_READY:
        out["state"] = "FLOW_PL_STORE_NOT_READY"
        return out
    try:
        identities: Dict[str, Dict[str, Any]] = {}
        lifecycle: Dict[str, Dict[str, Any]] = {}
        excursions: Dict[str, Dict[str, Any]] = {}
        origin_counts: Dict[str, int] = {}
        with _conn() as c:
            for r in c.execute(
                "SELECT sample_id,session_date,legacy_cluster_key,decision_time,samples,first_seen,last_seen "
                "FROM flow_sample_excursions WHERE session_date=?", (day,)):
                excursions[str(r["sample_id"])] = dict(r)
            if requested:
                for i in range(0, len(requested), 400):
                    chunk = requested[i:i + 400]
                    q = ",".join("?" * len(chunk))
                    for r in c.execute(
                        f"SELECT sample_id,session_date,legacy_cluster_key,decision_time,registered_at "
                        f"FROM flow_sample_identity_map WHERE sample_id IN ({q})", chunk):
                        identities[str(r["sample_id"])] = dict(r)
                    for r in c.execute(
                        f"SELECT sample_id,session_date,legacy_cluster_key,decision_time,state,reason," 
                        f"pl_observations,excursion_writes,last_observed_at FROM flow_sample_pl_lifecycle "
                        f"WHERE sample_id IN ({q})", chunk):
                        lifecycle[str(r["sample_id"])] = dict(r)
                    for r in c.execute(
                        f"SELECT sample_id,COUNT(*) AS n FROM flow_feature_origin_bindings "
                        f"WHERE sample_id IN ({q}) GROUP BY sample_id", chunk):
                        origin_counts[str(r["sample_id"])] = int(r["n"] or 0)

        req, ex, reg = set(requested), set(excursions), set(identities)
        requested_and_excursion = req & ex
        feature_only_unregistered = req - reg
        requested_no_excursion = (req & reg) - ex
        excursion_not_requested = ex - req

        partitions = {
            "REQUESTED_AND_EXCURSION": requested_and_excursion,
            "REQUESTED_NO_EXCURSION": requested_no_excursion,
            "EXCURSION_NOT_REQUESTED": excursion_not_requested,
            "FEATURE_ONLY_UNREGISTERED": feature_only_unregistered,
        }
        for name, ids in partitions.items():
            out["sets"][name]["count"] = len(ids)

        # A feature that never registered forks before lifecycle ownership exists.
        out["identity_fork_stages"]["FEATURE_TO_LIFECYCLE"] = len(feature_only_unregistered)
        # Registered requested features without an exact excursion fork on the
        # lifecycle -> excursion handoff (or are legitimately awaiting genuine P/L).
        out["identity_fork_stages"]["LIFECYCLE_TO_EXCURSION"] = len(requested_no_excursion)
        # Excursion owners absent from the settlement request expose selector drift.
        out["identity_fork_stages"]["EXCURSION_TO_SETTLEMENT"] = len(excursion_not_requested)
        out["identity_fork_stages"]["NONE"] = len(requested_and_excursion)

        lim = max(0, int(sample_limit))
        def prov(sid: str, classification: str) -> Dict[str, Any]:
            ir, lr, er = identities.get(sid), lifecycle.get(sid), excursions.get(sid)
            return {
                "sample_id": sid,
                "classification": classification,
                "feature_origin": "SETTLEMENT_PENDING_FEATURE" if sid in req else None,
                "lifecycle_registered": bool(ir),
                "identity_session_date": ir.get("session_date") if ir else None,
                "identity_decision_time": ir.get("decision_time") if ir else None,
                "identity_legacy_cluster_key": ir.get("legacy_cluster_key") if ir else None,
                "lifecycle_state": lr.get("state") if lr else None,
                "lifecycle_reason": lr.get("reason") if lr else None,
                "pl_observations": int(lr.get("pl_observations") or 0) if lr else 0,
                "excursion_writes": int(lr.get("excursion_writes") or 0) if lr else 0,
                "origin_event_bindings": int(origin_counts.get(sid, 0)),
                "excursion_present": bool(er),
                "excursion_owner_sample_id": sid if er else None,
                "excursion_session_date": er.get("session_date") if er else None,
                "excursion_decision_time": er.get("decision_time") if er else None,
                "settlement_requested": sid in req,
                "settlement_requested_sample_id": sid if sid in req else None,
                "exact_identity_match": bool(sid in req and er),
            }
        for name, ids in partitions.items():
            out["sets"][name]["samples"] = [prov(sid, name) for sid in sorted(ids)[:lim]]

        out["settlement_requested_ids"] = len(req)
        out["excursion_session_ids"] = len(ex)
        out["exact_requested_excursion_overlap"] = len(requested_and_excursion)
        out["exact_requested_excursion_overlap_pct"] = (
            round(len(requested_and_excursion) / len(req) * 100.0, 4) if req else 0.0)
        out["partition_complete"] = (
            len(requested_and_excursion) + len(requested_no_excursion) +
            len(feature_only_unregistered) == len(req)
        )
        out["state"] = "EXACT_IDENTITY_ALIGNED" if req and req <= ex else (
            "NO_SETTLEMENT_REQUESTS" if not req else "EXACT_IDENTITY_DIVERGENCE")
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
                out["feature_pl_handoff"] = feature_pl_handoff_health()
                out["feature_origin_provenance"] = feature_origin_provenance_health()
                out["origin_transport_coverage"] = feature_origin_transport_coverage_health()
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
