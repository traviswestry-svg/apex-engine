"""APEX 44 — Institutional Liquidity Intelligence Engine.

Builds a ranked liquidity map, estimates institutional intent, classifies sweep
behavior, and records resolved observations for later calibration. Advisory only.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from engine.liquidity_race import evaluate as evaluate_race

VERSION = "44.0.0"
SCHEMA_VERSION = "apex.liquidity_intelligence.v1"
DEFAULT_DB = os.getenv("APEX_LIQUIDITY_MEMORY_DB", "apex_liquidity_memory.db")


def _num(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
        return x if math.isfinite(x) else default
    except (TypeError, ValueError):
        return default


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _first(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def _pool(level: Any, kind: str, side: str, *, touches: Any = 0, volume: Any = 0,
          gamma: Any = 0, age_minutes: Any = 0, source: str = "derived") -> dict[str, Any] | None:
    px = _num(level)
    if px <= 0:
        return None
    return {
        "level": round(px, 2), "type": kind, "side": side,
        "touches": max(0, int(_num(touches))), "volume": max(0.0, _num(volume)),
        "gamma": abs(_num(gamma)), "age_minutes": max(0.0, _num(age_minutes)),
        "source": source,
    }


def build_liquidity_map(snapshot: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    s = dict(snapshot or {})
    price = _num(_first(s.get("current_price"), s.get("price"), s.get("spot")))
    if price <= 0:
        return []
    pools: list[dict[str, Any] | None] = [
        _pool(s.get("pdh"), "PDH", "UPPER"), _pool(s.get("pdl"), "PDL", "LOWER"),
        _pool(s.get("onh"), "ONH", "UPPER"), _pool(s.get("onl"), "ONL", "LOWER"),
        _pool(s.get("vah"), "VAH", "UPPER" if _num(s.get("vah")) > price else "LOWER"),
        _pool(s.get("val"), "VAL", "UPPER" if _num(s.get("val")) > price else "LOWER"),
        _pool(s.get("poc"), "POC", "UPPER" if _num(s.get("poc")) > price else "LOWER"),
        _pool(s.get("call_wall"), "CALL_WALL", "UPPER", gamma=s.get("call_wall_gamma")),
        _pool(s.get("put_wall"), "PUT_WALL", "LOWER", gamma=s.get("put_wall_gamma")),
        _pool(s.get("expected_move_high"), "EXPECTED_MOVE_HIGH", "UPPER"),
        _pool(s.get("expected_move_low"), "EXPECTED_MOVE_LOW", "LOWER"),
        _pool(s.get("equal_high"), "EQUAL_HIGH", "UPPER", touches=s.get("equal_high_touches")),
        _pool(s.get("equal_low"), "EQUAL_LOW", "LOWER", touches=s.get("equal_low_touches")),
        _pool(s.get("swing_high"), "SWING_HIGH", "UPPER", touches=s.get("swing_high_touches")),
        _pool(s.get("swing_low"), "SWING_LOW", "LOWER", touches=s.get("swing_low_touches")),
    ]
    for raw in s.get("additional_pools") or []:
        if isinstance(raw, Mapping):
            level = _num(raw.get("level"))
            side = str(raw.get("side") or ("UPPER" if level > price else "LOWER")).upper()
            pools.append(_pool(level, str(raw.get("type") or "CUSTOM").upper(), side,
                               touches=raw.get("touches"), volume=raw.get("volume"),
                               gamma=raw.get("gamma"), age_minutes=raw.get("age_minutes"),
                               source=str(raw.get("source") or "external")))
    # Round-number pools support fast SPX decisions without pretending they are orders.
    interval = max(5.0, _num(s.get("round_interval"), 25.0))
    lower_round = math.floor(price / interval) * interval
    upper_round = math.ceil(price / interval) * interval
    if lower_round < price:
        pools.append(_pool(lower_round, "ROUND_NUMBER", "LOWER", source="synthetic"))
    if upper_round > price:
        pools.append(_pool(upper_round, "ROUND_NUMBER", "UPPER", source="synthetic"))

    dedup: dict[tuple[float, str], dict[str, Any]] = {}
    type_weight = {"CALL_WALL": 22, "PUT_WALL": 22, "PDH": 18, "PDL": 18, "ONH": 16, "ONL": 16,
                   "VAH": 14, "VAL": 14, "POC": 17, "EQUAL_HIGH": 18, "EQUAL_LOW": 18,
                   "EXPECTED_MOVE_HIGH": 15, "EXPECTED_MOVE_LOW": 15, "SWING_HIGH": 12,
                   "SWING_LOW": 12, "ROUND_NUMBER": 8, "CUSTOM": 10}
    for p in pools:
        if not p or p["level"] == price:
            continue
        actual_side = "UPPER" if p["level"] > price else "LOWER"
        if p["side"] != actual_side:
            p["side"] = actual_side
        distance = abs(p["level"] - price)
        proximity = 30.0 * math.exp(-distance / max(12.0, _num(s.get("atr"), 20.0) * 1.5))
        touch_score = min(14.0, p["touches"] * 4.0)
        volume_score = min(10.0, math.log10(1.0 + p["volume"]) * 2.0)
        gamma_score = min(12.0, math.log10(1.0 + p["gamma"]) * 2.5)
        freshness = max(0.0, 8.0 - min(8.0, p["age_minutes"] / 60.0))
        score = _clamp(type_weight.get(p["type"], 10) + proximity + touch_score + volume_score + gamma_score + freshness)
        p.update({"distance": round(distance, 2), "strength_score": round(score, 1),
                  "status": "ACTIVE", "reaction_expectation": "HIGH" if score >= 75 else "MODERATE" if score >= 55 else "LOW"})
        key = (p["level"], p["side"])
        if key not in dedup or p["strength_score"] > dedup[key]["strength_score"]:
            dedup[key] = p
    return sorted(dedup.values(), key=lambda p: (-p["strength_score"], p["distance"]))


def infer_intent(snapshot: Mapping[str, Any] | None = None) -> dict[str, Any]:
    s = dict(snapshot or {})
    components = {
        "order_flow": _num(s.get("order_flow_score"), 50), "delta": _num(s.get("delta_score"), 50),
        "momentum": _num(s.get("momentum_score"), 50), "structure": _num(s.get("structure_score"), 50),
        "auction": _num(s.get("auction_score"), 50), "vwap": _num(s.get("vwap_score"), 50),
        "gamma": _num(s.get("gamma_score"), 50),
    }
    weights = {"order_flow": .22, "delta": .18, "momentum": .15, "structure": .14,
               "auction": .12, "vwap": .10, "gamma": .09}
    score = sum(components[k] * weights[k] for k in weights)
    delta = components["delta"] - 50
    flow = components["order_flow"] - 50
    price_change = _num(s.get("price_change_pct"))
    if score >= 62:
        state = "SHORT_COVERING" if price_change > 0 and delta > 12 and _num(s.get("put_unwind_score")) > 60 else "ACCUMULATION"
    elif score <= 38:
        state = "LONG_LIQUIDATION" if price_change < 0 and delta < -12 else "DISTRIBUTION"
    else:
        state = "NEUTRAL"
    confidence = _clamp(40 + abs(score - 50) * 2.2)
    return {"state": state, "direction": "BULLISH" if score > 55 else "BEARISH" if score < 45 else "NEUTRAL",
            "score": round(score, 1), "confidence": round(confidence, 1), "components": components,
            "interpretation": f"Evidence is most consistent with {state.lower().replace('_', ' ')}.",
            "advisory_only": True}


def classify_sweep(snapshot: Mapping[str, Any] | None, pools: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    s = dict(snapshot or {})
    price = _num(_first(s.get("current_price"), s.get("price"), s.get("spot")))
    previous = _num(s.get("previous_price"), price)
    high = _num(s.get("bar_high"), price)
    low = _num(s.get("bar_low"), price)
    tolerance = max(0.25, _num(s.get("sweep_tolerance"), 1.0))
    candidates = sorted(pools, key=lambda p: abs(_num(p.get("level")) - price))
    for p in candidates:
        level = _num(p.get("level")); side = p.get("side")
        if side == "UPPER" and high >= level and previous < level:
            held_above = price >= level - tolerance
            return {"state": "BUY_SIDE_SWEEP_CONTINUATION" if held_above else "BUY_SIDE_FAILED_SWEEP",
                    "side": "BUY_SIDE", "level": level, "pool_type": p.get("type"),
                    "continuation_probability_pct": 66.0 if held_above else 34.0,
                    "reversal_probability_pct": 34.0 if held_above else 66.0}
        if side == "LOWER" and low <= level and previous > level:
            held_below = price <= level + tolerance
            return {"state": "SELL_SIDE_SWEEP_CONTINUATION" if held_below else "SELL_SIDE_FAILED_SWEEP",
                    "side": "SELL_SIDE", "level": level, "pool_type": p.get("type"),
                    "continuation_probability_pct": 66.0 if held_below else 34.0,
                    "reversal_probability_pct": 34.0 if held_below else 66.0}
    return {"state": "NO_ACTIVE_SWEEP", "side": "NONE", "continuation_probability_pct": 50.0,
            "reversal_probability_pct": 50.0}


def evaluate(snapshot: Mapping[str, Any] | None = None) -> dict[str, Any]:
    s = dict(snapshot or {})
    price = _num(_first(s.get("current_price"), s.get("price"), s.get("spot")))
    pools = build_liquidity_map(s)
    upper = [p for p in pools if p["side"] == "UPPER"]
    lower = [p for p in pools if p["side"] == "LOWER"]
    race_input = dict(s)
    if upper and lower:
        race_input.update({"current_price": price, "upper_level": upper[0]["level"], "lower_level": lower[0]["level"],
                           "upper_size": max(1, upper[0].get("volume", 1)), "lower_size": max(1, lower[0].get("volume", 1))})
    race = evaluate_race(race_input)
    intent = infer_intent(s)
    sweep = classify_sweep(s, pools)
    top = (upper[:3] + lower[:3])
    return {"ok": bool(price > 0 and pools), "status": "READY" if price > 0 and pools else "INSUFFICIENT_DATA",
            "current_price": price, "liquidity_map": pools, "top_pools": top, "race": race,
            "institutional_intent": intent, "sweep_detection": sweep,
            "trade_director_context": {"preferred_target_side": race.get("leader", "BALANCED"),
                "intent_alignment": intent["direction"], "sweep_state": sweep["state"],
                "eligible": race.get("ok", False) and race.get("edge_pct", 0) >= 10 and intent["confidence"] >= 50,
                "warning": "Re-evaluate absorption and replenishment when price contacts the target pool."},
            "schema_version": SCHEMA_VERSION, "engine_version": VERSION, "advisory_only": True}


def _connect(db_path: str | Path = DEFAULT_DB) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("""CREATE TABLE IF NOT EXISTS liquidity_outcomes (
        id INTEGER PRIMARY KEY AUTOINCREMENT, observed_at TEXT NOT NULL, ticker TEXT NOT NULL,
        pool_type TEXT NOT NULL, side TEXT NOT NULL, level REAL NOT NULL, strength REAL,
        outcome TEXT NOT NULL, minutes_to_hit REAL, reaction TEXT, regime TEXT, payload_json TEXT)""")
    return conn


def record_outcome(observation: Mapping[str, Any], db_path: str | Path = DEFAULT_DB) -> int:
    o = dict(observation)
    with _connect(db_path) as conn:
        cur = conn.execute("""INSERT INTO liquidity_outcomes
            (observed_at,ticker,pool_type,side,level,strength,outcome,minutes_to_hit,reaction,regime,payload_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (
            str(o.get("observed_at") or datetime.now(timezone.utc).isoformat()), str(o.get("ticker") or "SPX"),
            str(o.get("pool_type") or "UNKNOWN"), str(o.get("side") or "UNKNOWN"), _num(o.get("level")),
            _num(o.get("strength")), str(o.get("outcome") or "UNKNOWN"), _num(o.get("minutes_to_hit")),
            str(o.get("reaction") or "UNKNOWN"), str(o.get("regime") or "UNKNOWN"), json.dumps(o, default=str)))
        return int(cur.lastrowid)


def memory_summary(db_path: str | Path = DEFAULT_DB, limit: int = 500) -> dict[str, Any]:
    if not Path(db_path).exists():
        return {"observations": 0, "by_pool_type": [], "calibration_ready": False}
    with _connect(db_path) as conn:
        rows = conn.execute("""SELECT pool_type, COUNT(*),
            AVG(CASE WHEN outcome='HIT' THEN 1.0 ELSE 0.0 END),
            AVG(CASE WHEN reaction='REVERSAL' THEN 1.0 ELSE 0.0 END), AVG(minutes_to_hit)
            FROM (SELECT * FROM liquidity_outcomes ORDER BY id DESC LIMIT ?) GROUP BY pool_type""", (limit,)).fetchall()
        count = conn.execute("SELECT COUNT(*) FROM liquidity_outcomes").fetchone()[0]
    return {"observations": count, "calibration_ready": count >= 100,
            "by_pool_type": [{"pool_type": r[0], "samples": r[1], "hit_rate": round((r[2] or 0)*100,1),
                              "reversal_rate": round((r[3] or 0)*100,1), "avg_minutes_to_hit": round(r[4] or 0,1)} for r in rows]}
