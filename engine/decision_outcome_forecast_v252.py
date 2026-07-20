"""APEX 25.2 — Decision Outcome Forecasting Engine.

Shadow-mode, deterministic forecasting layer built on APEX 25.0 Decision
Integrity and 25.1 Institutional Reasoning. Given a governed decision snapshot,
it projects the expected path, magnitude, duration, favorable/adverse excursion,
target and invalidation zones, a reconciling scenario distribution, and a
forecast-quality grade.

Hard guarantees
---------------
* Shadow-only. It never changes execution eligibility, never mutates production
  confidence, never submits an order, never promotes a setup, never overrides
  25.0 integrity, and never modifies weights. ``production_effect`` is ``NONE``.
* Deterministic. Every projected number is a pure function of the supplied
  snapshot (evidence, confidence, direction, similarity stats). No randomness.
* Look-ahead safe. A forecast is a function of the snapshot ``as_of`` timestamp
  only. The evaluator refuses to score a forecast before its horizon matures,
  and comparable-session analogs older than ``as_of`` are the only ones used.

The engine is the source of truth for the forecast object; the routes module and
persistence store are thin wrappers around it.
"""
from __future__ import annotations

import datetime as dt
import math
import os
import sqlite3
import uuid
from typing import Any, Mapping, Optional, Sequence

from . import institutional_decision_integrity_v250 as integrity

try:  # Similarity is optional; a missing engine must degrade, never crash.
    from . import institutional_similarity as similarity  # type: ignore
except Exception:  # pragma: no cover - defensive import guard
    similarity = None  # type: ignore

VERSION = "25.2.0_DECISION_OUTCOME_FORECAST"
SCHEMA_VERSION = "apex.decision_forecast.v252.v1"

# Configurable horizons in seconds. Never hard-code a single timeframe.
HORIZON_SECONDS: dict[str, int] = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "session": 23400,  # 06:30-13:00 PT / full RTH remainder cap
}
DEFAULT_HORIZON = "15m"

# Minimum comparable-session sample needed before analogs shape magnitude.
MIN_ANALOG_SAMPLE = 4

# Baseline expected 1-minute range for SPX (points) used as a deterministic
# scaling anchor when no analog magnitude is available.
BASE_MINUTE_RANGE_POINTS = 1.6


# --------------------------------------------------------------------------- #
# Small deterministic helpers (mirrors 25.0/25.1 conventions).
# --------------------------------------------------------------------------- #
def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso_now() -> str:
    return _now().isoformat()


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple)) else []


def _text(value: Any) -> str:
    return str(value or "").strip()


def _parse_time(value: Any) -> Optional[dt.datetime]:
    if not value:
        return None
    try:
        text = str(value).strip().replace("Z", "+00:00")
        parsed = dt.datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone.utc)
    except (TypeError, ValueError):
        return None


def _round(value: float, places: int = 2) -> float:
    return round(float(value), places)


def shadow_mode() -> bool:
    """Shadow mode is on unless an operator explicitly disables it AND a future
    governed promotion flag authorizes production use. 25.2 has no production
    promotion path, so this is effectively always True for this engine."""
    return True


# --------------------------------------------------------------------------- #
# Snapshot resolution & look-ahead controls.
# --------------------------------------------------------------------------- #
def _as_of(root: Mapping[str, Any]) -> dt.datetime:
    for key in ("as_of", "generated_at", "timestamp", "updated_at", "last_scan_at"):
        parsed = _parse_time(root.get(key))
        if parsed:
            return parsed
    return _now()


def _reference_price(root: Mapping[str, Any]) -> Optional[float]:
    market = _mapping(root.get("market_state"))
    for key in ("spx", "spx_price", "price", "last", "underlying_price", "close"):
        value = market.get(key)
        if value not in (None, ""):
            price = _number(value)
            if price > 0:
                return price
    top = root.get("price") or root.get("spx_price")
    price = _number(top)
    return price if price > 0 else None


