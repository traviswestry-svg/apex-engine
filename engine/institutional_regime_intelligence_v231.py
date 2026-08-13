"""APEX 23.1 Institutional Regime Intelligence.

Read-only regime classification and transition guidance. It consumes the
point-in-time market payload and the APEX 23.0 Trading Brain, then publishes a
stable regime object without changing execution permissions or production
weights.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple
import math

from .institutional_trading_brain_v230 import build_institutional_trading_brain

VERSION = "16.1.0_INSTITUTIONAL_REGIME_INTELLIGENCE"
SEMANTIC_VERSION = "16.1.0"
SCHEMA_VERSION = "apex.institutional_regime_intelligence.v1"


def _f(value: Any, default: float = 0.0) -> float:
    try:
        n = float(value)
        return default if math.isnan(n) or math.isinf(n) else n
    except Exception:
        return default


def _clip(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return round(max(lo, min(hi, value)), 1)


def _txt(value: Any, default: str = "UNKNOWN") -> str:
    text = str(value or "").strip().upper()
    return text or default


def _nested(payload: Mapping[str, Any], *paths: str) -> Any:
    for path in paths:
        node: Any = payload
        ok = True
        for part in path.split("."):
            if not isinstance(node, Mapping) or part not in node:
                ok = False
                break
            node = node[part]
        if ok and node not in (None, ""):
            return node
    return None


def _history_rows(history: Any) -> List[Mapping[str, Any]]:
    if isinstance(history, list):
        return [x for x in history if isinstance(x, Mapping)]
    if isinstance(history, Mapping):
        for key in ("items", "rows", "history", "snapshots", "results"):
            value = history.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, Mapping)]
    return []


def _feature_snapshot(last: Mapping[str, Any], brain: Mapping[str, Any]) -> Dict[str, Any]:
    atr_pct = _f(_nested(last, "atr_percent", "atr_pct", "market_state.atr_pct", "structure.atr_pct"))
    realized_vol = _f(_nested(last, "realized_volatility", "market_state.realized_volatility", "volatility.realized"))
    vix = _f(_nested(last, "vix", "market_state.vix", "indices.vix"))
    trend_prob = _f(_nested(last, "trend_day_probability", "probabilities.trend_day", "institutional_probability.trend_day"))
    range_prob = _f(_nested(last, "range_day_probability", "probabilities.range_day", "institutional_probability.range_day"))
    breadth = _f(_nested(last, "breadth", "market_state.breadth", "internals.breadth"))
    value_migration = _txt(_nested(last, "value_migration", "market_structure.value_migration", "auction.value_migration"))
    poc_migration = _txt(_nested(last, "poc_migration", "market_structure.poc_migration", "auction.poc_migration"))
    opening_type = _txt(_nested(last, "opening_type", "market_structure.opening_type", "auction.opening_type"))
    dealer = _txt(_nested(last, "dealer_regime", "dealer.regime", "dealer_positioning.regime"))
    flow = _txt(_nested(last, "flow_bias", "flow.bias", "options_flow.bias"))
    brain_regime = _txt(brain.get("regime"), "UNKNOWN")
    brain_bias = _txt(brain.get("bias"), "NEUTRAL")
    confidence = _f(brain.get("calibrated_confidence") or brain.get("base_confidence"))
    conflict_count = len(brain.get("conflicting_evidence") or [])
    return {
        "atr_pct": atr_pct, "realized_volatility": realized_vol, "vix": vix,
        "trend_probability": trend_prob, "range_probability": range_prob,
        "breadth": breadth, "value_migration": value_migration,
        "poc_migration": poc_migration, "opening_type": opening_type,
        "dealer_regime": dealer, "flow_bias": flow, "brain_regime": brain_regime,
        "brain_bias": brain_bias, "brain_confidence": confidence,
        "conflict_count": conflict_count,
    }


def _scores(features: Mapping[str, Any]) -> Dict[str, float]:
    scores = {"TREND_EXPANSION": 0.0, "BALANCED_ROTATION": 0.0, "MEAN_REVERSION": 0.0,
              "VOLATILITY_EXPANSION": 0.0, "COMPRESSION": 0.0, "TRANSITION": 0.0}
    trend = _f(features.get("trend_probability")); rng = _f(features.get("range_probability"))
    vix = _f(features.get("vix")); atr = _f(features.get("atr_pct")); rv = _f(features.get("realized_volatility"))
    confidence = _f(features.get("brain_confidence")); conflicts = int(features.get("conflict_count") or 0)
    brain_regime = _txt(features.get("brain_regime")); opening = _txt(features.get("opening_type"))
    value = _txt(features.get("value_migration")); poc = _txt(features.get("poc_migration")); dealer = _txt(features.get("dealer_regime"))

    scores["TREND_EXPANSION"] += trend * 0.55 + max(0.0, confidence - 50.0) * 0.25
    scores["BALANCED_ROTATION"] += rng * 0.60
    scores["MEAN_REVERSION"] += rng * 0.40
    if brain_regime in ("EXPANSION", "TREND", "TRENDING"): scores["TREND_EXPANSION"] += 25
    if brain_regime in ("MEAN_REVERSION", "BALANCE", "BALANCED"): scores["MEAN_REVERSION"] += 20; scores["BALANCED_ROTATION"] += 15
    if any(x in opening for x in ("DRIVE", "REJECTION_REVERSE", "OPEN_AUCTION_OUTSIDE")): scores["TREND_EXPANSION"] += 14
    if "OPEN_AUCTION_IN_RANGE" in opening or "ROTATION" in opening: scores["BALANCED_ROTATION"] += 16
    if value in ("RISING", "FALLING") and poc in ("RISING", "FALLING") and value == poc: scores["TREND_EXPANSION"] += 18
    if value in ("OVERLAPPING", "UNCHANGED", "FLAT") or poc in ("UNCHANGED", "FLAT"): scores["BALANCED_ROTATION"] += 14; scores["COMPRESSION"] += 8
    if dealer in ("LONG_GAMMA", "POSITIVE_GAMMA"): scores["MEAN_REVERSION"] += 18; scores["BALANCED_ROTATION"] += 10
    if dealer in ("SHORT_GAMMA", "NEGATIVE_GAMMA"): scores["VOLATILITY_EXPANSION"] += 22; scores["TREND_EXPANSION"] += 8
    if vix >= 25 or rv >= 30 or atr >= 1.2: scores["VOLATILITY_EXPANSION"] += 32
    elif vix and vix <= 15 and atr and atr <= 0.55: scores["COMPRESSION"] += 26
    if conflicts >= 2: scores["TRANSITION"] += 18 + min(18, conflicts * 3)
    if abs(trend - rng) <= 10 and max(trend, rng) > 0: scores["TRANSITION"] += 20
    if confidence < 55: scores["TRANSITION"] += 12
    return {k: round(v, 2) for k, v in scores.items()}


def _transition(history: Any, current: str, confidence: float) -> Dict[str, Any]:
    rows = _history_rows(history)[-12:]
    prior = []
    for row in rows:
        value = _nested(row, "regime", "regime_intelligence.primary_regime", "institutional_regime.primary_regime")
        if value:
            prior.append(_txt(value))
    previous = prior[-1] if prior else "UNKNOWN"
    changed = previous not in ("UNKNOWN", current)
    persistence = 1
    for item in reversed(prior):
        if item == current: persistence += 1
        else: break
    state = "CONFIRMED" if persistence >= 3 and confidence >= 65 else "EMERGING" if changed else "STABLE" if persistence >= 2 else "UNCONFIRMED"
    return {"state": state, "previous_regime": previous, "current_regime": current,
            "changed": changed, "persistence_observations": persistence,
            "confirmation_required": state in ("EMERGING", "UNCONFIRMED")}


def _weight_guidance(regime: str) -> Dict[str, Dict[str, Any]]:
    maps = {
        "TREND_EXPANSION": {"market_structure": 1.20, "flow": 1.15, "dealer": 1.05, "probability": 1.10, "mean_reversion": 0.70},
        "BALANCED_ROTATION": {"market_structure": 1.10, "dealer": 1.15, "probability": 1.05, "flow": 0.85, "mean_reversion": 1.20},
        "MEAN_REVERSION": {"dealer": 1.20, "market_structure": 1.10, "probability": 1.10, "flow": 0.80, "mean_reversion": 1.25},
        "VOLATILITY_EXPANSION": {"dealer": 1.15, "flow": 1.15, "market_structure": 1.10, "probability": 1.00, "mean_reversion": 0.65},
        "COMPRESSION": {"dealer": 1.10, "market_structure": 1.05, "probability": 1.10, "flow": 0.75, "mean_reversion": 1.10},
        "TRANSITION": {"market_structure": 1.05, "dealer": 1.00, "flow": 0.85, "probability": 0.95, "mean_reversion": 0.90},
    }
    return {k: {"multiplier": v, "mode": "ADVISORY_ONLY"} for k, v in maps.get(regime, maps["TRANSITION"]).items()}


def build_regime_intelligence(last: Dict[str, Any], history: Any = None, *, before: Optional[str] = None) -> Dict[str, Any]:
    last = last if isinstance(last, dict) else {}
    brain = build_institutional_trading_brain(last, history, before=before)
    features = _feature_snapshot(last, brain)
    scores = _scores(features)
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    primary, top = ranked[0]
    secondary, second = ranked[1]
    separation = max(0.0, top - second)
    evidence_coverage = sum(1 for v in features.values() if v not in (0, 0.0, "UNKNOWN", None)) / max(1, len(features)) * 100
    confidence = _clip(35 + min(35, separation * 1.4) + evidence_coverage * 0.25)
    if primary == "TRANSITION": confidence = min(confidence, 68.0)
    transition = _transition(history, primary, confidence)
    risk_mode = "DEFENSIVE" if primary in ("TRANSITION", "VOLATILITY_EXPANSION") or transition["confirmation_required"] else "NORMAL"
    eligible = bool(brain.get("execution_readiness", {}).get("eligible")) and confidence >= 65 and not transition["confirmation_required"]
    return {
        "ok": True, "version": VERSION, "semantic_version": SEMANTIC_VERSION, "schema_version": SCHEMA_VERSION,
        "evaluated_at": datetime.now(timezone.utc).isoformat(), "ticker": last.get("ticker", "SPX"),
        "primary_regime": primary, "secondary_regime": secondary, "confidence": confidence,
        "scores": scores, "features": features, "transition": transition,
        "risk_posture": {"mode": risk_mode, "size_guidance": "REDUCED" if risk_mode == "DEFENSIVE" else "STANDARD",
                         "execution_eligible": eligible, "reason": "Regime transition must confirm before normal execution." if transition["confirmation_required"] else "Regime is sufficiently stable for existing execution governance."},
        "engine_weight_guidance": _weight_guidance(primary),
        "playbook_guidance": {
            "preferred": {"TREND_EXPANSION": ["PULLBACK_CONTINUATION", "BREAKOUT_RETEST"], "BALANCED_ROTATION": ["VALUE_EDGE_FADE", "IRON_CONDOR"],
                          "MEAN_REVERSION": ["FAILED_BREAK_FADE", "DEFINED_RISK_CREDIT_SPREAD"], "VOLATILITY_EXPANSION": ["CONFIRMED_MOMENTUM_SPREAD", "REDUCED_SIZE"],
                          "COMPRESSION": ["WAIT_FOR_EXPANSION", "TIGHT_DEFINED_RISK"], "TRANSITION": ["STAND_DOWN", "WAIT_FOR_CONFIRMATION"]}[primary],
            "avoid": ["FULL_SIZE_UNCONFIRMED_ENTRY"] if transition["confirmation_required"] else [],
        },
        "explainability": {
            "summary": f"{primary.replace('_', ' ').title()} leads {secondary.replace('_', ' ').lower()} by {round(separation,1)} score points.",
            "limitations": ["Classification quality depends on available point-in-time inputs.", "Weight guidance is advisory and never mutates production configuration."],
        },
        "trading_brain_context": {"headline": brain.get("headline"), "bias": brain.get("bias"), "confidence": brain.get("calibrated_confidence"), "execution_readiness": brain.get("execution_readiness")},
        "guardrails": {"read_only": True, "broker_mutation": False, "automatic_weight_mutation": False,
                       "human_confirmation_required": True, "existing_kill_switch_authoritative": True,
                       "look_ahead_protected": bool(before)},
    }
