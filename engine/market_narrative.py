"""APEX 45 — Institutional Market Narrative Engine.

Transforms composed APEX evidence into an explainable, contradiction-aware,
advisory market thesis. It never grants execution authority.
"""
from __future__ import annotations

import json, math, os, sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

VERSION = "45.0.0"
SCHEMA_VERSION = "apex.market_narrative.v1"
DEFAULT_DB = os.getenv("APEX_NARRATIVE_DB", "apex_narrative_memory.db")


def _num(v: Any, default: float = 50.0) -> float:
    try:
        x = float(v)
        return x if math.isfinite(x) else default
    except (TypeError, ValueError):
        return default


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _direction(score: Any) -> str:
    # Sanitize here, not at call sites: several callers pass raw .get() values,
    # and a missing score (None) must read as NEUTRAL, not raise. This was the
    # recurring "'>=' not supported between 'NoneType' and 'int'" compose error.
    x = _num(score, 50.0)
    return "BULLISH" if x >= 58 else "BEARISH" if x <= 42 else "NEUTRAL"


def _component(name: str, score: Any, weight: float, detail: str = "") -> dict[str, Any]:
    s = _clamp(_num(score))
    contribution = (s - 50.0) * weight
    return {"name": name, "score": round(s, 1), "weight": weight,
            "direction": _direction(s), "contribution": round(contribution, 1), "detail": detail}


def evaluate(snapshot: Mapping[str, Any] | None = None) -> dict[str, Any]:
    s = dict(snapshot or {})
    li = s.get("liquidity_intelligence") or {}
    race = li.get("race") or s.get("liquidity_race") or {}
    intent = li.get("institutional_intent") or s.get("institutional_intent") or {}
    sweep = li.get("sweep_detection") or {}
    auction = s.get("auction_intelligence") or s.get("auction") or {}
    flow = s.get("flow_intelligence_2") or s.get("flow_intelligence") or {}
    gamma = s.get("gamma_regime") or {}
    structure = s.get("structure") or {}

    race_leader = str(race.get("leader") or "BALANCED").upper()
    liquidity_score = 50 + (_num(race.get("edge_pct"), 0) / 2) * (1 if race_leader == "UPPER" else -1 if race_leader == "LOWER" else 0)
    intent_score = _num(intent.get("score"), 50)
    adaptive = s.get("adaptive_learning") or {}
    weights = adaptive.get("active_weights") or {}
    def w(name: str, default: float) -> float:
        return _clamp(_num(weights.get(name), default), 0.01, 0.40)
    components = [
        _component("Liquidity", liquidity_score, w("liquidity", .22), str(race.get("interpretation") or "")),
        _component("Order Flow", flow.get("flow_score") or flow.get("order_flow_score"), w("order_flow", .18)),
        _component("Delta", flow.get("delta_score") or flow.get("cumulative_delta_score"), w("delta", .14)),
        _component("Auction", auction.get("auction_score"), w("auction", .12)),
        _component("Structure", s.get("structure_score") or structure.get("score"), w("structure", .12)),
        _component("Momentum", s.get("momentum_score"), w("momentum", .10)),
        _component("Gamma", s.get("dealer_score") or gamma.get("score"), w("gamma", .07)),
        _component("VWAP", s.get("vwap_score"), w("vwap", .05)),
    ]
    weighted = 50 + sum(c["contribution"] for c in components)
    weighted = _clamp(weighted)
    thesis_direction = _direction(weighted)

    active = [c for c in components if c["direction"] != "NEUTRAL"]
    bulls = [c for c in active if c["direction"] == "BULLISH"]
    bears = [c for c in active if c["direction"] == "BEARISH"]
    contradictions: list[str] = []
    if bulls and bears:
        contradictions.append(f"Bullish {', '.join(c['name'] for c in bulls[:3])} conflicts with bearish {', '.join(c['name'] for c in bears[:3])}.")
    if _direction(intent_score) != "NEUTRAL" and _direction(intent_score) != thesis_direction and thesis_direction != "NEUTRAL":
        contradictions.append(f"Institutional intent is {_direction(intent_score).lower()} while the composite thesis is {thesis_direction.lower()}.")
    sweep_state = str(sweep.get("state") or "NO_ACTIVE_SWEEP")
    if "FAILED" in sweep_state and (("BUY_SIDE" in sweep_state and thesis_direction == "BULLISH") or ("SELL_SIDE" in sweep_state and thesis_direction == "BEARISH")):
        contradictions.append("The active failed sweep opposes continuation in the thesis direction.")

    conflict_score = min(100.0, len(contradictions) * 28.0 + (25.0 if bulls and bears else 0.0))
    alignment = "STRONG_ALIGNMENT" if conflict_score < 20 and abs(weighted-50) >= 15 else "MODERATE_ALIGNMENT" if conflict_score < 45 else "HIGH_CONFLICT" if conflict_score < 75 else "NO_TRADE"
    readiness = _clamp(abs(weighted-50)*2.0 + 45.0 - conflict_score*.55)
    if thesis_direction == "NEUTRAL": readiness = min(readiness, 45.0)

    target = race.get("upper") if thesis_direction == "BULLISH" else race.get("lower") if thesis_direction == "BEARISH" else {}
    target_level = (target or {}).get("level")
    intent_label = str(intent.get("state") or "NEUTRAL").replace("_", " ").lower()
    sweep_phrase = ""
    if sweep_state != "NO_ACTIVE_SWEEP": sweep_phrase = f" A {sweep_state.replace('_',' ').lower()} is active."
    target_phrase = f" The next liquidity objective is {target_level}." if target_level else " No reliable liquidity objective is confirmed."
    market_story = (f"APEX reads a {thesis_direction.lower()} institutional thesis with {alignment.replace('_',' ').lower()}. "
                    f"The evidence is most consistent with {intent_label}.{sweep_phrase}{target_phrase}")

    checklist = {
        "trend_aligned": _direction(s.get("structure_score") or structure.get("score")) in (thesis_direction, "NEUTRAL"),
        "liquidity_target_identified": bool(target_level),
        "institutional_intent_confirmed": str(intent.get("state") or "NEUTRAL") != "NEUTRAL",
        "sweep_context_known": bool(sweep_state),
        "delta_supportive": _direction(flow.get("delta_score") or flow.get("cumulative_delta_score")) in (thesis_direction, "NEUTRAL"),
        "auction_supportive": _direction(auction.get("auction_score")) in (thesis_direction, "NEUTRAL"),
        "conflict_acceptable": alignment not in ("HIGH_CONFLICT", "NO_TRADE"),
    }
    passed = sum(bool(v) for v in checklist.values())
    readiness = round((readiness + passed/len(checklist)*100)/2, 1)

    return {
        "ok": True, "status": "READY", "market_story": market_story,
        "thesis": {"direction": thesis_direction, "score": round(weighted,1), "target_level": target_level,
                   "alignment": alignment, "readiness_score": readiness},
        "confidence_breakdown": components,
        "contradiction_engine": {"classification": alignment, "conflict_score": round(conflict_score,1), "items": contradictions},
        "institutional_checklist": {"items": checklist, "passed": passed, "total": len(checklist), "readiness_score": readiness},
        "trade_director_context": {"eligible": readiness >= 65 and alignment not in ("HIGH_CONFLICT","NO_TRADE"),
                                   "direction": thesis_direction, "target_level": target_level,
                                   "reason": market_story, "advisory_only": True},
        "adaptive_weights_applied": bool(adaptive.get("applied_to_live_scoring")),
        "schema_version": SCHEMA_VERSION, "engine_version": VERSION, "advisory_only": True,
    }