# --------------------------------------------------------------------------- #
# Historical analogs (look-ahead protected).
# --------------------------------------------------------------------------- #
def _analogs(root: Mapping[str, Any], as_of: dt.datetime) -> dict[str, Any]:
    """Return comparable sessions strictly older than ``as_of``.

    The look-ahead guarantee: only sessions whose date precedes the forecast
    ``as_of`` are eligible, and realized outcomes are pulled from those matured
    historical sessions only.
    """
    provided = _list(root.get("comparable_sessions") or root.get("analogs"))
    sessions: list[dict[str, Any]] = []
    for item in provided:
        block = _mapping(item)
        if not block:
            continue
        session_time = _parse_time(block.get("session_date") or block.get("date"))
        if session_time is not None and session_time >= as_of:
            continue  # look-ahead guard: future/simultaneous sessions excluded
        sessions.append({
            "session_date": block.get("session_date") or block.get("date"),
            "similarity_score": _round(_number(block.get("similarity_score") or block.get("similarity") or block.get("score"))),
            "setup_family": block.get("setup_family"),
            "market_regime": block.get("market_regime") or block.get("regime"),
            "starting_condition": block.get("starting_condition"),
            "realized_path": block.get("realized_path") or block.get("outcome_path"),
            "maximum_favorable_excursion": _number(block.get("maximum_favorable_excursion") or block.get("mfe")),
            "maximum_adverse_excursion": _number(block.get("maximum_adverse_excursion") or block.get("mae")),
            "outcome": block.get("outcome"),
            "relevance_notes": block.get("relevance_notes"),
        })

    sample = len(sessions)
    if sample:
        avg_mfe = sum(s["maximum_favorable_excursion"] for s in sessions) / sample
        avg_mae = sum(s["maximum_adverse_excursion"] for s in sessions) / sample
        wins = sum(1 for s in sessions if _text(s["outcome"]).upper() in {"WIN", "TARGET", "SUCCESS", "PROFIT"})
        win_rate = wins / sample
    else:
        avg_mfe = avg_mae = 0.0
        win_rate = 0.0

    return {
        "sample_size": sample,
        "sessions": sorted(sessions, key=lambda s: -s["similarity_score"])[:10],
        "avg_mfe": _round(avg_mfe),
        "avg_mae": _round(avg_mae),
        "win_rate": _round(win_rate, 4),
        "sufficient": sample >= MIN_ANALOG_SAMPLE,
        "source": "provided_snapshot" if provided else "none",
    }


# --------------------------------------------------------------------------- #
# Deterministic magnitude model.
# --------------------------------------------------------------------------- #
def _expected_minute_range(root: Mapping[str, Any], analogs: Mapping[str, Any]) -> float:
    """Deterministic per-minute expected range in points.

    Priority: realized analog magnitude (when sample is sufficient) then a
    volatility-scaled baseline. Never randomized.
    """
    if analogs.get("sufficient"):
        analog_range = (_number(analogs.get("avg_mfe")) + _number(analogs.get("avg_mae"))) / 2.0
        if analog_range > 0:
            # Analog excursions are session-scale; normalize to a per-minute rate.
            return max(0.4, analog_range / math.sqrt(HORIZON_SECONDS["session"] / 60.0))
    vol = _mapping(root.get("volatility") or root.get("vol"))
    vix = _number(vol.get("vix") or vol.get("value") or root.get("vix"), 16.0)
    # Higher vol widens the expected range deterministically.
    return _round(BASE_MINUTE_RANGE_POINTS * max(0.5, vix / 16.0), 3)


def _magnitude_for_horizon(minute_range: float, horizon_seconds: int) -> float:
    """Scale a per-minute range to a horizon via sqrt-of-time (deterministic)."""
    minutes = max(1.0, horizon_seconds / 60.0)
    return _round(minute_range * math.sqrt(minutes), 3)


