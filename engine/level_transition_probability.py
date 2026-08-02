"""APEX 50.6.1 — Level Transition Probability Engine (LTPE).

Extension of the Historical Level Calibration Engine (HLCE).  HLCE learns how
individual institutional levels behave.  LTPE learns the *path between levels*:

    source level + resolved event -> next distinct institutional level

Examples:
    PDH ACCEPTED UP -> Expected Move High
    Call Wall REJECTED DOWN -> Developing POC

The engine is evidence-only.  It never invents a transition probability when
history is absent.  All observations are derived from HLCE's append-only level,
interaction, outcome, and price-sample tables and are stored in the same SQLite
database.  No network/provider calls are made here.
"""
from __future__ import annotations

import importlib
import json
import math
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from statistics import median
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

class _LazyHLCEProxy:
    """Resolve HLCE only when LTPE actually needs it.

    APEX 50.7.0.2: HLCE owns the collector and can import LTPE from startup
    and live-cycle hooks. Importing HLCE eagerly here creates a reverse module
    dependency and can expose a partially initialized LTPE module under
    threaded Gunicorn startup. This proxy keeps LTPE import-complete before
    resolving the shared HLCE store/helpers.
    """
    _module = None

    def _resolve(self):
        module = self._module
        if module is None:
            module = importlib.import_module(".historical_level_calibration", __package__)
            self._module = module
        return module

    def __getattr__(self, name):
        return getattr(self._resolve(), name)


hlce = _LazyHLCEProxy()

VERSION = "50.6.2.2_LEVEL_TRANSITION_PROBABILITY"
PATH_INTELLIGENCE_VERSION = "50.6.5_INSTITUTIONAL_LEVEL_PATH_INTELLIGENCE"
PATH_RESILIENCE_VERSION = "50.6.5.2_LTPE_EMBEDDED_PATH_RESILIENCE"
LEARNING_VERSION = "50.7.0_LEVEL_TRANSITION_LEARNING_ACTIVATION"
CIRCULAR_IMPORT_REPAIR_VERSION = "50.7.0.2_LTPE_CIRCULAR_IMPORT_REPAIR"
SCHEMA_VERSION = 1


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


TRANSITION_HORIZON_SECONDS = _env_int("APEX_LEVEL_TRANSITION_HORIZON_SECONDS", 1800)
MIN_TARGET_GAP_ABS = _env_float("APEX_LEVEL_TRANSITION_MIN_GAP_ABS", 3.0)
MIN_TARGET_GAP_PCT = _env_float("APEX_LEVEL_TRANSITION_MIN_GAP_PCT", 0.0003)
TARGET_CLUSTER_ABS = _env_float("APEX_LEVEL_TRANSITION_CLUSTER_ABS", 2.0)
FAILURE_FRACTION = _env_float("APEX_LEVEL_TRANSITION_FAILURE_FRACTION", 0.35)
MIN_STAT_SAMPLE = _env_int("APEX_LEVEL_TRANSITION_MIN_STAT_SAMPLE", 5)

# APEX 50.6.5 — Institutional Level Path Intelligence
ZONE_RADIUS_ABS = _env_float("APEX_LTPE_ZONE_RADIUS_ABS", 4.0)
ZONE_RADIUS_PCT = _env_float("APEX_LTPE_ZONE_RADIUS_PCT", 0.0005)
PRIMARY_PRIORITY = _env_int("APEX_LTPE_PRIMARY_PRIORITY", 82)
SECONDARY_PRIORITY = _env_int("APEX_LTPE_SECONDARY_PRIORITY", 70)
INTERMEDIATE_PRIORITY = _env_int("APEX_LTPE_INTERMEDIATE_PRIORITY", 60)
SECONDARY_PRUNE_NEAR_PRIMARY_ABS = _env_float("APEX_LTPE_SECONDARY_PRUNE_NEAR_PRIMARY_ABS", 10.0)
MAX_PATH_DISTANCE_ABS = _env_float("APEX_LTPE_MAX_PATH_DISTANCE_ABS", 150.0)
MAX_EXPECTED_MOVE_MULTIPLE = _env_float("APEX_LTPE_MAX_EXPECTED_MOVE_MULTIPLE", 2.0)

# Higher-priority institutional references win when several level labels occupy
# effectively the same price cluster. Distance always determines the cluster;
# this map only selects the representative label inside that cluster.
_LEVEL_PRIORITY = {
    "expected_move_high": 100,
    "expected_move_low": 100,
    "prev_day_high": 95,
    "prev_day_low": 95,
    "gamma_flip": 92,
    "zero_gamma": 91,
    "call_wall": 90,
    "put_wall": 90,
    "volatility_trigger": 88,
    "high_gamma_strike": 86,
    "low_gamma_strike": 86,
    "vah": 82,
    "val": 82,
    "composite_vah": 80,
    "composite_val": 80,
    "developing_poc": 78,
    "prev_poc": 77,
    "poc": 76,
    "composite_poc": 75,
    "overnight_high": 73,
    "overnight_low": 73,
    "or_high": 70,
    "or_low": 70,
    "initial_balance_high": 68,
    "initial_balance_low": 68,
    "liquidity_pool": 65,
    "swing_high": 62,
    "swing_low": 62,
    "hvn": 55,
    "lvn": 55,
    "equal_highs": 50,
    "equal_lows": 50,
    "fair_value_gap": 45,
}


_TRANSITION_SCHEMA = """
CREATE TABLE IF NOT EXISTS level_transition_observations (
    transition_id TEXT PRIMARY KEY,
    source_outcome_id TEXT NOT NULL UNIQUE,
    source_interaction_id TEXT NOT NULL,
    session_date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    source_level_id TEXT NOT NULL,
    source_level_type TEXT NOT NULL,
    source_level_price REAL NOT NULL,
    source_event TEXT NOT NULL,
    direction TEXT NOT NULL,
    target_level_id TEXT,
    target_level_type TEXT,
    target_level_price REAL,
    target_cluster_json TEXT,
    target_distance REAL,
    target_reached INTEGER NOT NULL DEFAULT 0,
    failure_before_target INTEGER NOT NULL DEFAULT 0,
    resolution TEXT NOT NULL,
    started_at TEXT NOT NULL,
    resolved_at TEXT,
    seconds_to_target REAL,
    seconds_to_resolution REAL,
    mfe REAL,
    mae REAL,
    failure_threshold REAL,
    gamma_regime TEXT,
    auction_regime TEXT,
    trend_regime TEXT,
    volatility_regime TEXT,
    session_bucket TEXT,
    expected_move_regime TEXT,
    approach_direction TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_lt_obs_source
    ON level_transition_observations(symbol, source_level_type, source_event, direction);
CREATE INDEX IF NOT EXISTS ix_lt_obs_target
    ON level_transition_observations(symbol, target_level_type, target_reached);
CREATE INDEX IF NOT EXISTS ix_lt_obs_session
    ON level_transition_observations(session_date, symbol);

CREATE TABLE IF NOT EXISTS level_transition_statistics (
    stat_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    source_level_type TEXT NOT NULL,
    source_event TEXT NOT NULL,
    direction TEXT NOT NULL,
    target_level_type TEXT NOT NULL,
    segment_key TEXT NOT NULL,
    segment_value TEXT NOT NULL,
    sample_count INTEGER NOT NULL,
    target_reached_count INTEGER NOT NULL,
    target_reach_pct REAL,
    failure_pct REAL,
    no_resolution_pct REAL,
    avg_seconds_to_target REAL,
    median_seconds_to_target REAL,
    avg_mfe REAL,
    avg_mae REAL,
    avg_target_distance REAL,
    ci_low REAL,
    ci_high REAL,
    stability_score REAL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_lt_stats
    ON level_transition_statistics(
        symbol, source_level_type, source_event, direction, target_level_type,
        segment_key, segment_value
    );
"""


def initialize_transition_store(path: Optional[str] = None) -> None:
    hlce.initialize_store(path)
    with hlce._connect(path) as conn:  # same persistent HLCE store by design
        conn.executescript(_TRANSITION_SCHEMA)
        conn.commit()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm(value: Any, default: str = "UNKNOWN") -> str:
    text = str(value if value is not None else "").strip().upper()
    return text or default


def _event_from_outcome(row: Mapping[str, Any]) -> Optional[str]:
    classification = _norm(row.get("classification"))
    if row.get("accepted"):
        return "ACCEPTED"
    if classification == "BREAK":
        return "BREAK"
    if classification in {"REACTION", "REVERSAL"}:
        return "REJECTED"
    if classification == "FAILED_BREAK":
        return "FAILED_BREAK"
    return None


