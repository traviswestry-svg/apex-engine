"""APEX 19.0 Institutional Intelligence Engine.

Pure, deterministic synthesis over already-computed APEX state. It performs no
network calls and cannot submit or mutate broker orders.
"""
from __future__ import annotations
from datetime import datetime, timezone
import math
from typing import Any, Dict, Iterable, List, Tuple
from .institutional_market_structure_engine import build_institutional_market_structure

VERSION = "12.1.0_INSTITUTIONAL_MARKET_STRUCTURE_ENGINE"
SEMANTIC_VERSION = "12.1.0"


def _f(v: Any, d: float = 0.0) -> float:
    try:
        n = float(v)
        return d if math.isnan(n) or math.isinf(n) else n
    except Exception:
        return d


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _direction(value: Any) -> str:
    s = str(value or "").upper()
    if any(k in s for k in ("BULL", "CALL", "UP", "RISING", "BUY")): return "BULLISH"
    if any(k in s for k in ("BEAR", "PUT", "DOWN", "FALLING", "SELL")): return "BEARISH"
    return "NEUTRAL"


def _profile_rows(profile: Any) -> List[Dict[str, Any]]:
    if isinstance(profile, dict):
        rows = profile.get("profile") or profile.get("rows") or profile.get("levels") or []
    else:
        rows = profile or []
    return [r for r in rows if isinstance(r, dict)]


