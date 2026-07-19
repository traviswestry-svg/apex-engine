"""APEX 23.2 Institutional Forecast Engine.

Read-only, regime-aware scenario forecasting for SPX. Produces probability
mass, projected paths, uncertainty bands, target zones, timing windows, and
explicit invalidations without authorizing execution.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional
import math

from .institutional_trading_brain_v230 import build_institutional_trading_brain
from .institutional_regime_intelligence_v231 import build_regime_intelligence

VERSION = "16.2.0_INSTITUTIONAL_FORECAST_ENGINE"
SEMANTIC_VERSION = "16.2.0"
SCHEMA_VERSION = "apex.institutional_forecast_engine.v1"


def _f(value: Any, default: float = 0.0) -> float:
    try:
        n = float(value)
        return default if math.isnan(n) or math.isinf(n) else n
    except Exception:
        return default


def _nested(payload: Mapping[str, Any], *paths: str) -> Any:
    for path in paths:
        node: Any = payload
        valid = True
        for part in path.split("."):
            if not isinstance(node, Mapping) or part not in node:
                valid = False
                break
            node = node[part]
        if valid and node not in (None, ""):
            return node
    return None


def _clip(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return round(max(low, min(high, value)), 1)


def _normalize(values: Dict[str, float]) -> Dict[str, float]:
    clean = {k: max(0.0, float(v)) for k, v in values.items()}
    total = sum(clean.values()) or 1.0
    out = {k: round(v / total * 100.0, 1) for k, v in clean.items()}
    drift = round(100.0 - sum(out.values()), 1)
    if drift:
        leader = max(out, key=out.get)
        out[leader] = round(out[leader] + drift, 1)
    return out


def _price_context(last: Mapping[str, Any]) -> Dict[str, float]:
    spot = _f(_nested(last, "price", "spx", "last", "market_state.price", "underlying.price"))
    expected_move = _f(_nested(last, "expected_move", "expected_move.points", "options.expected_move", "market_state.expected_move"))
    atr = _f(_nested(last, "atr", "market_state.atr", "structure.atr"))
    if expected_move <= 0 and spot > 0:
        expected_move = max(atr, spot * 0.006)
    if atr <= 0:
        atr = expected_move * 0.55 if expected_move > 0 else max(1.0, spot * 0.003)
    return {"spot": round(spot, 2), "expected_move": round(expected_move, 2), "atr": round(atr, 2)}


def _scenario_probabilities(last: Mapping[str, Any], brain: Mapping[str, Any], regime: Mapping[str, Any]) -> Dict[str, float]:
    bias = str(brain.get("bias") or "NEUTRAL").upper()
    confidence = _f(brain.get("calibrated_confidence") or brain.get("base_confidence"), 50.0)
    primary = str(regime.get("primary_regime") or "TRANSITION").upper()
    trend = _f(_nested(last, "trend_day_probability", "probabilities.trend_day"), 50.0)
    rng = _f(_nested(last, "range_day_probability", "probabilities.range_day"), 50.0)
    bull = 30.0; bear = 30.0; balance = 40.0
    directional = max(0.0, confidence - 45.0) * 0.55
    if bias in ("BULLISH", "CALLS", "LONG", "UP"):
        bull += directional; bear -= directional * 0.35
    elif bias in ("BEARISH", "PUTS", "SHORT", "DOWN"):
        bear += directional; bull -= directional * 0.35
    else:
        balance += 8.0
    if primary in ("TREND_EXPANSION", "VOLATILITY_EXPANSION"):
        balance -= 10.0
        if bull >= bear: bull += trend * 0.12
        else: bear += trend * 0.12
    elif primary in ("BALANCED_ROTATION", "MEAN_REVERSION", "COMPRESSION"):
        balance += rng * 0.20
        bull -= 4.0; bear -= 4.0
    else:
        balance += 10.0
    conflicts = len(brain.get("conflicting_evidence") or [])
    balance += min(15.0, conflicts * 3.0)
    return _normalize({"BULL_PATH": bull, "BEAR_PATH": bear, "BALANCE_PATH": balance})


def _bands(spot: float, move: float, probs: Mapping[str, float], regime: str) -> Dict[str, Any]:
    expansion = 1.15 if regime in ("TREND_EXPANSION", "VOLATILITY_EXPANSION") else 0.85 if regime == "COMPRESSION" else 1.0
    one_sigma = move * expansion
    weighted_center = spot + one_sigma * ((probs["BULL_PATH"] - probs["BEAR_PATH"]) / 100.0) * 0.45
    return {
        "center": round(weighted_center, 2),
        "confidence_50": {"low": round(weighted_center - one_sigma * 0.45, 2), "high": round(weighted_center + one_sigma * 0.45, 2)},
        "confidence_70": {"low": round(weighted_center - one_sigma * 0.75, 2), "high": round(weighted_center + one_sigma * 0.75, 2)},
        "confidence_90": {"low": round(weighted_center - one_sigma * 1.25, 2), "high": round(weighted_center + one_sigma * 1.25, 2)},
        "method": "REGIME_SCALED_EXPECTED_MOVE",
    }


def _paths(spot: float, move: float, atr: float, probs: Mapping[str, float], regime: str, last: Mapping[str, Any]) -> List[Dict[str, Any]]:
    vah = _f(_nested(last, "vah", "volume_profile.vah", "market_structure.vah"))
    val = _f(_nested(last, "val", "volume_profile.val", "market_structure.val"))
    poc = _f(_nested(last, "poc", "volume_profile.poc", "market_structure.poc"))
    scale = 1.15 if regime in ("TREND_EXPANSION", "VOLATILITY_EXPANSION") else 0.75 if regime == "COMPRESSION" else 1.0
    dist = max(atr, move * 0.55) * scale
    def zone(a: float, b: float) -> Dict[str, float]:
        return {"low": round(min(a,b),2), "high": round(max(a,b),2)}
    return [
        {"scenario":"BULL_PATH","probability":probs["BULL_PATH"],"sequence":["HOLD_OR_RECLAIM_VALUE","ACCEPT_ABOVE_RESISTANCE","EXTEND_TOWARD_UPPER_EXPECTED_MOVE"],
         "target_1":zone(spot+dist*0.35, spot+dist*0.55),"target_2":zone(spot+dist*0.80, spot+dist*1.10),
         "invalidation":{"condition":"ACCEPTANCE_BELOW_SUPPORT","reference":round(val or poc or spot-dist*0.35,2)}},
        {"scenario":"BEAR_PATH","probability":probs["BEAR_PATH"],"sequence":["FAIL_OR_LOSE_VALUE","ACCEPT_BELOW_SUPPORT","EXTEND_TOWARD_LOWER_EXPECTED_MOVE"],
         "target_1":zone(spot-dist*0.55, spot-dist*0.35),"target_2":zone(spot-dist*1.10, spot-dist*0.80),
         "invalidation":{"condition":"ACCEPTANCE_ABOVE_RESISTANCE","reference":round(vah or poc or spot+dist*0.35,2)}},
        {"scenario":"BALANCE_PATH","probability":probs["BALANCE_PATH"],"sequence":["ROTATE_AROUND_FAIR_VALUE","REJECT_RANGE_EXTREMES","RETURN_TOWARD_POC"],
         "range":zone(val or spot-dist*0.45, vah or spot+dist*0.45),"magnet":round(poc or spot,2),
         "invalidation":{"condition":"SUSTAINED_ACCEPTANCE_OUTSIDE_BALANCE","reference":"VAH_OR_VAL"}},
    ]


def _timing(regime: str, confidence: float) -> Dict[str, Any]:
    if regime in ("TREND_EXPANSION", "VOLATILITY_EXPANSION"):
        windows = ["OPENING_30_MINUTES", "POST_INITIAL_BALANCE_BREAK", "POWER_HOUR_CONTINUATION"]
    elif regime in ("BALANCED_ROTATION", "MEAN_REVERSION"):
        windows = ["AFTER_OPENING_RANGE_FORMS", "VALUE_EDGE_TEST", "MIDDAY_ROTATION"]
    elif regime == "COMPRESSION":
        windows = ["WAIT_FOR_RANGE_EXPANSION", "POST_BREAK_RETEST"]
    else:
        windows = ["WAIT_FOR_REGIME_CONFIRMATION", "REASSESS_AFTER_NEXT_STRUCTURE_EVENT"]
    return {"windows": windows, "precision": "MODERATE" if confidence >= 65 else "LOW", "note":"Timing windows are conditional, not guaranteed timestamps."}


def build_institutional_forecast(last: Dict[str, Any], history: Any = None, *, before: Optional[str] = None) -> Dict[str, Any]:
    last = last if isinstance(last, dict) else {}
    brain = build_institutional_trading_brain(last, history, before=before)
    regime = build_regime_intelligence(last, history, before=before)
    prices = _price_context(last)
    probs = _scenario_probabilities(last, brain, regime)
    primary = max(probs, key=probs.get)
    confidence = _clip((probs[primary] * 0.55) + (_f(regime.get("confidence"),50) * 0.25) + (_f(brain.get("calibrated_confidence"),50) * 0.20))
    coverage = sum(1 for v in prices.values() if v > 0) / 3 * 100
    status = "ACTIVE" if prices["spot"] > 0 and confidence >= 55 else "LIMITED"
    return {
        "ok": True, "version": VERSION, "semantic_version": SEMANTIC_VERSION, "schema_version": SCHEMA_VERSION,
        "evaluated_at": datetime.now(timezone.utc).isoformat(), "ticker": last.get("ticker","SPX"), "status": status,
        "primary_scenario": primary, "forecast_confidence": confidence, "scenario_probabilities": probs,
        "price_context": prices, "uncertainty_bands": _bands(prices["spot"], prices["expected_move"], probs, str(regime.get("primary_regime"))),
        "projected_paths": _paths(prices["spot"], prices["expected_move"], prices["atr"], probs, str(regime.get("primary_regime")), last),
        "timing_guidance": _timing(str(regime.get("primary_regime")), confidence),
        "forecast_quality": {"state":status,"input_coverage":round(coverage,1),"regime_confidence":regime.get("confidence"),"brain_confidence":brain.get("calibrated_confidence"),"requires_live_price":prices["spot"]<=0},
        "explainability": {"summary":f"{primary.replace('_',' ').title()} is the highest-probability path at {probs[primary]}% under {regime.get('primary_regime')} conditions.",
                           "limitations":["Forecasts are conditional probability estimates, not price guarantees.","Target zones expand or contract with expected move, ATR, and regime.","Sparse or closed-market data reduces precision."]},
        "context": {"regime":regime.get("primary_regime"),"transition":regime.get("transition"),"trading_brain_bias":brain.get("bias"),"trading_brain_headline":brain.get("headline")},
        "guardrails": {"read_only":True,"broker_mutation":False,"automatic_execution":False,"human_confirmation_required":True,"existing_kill_switch_authoritative":True,"look_ahead_protected":bool(before)},
    }