def _direction(event: str, approach_direction: str) -> str:
    approach = _norm(approach_direction)
    # Acceptance continues through the level. Rejection/failed-break travels
    # back toward the side from which price approached.
    if event in {"ACCEPTED", "BREAK"}:
        return "UP" if approach == "FROM_BELOW" else "DOWN"
    return "DOWN" if approach == "FROM_BELOW" else "UP"


def _min_gap(source_price: float) -> float:
    return max(MIN_TARGET_GAP_ABS, abs(source_price) * MIN_TARGET_GAP_PCT)


def _cluster_band(price: float) -> float:
    return max(TARGET_CLUSTER_ABS, hlce._touch_band(price))


def _candidate_levels(conn: sqlite3.Connection, session_date: str, symbol: str,
                      source_level_id: str, source_price: float, direction: str) -> List[sqlite3.Row]:
    rows = conn.execute(
        """SELECT * FROM daily_levels
           WHERE session_date=? AND symbol=? AND level_id<>?
           ORDER BY price""",
        (session_date, symbol, source_level_id),
    ).fetchall()
    gap = _min_gap(source_price)
    if direction == "UP":
        return [r for r in rows if float(r["price"]) >= source_price + gap]
    return list(reversed([r for r in rows if float(r["price"]) <= source_price - gap]))


def _select_target(conn: sqlite3.Connection, session_date: str, symbol: str,
                   source_level_id: str, source_price: float, direction: str) -> Optional[Dict[str, Any]]:
    candidates = _candidate_levels(conn, session_date, symbol, source_level_id, source_price, direction)
    if not candidates:
        return None
    nearest = candidates[0]
    anchor = float(nearest["price"])
    band = _cluster_band(anchor)
    cluster = [r for r in candidates if abs(float(r["price"]) - anchor) <= band]
    representative = max(
        cluster,
        key=lambda r: (_LEVEL_PRIORITY.get(str(r["level_type"]), 20), -abs(float(r["price"]) - anchor)),
    )
    aliases = [
        {"level_id": r["level_id"], "level_type": r["level_type"], "price": float(r["price"])}
        for r in cluster
    ]
    return {
        "level_id": representative["level_id"],
        "level_type": representative["level_type"],
        "price": float(representative["price"]),
        "cluster": aliases,
    }


def _future_samples(conn: sqlite3.Connection, symbol: str, start_ts: float, end_ts: float) -> List[Tuple[float, float]]:
    rows = conn.execute(
        """SELECT ts_epoch, price FROM level_price_samples
           WHERE symbol=? AND ts_epoch>=? AND ts_epoch<=?
           ORDER BY ts_epoch""",
        (symbol, start_ts, end_ts),
    ).fetchall()
    return [(float(r["ts_epoch"]), float(r["price"])) for r in rows]


def _resolve_transition(source_price: float, target_price: float, direction: str,
                        samples: Sequence[Tuple[float, float]], start_ts: float) -> Dict[str, Any]:
    sign = 1.0 if direction == "UP" else -1.0
    target_distance = abs(target_price - source_price)
    source_band = hlce._touch_band(source_price)
    target_band = hlce._touch_band(target_price)
    failure_threshold = max(2.0 * source_band, target_distance * FAILURE_FRACTION)
    target_boundary = target_price - target_band if direction == "UP" else target_price + target_band

    max_favorable = 0.0
    max_adverse = 0.0
    target_ts: Optional[float] = None
    failure_ts: Optional[float] = None
    last_ts = start_ts
    for ts, price in samples:
        last_ts = ts
        excursion = (price - source_price) * sign
        max_favorable = max(max_favorable, excursion)
        max_adverse = max(max_adverse, -excursion)
        if target_ts is None:
            reached = price >= target_boundary if direction == "UP" else price <= target_boundary
            if reached:
                target_ts = ts
        if failure_ts is None and excursion <= -failure_threshold:
            failure_ts = ts

    if target_ts is not None and (failure_ts is None or target_ts <= failure_ts):
        resolution = "TARGET_REACHED"
        resolved_ts = target_ts
        reached = 1
        failed = 0
    elif failure_ts is not None:
        resolution = "FAILED_BEFORE_TARGET"
        resolved_ts = failure_ts
        reached = 0
        failed = 1
    else:
        resolution = "NO_RESOLUTION"
        resolved_ts = last_ts if samples else start_ts
        reached = 0
        failed = 0

    return {
        "target_reached": reached,
        "failure_before_target": failed,
        "resolution": resolution,
        "resolved_ts": resolved_ts,
        "seconds_to_target": round(target_ts - start_ts, 2) if reached and target_ts is not None else None,
        "seconds_to_resolution": round(max(0.0, resolved_ts - start_ts), 2),
        "mfe": round(max_favorable, 4),
        "mae": round(max_adverse, 4),
        "failure_threshold": round(failure_threshold, 4),
        "target_distance": round(target_distance, 4),
    }