def build_volume_transition_intelligence(profile: Any, price: float = 0.0) -> Dict[str, Any]:
    rows = _profile_rows(profile)
    parsed: List[Tuple[float, float]] = []
    for row in rows:
        level = _f(row.get("price") or row.get("level") or row.get("strike"))
        volume = _f(row.get("volume") or row.get("total_volume") or row.get("activity") or row.get("value"))
        if level and volume >= 0: parsed.append((level, volume))
    parsed.sort()
    if len(parsed) < 3:
        return {"available": False, "state": "INSUFFICIENT_DATA", "levels": [], "signal": "NEUTRAL", "confidence": 0.0}
    max_v = max(v for _, v in parsed) or 1.0
    active_floor = max_v * 0.18
    levels = []
    for idx, (level, volume) in enumerate(parsed):
        prev_v = parsed[idx-1][1] if idx else volume
        next_v = parsed[idx+1][1] if idx + 1 < len(parsed) else volume
        expanding = volume >= active_floor and volume >= prev_v * 1.12
        stalled = volume < active_floor or (volume <= prev_v * 0.70 and next_v <= volume * 1.10)
        status = "ACTIVE" if expanding else "STALLED" if stalled else "BALANCED"
        levels.append({"price": round(level, 2), "volume": round(volume, 2), "status": status,
                       "display_color": "GREEN" if status == "ACTIVE" else "RED" if status == "STALLED" else "NEUTRAL"})
    below = [x for x in levels if x["price"] <= price] if price else levels[:len(levels)//2]
    above = [x for x in levels if x["price"] > price] if price else levels[len(levels)//2:]
    below_active = sum(1 for x in below[-5:] if x["status"] == "ACTIVE")
    above_active = sum(1 for x in above[:5] if x["status"] == "ACTIVE")
    below_stalled = sum(1 for x in below[-5:] if x["status"] == "STALLED")
    above_stalled = sum(1 for x in above[:5] if x["status"] == "STALLED")
    bull = below_stalled + above_active
    bear = above_stalled + below_active
    signal = "BULLISH" if bull >= bear + 2 else "BEARISH" if bear >= bull + 2 else "NEUTRAL"
    confidence = _clamp(45 + abs(bull-bear)*9)
    return {"available": True, "state": "ACTIVE", "signal": signal, "confidence": round(confidence, 1),
            "active_above": above_active, "active_below": below_active, "stalled_above": above_stalled,
            "stalled_below": below_stalled, "levels": levels}


def build_expected_move_intelligence(last: Dict[str, Any]) -> Dict[str, Any]:
    ms = last.get("market_state") or {}
    oc = last.get("options_chain") or last.get("options_chain_intelligence") or {}
    price = _f(ms.get("price") or last.get("price") or oc.get("spot"))
    move = _f(oc.get("expected_move") or oc.get("expected_move_points") or last.get("expected_move"))
    if not move:
        pct = _f(oc.get("expected_move_pct") or last.get("expected_move_pct"))
        move = price * pct / 100.0 if price and pct else 0.0
    if not price or not move:
        return {"available": False, "state": "UNAVAILABLE", "price": price, "expected_move_points": move}
    upper, lower = price + move, price - move
    session_high = _f(ms.get("session_high") or ms.get("high"))
    session_low = _f(ms.get("session_low") or ms.get("low"))
    consumed_up = ((session_high-price)/move*100) if session_high else 0.0
    consumed_down = ((price-session_low)/move*100) if session_low else 0.0
    return {"available": True, "state": "READY", "price": round(price,2), "expected_move_points": round(move,2),
            "upper": round(upper,2), "lower": round(lower,2), "consumed_up_pct": round(_clamp(consumed_up),1),
            "consumed_down_pct": round(_clamp(consumed_down),1)}


def build_overnight_structure(last: Dict[str, Any]) -> Dict[str, Any]:
    ms = last.get("market_state") or {}; ov = last.get("overnight") or last.get("overnight_intelligence") or {}
    price = _f(ms.get("price") or last.get("price")); onh = _f(ov.get("overnight_high") or ms.get("overnight_high")); onl = _f(ov.get("overnight_low") or ms.get("overnight_low"))
    pdh = _f(ms.get("previous_day_high") or ms.get("pdh")); pdl = _f(ms.get("previous_day_low") or ms.get("pdl"))
    if not price or not (onh and onl): return {"available": False, "state": "UNAVAILABLE", "price": price}
    location = "ABOVE_ONH" if price > onh else "BELOW_ONL" if price < onl else "INSIDE_OVERNIGHT_RANGE"
    direction = "BULLISH" if location == "ABOVE_ONH" else "BEARISH" if location == "BELOW_ONL" else "NEUTRAL"
    return {"available": True, "state": "READY", "price": round(price,2), "overnight_high": round(onh,2), "overnight_low": round(onl,2),
            "previous_day_high": round(pdh,2) if pdh else None, "previous_day_low": round(pdl,2) if pdl else None,
            "location": location, "signal": direction, "range_points": round(onh-onl,2)}


def build_institutional_intelligence_v19(last: Dict[str, Any]) -> Dict[str, Any]:
    last = last if isinstance(last, dict) else {}
    ms = last.get("market_state") or {}; price = _f(ms.get("price") or last.get("price"))
    profile = last.get("volume_profile") or last.get("profile") or {}
    volume = build_volume_transition_intelligence(profile, price)
    expected = build_expected_move_intelligence(last)
    overnight = build_overnight_structure(last)
    auction = last.get("auction_intelligence") or last.get("auction") or {}
    dealer = last.get("dealer_positioning") or {}; flow = last.get("flow_intelligence_2") or last.get("flow_intelligence") or {}
    volatility = last.get("volatility") or {}; legacy = last.get("institutional_intelligence") or {}
    signals = [
        ("volume_transition", volume.get("signal"), _f(volume.get("confidence")), 0.20),
        ("auction", _direction((auction.get("auction_state") or {}).get("state") if isinstance(auction.get("auction_state"), dict) else auction.get("state") or ms.get("poc_migration")), _f((auction.get("auction_state") or {}).get("confidence") if isinstance(auction.get("auction_state"), dict) else auction.get("confidence"), 55) if (auction or ms.get("poc_migration")) else 0, 0.18),
        ("dealer", _direction(((dealer.get("delta") or {}).get("bias") if isinstance(dealer, dict) else None)), 65 if dealer else 0, 0.18),
        ("flow", _direction(flow.get("flow_bias") or flow.get("bias")), _f(flow.get("flow_conviction") or flow.get("score"), 55) if flow else 0, 0.18),
        ("overnight", overnight.get("signal"), 60 if overnight.get("available") else 0, 0.12),
        ("legacy_consensus", _direction(legacy.get("institutional_bias") or legacy.get("bias")), _f(legacy.get("confidence"), 55) if legacy else 0, 0.14),
    ]
    bull = bear = coverage = 0.0; evidence=[]
    for name, direction, confidence, weight in signals:
        if confidence <= 0: continue
        coverage += weight
        contribution = weight * confidence
        if direction == "BULLISH": bull += contribution
        elif direction == "BEARISH": bear += contribution
        evidence.append({"source": name, "direction": direction, "confidence": round(confidence,1), "weight": weight})
    denom = max(1.0, (bull+bear)); net = (bull-bear)/max(1.0, coverage)
    bias = "BULLISH" if net >= 12 else "BEARISH" if net <= -12 else "NEUTRAL"
    conviction = _clamp(50 + abs(net)*0.65)
    quality_flags=[]
    if coverage < 0.55: quality_flags.append("LOW_INPUT_COVERAGE")
    stale = bool(ms.get("data_fresh") is False or last.get("data_fresh") is False)
    if stale: quality_flags.append("STALE_DATA")
    execution_eligible = not stale and coverage >= 0.55 and bias != "NEUTRAL" and conviction >= 62
    if not execution_eligible: quality_flags.append("INTELLIGENCE_NOT_EXECUTION_ELIGIBLE")
    market_structure = build_institutional_market_structure(last)
    ms_direction = market_structure.get("direction", "NEUTRAL")
    if ms_direction in {"BULLISH", "BEARISH"}:
        evidence.append({"source": "market_structure", "direction": ms_direction, "confidence": 70.0, "weight": 0.16})
        if ms_direction == "BULLISH": bull += 11.2
        else: bear += 11.2
        coverage = min(1.0, coverage + 0.16)
        net = (bull-bear)/max(1.0, coverage)
        bias = "BULLISH" if net >= 12 else "BEARISH" if net <= -12 else "NEUTRAL"
        conviction = _clamp(50 + abs(net)*0.65)
    scenario = "TREND_CONTINUATION" if market_structure.get("day_type_probability",{}).get("classification") == "TREND_FAVORED" and bias != "NEUTRAL" else "ROTATION_OR_BALANCE" if bias == "NEUTRAL" else "DIRECTIONAL_OPPORTUNITY"
    return {"ok": True, "version": VERSION, "semantic_version": SEMANTIC_VERSION, "evaluated_at": datetime.now(timezone.utc).isoformat(),
            "ticker": str(last.get("ticker") or "SPX"), "price": round(price,2) if price else None, "bias": bias,
            "conviction": round(conviction,1), "coverage_pct": round(coverage*100,1), "scenario": scenario,
            "execution_eligible": execution_eligible, "quality_flags": quality_flags, "evidence": evidence,
            "volume_transition": volume, "expected_move": expected, "overnight_structure": overnight,
            "market_structure": market_structure,
            "guardrails": {"read_only": True, "broker_mutation": False, "automatic_execution": False,
                           "note": "Intelligence output is advisory and remains subordinate to existing execution safety controls."}}
