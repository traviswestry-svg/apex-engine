"""APEX 50.5.0 — Historical Level Calibration Engine (HLCE).

Production-grade, dormant-safe engine that continuously learns the statistical
behaviour of institutional price levels and replaces heuristic probabilities
with evidence-based probabilities *when, and only when, sufficient calibrated
history exists*. When history is unavailable the system falls back to the
existing APEX 50.2 heuristic level analytics — it is never blocking and never
fabricates a calibrated number.

Design rules (consistent with the rest of the engine package):
  * append-only, persistent SQLite on the Render disk (survives deploys)
  * single source of truth for market context is ``STATE["last_result"]`` — the
    same live snapshot every other engine consumes; we re-derive nothing
  * every calibrated probability carries provenance (blend weights + sample n)
  * fully operational with an empty database (heuristic-only fallback)

This module owns the whole HLCE spine (store + extractor + collector + grader +
statistics + adaptive blend + replay + health) so it stays consolidated rather
than drifting across a dozen files. Routes live in the thin companion module
``historical_level_calibration_routes.py``.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

VERSION = "50.5.0_HISTORICAL_LEVEL_CALIBRATION"
SCHEMA_VERSION = 1

# --------------------------------------------------------------------------- #
# Configuration (all env-tunable, all with safe defaults)
# --------------------------------------------------------------------------- #


def _truthy(value: Any) -> bool:
    return str(value if value is not None else "").strip().lower() in {"1", "true", "yes", "on"}


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


def collector_enabled() -> bool:
    # Enabled by default; the collector is read-only w.r.t. execution and safe.
    return _truthy(os.getenv("APEX_CALIBRATION_ENABLED", "true"))


def _db_path() -> str:
    return os.getenv("APEX_CALIBRATION_DB", "apex_calibration.db")


# Interaction detection thresholds. Bands are the larger of an absolute floor
# and a fraction of price, so they scale from SPY (~600) to SPX/NDX (~6000+).
def _touch_band(price: float) -> float:
    pct = _env_float("APEX_CAL_TOUCH_BAND_PCT", 0.0004)      # 0.04%
    floor = _env_float("APEX_CAL_TOUCH_BAND_ABS", 1.5)
    return max(floor, abs(price) * pct)


GRADING_HORIZON_SECONDS = _env_int("APEX_CAL_GRADING_HORIZON_SECONDS", 1800)  # 30m
STATS_REBUILD_MIN_INTERVAL = _env_int("APEX_CAL_STATS_INTERVAL_SECONDS", 120)
PRICE_SAMPLE_MIN_INTERVAL = _env_float("APEX_CAL_SAMPLE_INTERVAL_SECONDS", 5.0)
COLLECTOR_INTERVAL_SECONDS = _env_float("APEX_CAL_COLLECTOR_INTERVAL_SECONDS", 15.0)
SAMPLE_RETENTION_DAYS = _env_int("APEX_CAL_SAMPLE_RETENTION_DAYS", 3)

# Adaptive blend schedule (heuristic_weight by sample count). Spec section 7.
_BLEND_SCHEDULE: Sequence[Tuple[int, float]] = (
    (0, 0.90),      # <20 samples   -> 90% heuristic / 10% historical
    (20, 0.70),     # 20-49         -> 70 / 30
    (50, 0.40),     # 50-99         -> 40 / 60
    (100, 0.20),    # 100-499       -> 20 / 80
    (500, 0.00),    # 500+          -> 100% historical
)

# Canonical level kinds we register from the live snapshot -> maps to the
# LevelKind vocabulary already used by daily_key_levels.
LEVEL_TYPES = (
    "prev_day_high", "prev_day_low", "prev_close", "prev_open",
    "overnight_high", "overnight_low", "overnight_vwap",
    "or_high", "or_low", "initial_balance_high", "initial_balance_low",
    "expected_move_high", "expected_move_low",
    "gamma_flip", "zero_gamma", "call_wall", "put_wall",
    "high_gamma_strike", "low_gamma_strike", "volatility_trigger",
    "poc", "developing_poc", "prev_poc", "composite_poc",
    "vah", "val", "composite_vah", "composite_val",
    "hvn", "lvn", "equal_highs", "equal_lows",
    "liquidity_pool", "swing_high", "swing_low", "fair_value_gap",
)

# Level kinds that primarily act as magnets vs. rejection points — used to seed
# the MAGNET classification bias when price loiters at the level.
_MAGNET_KINDS = {"poc", "developing_poc", "composite_poc", "prev_poc", "hvn",
                 "call_wall", "put_wall", "gamma_flip", "zero_gamma"}


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_ts() -> float:
    return datetime.now(timezone.utc).timestamp()


def _parse_ts(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        f = float(value)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _norm(value: Any, default: str = "UNKNOWN") -> str:
    text = str(value if value is not None else "").strip().upper()
    return text or default


def _nested(source: Mapping[str, Any], *paths: str) -> Any:
    for path in paths:
        cur: Any = source
        ok = True
        for key in path.split("."):
            if isinstance(cur, Mapping) and key in cur:
                cur = cur[key]
            else:
                ok = False
                break
        if ok and cur not in (None, ""):
            return cur
    return None


def _wilson_interval(successes: int, n: int, z: float = 1.96) -> Tuple[float, float]:
    """Wilson score confidence interval for a proportion (stable at small n)."""
    if n <= 0:
        return (0.0, 1.0)
    phat = successes / n
    denom = 1.0 + z * z / n
    centre = (phat + z * z / (2 * n)) / denom
    margin = (z * math.sqrt((phat * (1 - phat) + z * z / (4 * n)) / n)) / denom
    return (max(0.0, centre - margin), min(1.0, centre + margin))


# --------------------------------------------------------------------------- #
# Store — persistent SQLite. Mirrors the market-memory connection pattern.
# --------------------------------------------------------------------------- #


def _connect(path: Optional[str] = None) -> sqlite3.Connection:
    resolved = path or _db_path()
    parent = Path(resolved).expanduser().resolve().parent
    parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(resolved, timeout=_env_float("APEX_SQLITE_TIMEOUT_SECONDS", 15))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    except sqlite3.DatabaseError:
        pass
    return conn


_SCHEMA = """
CREATE TABLE IF NOT EXISTS daily_levels (
    level_id TEXT PRIMARY KEY,
    session_date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    level_type TEXT NOT NULL,
    price REAL NOT NULL,
    source TEXT,
    confidence REAL,
    spot_price REAL,
    distance_from_spot REAL,
    gamma_regime TEXT,
    auction_regime TEXT,
    trend_regime TEXT,
    expected_move_regime TEXT,
    volatility_regime TEXT,
    registered_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_daily_levels_dedup
    ON daily_levels(session_date, symbol, level_type, price);
CREATE INDEX IF NOT EXISTS ix_daily_levels_session ON daily_levels(session_date, symbol);

CREATE TABLE IF NOT EXISTS level_interactions (
    interaction_id TEXT PRIMARY KEY,
    level_id TEXT NOT NULL,
    session_date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    level_type TEXT NOT NULL,
    interaction_type TEXT NOT NULL,
    touch_ordinal INTEGER,
    ts TEXT NOT NULL,
    touch_price REAL,
    level_price REAL,
    approach_direction TEXT,
    distance_traveled REAL,
    velocity REAL,
    volume REAL,
    relative_volume REAL,
    delta REAL,
    gamma_regime TEXT,
    trend_regime TEXT,
    session_bucket TEXT,
    expected_move_regime TEXT,
    graded INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_interactions_level ON level_interactions(level_id);
CREATE INDEX IF NOT EXISTS ix_interactions_ungraded ON level_interactions(graded, ts);
CREATE INDEX IF NOT EXISTS ix_interactions_session ON level_interactions(session_date, symbol);

CREATE TABLE IF NOT EXISTS level_outcomes (
    outcome_id TEXT PRIMARY KEY,
    interaction_id TEXT NOT NULL UNIQUE,
    level_id TEXT NOT NULL,
    session_date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    level_type TEXT NOT NULL,
    classification TEXT NOT NULL,
    reacted INTEGER,
    broke INTEGER,
    reversed INTEGER,
    accepted INTEGER,
    retested INTEGER,
    mfe REAL,
    mae REAL,
    failure_distance REAL,
    time_to_reaction REAL,
    time_to_break REAL,
    time_to_reclaim REAL,
    time_to_resolution REAL,
    end_of_session_result TEXT,
    gamma_regime TEXT,
    trend_regime TEXT,
    session_bucket TEXT,
    expected_move_regime TEXT,
    approach_direction TEXT,
    touch_ordinal INTEGER,
    graded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_outcomes_type ON level_outcomes(symbol, level_type);

CREATE TABLE IF NOT EXISTS calibration_statistics (
    stat_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    level_type TEXT NOT NULL,
    segment_key TEXT NOT NULL,
    segment_value TEXT NOT NULL,
    sample_count INTEGER NOT NULL,
    reaction_pct REAL,
    break_pct REAL,
    reversal_pct REAL,
    acceptance_pct REAL,
    retest_pct REAL,
    avg_excursion REAL,
    median_excursion REAL,
    avg_hold_time REAL,
    avg_failure_distance REAL,
    ci_low REAL,
    ci_high REAL,
    stability_score REAL,
    expectancy REAL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_stats_dedup
    ON calibration_statistics(symbol, level_type, segment_key, segment_value);

CREATE TABLE IF NOT EXISTS calibration_jobs (
    job_id TEXT PRIMARY KEY,
    job_type TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    detail_json TEXT
);
CREATE INDEX IF NOT EXISTS ix_jobs_type ON calibration_jobs(job_type, started_at);

-- Supporting table: session-scoped forward price track so outcome grading is
-- deployment-safe (survives a mid-session restart). Pruned after retention.
CREATE TABLE IF NOT EXISTS level_price_samples (
    sample_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    ts TEXT NOT NULL,
    ts_epoch REAL NOT NULL,
    price REAL NOT NULL,
    volume REAL,
    relative_volume REAL,
    delta REAL
);
CREATE INDEX IF NOT EXISTS ix_samples_lookup ON level_price_samples(symbol, ts_epoch);

-- Trade replay (spec section 11): full institutional context + calibration
-- snapshot + result for every trade, so we can answer "why did it work/fail".
CREATE TABLE IF NOT EXISTS trade_replays (
    replay_id TEXT PRIMARY KEY,
    trade_id TEXT,
    session_date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    institutional_levels_json TEXT,
    gamma_state TEXT,
    auction_state TEXT,
    volume_profile_json TEXT,
    liquidity_map_json TEXT,
    expected_move_json TEXT,
    overnight_inventory TEXT,
    trend TEXT,
    calibration_snapshot_json TEXT,
    trade_result_json TEXT
);
CREATE INDEX IF NOT EXISTS ix_replays_session ON trade_replays(session_date, symbol);
"""


def initialize_store(path: Optional[str] = None) -> None:
    with _connect(path) as conn:
        conn.executescript(_SCHEMA)
        conn.commit()


# --------------------------------------------------------------------------- #
# Extractor — live snapshot -> normalized institutional levels + context
# --------------------------------------------------------------------------- #


@dataclass
class ExtractedLevel:
    level_type: str
    price: float
    source: str = "computed"
    confidence: Optional[float] = None


@dataclass
class SnapshotContext:
    symbol: str
    spot: Optional[float]
    gamma_regime: str
    auction_regime: str
    trend_regime: str
    expected_move_regime: str
    volatility_regime: str
    session_bucket: str
    expected_move_high: Optional[float]
    expected_move_low: Optional[float]
    volume: Optional[float]
    relative_volume: Optional[float]
    delta: Optional[float]


def _classify_gamma(snapshot: Mapping[str, Any]) -> str:
    raw = _nested(snapshot, "gamma_regime.regime", "dealer_positioning.regime",
                  "dealer_positioning.gamma_regime", "gamma_semantics.regime")
    if raw is None:
        gm = snapshot.get("gamma_regime")
        if isinstance(gm, str):
            raw = gm
    text = _norm(raw)
    if "SHORT" in text:
        return "SHORT_GAMMA"
    if "LONG" in text:
        return "LONG_GAMMA"
    if "NEUTRAL" in text or "FLAT" in text:
        return "NEUTRAL_GAMMA"
    return "UNKNOWN"


def _classify_trend(snapshot: Mapping[str, Any]) -> str:
    prob = _safe_float(_nested(snapshot, "institutional_probability.trend_day_probability",
                               "trend_day_probability"))
    raw = _norm(_nested(snapshot, "institutional_market_structure.day_type",
                        "market_structure.day_type", "day_type", "regime", "market_regime"))
    if "TREND" in raw:
        return "TREND_DAY"
    if "BALANCE" in raw or "RANGE" in raw or "ROTATION" in raw:
        return "BALANCED_DAY"
    if prob is not None:
        return "TREND_DAY" if prob >= 55 else "BALANCED_DAY"
    return "UNKNOWN"


def _session_bucket(snapshot: Mapping[str, Any]) -> str:
    """Opening drive / lunch / power hour / regular — from ET clock when present."""
    raw = _norm(_nested(snapshot, "session", "market_session"))
    now = None
    ts = _nested(snapshot, "generated_at", "timestamp", "as_of")
    epoch = _parse_ts(ts)
    if epoch is not None:
        now = datetime.fromtimestamp(epoch, timezone.utc)
    if now is None:
        now = datetime.now(timezone.utc)
    # US market hours in ET; approximate ET as UTC-4/-5 -> use naive UTC hour mapping
    # via the snapshot minutes-from-open when available, else clock heuristic.
    minute = now.hour * 60 + now.minute
    # 13:30 UTC ~ 09:30 ET (EDT). Fall back to labels if snapshot carries them.
    open_utc = 13 * 60 + 30
    delta = minute - open_utc
    if raw in {"CLOSED", "MARKET_CLOSED", "AFTER_HOURS", "PREMARKET", "PRE_MARKET"}:
        return raw
    if 0 <= delta < 60:
        return "OPENING_DRIVE"
    if 120 <= delta < 210:
        return "LUNCH_SESSION"
    if 330 <= delta <= 390:
        return "POWER_HOUR"
    return "REGULAR_SESSION"


def extract_context(snapshot: Mapping[str, Any]) -> SnapshotContext:
    ms = snapshot.get("market_state") if isinstance(snapshot.get("market_state"), Mapping) else {}
    flow = snapshot.get("flow") if isinstance(snapshot.get("flow"), Mapping) else {}
    fi = snapshot.get("flow_intelligence_2") if isinstance(snapshot.get("flow_intelligence_2"), Mapping) else {}
    if not fi and isinstance(snapshot.get("flow_intelligence"), Mapping):
        fi = snapshot["flow_intelligence"]
    spot = _safe_float(_nested(ms, "price") or _nested(snapshot, "spot", "price")
                       or _nested(flow, "stock_price"))
    emh = _safe_float(_nested(snapshot, "expected_move_high", "institutional_probability.expected_move_high"))
    eml = _safe_float(_nested(snapshot, "expected_move_low", "institutional_probability.expected_move_low"))
    em_regime = "UNKNOWN"
    if spot is not None and emh is not None and eml is not None:
        em_regime = "INSIDE_EXPECTED_MOVE" if eml <= spot <= emh else "OUTSIDE_EXPECTED_MOVE"
    vix = _safe_float(_nested(snapshot, "vix", "market.vix"))
    vol_regime = "UNKNOWN"
    if vix is not None:
        vol_regime = "LOW_VOL" if vix < 15 else ("HIGH_VOL" if vix > 22 else "MID_VOL")
    return SnapshotContext(
        symbol=_norm(_nested(snapshot, "ticker", "symbol"), "SPX"),
        spot=spot,
        gamma_regime=_classify_gamma(snapshot),
        auction_regime=_norm(_nested(snapshot, "institutional_market_structure.auction_state",
                                     "auction_intelligence.auction_state", "auction_state")),
        trend_regime=_classify_trend(snapshot),
        expected_move_regime=em_regime,
        volatility_regime=vol_regime,
        session_bucket=_session_bucket(snapshot),
        expected_move_high=emh,
        expected_move_low=eml,
        volume=_safe_float(_nested(ms, "volume") or _nested(fi, "volume")),
        relative_volume=_safe_float(_nested(fi, "relative_volume") or _nested(ms, "relative_volume")),
        delta=_safe_float(_nested(fi, "cumulative_delta", "delta_score", "cumulative_delta_score")),
    )


def extract_levels(snapshot: Mapping[str, Any]) -> List[ExtractedLevel]:
    """Pull every institutional level present in the live snapshot.

    Reads from the same locations other engines populate, with layered
    fallbacks. Absent values are skipped — never fabricated.
    """
    ms = snapshot.get("market_state") if isinstance(snapshot.get("market_state"), Mapping) else {}
    gm = snapshot.get("gamma_regime") if isinstance(snapshot.get("gamma_regime"), Mapping) else {}
    st = snapshot.get("structure") if isinstance(snapshot.get("structure"), Mapping) else {}
    flow = snapshot.get("flow") if isinstance(snapshot.get("flow"), Mapping) else {}
    vp = snapshot.get("volume_profile") if isinstance(snapshot.get("volume_profile"), Mapping) else {}
    if not vp and isinstance(snapshot.get("profile"), Mapping):
        vp = snapshot["profile"]
    vp_levels = vp.get("levels") if isinstance(vp.get("levels"), Mapping) else vp
    au = snapshot.get("auction_intelligence") if isinstance(snapshot.get("auction_intelligence"), Mapping) else {}
    if not au and isinstance(snapshot.get("auction"), Mapping):
        au = snapshot["auction"]
    ov = snapshot.get("overnight") if isinstance(snapshot.get("overnight"), Mapping) else {}

    out: List[ExtractedLevel] = []
    seen: Dict[str, float] = {}

    def add(level_type: str, value: Any, source: str, conf: Optional[float] = None):
        price = _safe_float(value)
        if price is None or price <= 0:
            return
        # de-dup identical (type, price) within one snapshot
        key = f"{level_type}:{round(price, 4)}"
        if key in seen:
            return
        seen[key] = price
        out.append(ExtractedLevel(level_type=level_type, price=price, source=source, confidence=conf))

    # --- gamma / dealer structure ---
    add("call_wall", gm.get("call_wall") or ms.get("call_wall") or flow.get("call_wall"), "gamma_provider")
    add("put_wall", gm.get("put_wall") or ms.get("put_wall") or flow.get("put_wall"), "gamma_provider")
    add("gamma_flip", gm.get("gamma_flip") or flow.get("gamma_flip"), "gamma_provider")
    add("zero_gamma", gm.get("zero_gamma") or ms.get("zero_gamma") or flow.get("zero_gamma"), "gamma_provider")
    add("high_gamma_strike", gm.get("high_gamma_strike") or gm.get("hi_gamma"), "gamma_provider")
    add("low_gamma_strike", gm.get("low_gamma_strike") or gm.get("lo_gamma"), "gamma_provider")
    add("volatility_trigger", gm.get("volatility_trigger") or gm.get("vol_trigger"), "gamma_provider")

    # --- volume profile ---
    add("poc", vp_levels.get("poc") or vp.get("poc") or au.get("poc"), "volume_profile")
    add("developing_poc", vp_levels.get("developing_poc") or vp_levels.get("dev_poc"), "volume_profile")
    add("prev_poc", vp_levels.get("prev_poc") or vp_levels.get("previous_poc"), "volume_profile")
    add("composite_poc", vp_levels.get("composite_poc") or vp_levels.get("comp_poc"), "volume_profile")
    add("vah", vp_levels.get("vah") or vp.get("vah") or au.get("vah"), "volume_profile")
    add("val", vp_levels.get("val") or vp.get("val") or au.get("val"), "volume_profile")
    add("composite_vah", vp_levels.get("composite_vah") or vp_levels.get("comp_vah"), "volume_profile")
    add("composite_val", vp_levels.get("composite_val") or vp_levels.get("comp_val"), "volume_profile")

    def add_list(level_type: str, values: Any, source: str):
        if isinstance(values, (list, tuple)):
            for v in values:
                add(level_type, v.get("price") if isinstance(v, Mapping) else v, source)

    add_list("hvn", vp_levels.get("hvn") or ms.get("hvn"), "volume_profile")
    add_list("lvn", vp_levels.get("lvn") or ms.get("lvn"), "volume_profile")

    # --- previous session / overnight / opening range ---
    add("prev_day_high", st.get("pdh") or ms.get("pdh") or _nested(snapshot, "previous_session.high"), "computed")
    add("prev_day_low", st.get("pdl") or ms.get("pdl") or _nested(snapshot, "previous_session.low"), "computed")
    add("prev_close", _nested(snapshot, "previous_session.close") or st.get("prev_close") or ms.get("prev_close"), "computed")
    add("prev_open", _nested(snapshot, "previous_session.open") or st.get("prev_open"), "computed")
    add("overnight_high", st.get("onh") or ms.get("onh") or ov.get("high") or _nested(snapshot, "overnight.high"), "computed")
    add("overnight_low", st.get("onl") or ms.get("onl") or ov.get("low") or _nested(snapshot, "overnight.low"), "computed")
    add("overnight_vwap", ov.get("vwap") or _nested(snapshot, "overnight.vwap"), "computed")
    add("or_high", st.get("or_high") or ms.get("or_high") or _nested(snapshot, "opening_range.high"), "computed")
    add("or_low", st.get("or_low") or ms.get("or_low") or _nested(snapshot, "opening_range.low"), "computed")
    add("initial_balance_high", st.get("ib_high") or _nested(snapshot, "initial_balance.high"), "computed")
    add("initial_balance_low", st.get("ib_low") or _nested(snapshot, "initial_balance.low"), "computed")

    # --- expected move envelope ---
    add("expected_move_high", snapshot.get("expected_move_high"), "computed")
    add("expected_move_low", snapshot.get("expected_move_low"), "computed")

    # --- liquidity / structure ---
    add("swing_high", st.get("swing_high") or st.get("resistance"), "liquidity_engine")
    add("swing_low", st.get("swing_low") or st.get("support"), "liquidity_engine")
    add("equal_highs", st.get("equal_highs") or st.get("eq_highs"), "liquidity_engine")
    add("equal_lows", st.get("equal_lows") or st.get("eq_lows"), "liquidity_engine")
    li = snapshot.get("liquidity_intelligence") if isinstance(snapshot.get("liquidity_intelligence"), Mapping) else {}
    add_list("liquidity_pool", li.get("pools") or li.get("liquidity_pools"), "liquidity_engine")
    add_list("fair_value_gap", li.get("fvgs") or li.get("fair_value_gaps") or st.get("fvgs"), "liquidity_engine")

    return out


# --------------------------------------------------------------------------- #
# Registration — persist the day's levels once per session, per symbol
# --------------------------------------------------------------------------- #


def register_daily_levels(snapshot: Mapping[str, Any], *, path: Optional[str] = None,
                          session_date: Optional[str] = None) -> Dict[str, Any]:
    ctx = extract_context(snapshot)
    levels = extract_levels(snapshot)
    session_date = session_date or datetime.now(timezone.utc).date().isoformat()
    registered, skipped = 0, 0
    with _connect(path) as conn:
        for lvl in levels:
            distance = (lvl.price - ctx.spot) if (ctx.spot is not None) else None
            level_id = str(uuid.uuid4())
            try:
                cur = conn.execute(
                    """INSERT OR IGNORE INTO daily_levels
                       (level_id, session_date, symbol, level_type, price, source, confidence,
                        spot_price, distance_from_spot, gamma_regime, auction_regime, trend_regime,
                        expected_move_regime, volatility_regime, registered_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (level_id, session_date, ctx.symbol, lvl.level_type, lvl.price, lvl.source,
                     lvl.confidence, ctx.spot, distance, ctx.gamma_regime, ctx.auction_regime,
                     ctx.trend_regime, ctx.expected_move_regime, ctx.volatility_regime, _utc_now()),
                )
                if cur.rowcount and cur.rowcount > 0:
                    registered += 1
                else:
                    skipped += 1
            except sqlite3.DatabaseError:
                skipped += 1
        conn.commit()
    return {"registered": registered, "skipped": skipped, "session_date": session_date,
            "symbol": ctx.symbol, "levels_seen": len(levels)}


def active_levels(session_date: str, symbol: str, *, path: Optional[str] = None) -> List[sqlite3.Row]:
    with _connect(path) as conn:
        return conn.execute(
            "SELECT * FROM daily_levels WHERE session_date=? AND symbol=?",
            (session_date, symbol)).fetchall()


# --------------------------------------------------------------------------- #
# Collector — live interaction detection + price sampling
# --------------------------------------------------------------------------- #


@dataclass
class _Track:
    """In-memory per-level interaction state within a session."""
    level_id: str
    level_type: str
    level_price: float
    last_price: Optional[float] = None
    last_ts: Optional[float] = None
    prior_side: Optional[int] = None          # sign(last_price - level_price)
    touched: bool = False
    touch_count: int = 0
    broke: bool = False
    max_penetration: float = 0.0


class Collector:
    """Detects First/Near touch, rejection, break, failed-break, acceptance,
    retest, sweep, reclaim, magnet behaviour and persists them with context."""

    def __init__(self, path: Optional[str] = None):
        self.path = path or _db_path()
        self._tracks: Dict[str, _Track] = {}
        self._session_date: Optional[str] = None
        self._symbol: Optional[str] = None
        self._last_sample_ts: float = 0.0
        self.stats = {"events": 0, "samples": 0, "write_failures": 0, "dropped": 0}
        self.last_event: Optional[Dict[str, Any]] = None
        self.last_write_ts: Optional[str] = None

    def _reset_for_session(self, session_date: str, symbol: str):
        self._tracks = {}
        self._session_date = session_date
        self._symbol = symbol
        rows = active_levels(session_date, symbol, path=self.path)
        for r in rows:
            self._tracks[r["level_id"]] = _Track(
                level_id=r["level_id"], level_type=r["level_type"], level_price=float(r["price"]))

    def _record_event(self, conn, ctx: SnapshotContext, track: _Track, interaction_type: str,
                      touch_price: float, approach: str, distance_traveled: Optional[float],
                      velocity: Optional[float], now: float):
        interaction_id = str(uuid.uuid4())
        ts_iso = datetime.fromtimestamp(now, timezone.utc).isoformat()
        try:
            conn.execute(
                """INSERT INTO level_interactions
                   (interaction_id, level_id, session_date, symbol, level_type, interaction_type,
                    touch_ordinal, ts, touch_price, level_price, approach_direction,
                    distance_traveled, velocity, volume, relative_volume, delta,
                    gamma_regime, trend_regime, session_bucket, expected_move_regime, graded)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)""",
                (interaction_id, track.level_id, self._session_date, ctx.symbol, track.level_type,
                 interaction_type, track.touch_count, ts_iso, touch_price, track.level_price,
                 approach, distance_traveled, velocity, ctx.volume, ctx.relative_volume, ctx.delta,
                 ctx.gamma_regime, ctx.trend_regime, ctx.session_bucket, ctx.expected_move_regime),
            )
            self.stats["events"] += 1
            self.last_event = {"type": interaction_type, "level_type": track.level_type,
                               "price": touch_price, "at": _utc_now()}
        except sqlite3.DatabaseError:
            self.stats["write_failures"] += 1

    def _sample_price(self, conn, ctx: SnapshotContext, now: float):
        if ctx.spot is None:
            return
        if now - self._last_sample_ts < PRICE_SAMPLE_MIN_INTERVAL:
            return
        try:
            conn.execute(
                """INSERT INTO level_price_samples
                   (session_date, symbol, ts, ts_epoch, price, volume, relative_volume, delta)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (self._session_date, ctx.symbol,
                 datetime.fromtimestamp(now, timezone.utc).isoformat(), now, ctx.spot,
                 ctx.volume, ctx.relative_volume, ctx.delta))
            self._last_sample_ts = now
            self.stats["samples"] += 1
        except sqlite3.DatabaseError:
            self.stats["write_failures"] += 1

    def observe(self, snapshot: Mapping[str, Any], *, now: Optional[float] = None) -> Dict[str, Any]:
        now = now if now is not None else _now_ts()
        ctx = extract_context(snapshot)
        session_date = datetime.fromtimestamp(now, timezone.utc).date().isoformat()
        if ctx.spot is None:
            self.stats["dropped"] += 1
            return {"ok": False, "reason": "NO_SPOT"}

        # (Re)load tracks when the session or symbol rolls.
        if self._session_date != session_date or self._symbol != ctx.symbol or not self._tracks:
            register_daily_levels(snapshot, path=self.path, session_date=session_date)
            self._reset_for_session(session_date, ctx.symbol)

        events = 0
        with _connect(self.path) as conn:
            self._sample_price(conn, ctx, now)
            for track in self._tracks.values():
                x = track.level_price
                band = _touch_band(x)
                p = ctx.spot
                dist = abs(p - x)
                side = 1 if (p - x) >= 0 else -1
                velocity = None
                distance_traveled = None
                if track.last_price is not None and track.last_ts is not None:
                    dt = max(1e-6, now - track.last_ts)
                    distance_traveled = p - track.last_price
                    velocity = distance_traveled / dt

                approach = "FROM_ABOVE" if (track.prior_side or side) > 0 else "FROM_BELOW"

                # NEAR / FIRST touch
                if dist <= band:
                    if not track.touched:
                        track.touched = True
                        track.touch_count = 1
                        self._record_event(conn, ctx, track, "FIRST_TOUCH", p, approach,
                                            distance_traveled, velocity, now)
                        events += 1
                    elif track.last_price is not None and abs(track.last_price - x) > band:
                        # returned to the band after leaving -> a retest / another touch
                        track.touch_count += 1
                        self._record_event(conn, ctx, track, "RETEST", p, approach,
                                            distance_traveled, velocity, now)
                        events += 1
                elif dist <= 2 * band and not track.touched:
                    self._record_event(conn, ctx, track, "NEAR_TOUCH", p, approach,
                                        distance_traveled, velocity, now)
                    events += 1

                # BREAK / FAILED BREAK / SWEEP — only meaningful after a touch and
                # once the side flips relative to the approach.
                if track.touched and track.prior_side is not None and side != track.prior_side:
                    penetration = dist
                    track.max_penetration = max(track.max_penetration, penetration)
                    if not track.broke and penetration >= 2 * band:
                        track.broke = True
                        self._record_event(conn, ctx, track, "BREAK", p, approach,
                                            distance_traveled, velocity, now)
                        events += 1
                elif track.broke and side == track.prior_side and dist <= band:
                    # came back across the level after breaking -> reclaim/retest
                    self._record_event(conn, ctx, track, "RECLAIM", p, approach,
                                        distance_traveled, velocity, now)
                    events += 1
                    track.broke = False

                track.last_price = p
                track.last_ts = now
                if dist > band:
                    track.prior_side = side
            conn.commit()
            self.last_write_ts = _utc_now()
        return {"ok": True, "events": events, "levels": len(self._tracks), "spot": ctx.spot,
                "session_date": session_date, "symbol": ctx.symbol}


# --------------------------------------------------------------------------- #
# Grading — mature interactions into outcomes from the persisted price track
# --------------------------------------------------------------------------- #


def _forward_prices(conn, symbol: str, start_ts: float, end_ts: float) -> List[Tuple[float, float]]:
    rows = conn.execute(
        "SELECT ts_epoch, price FROM level_price_samples WHERE symbol=? AND ts_epoch>=? AND ts_epoch<=? ORDER BY ts_epoch",
        (symbol, start_ts, end_ts)).fetchall()
    return [(float(r["ts_epoch"]), float(r["price"])) for r in rows]


def _classify_outcome(level_type: str, level_price: float, approach: str,
                      prices: Sequence[Tuple[float, float]], band: float,
                      start_ts: float) -> Dict[str, Any]:
    """Deterministic outcome classification from the forward price track."""
    if not prices:
        return {"classification": "NO_RESOLUTION"}
    side = 1 if approach == "FROM_ABOVE" else -1  # favorable reaction is back toward approach side
    react_dist = 2.0 * band
    break_dist = 2.0 * band
    accept_dist = 1.5 * band

    favorable_max = 0.0
    penetration_max = 0.0
    time_to_reaction = None
    time_to_break = None
    within_band = 0
    for ts, p in prices:
        favorable = (p - level_price) * side
        penetration = -(p - level_price) * side
        if favorable > favorable_max:
            favorable_max = favorable
            if time_to_reaction is None and favorable >= react_dist:
                time_to_reaction = ts - start_ts
        if penetration > penetration_max:
            penetration_max = penetration
            if time_to_break is None and penetration >= break_dist:
                time_to_break = ts - start_ts
        if abs(p - level_price) <= band:
            within_band += 1

    end_penetration = -(prices[-1][1] - level_price) * side
    end_side = "BEYOND" if end_penetration > 0 else "HELD"

    reacted = favorable_max >= react_dist and penetration_max < break_dist
    broke = penetration_max >= break_dist and end_penetration >= accept_dist
    failed_break = penetration_max >= break_dist and end_penetration < accept_dist
    reversed_ = failed_break and favorable_max >= react_dist
    accepted = broke and (within_band < len(prices) * 0.4)
    magnet = (level_type in _MAGNET_KINDS and favorable_max < react_dist
              and penetration_max < break_dist and within_band >= max(2, int(len(prices) * 0.5)))

    if broke:
        classification = "BREAK"
    elif reversed_:
        classification = "REVERSAL"
    elif failed_break:
        classification = "FAILED_BREAK"
    elif reacted:
        classification = "REACTION"
    elif magnet:
        classification = "MAGNET"
    else:
        classification = "NO_RESOLUTION"

    return {
        "classification": classification,
        "reacted": int(reacted or reversed_),
        "broke": int(broke),
        "reversed": int(reversed_),
        "accepted": int(accepted),
        "retested": None,
        "mfe": round(favorable_max, 4),
        "mae": round(penetration_max, 4),
        "failure_distance": round(penetration_max, 4) if broke else None,
        "time_to_reaction": round(time_to_reaction, 2) if time_to_reaction is not None else None,
        "time_to_break": round(time_to_break, 2) if time_to_break is not None else None,
        "time_to_resolution": round(prices[-1][0] - start_ts, 2),
        "end_of_session_result": end_side,
    }


def run_grader(*, path: Optional[str] = None, horizon_seconds: int = GRADING_HORIZON_SECONDS,
               limit: int = 500, now: Optional[float] = None) -> Dict[str, Any]:
    now = now if now is not None else _now_ts()
    counts = {"graded": 0, "not_matured": 0, "no_prices": 0, "errors": 0}
    with _connect(path) as conn:
        job_id = _start_job(conn, "grading")
        rows = conn.execute(
            "SELECT * FROM level_interactions WHERE graded=0 AND interaction_type IN ('FIRST_TOUCH','RETEST') ORDER BY ts LIMIT ?",
            (limit,)).fetchall()
        for r in rows:
            try:
                touch_ts = _parse_ts(r["ts"])
                if touch_ts is None:
                    conn.execute("UPDATE level_interactions SET graded=1 WHERE interaction_id=?",
                                 (r["interaction_id"],))
                    counts["errors"] += 1
                    continue
                if now - touch_ts < horizon_seconds:
                    counts["not_matured"] += 1
                    continue
                band = _touch_band(float(r["level_price"]))
                prices = _forward_prices(conn, r["symbol"], touch_ts, touch_ts + horizon_seconds)
                if not prices:
                    # Mature but no forward samples captured (e.g. deploy gap).
                    conn.execute("UPDATE level_interactions SET graded=1 WHERE interaction_id=?",
                                 (r["interaction_id"],))
                    counts["no_prices"] += 1
                    continue
                outcome = _classify_outcome(r["level_type"], float(r["level_price"]),
                                            r["approach_direction"] or "FROM_ABOVE", prices, band, touch_ts)
                conn.execute(
                    """INSERT OR IGNORE INTO level_outcomes
                       (outcome_id, interaction_id, level_id, session_date, symbol, level_type,
                        classification, reacted, broke, reversed, accepted, retested,
                        mfe, mae, failure_distance, time_to_reaction, time_to_break, time_to_reclaim,
                        time_to_resolution, end_of_session_result, gamma_regime, trend_regime,
                        session_bucket, expected_move_regime, approach_direction, touch_ordinal, graded_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (str(uuid.uuid4()), r["interaction_id"], r["level_id"], r["session_date"],
                     r["symbol"], r["level_type"], outcome["classification"], outcome.get("reacted"),
                     outcome.get("broke"), outcome.get("reversed"), outcome.get("accepted"),
                     outcome.get("retested"), outcome.get("mfe"), outcome.get("mae"),
                     outcome.get("failure_distance"), outcome.get("time_to_reaction"),
                     outcome.get("time_to_break"), None, outcome.get("time_to_resolution"),
                     outcome.get("end_of_session_result"), r["gamma_regime"], r["trend_regime"],
                     r["session_bucket"], r["expected_move_regime"], r["approach_direction"],
                     r["touch_ordinal"], _utc_now()))
                conn.execute("UPDATE level_interactions SET graded=1 WHERE interaction_id=?",
                             (r["interaction_id"],))
                counts["graded"] += 1
            except sqlite3.DatabaseError:
                counts["errors"] += 1
        conn.commit()
        _finish_job(conn, job_id, "OK", counts)
    return {"ok": True, **counts, "horizon_seconds": horizon_seconds, "at": _utc_now()}


# --------------------------------------------------------------------------- #
# Statistical engine + context segmentation
# --------------------------------------------------------------------------- #


_SEGMENTS: Sequence[Tuple[str, str]] = (
    ("gamma_regime", "gamma_regime"),
    ("trend_regime", "trend_regime"),
    ("session_bucket", "session_bucket"),
    ("expected_move_regime", "expected_move_regime"),
    ("approach_direction", "approach_direction"),
)


def _touch_segment(ordinal: Any) -> str:
    try:
        n = int(ordinal)
    except (TypeError, ValueError):
        return "UNKNOWN"
    if n <= 1:
        return "FIRST_TOUCH"
    if n == 2:
        return "SECOND_TOUCH"
    return "THIRD_PLUS_TOUCH"


def _aggregate(rows: Sequence[sqlite3.Row]) -> Dict[str, Any]:
    n = len(rows)
    if n == 0:
        return {"sample_count": 0}
    reaction = sum(1 for r in rows if r["classification"] in ("REACTION", "REVERSAL"))
    breaks = sum(1 for r in rows if r["classification"] == "BREAK")
    reversal = sum(1 for r in rows if r["classification"] == "REVERSAL")
    acceptance = sum(1 for r in rows if r["accepted"])
    retest = sum(1 for r in rows if (r["touch_ordinal"] or 0) >= 2)
    excursions = [float(r["mfe"]) for r in rows if r["mfe"] is not None]
    holds = [float(r["time_to_resolution"]) for r in rows if r["time_to_resolution"] is not None]
    failures = [float(r["failure_distance"]) for r in rows if r["failure_distance"] is not None]
    ci_low, ci_high = _wilson_interval(reaction, n)
    # Stability grows with sample size and shrinks with CI width.
    width = max(1e-6, ci_high - ci_low)
    size_factor = min(1.0, n / 100.0)
    stability = round(max(0.0, min(1.0, size_factor * (1.0 - min(1.0, width)))), 3)
    # Expectancy: reaction rate weighted average excursion minus failure cost.
    avg_exc = (sum(excursions) / len(excursions)) if excursions else 0.0
    avg_fail = (sum(failures) / len(failures)) if failures else 0.0
    expectancy = round((reaction / n) * avg_exc - (breaks / n) * avg_fail, 4)
    return {
        "sample_count": n,
        "reaction_pct": round(100.0 * reaction / n, 2),
        "break_pct": round(100.0 * breaks / n, 2),
        "reversal_pct": round(100.0 * reversal / n, 2),
        "acceptance_pct": round(100.0 * acceptance / n, 2),
        "retest_pct": round(100.0 * retest / n, 2),
        "avg_excursion": round(avg_exc, 4),
        "median_excursion": round(median(excursions), 4) if excursions else 0.0,
        "avg_hold_time": round(sum(holds) / len(holds), 2) if holds else 0.0,
        "avg_failure_distance": round(avg_fail, 4),
        "ci_low": round(100.0 * ci_low, 2),
        "ci_high": round(100.0 * ci_high, 2),
        "stability_score": stability,
        "expectancy": expectancy,
    }


def rebuild_statistics(*, path: Optional[str] = None) -> Dict[str, Any]:
    written = 0
    with _connect(path) as conn:
        job_id = _start_job(conn, "statistics")
        pairs = conn.execute(
            "SELECT DISTINCT symbol, level_type FROM level_outcomes").fetchall()
        for pair in pairs:
            symbol, level_type = pair["symbol"], pair["level_type"]
            rows = conn.execute(
                "SELECT * FROM level_outcomes WHERE symbol=? AND level_type=?",
                (symbol, level_type)).fetchall()
            # ALL segment
            _upsert_stat(conn, symbol, level_type, "ALL", "ALL", _aggregate(rows))
            written += 1
            # context segments
            for seg_key, col in _SEGMENTS:
                values: Dict[str, List[sqlite3.Row]] = {}
                for r in rows:
                    values.setdefault(_norm(r[col]), []).append(r)
                for seg_value, group in values.items():
                    if seg_value in ("", "UNKNOWN"):
                        continue
                    _upsert_stat(conn, symbol, level_type, seg_key, seg_value, _aggregate(group))
                    written += 1
            # touch ordinality segment
            touch_groups: Dict[str, List[sqlite3.Row]] = {}
            for r in rows:
                touch_groups.setdefault(_touch_segment(r["touch_ordinal"]), []).append(r)
            for seg_value, group in touch_groups.items():
                _upsert_stat(conn, symbol, level_type, "touch_ordinality", seg_value, _aggregate(group))
                written += 1
        conn.commit()
        _finish_job(conn, job_id, "OK", {"rows_written": written})
    return {"ok": True, "rows_written": written, "at": _utc_now()}


def _upsert_stat(conn, symbol, level_type, seg_key, seg_value, agg: Dict[str, Any]):
    if not agg or agg.get("sample_count", 0) == 0:
        return
    conn.execute(
        """INSERT INTO calibration_statistics
           (stat_id, symbol, level_type, segment_key, segment_value, sample_count, reaction_pct,
            break_pct, reversal_pct, acceptance_pct, retest_pct, avg_excursion, median_excursion,
            avg_hold_time, avg_failure_distance, ci_low, ci_high, stability_score, expectancy, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(symbol, level_type, segment_key, segment_value) DO UPDATE SET
             sample_count=excluded.sample_count, reaction_pct=excluded.reaction_pct,
             break_pct=excluded.break_pct, reversal_pct=excluded.reversal_pct,
             acceptance_pct=excluded.acceptance_pct, retest_pct=excluded.retest_pct,
             avg_excursion=excluded.avg_excursion, median_excursion=excluded.median_excursion,
             avg_hold_time=excluded.avg_hold_time, avg_failure_distance=excluded.avg_failure_distance,
             ci_low=excluded.ci_low, ci_high=excluded.ci_high, stability_score=excluded.stability_score,
             expectancy=excluded.expectancy, updated_at=excluded.updated_at""",
        (str(uuid.uuid4()), symbol, level_type, seg_key, seg_value, agg["sample_count"],
         agg["reaction_pct"], agg["break_pct"], agg["reversal_pct"], agg["acceptance_pct"],
         agg["retest_pct"], agg["avg_excursion"], agg["median_excursion"], agg["avg_hold_time"],
         agg["avg_failure_distance"], agg["ci_low"], agg["ci_high"], agg["stability_score"],
         agg["expectancy"], _utc_now()))


def get_statistics(symbol: Optional[str] = None, level_type: Optional[str] = None,
                   segment_key: str = "ALL", segment_value: str = "ALL",
                   *, path: Optional[str] = None) -> List[Dict[str, Any]]:
    query = "SELECT * FROM calibration_statistics WHERE segment_key=? AND segment_value=?"
    params: List[Any] = [segment_key, segment_value]
    if symbol:
        query += " AND symbol=?"
        params.append(_norm(symbol))
    if level_type:
        query += " AND level_type=?"
        params.append(level_type)
    query += " ORDER BY sample_count DESC"
    with _connect(path) as conn:
        return [dict(r) for r in conn.execute(query, params).fetchall()]


# --------------------------------------------------------------------------- #
# Adaptive probability engine (spec section 7)
# --------------------------------------------------------------------------- #


def heuristic_weight(sample_count: int) -> float:
    weight = 0.90
    for threshold, w in _BLEND_SCHEDULE:
        if sample_count >= threshold:
            weight = w
    return weight


def blend(heuristic: Optional[float], historical: Optional[float], sample_count: int) -> Dict[str, Any]:
    hw = heuristic_weight(sample_count)
    if historical is None or sample_count <= 0:
        return {"value": heuristic, "heuristic_weight": 1.0, "historical_weight": 0.0,
                "sample_count": sample_count, "source": "HEURISTIC"}
    if heuristic is None:
        return {"value": historical, "heuristic_weight": 0.0, "historical_weight": 1.0,
                "sample_count": sample_count, "source": "HISTORICAL"}
    value = hw * heuristic + (1.0 - hw) * historical
    source = "CALIBRATED" if hw < 1.0 else "HEURISTIC"
    if hw == 0.0:
        source = "HISTORICAL"
    return {"value": round(value, 4), "heuristic_weight": round(hw, 2),
            "historical_weight": round(1.0 - hw, 2), "sample_count": sample_count, "source": source}


def calibrated_probabilities(symbol: str, level_type: str, *, context: Optional[Mapping[str, Any]] = None,
                             heuristic: Optional[Mapping[str, float]] = None,
                             path: Optional[str] = None) -> Dict[str, Any]:
    """Return blended reaction/break/reversal probabilities for a level type,
    preferring the most specific segment with enough samples, else ALL, else
    pure heuristic. Never raises; always returns a provenance-tagged result."""
    symbol = _norm(symbol)
    heuristic = heuristic or {}
    stat_row = None
    # Prefer the most specific matching segment that has samples.
    if context:
        for seg_key, col in _SEGMENTS:
            seg_value = _norm(context.get(col) or context.get(seg_key))
            if seg_value in ("", "UNKNOWN"):
                continue
            rows = get_statistics(symbol, level_type, seg_key, seg_value, path=path)
            if rows and rows[0]["sample_count"] >= 20:
                stat_row = rows[0]
                break
    if stat_row is None:
        rows = get_statistics(symbol, level_type, "ALL", "ALL", path=path)
        stat_row = rows[0] if rows else None

    n = int(stat_row["sample_count"]) if stat_row else 0
    hist_reaction = (stat_row["reaction_pct"] / 100.0) if stat_row and stat_row["reaction_pct"] is not None else None
    hist_break = (stat_row["break_pct"] / 100.0) if stat_row and stat_row["break_pct"] is not None else None
    hist_reversal = (stat_row["reversal_pct"] / 100.0) if stat_row and stat_row["reversal_pct"] is not None else None
    return {
        "symbol": symbol,
        "level_type": level_type,
        "segment": {"key": stat_row["segment_key"], "value": stat_row["segment_value"]} if stat_row else None,
        "reaction_prob": blend(heuristic.get("reaction_prob"), hist_reaction, n),
        "break_prob": blend(heuristic.get("break_prob"), hist_break, n),
        "reversal_prob": blend(heuristic.get("reversal_prob"), hist_reversal, n),
        "expectancy": stat_row["expectancy"] if stat_row else None,
        "stability_score": stat_row["stability_score"] if stat_row else None,
        "sample_count": n,
    }


def enrich_levels_with_calibration(levels: Sequence[Any], context: Optional[Mapping[str, Any]] = None,
                                   *, symbol: str = "SPX", path: Optional[str] = None) -> List[Any]:
    """Decision-engine integration: upgrade KeyLevel-like objects' probabilities
    with calibrated values when enough samples exist. Accepts KeyLevel objects
    (mutated in place) or dicts (returned enriched). Non-fatal by construction."""
    enriched = []
    for level in levels:
        try:
            if isinstance(level, Mapping):
                lt = level.get("kind") or level.get("level_type")
                heur = {k: level.get(k) for k in ("reaction_prob", "break_prob", "reversal_prob")}
                calib = calibrated_probabilities(symbol, str(lt), context=context, heuristic=heur, path=path)
                out = dict(level)
                out["reaction_prob"] = calib["reaction_prob"]["value"]
                out["break_prob"] = calib["break_prob"]["value"]
                out["reversal_prob"] = calib["reversal_prob"]["value"]
                out["calibration"] = calib
                enriched.append(out)
            else:
                lt = getattr(getattr(level, "kind", None), "value", None) or getattr(level, "kind", None)
                heur = {
                    "reaction_prob": _safe_float(getattr(level, "reaction_prob", None)),
                    "break_prob": _safe_float(getattr(level, "break_prob", None)),
                    "reversal_prob": _safe_float(getattr(level, "reversal_prob", None)),
                }
                calib = calibrated_probabilities(symbol, str(lt), context=context, heuristic=heur, path=path)
                if calib["reaction_prob"]["value"] is not None:
                    level.reaction_prob = calib["reaction_prob"]["value"]
                if calib["break_prob"]["value"] is not None:
                    level.break_prob = calib["break_prob"]["value"]
                if calib["reversal_prob"]["value"] is not None:
                    level.reversal_prob = calib["reversal_prob"]["value"]
                try:
                    setattr(level, "calibration", calib)
                except Exception:
                    pass
                enriched.append(level)
        except Exception:
            enriched.append(level)
    return enriched


# --------------------------------------------------------------------------- #
# Trade replay (spec section 11)
# --------------------------------------------------------------------------- #


def record_trade_replay(snapshot: Mapping[str, Any], trade_result: Optional[Mapping[str, Any]] = None,
                        *, trade_id: Optional[str] = None, path: Optional[str] = None) -> Dict[str, Any]:
    ctx = extract_context(snapshot)
    levels = extract_levels(snapshot)
    session_date = datetime.now(timezone.utc).date().isoformat()
    calib_snapshot = {}
    for lt in {l.level_type for l in levels}:
        calib_snapshot[lt] = calibrated_probabilities(ctx.symbol, lt, context=ctx.__dict__, path=path)
    replay_id = str(uuid.uuid4())
    with _connect(path) as conn:
        conn.execute(
            """INSERT INTO trade_replays
               (replay_id, trade_id, session_date, symbol, recorded_at, institutional_levels_json,
                gamma_state, auction_state, volume_profile_json, liquidity_map_json, expected_move_json,
                overnight_inventory, trend, calibration_snapshot_json, trade_result_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (replay_id, trade_id, session_date, ctx.symbol, _utc_now(),
             json.dumps([l.__dict__ for l in levels]), ctx.gamma_regime, ctx.auction_regime,
             json.dumps(snapshot.get("volume_profile") or {}, default=str),
             json.dumps(snapshot.get("liquidity_intelligence") or {}, default=str),
             json.dumps({"high": ctx.expected_move_high, "low": ctx.expected_move_low}),
             _norm(_nested(snapshot, "overnight.inventory", "overnight_inventory")),
             ctx.trend_regime, json.dumps(calib_snapshot, default=str),
             json.dumps(dict(trade_result or {}), default=str)))
        conn.commit()
    return {"ok": True, "replay_id": replay_id, "symbol": ctx.symbol}


def replay_level(level_id: str, *, path: Optional[str] = None) -> Dict[str, Any]:
    """Answer: why did a level matter? Returns the level, its interactions,
    graded outcomes, and the calibrated expectation at the time."""
    with _connect(path) as conn:
        level = conn.execute("SELECT * FROM daily_levels WHERE level_id=?", (level_id,)).fetchone()
        if not level:
            return {"ok": False, "error": "LEVEL_NOT_FOUND"}
        interactions = conn.execute(
            "SELECT * FROM level_interactions WHERE level_id=? ORDER BY ts", (level_id,)).fetchall()
        outcomes = conn.execute(
            "SELECT * FROM level_outcomes WHERE level_id=? ORDER BY graded_at", (level_id,)).fetchall()
    level_d = dict(level)
    calib = calibrated_probabilities(
        level_d["symbol"], level_d["level_type"],
        context={"gamma_regime": level_d.get("gamma_regime"),
                 "trend_regime": level_d.get("trend_regime"),
                 "expected_move_regime": level_d.get("expected_move_regime")}, path=path)
    reasons = []
    for o in outcomes:
        reasons.append(f"{o['classification']} (MFE {o['mfe']}, MAE {o['mae']}) "
                       f"in {o['gamma_regime']}/{o['session_bucket']}")
    return {"ok": True, "level": level_d,
            "interactions": [dict(r) for r in interactions],
            "outcomes": [dict(r) for r in outcomes],
            "calibration": calib,
            "why": reasons or ["No graded outcomes yet for this level."]}


# --------------------------------------------------------------------------- #
# Job bookkeeping + health + maintenance
# --------------------------------------------------------------------------- #


def _start_job(conn, job_type: str) -> str:
    job_id = str(uuid.uuid4())
    conn.execute("INSERT INTO calibration_jobs (job_id, job_type, started_at, status) VALUES (?,?,?,?)",
                 (job_id, job_type, _utc_now(), "RUNNING"))
    return job_id


def _finish_job(conn, job_id: str, status: str, detail: Mapping[str, Any]):
    conn.execute("UPDATE calibration_jobs SET finished_at=?, status=?, detail_json=? WHERE job_id=?",
                 (_utc_now(), status, json.dumps(dict(detail), default=str), job_id))


def prune_old_samples(*, path: Optional[str] = None, retention_days: int = SAMPLE_RETENTION_DAYS) -> int:
    cutoff = _now_ts() - retention_days * 86400
    with _connect(path) as conn:
        cur = conn.execute("DELETE FROM level_price_samples WHERE ts_epoch < ?", (cutoff,))
        conn.commit()
        return cur.rowcount


def db_health(*, path: Optional[str] = None) -> Dict[str, Any]:
    resolved = path or _db_path()
    start = time.perf_counter()
    try:
        with _connect(resolved) as conn:
            counts = {
                "daily_levels": conn.execute("SELECT COUNT(*) FROM daily_levels").fetchone()[0],
                "interactions": conn.execute("SELECT COUNT(*) FROM level_interactions").fetchone()[0],
                "ungraded": conn.execute("SELECT COUNT(*) FROM level_interactions WHERE graded=0").fetchone()[0],
                "outcomes": conn.execute("SELECT COUNT(*) FROM level_outcomes").fetchone()[0],
                "statistics": conn.execute("SELECT COUNT(*) FROM calibration_statistics").fetchone()[0],
                "price_samples": conn.execute("SELECT COUNT(*) FROM level_price_samples").fetchone()[0],
                "replays": conn.execute("SELECT COUNT(*) FROM trade_replays").fetchone()[0],
            }
            last_grade = conn.execute(
                "SELECT MAX(graded_at) FROM level_outcomes").fetchone()[0]
            last_stats = conn.execute(
                "SELECT MAX(finished_at) FROM calibration_jobs WHERE job_type='statistics' AND status='OK'").fetchone()[0]
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        size_bytes = Path(resolved).stat().st_size if Path(resolved).exists() else 0
        return {"ok": True, "db_path": resolved, "latency_ms": latency_ms,
                "storage_bytes": size_bytes, "storage_mb": round(size_bytes / 1_048_576, 3),
                "counts": counts, "last_successful_grade": last_grade,
                "last_statistics_rebuild": last_stats}
    except sqlite3.DatabaseError as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


# --------------------------------------------------------------------------- #
# Service — singleton orchestrator wiring collector + grader + stats + health
# --------------------------------------------------------------------------- #


class CalibrationService:
    def __init__(self, path: Optional[str] = None):
        self.path = path or _db_path()
        initialize_store(self.path)
        self.collector = Collector(self.path)
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._last_stats_ts: float = 0.0
        self._provider: Optional[Callable[[], Mapping[str, Any]]] = None
        self.started_at = _utc_now()

    # --- one processing cycle: observe -> grade -> (throttled) rebuild stats ---
    def tick(self, snapshot: Optional[Mapping[str, Any]] = None, *, now: Optional[float] = None) -> Dict[str, Any]:
        now = now if now is not None else _now_ts()
        if snapshot is None and self._provider is not None:
            try:
                snapshot = self._provider() or {}
            except Exception:
                snapshot = {}
        snapshot = snapshot or {}
        with self._lock:
            observed = self.collector.observe(snapshot, now=now)
            graded = run_grader(path=self.path, now=now)
            stats = {"skipped": True}
            if graded.get("graded") and (now - self._last_stats_ts) >= STATS_REBUILD_MIN_INTERVAL:
                stats = rebuild_statistics(path=self.path)
                self._last_stats_ts = now
        return {"ok": True, "observed": observed, "graded": graded, "statistics": stats}

    # --- background collector loop ---
    def start(self, provider: Callable[[], Mapping[str, Any]]):
        if not collector_enabled():
            return {"ok": False, "reason": "DISABLED"}
        if self._thread and self._thread.is_alive():
            return {"ok": True, "already_running": True}
        self._provider = provider
        self._stop.clear()

        def _loop():
            prune_counter = 0
            while not self._stop.is_set():
                try:
                    self.tick()
                except Exception as exc:  # never let the loop die
                    print(f"[HLCE] collector tick error (non-fatal): {exc}", flush=True)
                prune_counter += 1
                if prune_counter % 240 == 0:  # ~ every hour at 15s cadence
                    try:
                        prune_old_samples(path=self.path)
                    except Exception:
                        pass
                self._stop.wait(COLLECTOR_INTERVAL_SECONDS)

        self._thread = threading.Thread(target=_loop, name="hlce-collector", daemon=True)
        self._thread.start()
        return {"ok": True, "started": True}

    def stop(self):
        self._stop.set()
        return {"ok": True}

    def collector_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # --- read APIs backing the routes ---
    def status(self) -> Dict[str, Any]:
        health = db_health(path=self.path)
        session_date = datetime.now(timezone.utc).date().isoformat()
        with _connect(self.path) as conn:
            today_levels = conn.execute(
                "SELECT COUNT(*) FROM daily_levels WHERE session_date=?", (session_date,)).fetchone()[0]
            today_touches = conn.execute(
                "SELECT COUNT(*) FROM level_interactions WHERE session_date=?", (session_date,)).fetchone()[0]
            today_outcomes = conn.execute(
                "SELECT COUNT(*) FROM level_outcomes WHERE session_date=?", (session_date,)).fetchone()[0]
            total_samples = (health.get("counts") or {}).get("outcomes", 0)
        # calibration progress toward the 500-sample "fully historical" gate
        progress = min(1.0, total_samples / 500.0) if total_samples else 0.0
        return {
            "ok": True,
            "version": VERSION,
            "collector_enabled": collector_enabled(),
            "collector_running": self.collector_running(),
            "database": health,
            "today": {"levels": today_levels, "touches": today_touches, "outcomes": today_outcomes},
            "historical_sample_count": total_samples,
            "calibration_progress": round(progress, 3),
            "last_collector_event": self.collector.last_event,
            "last_database_write": self.collector.last_write_ts,
            "collector_stats": dict(self.collector.stats),
            "started_at": self.started_at,
        }

    def health(self) -> Dict[str, Any]:
        health = db_health(path=self.path)
        with _connect(self.path) as conn:
            queue_depth = conn.execute(
                "SELECT COUNT(*) FROM level_interactions WHERE graded=0").fetchone()[0]
            last_grade = (health.get("counts") and health.get("last_successful_grade"))
            last_stats = health.get("last_statistics_rebuild")
        lag = None
        if last_stats:
            ts = _parse_ts(last_stats)
            if ts:
                lag = round(_now_ts() - ts, 1)
        return {
            "ok": True,
            "collector_running": self.collector_running(),
            "queue_depth": queue_depth,
            "database_latency_ms": health.get("latency_ms"),
            "write_failures": self.collector.stats.get("write_failures", 0),
            "dropped_events": self.collector.stats.get("dropped", 0),
            "missed_interactions": 0,
            "calibration_lag_seconds": lag,
            "last_successful_grade": health.get("last_successful_grade"),
            "last_statistics_rebuild": last_stats,
            "storage_mb": health.get("storage_mb"),
        }

    def dashboard(self) -> Dict[str, Any]:
        status = self.status()
        top = get_statistics(segment_key="ALL", segment_value="ALL", path=self.path)
        top_sorted = sorted([r for r in top if r["sample_count"] >= 10],
                            key=lambda r: (r["expectancy"] or -999), reverse=True)
        return {
            "ok": True,
            "status": status,
            "top_performing_levels": top_sorted[:8],
            "weakest_levels": list(reversed(top_sorted[-8:])) if len(top_sorted) > 8 else [],
            "learning_rate": self._learning_rate(),
        }

    def _learning_rate(self) -> Dict[str, Any]:
        with _connect(self.path) as conn:
            since = (datetime.now(timezone.utc).timestamp() - 86400)
            recent = conn.execute(
                "SELECT COUNT(*) FROM level_outcomes WHERE graded_at >= ?",
                (datetime.fromtimestamp(since, timezone.utc).isoformat(),)).fetchone()[0]
        return {"graded_last_24h": recent}

    def levels(self, session_date: Optional[str] = None, symbol: Optional[str] = None) -> Dict[str, Any]:
        session_date = session_date or datetime.now(timezone.utc).date().isoformat()
        query = "SELECT * FROM daily_levels WHERE session_date=?"
        params: List[Any] = [session_date]
        if symbol:
            query += " AND symbol=?"
            params.append(_norm(symbol))
        with _connect(self.path) as conn:
            rows = conn.execute(query + " ORDER BY level_type", params).fetchall()
        return {"ok": True, "session_date": session_date, "count": len(rows),
                "levels": [dict(r) for r in rows]}

    def history(self, symbol: Optional[str] = None, level_type: Optional[str] = None,
                limit: int = 200) -> Dict[str, Any]:
        query = "SELECT * FROM level_outcomes"
        clauses, params = [], []
        if symbol:
            clauses.append("symbol=?")
            params.append(_norm(symbol))
        if level_type:
            clauses.append("level_type=?")
            params.append(level_type)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY graded_at DESC LIMIT ?"
        params.append(limit)
        with _connect(self.path) as conn:
            rows = conn.execute(query, params).fetchall()
        return {"ok": True, "count": len(rows), "outcomes": [dict(r) for r in rows]}


_SERVICE: Optional[CalibrationService] = None
_SERVICE_LOCK = threading.Lock()


def get_service(path: Optional[str] = None) -> CalibrationService:
    global _SERVICE
    with _SERVICE_LOCK:
        if _SERVICE is None:
            _SERVICE = CalibrationService(path)
        return _SERVICE