def _connect(path: str | Path = DEFAULT_DB) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.execute("""CREATE TABLE IF NOT EXISTS narrative_timeline (
      id INTEGER PRIMARY KEY AUTOINCREMENT, observed_at TEXT NOT NULL, ticker TEXT NOT NULL,
      event_type TEXT NOT NULL, direction TEXT, confidence REAL, narrative TEXT NOT NULL,
      payload_json TEXT NOT NULL)""")
    return conn


def record_timeline(event: Mapping[str, Any], path: str | Path = DEFAULT_DB) -> int:
    e = dict(event)
    with _connect(path) as conn:
        cur = conn.execute("INSERT INTO narrative_timeline (observed_at,ticker,event_type,direction,confidence,narrative,payload_json) VALUES (?,?,?,?,?,?,?)",
            (str(e.get("observed_at") or datetime.now(timezone.utc).isoformat()), str(e.get("ticker") or "SPX"),
             str(e.get("event_type") or "SCAN"), str(e.get("direction") or "NEUTRAL"), _num(e.get("confidence"),0),
             str(e.get("narrative") or ""), json.dumps(e, default=str)))
        return int(cur.lastrowid)


def timeline_summary(path: str | Path = DEFAULT_DB, limit: int = 50) -> dict[str, Any]:
    if not Path(path).exists(): return {"events": 0, "timeline": []}
    with _connect(path) as conn:
        rows = conn.execute("SELECT observed_at,ticker,event_type,direction,confidence,narrative FROM narrative_timeline ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        count = conn.execute("SELECT COUNT(*) FROM narrative_timeline").fetchone()[0]
    return {"events": count, "timeline": [{"observed_at":r[0],"ticker":r[1],"event_type":r[2],"direction":r[3],"confidence":r[4],"narrative":r[5]} for r in rows]}