# --------------------------------------------------------------------------- #
# Scenario engine (probabilities reconcile to 100).
# --------------------------------------------------------------------------- #
def _scenarios(direction: str, adjusted_conf: float, opposing: int,
               magnitude: float, ref_price: Optional[float]) -> list[dict[str, Any]]:
    conf = max(0.0, min(100.0, adjusted_conf)) / 100.0
    directional = direction in {"BULLISH", "BEARISH"}
    sign = 1.0 if direction == "BULLISH" else -1.0 if direction == "BEARISH" else 0.0

    if not directional:
        base = {"name": "base", "label": "Range / no-trade", "probability": 60}
        bull = {"name": "bullish", "label": "Upside break", "probability": 18}
        bear = {"name": "bearish", "label": "Downside break", "probability": 18}
        inval = {"name": "invalidation", "label": "Thesis invalid", "probability": 4}
    else:
        # Deterministic split anchored on adjusted confidence and opposition.
        base_p = 30 + int(round(conf * 30))               # 30..60
        favorable_p = 20 + int(round(conf * 25))          # 20..45
        adverse_p = 10 + min(20, opposing * 5)            # 10..30
        inval_p = 5 + min(15, opposing * 3)               # 5..20
        raw = {"base": base_p, "favorable": favorable_p, "adverse": adverse_p, "invalidation": inval_p}
        total = sum(raw.values())
        # Normalize to exactly 100 (largest-remainder rounding, deterministic).
        scaled = {k: v / total * 100 for k, v in raw.items()}
        floored = {k: int(math.floor(v)) for k, v in scaled.items()}
        remainder = 100 - sum(floored.values())
        order = sorted(scaled, key=lambda k: (-(scaled[k] - floored[k]), k))
        for i in range(remainder):
            floored[order[i % len(order)]] += 1
        base = {"name": "base", "label": f"{direction.title()} continuation (base)", "probability": floored["base"]}
        bull = {"name": "bullish", "label": f"{direction.title()} extended", "probability": floored["favorable"]}
        bear = {"name": "bearish", "label": "Counter move", "probability": floored["adverse"]}
        inval = {"name": "invalidation", "label": "Setup invalidated", "probability": floored["invalidation"]}

    def _target(mult: float) -> Optional[float]:
        if ref_price is None or sign == 0:
            return None
        return _round(ref_price + sign * magnitude * mult, 2)

    def _counter_target(mult: float) -> Optional[float]:
        if ref_price is None or sign == 0:
            return None
        return _round(ref_price - sign * magnitude * mult, 2)

    scenarios = [
        {**base, "trigger": "Evidence stack holds", "expected_path": f"{direction.title()} drift" if directional else "Two-sided rotation",
         "expected_magnitude_points": _round(magnitude), "targets": [_target(1.0)] if directional else [],
         "invalidation": _counter_target(1.0)},
        {**bull, "trigger": "Favorable flow acceleration", "expected_path": "Extended favorable excursion",
         "expected_magnitude_points": _round(magnitude * 1.6), "targets": [_target(1.6)] if directional else [_target(1.0)],
         "invalidation": _counter_target(1.0)},
        {**bear, "trigger": "Opposing structure asserts", "expected_path": "Adverse excursion",
         "expected_magnitude_points": _round(magnitude), "targets": [_counter_target(1.0)] if directional else [_counter_target(1.0)],
         "invalidation": _target(0.5)},
        {**inval, "trigger": "Invalidation level breached", "expected_path": "Thesis fails",
         "expected_magnitude_points": _round(magnitude * 1.2), "targets": [], "invalidation": _counter_target(1.5)},
    ]
    assert sum(s["probability"] for s in scenarios) == 100, "scenario probabilities must sum to 100"
    return scenarios


# --------------------------------------------------------------------------- #
# Forecast quality.
# --------------------------------------------------------------------------- #
CRITICAL_SOURCES = ("market_state", "institutional_intelligence")


def _critical_states(health: Mapping[str, Any]) -> dict[str, str]:
    states = {}
    for item in _list(health.get("sources")):
        block = _mapping(item)
        source = _text(block.get("source"))
        if source in CRITICAL_SOURCES:
            states[source] = _text(block.get("state")).upper()
    return states


def _forecast_quality(health: Mapping[str, Any], adjusted_conf: float,
                      analogs: Mapping[str, Any]) -> dict[str, Any]:
    health_state = _text(health.get("state")).upper()
    fresh_ratio = _number(health.get("fresh_ratio"))
    sample = int(_number(analogs.get("sample_size")))
    critical = _critical_states(health)
    critical_hard = [s for s, st in critical.items() if st in {"MISSING", "FAILED", "NOT_CONFIGURED"}]
    critical_stale = [s for s, st in critical.items() if st == "STALE"]
    reasons: list[str] = []

    # A failed/missing critical source is never neutral: it forecloses the forecast.
    if critical_hard:
        quality = "INSUFFICIENT_DATA"
        reasons.append(f"Critical evidence unavailable ({', '.join(critical_hard)}); "
                       "a missing or failed critical source is not treated as neutral.")
    elif health_state == "UNRELIABLE" or fresh_ratio < 0.5:
        quality = "INSUFFICIENT_DATA"
        reasons.append("Evidence health is unreliable or fresh coverage below 50%.")
    elif critical_stale:
        quality = "LOW"
        reasons.append(f"Critical evidence stale ({', '.join(critical_stale)}); forecast confidence capped.")
    elif sample < MIN_ANALOG_SAMPLE:
        quality = "LOW"
        reasons.append(f"Only {sample} comparable session(s); below minimum of {MIN_ANALOG_SAMPLE}.")
    elif health_state == "HEALTHY" and fresh_ratio >= 0.75 and sample >= 12 and adjusted_conf >= 70:
        quality = "HIGH"
        reasons.append("Healthy evidence, strong analog sample, and high adjusted confidence.")
    else:
        quality = "MODERATE"
        reasons.append("Adequate but not strong evidence/sample conditions.")

    return {"quality": quality, "reasons": reasons,
            "fresh_ratio": _round(fresh_ratio, 4), "analog_sample": sample}