def process_transition_outcomes(*, path: Optional[str] = None,
                                horizon_seconds: int = TRANSITION_HORIZON_SECONDS,
                                limit: int = 500) -> Dict[str, Any]:
    """Convert newly graded HLCE outcomes into level-to-level observations.

    One transition is recorded per resolved source interaction. Source outcomes
    with no meaningful event or no distinct next level are marked skipped and
    remain absent from the transition sample set; probabilities therefore only
    describe genuine path opportunities.
    """
    initialize_transition_store(path)
    counts = {"processed": 0, "recorded": 0, "skipped_event": 0,
              "no_target": 0, "no_prices": 0, "errors": 0}
    with hlce._connect(path) as conn:
        rows = conn.execute(
            """SELECT o.*, i.ts AS interaction_ts, i.approach_direction AS interaction_approach,
                      d.auction_regime AS source_auction_regime,
                      d.volatility_regime AS source_volatility_regime
               FROM level_outcomes o
               JOIN level_interactions i ON i.interaction_id=o.interaction_id
               LEFT JOIN daily_levels d ON d.level_id=o.level_id
               LEFT JOIN level_transition_observations t ON t.source_outcome_id=o.outcome_id
               WHERE t.source_outcome_id IS NULL
                 AND o.classification IN ('BREAK','REACTION','REVERSAL','FAILED_BREAK')
               ORDER BY o.graded_at
               LIMIT ?""",
            (limit,),
        ).fetchall()
        for raw in rows:
            counts["processed"] += 1
            row = dict(raw)
            try:
                event = _event_from_outcome(row)
                if event is None:
                    counts["skipped_event"] += 1
                    continue
                approach = row.get("interaction_approach") or row.get("approach_direction") or "UNKNOWN"
                direction = _direction(event, approach)
                source_price = float(row["level_price"] if "level_price" in row and row.get("level_price") is not None
                                     else conn.execute("SELECT price FROM daily_levels WHERE level_id=?", (row["level_id"],)).fetchone()[0])
                target = _select_target(conn, row["session_date"], row["symbol"], row["level_id"],
                                        source_price, direction)
                if target is None:
                    counts["no_target"] += 1
                    continue
                start_ts = hlce._parse_ts(row.get("interaction_ts"))
                if start_ts is None:
                    counts["errors"] += 1
                    continue
                samples = _future_samples(conn, row["symbol"], start_ts, start_ts + horizon_seconds)
                if not samples:
                    counts["no_prices"] += 1
                    continue
                resolved = _resolve_transition(source_price, target["price"], direction, samples, start_ts)
                resolved_at = datetime.fromtimestamp(resolved["resolved_ts"], timezone.utc).isoformat()
                conn.execute(
                    """INSERT OR IGNORE INTO level_transition_observations
                       (transition_id, source_outcome_id, source_interaction_id, session_date, symbol,
                        source_level_id, source_level_type, source_level_price, source_event, direction,
                        target_level_id, target_level_type, target_level_price, target_cluster_json,
                        target_distance, target_reached, failure_before_target, resolution,
                        started_at, resolved_at, seconds_to_target, seconds_to_resolution,
                        mfe, mae, failure_threshold, gamma_regime, auction_regime, trend_regime,
                        volatility_regime, session_bucket, expected_move_regime, approach_direction, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (str(uuid.uuid4()), row["outcome_id"], row["interaction_id"], row["session_date"], row["symbol"],
                     row["level_id"], row["level_type"], source_price, event, direction,
                     target["level_id"], target["level_type"], target["price"], json.dumps(target["cluster"], separators=(",", ":")),
                     resolved["target_distance"], resolved["target_reached"], resolved["failure_before_target"],
                     resolved["resolution"], row["interaction_ts"], resolved_at,
                     resolved["seconds_to_target"], resolved["seconds_to_resolution"], resolved["mfe"], resolved["mae"],
                     resolved["failure_threshold"], row.get("gamma_regime"), row.get("source_auction_regime"),
                     row.get("trend_regime"), row.get("source_volatility_regime"), row.get("session_bucket"),
                     row.get("expected_move_regime"), approach, _utc_now()),
                )
                counts["recorded"] += 1
            except (sqlite3.DatabaseError, TypeError, ValueError, IndexError):
                counts["errors"] += 1
        conn.commit()
    return {"ok": True, "version": VERSION, "horizon_seconds": horizon_seconds, **counts}


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    """Return the columns currently present in a SQLite table.

    Render keeps the calibration DB across deploys, so an older table shape may
    survive a code upgrade.  Status/readiness code must therefore inspect the
    live schema instead of assuming CREATE TABLE IF NOT EXISTS migrated it.
    """
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return {str(row[1]) for row in rows}
    except sqlite3.DatabaseError:
        return set()


def _safe_scalar(conn: sqlite3.Connection, sql: str, params: Sequence[Any] = (), *,
                 default: Any = 0, diagnostics: Optional[List[Dict[str, Any]]] = None,
                 stage: str = "QUERY") -> Any:
    try:
        row = conn.execute(sql, tuple(params)).fetchone()
        return default if row is None or row[0] is None else row[0]
    except sqlite3.DatabaseError as exc:
        if diagnostics is not None:
            diagnostics.append({
                "stage": stage,
                "error_type": type(exc).__name__,
                "error": str(exc),
            })
        return default


def learning_status(*, path: Optional[str] = None, now: Optional[float] = None) -> Dict[str, Any]:
    """Operational truth for the live LTPE learning pipeline.

    This endpoint is deliberately fail-safe.  A persistent Render database can
    pre-date the current schema; status reporting must never turn a recoverable
    schema/store issue into Flask's HTML 500 response.  Missing counters are
    reported as unavailable and the response is marked DEGRADED.
    """
    diagnostics: List[Dict[str, Any]] = []
    init_ok = True
    try:
        initialize_transition_store(path)
    except (sqlite3.DatabaseError, OSError, ValueError, TypeError) as exc:
        init_ok = False
        diagnostics.append({
            "stage": "STORE_INITIALIZATION",
            "error_type": type(exc).__name__,
            "error": str(exc),
        })

    try:
        now_value = float(now if now is not None else datetime.now(timezone.utc).timestamp())
    except (TypeError, ValueError):
        now_value = datetime.now(timezone.utc).timestamp()
        diagnostics.append({
            "stage": "CLOCK_NORMALIZATION",
            "error_type": "INVALID_NOW",
            "error": "Invalid now value; current UTC timestamp used.",
        })

    ungraded = matured = eligible = observations = stats = 0
    last_obs = last_outcome = None
    schema: Dict[str, Any] = {}
    try:
        with hlce._connect(path) as conn:
            interactions_cols = _table_columns(conn, "level_interactions")
            outcomes_cols = _table_columns(conn, "level_outcomes")
            obs_cols = _table_columns(conn, "level_transition_observations")
            stats_cols = _table_columns(conn, "level_transition_statistics")
            schema = {
                "level_interactions": sorted(interactions_cols),
                "level_outcomes": sorted(outcomes_cols),
                "level_transition_observations": sorted(obs_cols),
                "level_transition_statistics": sorted(stats_cols),
            }

            if {"graded", "interaction_type", "ts"}.issubset(interactions_cols):
                ungraded = int(_safe_scalar(
                    conn,
                    "SELECT COUNT(*) FROM level_interactions WHERE graded=0 AND interaction_type IN ('FIRST_TOUCH','RETEST')",
                    diagnostics=diagnostics, stage="COUNT_UNGRADED_INTERACTIONS"))
                try:
                    rows = conn.execute(
                        "SELECT ts FROM level_interactions WHERE graded=0 AND interaction_type IN ('FIRST_TOUCH','RETEST')"
                    ).fetchall()
                    for row in rows:
                        ts = hlce._parse_ts(row[0])
                        if ts is not None and now_value - ts >= hlce.GRADING_HORIZON_SECONDS:
                            matured += 1
                except sqlite3.DatabaseError as exc:
                    diagnostics.append({"stage": "COUNT_MATURED_INTERACTIONS", "error_type": type(exc).__name__, "error": str(exc)})
            else:
                diagnostics.append({
                    "stage": "INTERACTION_SCHEMA",
                    "error_type": "SCHEMA_MISMATCH",
                    "error": "level_interactions is missing one or more required columns: graded, interaction_type, ts",
                })

            if {"outcome_id", "classification"}.issubset(outcomes_cols) and "source_outcome_id" in obs_cols:
                eligible = int(_safe_scalar(
                    conn,
                    """SELECT COUNT(*)
                       FROM level_outcomes o
                       LEFT JOIN level_transition_observations t ON t.source_outcome_id=o.outcome_id
                       WHERE t.source_outcome_id IS NULL
                         AND o.classification IN ('BREAK','REACTION','REVERSAL','FAILED_BREAK')""",
                    diagnostics=diagnostics, stage="COUNT_ELIGIBLE_OUTCOMES"))
            else:
                diagnostics.append({
                    "stage": "OUTCOME_TRANSITION_SCHEMA",
                    "error_type": "SCHEMA_MISMATCH",
                    "error": "Outcome/transition tables are missing columns required for eligibility accounting.",
                })

            if obs_cols:
                observations = int(_safe_scalar(conn, "SELECT COUNT(*) FROM level_transition_observations",
                                                diagnostics=diagnostics, stage="COUNT_OBSERVATIONS"))
                if "created_at" in obs_cols:
                    last_obs = _safe_scalar(conn, "SELECT MAX(created_at) FROM level_transition_observations",
                                            default=None, diagnostics=diagnostics, stage="LAST_OBSERVATION")
            else:
                diagnostics.append({"stage": "TRANSITION_OBSERVATION_SCHEMA", "error_type": "TABLE_UNAVAILABLE",
                                    "error": "level_transition_observations is unavailable."})

            if stats_cols:
                stats = int(_safe_scalar(conn, "SELECT COUNT(*) FROM level_transition_statistics",
                                         diagnostics=diagnostics, stage="COUNT_STATISTICS"))
            else:
                diagnostics.append({"stage": "TRANSITION_STATISTICS_SCHEMA", "error_type": "TABLE_UNAVAILABLE",
                                    "error": "level_transition_statistics is unavailable."})

            if "graded_at" in outcomes_cols:
                last_outcome = _safe_scalar(conn, "SELECT MAX(graded_at) FROM level_outcomes",
                                            default=None, diagnostics=diagnostics, stage="LAST_OUTCOME")
            elif outcomes_cols:
                diagnostics.append({"stage": "OUTCOME_SCHEMA", "error_type": "SCHEMA_MISMATCH",
                                    "error": "level_outcomes.graded_at is unavailable."})
    except (sqlite3.DatabaseError, OSError, ValueError, TypeError) as exc:
        diagnostics.append({
            "stage": "STORE_READ",
            "error_type": type(exc).__name__,
            "error": str(exc),
        })

    if matured:
        state = "READY_TO_GRADE"
    elif eligible:
        state = "READY_TO_RECORD"
    elif ungraded:
        state = "WAITING_FOR_MATURITY"
    else:
        state = "COLLECTING"

    degraded = bool(diagnostics) or not init_ok
    return {
        "ok": not degraded,
        "status": "DEGRADED" if degraded else "HEALTHY",
        "version": LEARNING_VERSION,
        "state": state,
        "collector_enabled": bool(hlce.collector_enabled()),
        "grading_horizon_seconds": int(hlce.GRADING_HORIZON_SECONDS),
        "transition_horizon_seconds": int(TRANSITION_HORIZON_SECONDS),
        "ungraded_interactions": int(ungraded),
        "matured_interactions": int(matured),
        "eligible_unrecorded_outcomes": int(eligible),
        "observations": int(observations),
        "statistics_rows": int(stats),
        "last_outcome_at": last_outcome,
        "last_observation_at": last_obs,
        "probability_policy": "EVIDENCE_ONLY_NO_FABRICATION",
        "failure_stage": diagnostics[0]["stage"] if diagnostics else None,
        "diagnostics": diagnostics,
        "schema_tables_seen": {k: bool(v) for k, v in schema.items()},
    }


def run_learning_cycle(*, path: Optional[str] = None, limit: int = 500) -> Dict[str, Any]:
    """Process all newly matured HLCE outcomes into LTPE evidence.

    Idempotency is guaranteed by the UNIQUE source_outcome_id constraint.
    Statistics rebuild only when at least one new observation is recorded.
    """
    before = learning_status(path=path)
    processed = process_transition_outcomes(path=path, limit=limit)
    statistics = {"skipped": True, "reason": "NO_NEW_OBSERVATIONS"}
    if int(processed.get("recorded") or 0) > 0:
        statistics = rebuild_transition_statistics(path=path)
    after = learning_status(path=path)
    return {
        "ok": True, "version": LEARNING_VERSION,
        "before": before, "processed": processed,
        "statistics": statistics, "after": after,
    }


_SEGMENTS = (
    ("gamma_regime", "gamma_regime"),
    ("auction_regime", "auction_regime"),
    ("trend_regime", "trend_regime"),
    ("volatility_regime", "volatility_regime"),
    ("session_bucket", "session_bucket"),
    ("expected_move_regime", "expected_move_regime"),
)


def _wilson(successes: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    if n <= 0:
        return (0.0, 1.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denom
    return max(0.0, centre - margin), min(1.0, centre + margin)


def _aggregate(rows: Sequence[sqlite3.Row]) -> Dict[str, Any]:
    n = len(rows)
    if n == 0:
        return {"sample_count": 0}
    successes = sum(1 for r in rows if r["target_reached"])
    failures = sum(1 for r in rows if r["failure_before_target"])
    unresolved = sum(1 for r in rows if r["resolution"] == "NO_RESOLUTION")
    times = [float(r["seconds_to_target"]) for r in rows if r["seconds_to_target"] is not None]
    mfes = [float(r["mfe"]) for r in rows if r["mfe"] is not None]
    maes = [float(r["mae"]) for r in rows if r["mae"] is not None]
    dists = [float(r["target_distance"]) for r in rows if r["target_distance"] is not None]
    lo, hi = _wilson(successes, n)
    width = max(1e-6, hi - lo)
    stability = min(1.0, n / 100.0) * (1.0 - min(1.0, width))
    return {
        "sample_count": n,
        "target_reached_count": successes,
        "target_reach_pct": round(100.0 * successes / n, 2),
        "failure_pct": round(100.0 * failures / n, 2),
        "no_resolution_pct": round(100.0 * unresolved / n, 2),
        "avg_seconds_to_target": round(sum(times) / len(times), 2) if times else None,
        "median_seconds_to_target": round(median(times), 2) if times else None,
        "avg_mfe": round(sum(mfes) / len(mfes), 4) if mfes else None,
        "avg_mae": round(sum(maes) / len(maes), 4) if maes else None,
        "avg_target_distance": round(sum(dists) / len(dists), 4) if dists else None,
        "ci_low": round(100.0 * lo, 2),
        "ci_high": round(100.0 * hi, 2),
        "stability_score": round(stability, 3),
    }


def _upsert_stat(conn: sqlite3.Connection, key: Tuple[str, str, str, str, str],
                 segment_key: str, segment_value: str, agg: Mapping[str, Any]) -> None:
    symbol, source_type, event, direction, target_type = key
    conn.execute(
        """INSERT INTO level_transition_statistics
           (stat_id, symbol, source_level_type, source_event, direction, target_level_type,
            segment_key, segment_value, sample_count, target_reached_count, target_reach_pct,
            failure_pct, no_resolution_pct, avg_seconds_to_target, median_seconds_to_target,
            avg_mfe, avg_mae, avg_target_distance, ci_low, ci_high, stability_score, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(symbol, source_level_type, source_event, direction, target_level_type,
                       segment_key, segment_value)
           DO UPDATE SET sample_count=excluded.sample_count,
                         target_reached_count=excluded.target_reached_count,
                         target_reach_pct=excluded.target_reach_pct,
                         failure_pct=excluded.failure_pct,
                         no_resolution_pct=excluded.no_resolution_pct,
                         avg_seconds_to_target=excluded.avg_seconds_to_target,
                         median_seconds_to_target=excluded.median_seconds_to_target,
                         avg_mfe=excluded.avg_mfe,
                         avg_mae=excluded.avg_mae,
                         avg_target_distance=excluded.avg_target_distance,
                         ci_low=excluded.ci_low, ci_high=excluded.ci_high,
                         stability_score=excluded.stability_score, updated_at=excluded.updated_at""",
        (str(uuid.uuid4()), symbol, source_type, event, direction, target_type,
         segment_key, segment_value, agg["sample_count"], agg["target_reached_count"],
         agg["target_reach_pct"], agg["failure_pct"], agg["no_resolution_pct"],
         agg["avg_seconds_to_target"], agg["median_seconds_to_target"], agg["avg_mfe"],
         agg["avg_mae"], agg["avg_target_distance"], agg["ci_low"], agg["ci_high"],
         agg["stability_score"], _utc_now()),
    )


def rebuild_transition_statistics(*, path: Optional[str] = None) -> Dict[str, Any]:
    initialize_transition_store(path)
    written = 0
    with hlce._connect(path) as conn:
        keys = conn.execute(
            """SELECT DISTINCT symbol, source_level_type, source_event, direction, target_level_type
               FROM level_transition_observations
               WHERE target_level_type IS NOT NULL AND resolution<>'NO_PRICE_DATA'"""
        ).fetchall()
        for k in keys:
            key = (k["symbol"], k["source_level_type"], k["source_event"], k["direction"], k["target_level_type"])
            rows = conn.execute(
                """SELECT * FROM level_transition_observations
                   WHERE symbol=? AND source_level_type=? AND source_event=? AND direction=? AND target_level_type=?
                     AND resolution<>'NO_PRICE_DATA'""",
                key,
            ).fetchall()
            _upsert_stat(conn, key, "ALL", "ALL", _aggregate(rows))
            written += 1
            for seg_key, col in _SEGMENTS:
                groups: Dict[str, List[sqlite3.Row]] = {}
                for row in rows:
                    val = _norm(row[col])
                    if val != "UNKNOWN":
                        groups.setdefault(val, []).append(row)
                for val, group in groups.items():
                    _upsert_stat(conn, key, seg_key, val, _aggregate(group))
                    written += 1
        conn.commit()
    return {"ok": True, "version": VERSION, "statistics_written": written}


def transition_statistics(*, symbol: Optional[str] = None, source_level_type: Optional[str] = None,
                          source_event: Optional[str] = None, direction: Optional[str] = None,
                          target_level_type: Optional[str] = None, segment_key: str = "ALL",
                          segment_value: str = "ALL", path: Optional[str] = None) -> List[Dict[str, Any]]:
    initialize_transition_store(path)
    query = "SELECT * FROM level_transition_statistics WHERE segment_key=? AND segment_value=?"
    params: List[Any] = [segment_key, segment_value]
    for col, value in (("symbol", symbol), ("source_level_type", source_level_type),
                       ("source_event", source_event), ("direction", direction),
                       ("target_level_type", target_level_type)):
        if value:
            query += f" AND {col}=?"
            params.append(_norm(value) if col in {"symbol", "source_event", "direction"} else value)
    query += " ORDER BY sample_count DESC, target_reach_pct DESC"
    with hlce._connect(path) as conn:
        return [dict(r) for r in conn.execute(query, params).fetchall()]


def _best_stat(rows: Sequence[Mapping[str, Any]], context: Optional[Mapping[str, Any]] = None) -> Optional[Dict[str, Any]]:
    if not rows:
        return None
    context = context or {}
    # Start with global evidence, then prefer a matching contextual segment if
    # it has enough samples. Never synthesize a probability across segments.
    all_rows = [dict(r) for r in rows if r.get("segment_key") == "ALL"]
    best = max(all_rows or [dict(r) for r in rows], key=lambda r: int(r.get("sample_count") or 0))
    for seg_key, _ in _SEGMENTS:
        desired = _norm(context.get(seg_key))
        if desired == "UNKNOWN":
            continue
        matches = [dict(r) for r in rows if r.get("segment_key") == seg_key and _norm(r.get("segment_value")) == desired]
        if matches:
            candidate = max(matches, key=lambda r: int(r.get("sample_count") or 0))
            if int(candidate.get("sample_count") or 0) >= MIN_STAT_SAMPLE:
                best = candidate
                break
    return best


def next_level_probability(symbol: str, source_level_type: str, source_event: str, direction: str,
                           target_level_type: Optional[str] = None,
                           context: Optional[Mapping[str, Any]] = None,
                           *, path: Optional[str] = None) -> Dict[str, Any]:
    rows = transition_statistics(
        symbol=symbol, source_level_type=source_level_type, source_event=source_event,
        direction=direction, target_level_type=target_level_type, path=path,
    )
    best = _best_stat(rows, context=context)
    if best is None:
        return {
            "ok": True, "version": VERSION, "symbol": _norm(symbol),
            "source_level_type": source_level_type, "source_event": _norm(source_event),
            "direction": _norm(direction), "target_level_type": target_level_type,
            "probability": None, "sample_count": 0, "source": "INSUFFICIENT_HISTORY",
            "message": "No historical transition sample is available; probability was not fabricated.",
        }
    n = int(best.get("sample_count") or 0)
    return {
        "ok": True, "version": VERSION, "symbol": _norm(symbol),
        "source_level_type": source_level_type, "source_event": _norm(source_event),
        "direction": _norm(direction), "target_level_type": best.get("target_level_type"),
        "probability": (float(best["target_reach_pct"]) / 100.0) if best.get("target_reach_pct") is not None else None,
        "probability_pct": best.get("target_reach_pct"), "sample_count": n,
        "median_seconds_to_target": best.get("median_seconds_to_target"),
        "avg_mfe": best.get("avg_mfe"), "avg_mae": best.get("avg_mae"),
        "ci_low": best.get("ci_low"), "ci_high": best.get("ci_high"),
        "stability_score": best.get("stability_score"),
        "segment_key": best.get("segment_key"), "segment_value": best.get("segment_value"),
        "source": "HISTORICAL" if n >= MIN_STAT_SAMPLE else "EARLY_HISTORY",
    }


def _latest_persisted_spot(symbol: str, *, path: Optional[str] = None) -> Tuple[Optional[float], Optional[str]]:
    """Return the latest HLCE-persisted session spot without mutating state.

    Production databases may lag a schema migration.  A stale/missing HLCE
    table must not take down the LTPE path endpoint; callers can continue to the
    next canonical source.
    """
    try:
        initialize_transition_store(path)
        with hlce._connect(path) as conn:
            row = conn.execute(
                """SELECT session_date, spot_price
                   FROM daily_levels
                   WHERE symbol=? AND spot_price IS NOT NULL
                   ORDER BY session_date DESC, registered_at DESC
                   LIMIT 1""",
                (_norm(symbol),),
            ).fetchone()
    except Exception:
        return None, None
    if not row:
        return None, None
    try:
        return float(row["spot_price"]), row["session_date"]
    except (TypeError, ValueError, KeyError, IndexError):
        return None, row["session_date"] if "session_date" in row.keys() else None


def _latest_persisted_levels(symbol: str, *, path: Optional[str] = None) -> Tuple[List[Any], Optional[str]]:
    """Return latest HLCE level set as a read-only fallback universe.

    Fail-soft by design: persistence/schema defects are diagnostics, not an HTML
    500 from a read-only path request.
    """
    try:
        initialize_transition_store(path)
        with hlce._connect(path) as conn:
            row = conn.execute(
                "SELECT MAX(session_date) AS session_date FROM daily_levels WHERE symbol=?",
                (_norm(symbol),),
            ).fetchone()
            session_date = row["session_date"] if row else None
            if not session_date:
                return [], None
            rows = conn.execute(
                """SELECT level_type, price, source, confidence
                   FROM daily_levels
                   WHERE symbol=? AND session_date=?
                   ORDER BY price""",
                (_norm(symbol), session_date),
            ).fetchall()
    except Exception:
        return [], None
    out: List[Any] = []
    for row in rows:
        try:
            price = float(row["price"])
        except (TypeError, ValueError, KeyError, IndexError):
            continue
        if not math.isfinite(price) or price <= 0:
            continue
        out.append(hlce.ExtractedLevel(
            level_type=str(row["level_type"]), price=price,
            source=str(row["source"] or "hlce_persisted"), confidence=row["confidence"],
        ))
    return out, session_date




def _load_durable_canonical_context(symbol: str = "SPX") -> Optional[Dict[str, Any]]:
    try:
        from .canonical_session_context import latest
        row = latest(symbol)
        return row if isinstance(row, dict) else None
    except Exception:
        return None

def _durable_context_as_brief(row: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(row, Mapping):
        return None
    return {
        "source_session_date": row.get("source_session_date"),
        "target_session_date": row.get("target_session_date"),
        "session_date": row.get("source_session_date"),
        "generated_at": row.get("generated_at"),
        "session_context": {"state": "WEEKEND", "brief_mode": "NEXT_SESSION_PREP"},
        "structured": {"spot": row.get("reference_spot"), "levels": row.get("levels") or []},
        "spot": row.get("reference_spot"),
        "prev_close": row.get("prev_close"),
        "durable_context_source": row.get("source"),
    }

def _load_latest_morning_brief(symbol: str = "SPX") -> Optional[Dict[str, Any]]:
    """Read the latest persisted Morning Brief revision without provider/network I/O.

    The revision table is intentionally used instead of only the immutable first
    forecast snapshot because LTPE's path is a *current read model*.  This lets a
    corrected next-session level set (for example, after a deterministic hotfix)
    become visible immediately while leaving forecast-grade archives immutable.
    """
    try:
        from . import evening_recap
        evening_recap.init_db()
        with sqlite3.connect(evening_recap.DB_PATH, timeout=5) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """SELECT payload_json FROM apex49_morning_revisions
                   WHERE ticker=? ORDER BY id DESC LIMIT 1""",
                (_norm(symbol),),
            ).fetchone()
            if not row:
                row = conn.execute(
                    """SELECT payload_json FROM apex49_morning_snapshots
                       WHERE ticker=? ORDER BY generated_at DESC LIMIT 1""",
                    (_norm(symbol),),
                ).fetchone()
        if not row:
            return None
        payload = json.loads(row["payload_json"] or "{}")
        return payload if isinstance(payload, dict) else None
    except Exception:
        # Path construction must remain fail-soft and side-effect free.
        return None


_BRIEF_KIND_MAP = {
    "em_upper": "expected_move_high",
    "em_lower": "expected_move_low",
    "high_volume_node": "hvn",
    "low_volume_node": "lvn",
    "or5_high": "or_high",
    "or15_high": "or_high",
    "or5_low": "or_low",
    "or15_low": "or_low",
    "ib_high": "initial_balance_high",
    "ib_low": "initial_balance_low",
    "ib_extension": "initial_balance_extension",
    "sellside_liquidity": "liquidity_pool",
    "buyside_liquidity": "liquidity_pool",
}


def _brief_levels(brief: Optional[Mapping[str, Any]]) -> List[Any]:
    """Convert deterministic Morning Brief levels into canonical HLCE level types."""
    if not isinstance(brief, Mapping):
        return []
    structured = brief.get("structured") if isinstance(brief.get("structured"), Mapping) else {}
    raw_levels = structured.get("levels") if isinstance(structured.get("levels"), list) else []
    out: List[Any] = []
    seen: set[Tuple[str, float]] = set()
    for item in raw_levels:
        if not isinstance(item, Mapping):
            continue
        raw_price = item.get("price")
        if raw_price in (None, "", "[FEED REQUIRED]"):
            continue
        try:
            price = float(raw_price)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(price) or price <= 0:
            continue
        raw_kind = str(item.get("kind") or "").strip().lower()
        level_type = _BRIEF_KIND_MAP.get(raw_kind, raw_kind)
        if not level_type:
            continue
        # Future-session OR/IB rows are deliberately [FEED REQUIRED] after
        # APEX 65.6.4 and therefore never reach this point.  Keep the guard for
        # older archives as an additional contamination barrier.
        target_date = str(brief.get("target_session_date") or "")
        source_date = str(brief.get("source_session_date") or brief.get("session_date") or "")
        if target_date and source_date and target_date != source_date and level_type in {
            "or_high", "or_low", "initial_balance_high", "initial_balance_low",
            "initial_balance_extension",
        }:
            continue
        key = (level_type, round(price, 4))
        if key in seen:
            continue
        seen.add(key)
        out.append(hlce.ExtractedLevel(
            level_type=level_type,
            price=price,
            source=str(item.get("source") or "morning_brief"),
            confidence=item.get("confidence"),
        ))
    return out


def _brief_spot(brief: Optional[Mapping[str, Any]]) -> Optional[float]:
    if not isinstance(brief, Mapping):
        return None
    structured = brief.get("structured") if isinstance(brief.get("structured"), Mapping) else {}
    for value in (structured.get("spot"), brief.get("spot")):
        try:
            if value not in (None, "", "[FEED REQUIRED]"):
                x = float(value)
                if math.isfinite(x) and x > 0:
                    return x
        except (TypeError, ValueError):
            pass
    return None


def _snapshot_session_date(snapshot: Mapping[str, Any]) -> Optional[str]:
    raw = hlce._nested(
        snapshot,
        "session_context.source_session_date",
        "source_session_date",
        "session_date",
    )
    return str(raw) if raw else None


def _brief_session_dates(brief: Optional[Mapping[str, Any]]) -> Tuple[Optional[str], Optional[str]]:
    if not isinstance(brief, Mapping):
        return None, None
    source = brief.get("source_session_date") or brief.get("session_date")
    target = brief.get("target_session_date") or source
    return (str(source) if source else None, str(target) if target else None)


def _is_closed_or_next_session(snapshot: Mapping[str, Any], brief: Optional[Mapping[str, Any]]) -> bool:
    sc = brief.get("session_context") if isinstance(brief, Mapping) and isinstance(brief.get("session_context"), Mapping) else {}
    state = _norm(sc.get("state") or hlce._nested(snapshot, "session_context.state", "session", "market_session"))
    mode = _norm(sc.get("brief_mode") or hlce._nested(snapshot, "session_context.brief_mode", "brief_mode"))
    if state in {"CLOSED", "MARKET_CLOSED", "WEEKEND", "AFTER_HOURS", "PREMARKET", "PRE_MARKET"}:
        return True
    return mode in {"NEXT_SESSION_PREP", "AFTER_CLOSE", "PREMARKET"}


def _canonical_level_universe(snapshot: Mapping[str, Any], ctx: Any, *,
                              path: Optional[str] = None,
                              brief: Optional[Mapping[str, Any]] = None) -> Tuple[List[Any], str, Optional[str], Optional[str]]:
    """Resolve the path's read-only institutional level universe.

    Priority is session-aware rather than simply "first non-empty": live-session
    levels win while the market is active; next-session Morning Brief levels win
    while closed because those levels are explicitly prepared for the target
    session.  Persisted HLCE levels are a last-resort structural fallback.
    """
    live_levels = hlce.extract_levels(snapshot)
    brief_levels = _brief_levels(brief)
    source_date, target_date = _brief_session_dates(brief)
    if not _is_closed_or_next_session(snapshot, brief) and live_levels:
        return live_levels, "LIVE_SESSION_LEVELS", _snapshot_session_date(snapshot), _snapshot_session_date(snapshot)
    if brief_levels:
        return brief_levels, "NEXT_SESSION_DAILY_KEY_LEVELS", source_date, target_date
    if live_levels:
        return live_levels, "CANONICAL_SNAPSHOT_LEVELS", _snapshot_session_date(snapshot), _snapshot_session_date(snapshot)
    persisted, session_date = _latest_persisted_levels(ctx.symbol, path=path)
    if persisted:
        return persisted, "LAST_HLCE_SESSION_LEVELS", session_date, None
    return [], "UNAVAILABLE", None, None


def _resolve_path_spot(snapshot: Mapping[str, Any], ctx: Any, levels: Sequence[Any], *,
                       explicit_spot: Optional[float] = None,
                       path: Optional[str] = None,
                       brief: Optional[Mapping[str, Any]] = None) -> Tuple[Optional[float], str, Optional[str], List[Dict[str, Any]]]:
    """Resolve a display-only spot for path construction with provenance diagnostics."""
    attempts: List[Dict[str, Any]] = []
    if explicit_spot is not None:
        try:
            value = float(explicit_spot)
            if math.isfinite(value) and value > 0:
                attempts.append({"source": "explicit_spot", "status": "AVAILABLE"})
                return value, "EXPLICIT_SPOT", _snapshot_session_date(snapshot), attempts
        except (TypeError, ValueError):
            pass
        attempts.append({"source": "explicit_spot", "status": "INVALID"})

    if ctx.spot is not None:
        attempts.append({"source": "canonical_live_snapshot", "status": "AVAILABLE"})
        return float(ctx.spot), "LIVE_SPOT", _snapshot_session_date(snapshot), attempts
    attempts.append({"source": "canonical_live_snapshot", "status": "UNAVAILABLE"})

    brief_value = _brief_spot(brief)
    brief_source, _ = _brief_session_dates(brief)
    if brief_value is not None:
        attempts.append({"source": "morning_brief_structured", "status": "AVAILABLE"})
        return brief_value, "CANONICAL_NEXT_SESSION_SPOT", brief_source, attempts
    attempts.append({"source": "morning_brief_structured", "status": "UNAVAILABLE"})

    persisted, session_date = _latest_persisted_spot(ctx.symbol, path=path)
    if persisted is not None:
        attempts.append({"source": "hlce_persisted_spot", "status": "AVAILABLE"})
        return persisted, "LAST_SESSION_SPOT", session_date, attempts
    attempts.append({"source": "hlce_persisted_spot", "status": "UNAVAILABLE"})

    # Last-resort structural context: prior close from whichever canonical level
    # universe was resolved. This remains display-only and never enters learning.
    for lvl in levels:
        if getattr(lvl, "level_type", None) == "prev_close":
            try:
                value = float(lvl.price)
                attempts.append({"source": "canonical_prev_close", "status": "AVAILABLE"})
                return value, "LAST_SESSION_CLOSE", brief_source or _snapshot_session_date(snapshot), attempts
            except (TypeError, ValueError):
                break
    attempts.append({"source": "canonical_prev_close", "status": "UNAVAILABLE"})
    return None, "UNAVAILABLE", brief_source or _snapshot_session_date(snapshot), attempts


def _path_context(ctx: Any, brief: Optional[Mapping[str, Any]], spot: float) -> Dict[str, Any]:
    """Resolve conditional context without inventing an intraday bucket when closed."""
    gamma = ctx.gamma_regime
    auction = ctx.auction_regime
    trend = ctx.trend_regime
    volatility = ctx.volatility_regime
    expected_move = ctx.expected_move_regime
    session_bucket = ctx.session_bucket

    if isinstance(brief, Mapping):
        structured = brief.get("structured") if isinstance(brief.get("structured"), Mapping) else {}
        gamma = _norm(structured.get("gamma_regime"), gamma)
        sc = brief.get("session_context") if isinstance(brief.get("session_context"), Mapping) else {}
        mode = _norm(sc.get("brief_mode"))
        state = _norm(sc.get("state"))
        if mode == "NEXT_SESSION_PREP" or state == "WEEKEND":
            session_bucket = "NEXT_SESSION_PREP"
        elif state in {"CLOSED", "MARKET_CLOSED", "AFTER_HOURS"}:
            session_bucket = "MARKET_CLOSED"

        em = structured.get("expected_move") if isinstance(structured.get("expected_move"), Mapping) else {}
        try:
            lo, hi = float(em.get("lower")), float(em.get("upper"))
            expected_move = "INSIDE_EXPECTED_MOVE" if lo <= spot <= hi else "OUTSIDE_EXPECTED_MOVE"
        except (TypeError, ValueError):
            pass
    return {
        "gamma_regime": gamma,
        "auction_regime": auction,
        "trend_regime": trend,
        "volatility_regime": volatility,
        "session_bucket": session_bucket,
        "expected_move_regime": expected_move,
    }



def _zone_radius(price: float) -> float:
    return max(ZONE_RADIUS_ABS, abs(price) * ZONE_RADIUS_PCT)


def _tier_for(level_type: str) -> str:
    p = _LEVEL_PRIORITY.get(level_type, 20)
    if p >= PRIMARY_PRIORITY:
        return "PRIMARY"
    if p >= SECONDARY_PRIORITY:
        return "SECONDARY"
    if p >= INTERMEDIATE_PRIORITY:
        return "INTERMEDIATE"
    return "SUPPORTING"


def _max_path_distance(brief: Optional[Mapping[str, Any]]) -> float:
    if isinstance(brief, Mapping):
        st = brief.get("structured") if isinstance(brief.get("structured"), Mapping) else {}
        em = st.get("expected_move") if isinstance(st.get("expected_move"), Mapping) else {}
        try:
            one_sigma = abs(float(em.get("one_sigma")))
            if math.isfinite(one_sigma) and one_sigma > 0:
                return min(MAX_PATH_DISTANCE_ABS, max(25.0, one_sigma * MAX_EXPECTED_MOVE_MULTIPLE))
        except (TypeError, ValueError):
            pass
    return MAX_PATH_DISTANCE_ABS


def _build_level_zones(levels: Sequence[Any], spot: float, direction: str,
                       brief: Optional[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Cluster nearby references into decision zones and prune microstructure noise."""
    sign = 1.0 if direction == "UP" else -1.0
    max_dist = _max_path_distance(brief)
    candidates = []
    for lvl in levels:
        try:
            price = float(lvl.price)
        except (TypeError, ValueError, AttributeError):
            continue
        delta = (price - spot) * sign
        if not math.isfinite(price) or delta <= _min_gap(spot) or delta > max_dist:
            continue
        candidates.append(lvl)
    candidates.sort(key=lambda x: float(x.price), reverse=(direction == "DOWN"))

    zones: List[Dict[str, Any]] = []
    for lvl in candidates:
        price = float(lvl.price)
        lt = str(getattr(lvl, "level_type", "unknown"))
        member = {
            "level_type": lt, "price": price, "source": getattr(lvl, "source", None),
            "priority": _LEVEL_PRIORITY.get(lt, 20), "tier": _tier_for(lt),
        }
        if zones and abs(price - zones[-1]["anchor_price"]) <= max(_zone_radius(price), _zone_radius(zones[-1]["anchor_price"])):
            z = zones[-1]
            z["members"].append(member)
            z["low"] = min(z["low"], price)
            z["high"] = max(z["high"], price)
            if member["priority"] > z["representative_priority"]:
                z["representative_type"] = lt
                z["representative_price"] = price
                z["representative_source"] = member["source"]
                z["representative_priority"] = member["priority"]
                z["tier"] = member["tier"]
            z["anchor_price"] = sum(m["price"] for m in z["members"]) / len(z["members"])
        else:
            zones.append({
                "low": price, "high": price, "anchor_price": price,
                "representative_type": lt, "representative_price": price,
                "representative_source": member["source"],
                "representative_priority": member["priority"], "tier": member["tier"],
                "members": [member],
            })

    if not zones:
        return []

    # Supporting/secondary zones immediately in front of a primary destination
    # are evidence around that destination, not separate path steps. Intermediate
    # zones are preserved when they materially divide a wide primary-to-primary span.
    pruned: List[Dict[str, Any]] = []
    i = 0
    while i < len(zones):
        z = zones[i]
        if z["tier"] in {"SUPPORTING", "SECONDARY"}:
            next_primary = next((x for x in zones[i+1:] if x["tier"] == "PRIMARY"), None)
            if next_primary is not None:
                gap = abs(next_primary["representative_price"] - z["representative_price"])
                limit = 6.0 if z["tier"] == "SUPPORTING" else SECONDARY_PRUNE_NEAR_PRIMARY_ABS
                if gap <= limit:
                    next_primary.setdefault("supporting_zones", []).append(z)
                    i += 1
                    continue
            if z["tier"] == "SUPPORTING":
                i += 1
                continue
        pruned.append(z)
        i += 1

    # Promote at most one intermediate between consecutive primary zones when it
    # materially divides a wide auction path. This preserves useful staging (e.g.
    # 7502 between VAH and PDH) without restoring every micro-level.
    final: List[Dict[str, Any]] = []
    for z in pruned:
        if z["tier"] == "INTERMEDIATE":
            prev_primary = next((x for x in reversed(final) if x["tier"] == "PRIMARY"), None)
            next_primary = next((x for x in pruned[pruned.index(z)+1:] if x["tier"] == "PRIMARY"), None)
            if not prev_primary or not next_primary:
                continue
            span = abs(next_primary["representative_price"] - prev_primary["representative_price"])
            if span < 12.0:
                continue
        final.append(z)
    return final


def _zone_probability(symbol: str, source_zone: Mapping[str, Any], target_zone: Mapping[str, Any],
                      direction: str, context: Mapping[str, Any], *, path: Optional[str] = None) -> Dict[str, Any]:
    """Aggregate evidence across all member level types in two price zones."""
    initialize_transition_store(path)
    source_types = sorted({str(m.get("level_type")) for m in source_zone.get("members", []) if m.get("level_type")})
    target_types = sorted({str(m.get("level_type")) for m in target_zone.get("members", []) if m.get("level_type")})
    # Supporting sub-zones are part of the target's semantic zone.
    for sub in target_zone.get("supporting_zones", []) or []:
        target_types.extend(str(m.get("level_type")) for m in sub.get("members", []) if m.get("level_type"))
    target_types = sorted(set(target_types))
    if not source_types or not target_types:
        return {"ok": True, "version": VERSION, "path_intelligence_version": PATH_INTELLIGENCE_VERSION, "probability": None, "sample_count": 0, "source": "INSUFFICIENT_HISTORY"}
    if len(source_types) == 1 and len(target_types) == 1:
        # Preserve the historical single-level query contract and its failure
        # semantics while zone aggregation is used for multi-member zones.
        out = next_level_probability(symbol, source_types[0], "ACCEPTED", direction,
                                     target_level_type=target_types[0], context=context, path=path)
        out["path_intelligence_version"] = PATH_INTELLIGENCE_VERSION
        out["source_zone_types"] = source_types
        out["target_zone_types"] = target_types
        return out
    q1 = ",".join("?" for _ in source_types)
    q2 = ",".join("?" for _ in target_types)
    params = [_norm(symbol), "ACCEPTED", _norm(direction), *source_types, *target_types]
    with hlce._connect(path) as conn:
        rows = conn.execute(
            f"""SELECT * FROM level_transition_observations
                WHERE symbol=? AND source_event=? AND direction=?
                  AND source_level_type IN ({q1}) AND target_level_type IN ({q2})
                  AND resolution<>'NO_PRICE_DATA'""", params,
        ).fetchall()
    selected = list(rows)
    for seg_key, col in _SEGMENTS:
        desired = _norm(context.get(seg_key))
        if desired == "UNKNOWN":
            continue
        subset = [r for r in rows if _norm(r[col]) == desired]
        if len(subset) >= MIN_STAT_SAMPLE:
            selected = subset
            break
    agg = _aggregate(selected)
    n = int(agg.get("sample_count") or 0)
    return {
        "ok": True, "version": VERSION, "probability": (float(agg["target_reach_pct"])/100.0) if n else None,
        "probability_pct": agg.get("target_reach_pct"), "sample_count": n,
        "median_seconds_to_target": agg.get("median_seconds_to_target"), "avg_mfe": agg.get("avg_mfe"),
        "avg_mae": agg.get("avg_mae"), "ci_low": agg.get("ci_low"), "ci_high": agg.get("ci_high"),
        "source": "HISTORICAL_ZONE" if n >= MIN_STAT_SAMPLE else ("EARLY_ZONE_HISTORY" if n else "INSUFFICIENT_HISTORY"),
        "source_zone_types": source_types, "target_zone_types": target_types,
        "probability_policy": "EVIDENCE_ONLY_NO_FABRICATION",
    }

def _path_failure(error: str, *, stage: str, exc: Optional[BaseException] = None,
                  direction: Optional[str] = None, spot_mode: str = "UNAVAILABLE",
                  spot_session: Optional[str] = None, attempts: Optional[List[Dict[str, Any]]] = None,
                  universe_mode: str = "UNAVAILABLE", source_session: Optional[str] = None,
                  target_session: Optional[str] = None) -> Dict[str, Any]:
    """Structured fail-closed response for read-only LTPE path resolution."""
    payload: Dict[str, Any] = {
        "ok": False, "version": VERSION, "error": error, "failure_stage": stage,
        "steps": [], "direction": _norm(direction or "UP"),
        "spot_mode": spot_mode, "spot_session": spot_session,
        "spot_resolution_attempts": attempts or [],
        "level_universe_mode": universe_mode,
        "source_session_date": source_session, "target_session_date": target_session,
        "probability_policy": "EVIDENCE_ONLY_NO_FABRICATION",
    }
    if exc is not None:
        payload["exception_type"] = type(exc).__name__
    return payload


def current_transition_path(snapshot: Mapping[str, Any], *, path: Optional[str] = None,
                            direction: Optional[str] = None, max_steps: int = 6,
                            spot: Optional[float] = None) -> Dict[str, Any]:
    """Build an evidence-backed path through canonical institutional levels.

    50.6.2.1 makes every read-model dependency independently fail-soft.  No
    resolver/database/statistics defect may escape as Flask's HTML 500 page.
    """
    norm_direction = _norm(direction or "UP")
    if norm_direction not in {"UP", "DOWN"}:
        return _path_failure("INVALID_DIRECTION", stage="INPUT", direction=norm_direction)
    store_warning = None
    try:
        initialize_transition_store(path)
    except Exception as exc:
        # Structural path construction is read-only and must remain available even
        # when the transition-statistics store is temporarily unavailable.
        store_warning = {"stage": "STORE_INIT", "exception_type": type(exc).__name__}

    try:
        ctx = hlce.extract_context(snapshot)
    except Exception as exc:
        return _path_failure("CONTEXT_EXTRACTION_FAILED", stage="SNAPSHOT_CONTEXT", exc=exc, direction=norm_direction)

    # If the caller already passed a Morning Brief payload, use that exact
    # structured object before consulting archives.  This prevents the embedded
    # dashboard path from mixing sessions and removes archive timing races.
    structured_inline = snapshot.get("structured") if isinstance(snapshot.get("structured"), Mapping) else {}
    inline_brief = snapshot if isinstance(structured_inline.get("levels"), list) else None
    try:
        brief = inline_brief or _load_latest_morning_brief(ctx.symbol)
    except Exception:
        brief = inline_brief
    durable_context = _load_durable_canonical_context(ctx.symbol)
    durable_brief = _durable_context_as_brief(durable_context)
    canonical_brief = brief or durable_brief

    try:
        levels, universe_mode, source_session, target_session = _canonical_level_universe(
            snapshot, ctx, path=path, brief=canonical_brief,
        )
        if levels and brief is None and durable_brief is not None and universe_mode == "NEXT_SESSION_DAILY_KEY_LEVELS":
            universe_mode = "DURABLE_NEXT_SESSION_LEVELS"
    except Exception as exc:
        return _path_failure(
            "LEVEL_CONTEXT_RESOLUTION_FAILED", stage="LEVEL_UNIVERSE", exc=exc,
            direction=norm_direction,
        )

    try:
        resolved_spot, spot_mode, spot_session, spot_attempts = _resolve_path_spot(
            snapshot, ctx, levels, explicit_spot=spot, path=path, brief=canonical_brief,
        )
        if resolved_spot is not None and brief is None and durable_brief is not None and spot_mode == "CANONICAL_NEXT_SESSION_SPOT":
            spot_mode = "DURABLE_CANONICAL_SPOT"
            for attempt in spot_attempts:
                if attempt.get("source") == "morning_brief_structured" and attempt.get("status") == "AVAILABLE":
                    attempt["source"] = "durable_canonical_context"
    except Exception as exc:
        return _path_failure(
            "SPOT_CONTEXT_RESOLUTION_FAILED", stage="SPOT_RESOLUTION", exc=exc,
            direction=norm_direction, universe_mode=universe_mode,
            source_session=source_session, target_session=target_session,
        )
    if resolved_spot is None:
        return _path_failure(
            "NO_SPOT", stage="SPOT_RESOLUTION", direction=norm_direction,
            spot_mode=spot_mode, spot_session=spot_session, attempts=spot_attempts,
            universe_mode=universe_mode, source_session=source_session, target_session=target_session,
        )

    try:
        zones = _build_level_zones(levels, resolved_spot, norm_direction, canonical_brief)
        zones = zones[:max(1, int(max_steps or 6))]
        context = _path_context(ctx, canonical_brief, resolved_spot)
    except Exception as exc:
        return _path_failure(
            "PATH_ASSEMBLY_FAILED", stage="PATH_ASSEMBLY", exc=exc, direction=norm_direction,
            spot_mode=spot_mode, spot_session=spot_session, attempts=spot_attempts,
            universe_mode=universe_mode, source_session=source_session, target_session=target_session,
        )

    steps: List[Dict[str, Any]] = []
    evidence_warnings: List[Dict[str, Any]] = []
    if store_warning is not None:
        evidence_warnings.append(store_warning)
    prior_zone: Optional[Dict[str, Any]] = None
    prior_price = resolved_spot
    for i, zone in enumerate(zones):
        evidence = None
        if prior_zone is not None:
            try:
                evidence = _zone_probability(ctx.symbol, prior_zone, zone, norm_direction, context, path=path)
            except Exception as exc:
                evidence = {
                    "ok": False, "version": VERSION, "source": "STATISTICS_UNAVAILABLE",
                    "probability": None, "sample_count": 0, "exception_type": type(exc).__name__,
                    "message": "Zone transition statistics were unavailable; probability was not fabricated.",
                }
                evidence_warnings.append({"stage": "TRANSITION_STATISTICS", "exception_type": type(exc).__name__})
        price = float(zone["representative_price"])
        zone_members = zone.get("members", [])
        supporting = zone.get("supporting_zones", []) or []
        steps.append({
            "ordinal": i + 1, "level_type": zone["representative_type"], "price": price,
            "source": zone.get("representative_source"), "tier": zone.get("tier"),
            "zone_low": round(float(zone["low"]), 4), "zone_high": round(float(zone["high"]), 4),
            "zone_member_count": len(zone_members) + sum(len(x.get("members", [])) for x in supporting),
            "zone_members": zone_members, "supporting_zones": supporting,
            "distance_from_prior": round(abs(price - prior_price), 4),
            "conditional_on": None if prior_zone is None else {
                "source_zone_type": prior_zone["representative_type"], "source_event": "ACCEPTED", "direction": norm_direction,
            },
            "transition": evidence,
        })
        prior_zone, prior_price = zone, price

    return {
        "ok": True, "version": VERSION, "path_intelligence_version": PATH_INTELLIGENCE_VERSION, "path_resilience_version": PATH_RESILIENCE_VERSION, "symbol": ctx.symbol, "spot": resolved_spot,
        "spot_mode": spot_mode, "spot_session": spot_session,
        "spot_resolution_attempts": spot_attempts, "spot_is_observation_input": False,
        "direction": norm_direction, "context": context, "steps": steps,
        "path_mode": "INSTITUTIONAL_ZONES", "zone_count": len(steps),
        "raw_level_count": len(levels), "max_path_distance": _max_path_distance(canonical_brief),
        "level_universe_mode": universe_mode, "level_universe_count": len(levels),
        "source_session_date": source_session, "target_session_date": target_session,
        "probability_policy": "EVIDENCE_ONLY_NO_FABRICATION",
        "resolution_warnings": evidence_warnings,
    }


def transition_history(*, symbol: Optional[str] = None, source_level_type: Optional[str] = None,
                       limit: int = 200, path: Optional[str] = None) -> Dict[str, Any]:
    initialize_transition_store(path)
    query = "SELECT * FROM level_transition_observations"
    clauses: List[str] = []
    params: List[Any] = []
    if symbol:
        clauses.append("symbol=?")
        params.append(_norm(symbol))
    if source_level_type:
        clauses.append("source_level_type=?")
        params.append(source_level_type)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY started_at DESC LIMIT ?"
    params.append(max(1, min(int(limit), 1000)))
    with hlce._connect(path) as conn:
        rows = []
        for r in conn.execute(query, params).fetchall():
            item = dict(r)
            try:
                item["target_cluster"] = json.loads(item.pop("target_cluster_json") or "[]")
            except (ValueError, TypeError):
                item["target_cluster"] = []
            rows.append(item)
    return {"ok": True, "version": VERSION, "count": len(rows), "rows": rows}


def status(*, path: Optional[str] = None) -> Dict[str, Any]:
    initialize_transition_store(path)
    with hlce._connect(path) as conn:
        observations = conn.execute("SELECT COUNT(*) FROM level_transition_observations").fetchone()[0]
        successes = conn.execute("SELECT COUNT(*) FROM level_transition_observations WHERE target_reached=1").fetchone()[0]
        stats = conn.execute("SELECT COUNT(*) FROM level_transition_statistics").fetchone()[0]
        last = conn.execute("SELECT MAX(created_at) FROM level_transition_observations").fetchone()[0]
    return {
        "ok": True, "version": VERSION, "schema_version": SCHEMA_VERSION,
        "observations": observations, "target_reached": successes,
        "statistics_rows": stats, "last_observation_at": last,
        "minimum_stat_sample": MIN_STAT_SAMPLE,
        "probability_policy": "EVIDENCE_ONLY_NO_FABRICATION",
    }