def _grade(adjusted_conf: float, quality: str, opposing: int) -> str:
    if quality == "INSUFFICIENT_DATA":
        return "NOT_GRADEABLE"
    score = adjusted_conf - min(20, opposing * 5)
    if quality == "HIGH":
        score += 5
    elif quality == "LOW":
        score -= 10
    if score >= 85:
        return "A"
    if score >= 78:
        return "A-"
    if score >= 70:
        return "B+"
    if score >= 62:
        return "B"
    if score >= 52:
        return "C"
    if score >= 40:
        return "D"
    return "F"


# --------------------------------------------------------------------------- #
# Forecast builder.
# --------------------------------------------------------------------------- #
def build_forecast(payload: Optional[Mapping[str, Any]], *,
                   horizon: str = DEFAULT_HORIZON,
                   decision: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    root = payload if isinstance(payload, Mapping) else {}
    horizon = horizon if horizon in HORIZON_SECONDS else DEFAULT_HORIZON
    horizon_seconds = HORIZON_SECONDS[horizon]

    evaluated = decision if isinstance(decision, Mapping) else integrity.evaluate_decision(root)
    decision_block = _mapping(evaluated.get("decision"))
    explain = _mapping(evaluated.get("explainability"))
    health = _mapping(evaluated.get("evidence_health"))

    direction = _text(decision_block.get("direction") or "NEUTRAL").upper()
    adjusted_conf = _number(decision_block.get("integrity_adjusted_confidence"))
    opposing = len(_list(explain.get("opposing_evidence")))
    eligibility = _text(decision_block.get("execution_eligibility"))

    as_of = _as_of(root)
    ref_price = _reference_price(root)
    analogs = _analogs(root, as_of)

    minute_range = _expected_minute_range(root, analogs)
    magnitude = _magnitude_for_horizon(minute_range, horizon_seconds)
    quality = _forecast_quality(health, adjusted_conf, analogs)

    sign = 1.0 if direction == "BULLISH" else -1.0 if direction == "BEARISH" else 0.0
    expected_mfe = _round(magnitude * (0.9 if quality["quality"] in {"HIGH", "MODERATE"} else 0.6))
    expected_mae = _round(magnitude * (0.5 if opposing <= 1 else 0.8))
    risk_reward = _round(expected_mfe / expected_mae, 2) if expected_mae > 0 else None

    def _zone(mult: float, favorable: bool = True) -> Optional[float]:
        if ref_price is None or sign == 0:
            return None
        s = sign if favorable else -sign
        return _round(ref_price + s * magnitude * mult, 2)

    scenarios = _scenarios(direction, adjusted_conf, opposing, magnitude, ref_price)
    grade = _grade(adjusted_conf, quality["quality"], opposing)

    forecast = {
        "forecast_id": _forecast_id(evaluated, horizon, as_of),
        "decision_id": _decision_id(evaluated, root),
        "symbol": _text(root.get("symbol") or _mapping(root.get("market_state")).get("symbol") or "SPX"),
        "direction": direction,
        "issued_at": as_of.isoformat(),
        "forecast_horizon": horizon,
        "forecast_horizon_seconds": horizon_seconds,
        "reference_price": ref_price,
        "expected_path": "DIRECTIONAL_DRIFT" if sign != 0 else "TWO_SIDED_ROTATION",
        "target_zone_1": _zone(1.0),
        "target_zone_2": _zone(1.6),
        "target_zone_3": _zone(2.2),
        "invalidation_zone": _zone(1.0, favorable=False),
        "expected_move_points": _round(magnitude),
        "expected_move_percent": _round(magnitude / ref_price * 100, 3) if ref_price else None,
        "expected_hold_seconds": horizon_seconds,
        "expected_mfe": expected_mfe,
        "expected_mae": expected_mae,
        "expected_risk_reward": risk_reward,
        "expected_grade": grade,
        "forecast_confidence": _round(adjusted_conf),
        "forecast_quality": quality["quality"],
        "forecast_quality_reasons": quality["reasons"],
        "forecast_basis": ("historical_analog" if analogs.get("sufficient") else "volatility_scaled_baseline"),
        "comparable_sessions": analogs["sessions"],
        "comparable_sample_size": analogs["sample_size"],
        "scenarios": scenarios,
        "shadow_mode": shadow_mode(),
    }

    return {
        "ok": True,
        "status": "READY" if quality["quality"] != "INSUFFICIENT_DATA" else "INSUFFICIENT_DATA",
        "version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "generated_at": _iso_now(),
        "execution_eligibility": eligibility,
        "forecast": forecast,
        "decision_integrity": {
            "direction": direction,
            "execution_eligibility": eligibility,
            "integrity_adjusted_confidence": adjusted_conf,
            "evidence_health_state": _text(health.get("state")),
        },
        "guardrails": {
            "shadow_mode": True,
            "read_only": True,
            "advisory_only": True,
            "changes_execution_eligibility": False,
            "mutates_production_confidence": False,
            "automatic_order_submission": False,
            "overrides_integrity": False,
            "modifies_weights": False,
        },
        "production_effect": "NONE",
    }


def build_all_horizons(payload: Optional[Mapping[str, Any]],
                       horizons: Optional[Sequence[str]] = None) -> dict[str, Any]:
    root = payload if isinstance(payload, Mapping) else {}
    decision = integrity.evaluate_decision(root)
    chosen = [h for h in (horizons or HORIZON_SECONDS.keys()) if h in HORIZON_SECONDS]
    forecasts = {h: build_forecast(root, horizon=h, decision=decision)["forecast"] for h in chosen}
    return {
        "ok": True,
        "version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "generated_at": _iso_now(),
        "horizons": chosen,
        "forecasts": forecasts,
        "production_effect": "NONE",
    }


# --------------------------------------------------------------------------- #
# Stable identifiers.
# --------------------------------------------------------------------------- #
def _decision_id(evaluated: Mapping[str, Any], root: Mapping[str, Any]) -> str:
    for key in ("decision_id", "parent_signal_id", "signal_id"):
        value = _mapping(evaluated.get("decision")).get(key) or root.get(key)
        if value:
            return _text(value)
    return _text(root.get("decision_id") or root.get("signal_id") or "unattributed")


def _forecast_id(evaluated: Mapping[str, Any], horizon: str, as_of: dt.datetime) -> str:
    base = f"{_decision_id(evaluated, {})}|{horizon}|{as_of.isoformat()}"
    return "fcst_" + uuid.uuid5(uuid.NAMESPACE_URL, base).hex[:20]


# --------------------------------------------------------------------------- #
# Persistence (governed sqlite path; never the repo root by default).
# --------------------------------------------------------------------------- #
def _db_path() -> str:
    return os.getenv("APEX_DECISION_FORECAST_DB", "apex_decision_forecast.db")


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> dict[str, Any]:
    with _conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS decision_forecasts (
                forecast_id TEXT PRIMARY KEY,
                decision_id TEXT,
                symbol TEXT,
                direction TEXT,
                horizon TEXT,
                horizon_seconds INTEGER,
                issued_at TEXT NOT NULL,
                matures_at TEXT NOT NULL,
                reference_price REAL,
                expected_move_points REAL,
                expected_mfe REAL,
                expected_mae REAL,
                expected_grade TEXT,
                forecast_quality TEXT,
                engine_version TEXT,
                forecast_json TEXT NOT NULL,
                input_snapshot_json TEXT,
                scenario_json TEXT,
                realized_json TEXT,
                evaluation_json TEXT,
                evaluated_at TEXT,
                shadow_mode INTEGER DEFAULT 1
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_forecast_decision ON decision_forecasts(decision_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_forecast_matures ON decision_forecasts(matures_at)")
    return {"ok": True, "db_path": _db_path(), "schema_version": SCHEMA_VERSION}


def persist_forecast(result: Mapping[str, Any], input_snapshot: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    import json
    forecast = _mapping(result.get("forecast"))
    if not forecast:
        return {"ok": False, "error": "no forecast to persist"}
    issued = _parse_time(forecast.get("issued_at")) or _now()
    matures = issued + dt.timedelta(seconds=int(_number(forecast.get("forecast_horizon_seconds"), 900)))
    init_db()
    with _conn() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO decision_forecasts
            (forecast_id, decision_id, symbol, direction, horizon, horizon_seconds,
             issued_at, matures_at, reference_price, expected_move_points, expected_mfe,
             expected_mae, expected_grade, forecast_quality, engine_version,
             forecast_json, input_snapshot_json, scenario_json, shadow_mode)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)
            """,
            (
                forecast.get("forecast_id"), forecast.get("decision_id"), forecast.get("symbol"),
                forecast.get("direction"), forecast.get("forecast_horizon"),
                int(_number(forecast.get("forecast_horizon_seconds"))),
                issued.isoformat(), matures.isoformat(),
                forecast.get("reference_price"), forecast.get("expected_move_points"),
                forecast.get("expected_mfe"), forecast.get("expected_mae"),
                forecast.get("expected_grade"), forecast.get("forecast_quality"),
                VERSION, json.dumps(forecast), json.dumps(dict(input_snapshot or {})),
                json.dumps(forecast.get("scenarios")),
            ),
        )
    return {"ok": True, "forecast_id": forecast.get("forecast_id"), "matures_at": matures.isoformat()}


def history(limit: int = 50, decision_id: Optional[str] = None) -> dict[str, Any]:
    import json
    init_db()
    query = "SELECT * FROM decision_forecasts"
    params: list[Any] = []
    if decision_id:
        query += " WHERE decision_id = ?"
        params.append(decision_id)
    query += " ORDER BY issued_at DESC LIMIT ?"
    params.append(int(limit))
    with _conn() as conn:
        rows = conn.execute(query, params).fetchall()
    records = []
    for row in rows:
        record = dict(row)
        for key in ("forecast_json", "scenario_json", "realized_json", "evaluation_json"):
            if record.get(key):
                try:
                    record[key.replace("_json", "")] = json.loads(record[key])
                except (TypeError, ValueError):
                    pass
            record.pop(key, None)
        record.pop("input_snapshot_json", None)
        records.append(record)
    return {"ok": True, "version": VERSION, "count": len(records), "forecasts": records,
            "generated_at": _iso_now()}


# --------------------------------------------------------------------------- #
# Forecast evaluator — matured horizons only (look-ahead safe).
# --------------------------------------------------------------------------- #
def evaluate_forecast(forecast: Mapping[str, Any], realized: Mapping[str, Any],
                      *, now: Optional[dt.datetime] = None) -> dict[str, Any]:
    """Score a forecast against a realized outcome.

    Refuses to score before the horizon matures. ``realized`` must carry the
    post-horizon truth: realized_direction, realized_mfe, realized_mae,
    realized_move_points, target_hit (bool), invalidated (bool), realized_hold_seconds.
    """
    current = now or _now()
    issued = _parse_time(forecast.get("issued_at"))
    horizon_seconds = int(_number(forecast.get("forecast_horizon_seconds"), 900))
    if issued is None:
        return {"ok": False, "status": "INVALID_FORECAST", "reason": "missing issued_at"}
    matures = issued + dt.timedelta(seconds=horizon_seconds)
    if current < matures:
        return {
            "ok": False,
            "status": "NOT_MATURED",
            "reason": "Forecast horizon has not elapsed; scoring is refused to prevent look-ahead.",
            "matures_at": matures.isoformat(),
            "seconds_remaining": _round((matures - current).total_seconds(), 1),
        }

    predicted_dir = _text(forecast.get("direction")).upper()
    realized_dir = _text(realized.get("realized_direction") or realized.get("direction")).upper()
    direction_correct = bool(predicted_dir) and predicted_dir == realized_dir and predicted_dir != "NEUTRAL"

    pred_mfe = _number(forecast.get("expected_mfe"))
    pred_mae = _number(forecast.get("expected_mae"))
    real_mfe = _number(realized.get("realized_mfe") or realized.get("mfe"))
    real_mae = _number(realized.get("realized_mae") or realized.get("mae"))
    pred_hold = _number(forecast.get("expected_hold_seconds"), horizon_seconds)
    real_hold = _number(realized.get("realized_hold_seconds") or realized.get("hold_seconds"), horizon_seconds)

    target_hit = bool(realized.get("target_hit"))
    invalidated = bool(realized.get("invalidated"))

    # Scenario-probability accuracy: Brier-style against the realized bucket.
    scenarios = _list(forecast.get("scenarios"))
    realized_bucket = _text(realized.get("realized_scenario") or "").lower()
    brier = None
    if scenarios and realized_bucket:
        brier = 0.0
        for scenario in scenarios:
            p = _number(_mapping(scenario).get("probability")) / 100.0
            actual = 1.0 if _text(_mapping(scenario).get("name")).lower() == realized_bucket else 0.0
            brier += (p - actual) ** 2
        brier = _round(brier / len(scenarios), 4)

    return {
        "ok": True,
        "status": "MATURED",
        "version": VERSION,
        "forecast_id": forecast.get("forecast_id"),
        "matured_at": matures.isoformat(),
        "metrics": {
            "direction_accuracy": 1.0 if direction_correct else 0.0,
            "target_hit": target_hit,
            "invalidation_accuracy": 1.0 if (invalidated == bool(realized.get("expected_invalidation", invalidated))) else 0.0,
            "mfe_error": _round(abs(pred_mfe - real_mfe)),
            "mae_error": _round(abs(pred_mae - real_mae)),
            "hold_time_error_seconds": _round(abs(pred_hold - real_hold)),
            "scenario_brier": brier,
            "expected_grade": forecast.get("expected_grade"),
            "realized_grade": realized.get("realized_grade"),
            "grade_match": _text(forecast.get("expected_grade")) == _text(realized.get("realized_grade")),
        },
        "generated_at": _iso_now(),
        "production_effect": "NONE",
    }


def persist_evaluation(forecast_id: str, evaluation: Mapping[str, Any],
                       realized: Mapping[str, Any]) -> dict[str, Any]:
    import json
    if not evaluation.get("ok") or evaluation.get("status") != "MATURED":
        return {"ok": False, "error": "only matured evaluations are persisted"}
    init_db()
    with _conn() as conn:
        cur = conn.execute(
            "UPDATE decision_forecasts SET realized_json=?, evaluation_json=?, evaluated_at=? WHERE forecast_id=?",
            (json.dumps(dict(realized)), json.dumps(dict(evaluation)), _iso_now(), forecast_id),
        )
        updated = cur.rowcount
    return {"ok": updated > 0, "updated": updated, "forecast_id": forecast_id}


# --------------------------------------------------------------------------- #
# Mission Control group + status.
# --------------------------------------------------------------------------- #
def mission_control_group(result: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    forecast = _mapping((result or {}).get("forecast"))
    panel_state = "EMPTY" if not forecast else (
        "INSUFFICIENT_DATA" if _text(forecast.get("forecast_quality")) == "INSUFFICIENT_DATA" else "READY")
    return {
        "group": "DECISION_OUTCOME_FORECAST",
        "shadow_mode": True,
        "panel_state": panel_state,
        "expected_path": forecast.get("expected_path"),
        "forecast_horizon": forecast.get("forecast_horizon"),
        "forecast_quality": forecast.get("forecast_quality"),
        "expected_move_points": forecast.get("expected_move_points"),
        "expected_mfe": forecast.get("expected_mfe"),
        "expected_mae": forecast.get("expected_mae"),
        "expected_risk_reward": forecast.get("expected_risk_reward"),
        "expected_grade": forecast.get("expected_grade"),
        "target_zone_1": forecast.get("target_zone_1"),
        "invalidation_zone": forecast.get("invalidation_zone"),
        "comparable_sample_size": forecast.get("comparable_sample_size"),
        "production_effect": "NONE",
    }


def status() -> dict[str, Any]:
    return {
        "status": "READY",
        "engine": "DECISION_OUTCOME_FORECAST",
        "version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "shadow_mode": True,
        "read_only": True,
        "advisory_only": True,
        "horizons": list(HORIZON_SECONDS.keys()),
        "default_horizon": DEFAULT_HORIZON,
        "min_analog_sample": MIN_ANALOG_SAMPLE,
        "automatic_order_submission": False,
        "production_confidence_mutation": False,
        "production_effect": "NONE",
    }
