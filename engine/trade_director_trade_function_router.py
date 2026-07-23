"""APEX Trade Director Phase 35 — multi-horizon trade-function router.

Uses one shared institutional evidence snapshot to rank multiple trading functions.
The router is advisory only: it does not place orders, mutate production weights, or
bypass confirmation/risk governance. Scores are transparent style-fit heuristics and
must be calibrated against Phase 31/32 outcomes before being treated as empirical edge.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Optional

FUNCTIONS = (
    "QUICK_SCALP",
    "SCALP_15M",
    "SCALP_30M",
    "INTRADAY",
    "SWING",
    "LEAP",
)

FUNCTION_META: Dict[str, Dict[str, Any]] = {
    "QUICK_SCALP": {
        "label": "Quick Scalp",
        "hold_window": "UNDER_5_MIN",
        "max_hold_minutes": 5,
        "entry_style": "Immediate rejection, reclaim, momentum burst, or liquidity response",
        "risk_posture": "TIGHT_STRUCTURAL",
    },
    "SCALP_15M": {
        "label": "15-Minute Scalp",
        "hold_window": "5_TO_15_MIN",
        "max_hold_minutes": 15,
        "entry_style": "Short auction rotation or confirmed breakout continuation",
        "risk_posture": "SHORT_HORIZON_STRUCTURAL",
    },
    "SCALP_30M": {
        "label": "30-Minute Scalp",
        "hold_window": "15_TO_30_MIN",
        "max_hold_minutes": 30,
        "entry_style": "Sustained flow with intraday structure and pullback confirmation",
        "risk_posture": "INTRADAY_STRUCTURAL",
    },
    "INTRADAY": {
        "label": "Intraday Trade",
        "hold_window": "30_MIN_TO_CLOSE",
        "max_hold_minutes": 360,
        "entry_style": "Session trend, range expansion, or value migration with confirmation",
        "risk_posture": "SESSION_STRUCTURAL",
    },
    "SWING": {
        "label": "Swing Trade",
        "hold_window": "2_TO_10_DAYS",
        "max_hold_minutes": None,
        "entry_style": "Higher-timeframe structure, catalyst, volatility, and daily confirmation",
        "risk_posture": "MULTI_DAY_DEFINED_RISK",
    },
    "LEAP": {
        "label": "LEAP",
        "hold_window": "MONTHS",
        "max_hold_minutes": None,
        "entry_style": "Long-duration thesis, macro/secular trend, valuation, and volatility fit",
        "risk_posture": "LONG_DURATION_DEFINED_RISK",
    },
}


def _norm(value: Any, default: str = "UNKNOWN") -> str:
    raw = str(value if value is not None else default).strip().upper().replace(" ", "_").replace("-", "_")
    aliases = {
        "POS": "POSITIVE", "NEG": "NEGATIVE", "BAL": "BALANCED",
        "UP": "BULLISH", "DOWN": "BEARISH", "NONE": "UNKNOWN",
        "HIGH_VOL": "EXPANDING", "LOW_VOL": "COMPRESSED",
        "TRENDING": "STRONG", "RANGE": "BALANCED",
    }
    return aliases.get(raw, raw or default)


def _num(value: Any, default: float = 50.0) -> float:
    try:
        return max(0.0, min(100.0, float(value)))
    except (TypeError, ValueError):
        return default


def _grade(score: float, coverage: float) -> str:
    if coverage < 45:
        return "INSUFFICIENT_DATA"
    if score >= 88:
        return "A+"
    if score >= 80:
        return "A"
    if score >= 72:
        return "B+"
    if score >= 64:
        return "B"
    if score >= 55:
        return "C"
    return "D"


def _score_style(style: str, e: Mapping[str, Any]) -> tuple[float, list[str], list[str]]:
    gamma = _norm(e.get("gamma_regime"))
    auction = _norm(e.get("auction_state"))
    flow = _norm(e.get("flow_state"))
    volatility = _norm(e.get("volatility_regime"))
    trend = _norm(e.get("trend_persistence"))
    liquidity = _norm(e.get("liquidity_state"), "NORMAL")
    event = _norm(e.get("event_risk"), "NORMAL")
    structure = _num(e.get("structure_score"))
    flow_score = _num(e.get("flow_score"))
    dealer_score = _num(e.get("dealer_score"))
    htf = _num(e.get("higher_timeframe_score"))
    fundamental = _num(e.get("fundamental_score"))

    score = 50.0
    why: list[str] = []
    blockers: list[str] = []

    if liquidity in {"POOR", "THIN", "UNAVAILABLE"}:
        score -= 22
        blockers.append("Liquidity is insufficient for reliable execution.")
    elif liquidity in {"HIGH", "DEEP", "NORMAL"}:
        score += 5

    if event in {"FOMC", "CPI", "NFP", "ELEVATED"}:
        if style in {"QUICK_SCALP", "SCALP_15M"}:
            score += 5
            why.append("Elevated event volatility can support short-duration opportunity after confirmation.")
        elif style in {"SWING", "LEAP"}:
            score -= 8
            blockers.append("Event risk reduces long-horizon entry quality until repricing stabilizes.")

    if style == "QUICK_SCALP":
        score += (structure - 50) * 0.22 + (flow_score - 50) * 0.18
        if volatility in {"EXPANDING", "ELEVATED"}: score += 13; why.append("Expanding volatility supports rapid price discovery.")
        if volatility in {"COMPRESSED", "LOW"}: score += 6; why.append("Compressed conditions can support quick range-edge mean reversion.")
        if gamma == "POSITIVE": score += 7; why.append("Positive gamma favors controlled mean reversion near defined levels.")
        if gamma == "NEGATIVE": score += 9; why.append("Negative gamma favors short momentum bursts with strict invalidation.")
        if auction in {"BALANCED", "ROTATION"}: score += 8; why.append("Balanced auction supports fast rotations at range extremes.")
        if auction in {"BREAKOUT", "VALUE_EXPANSION", "LEAVING_VALUE"}: score += 8; why.append("Auction expansion supports a short continuation scalp.")
    elif style == "SCALP_15M":
        score += (structure - 50) * 0.25 + (flow_score - 50) * 0.22 + (dealer_score - 50) * 0.10
        if volatility in {"EXPANDING", "ELEVATED"}: score += 10; why.append("Volatility supports a 5–15 minute directional window.")
        if trend in {"STRONG", "PERSISTENT"}: score += 9; why.append("Trend persistence supports continuation.")
        if auction in {"BREAKOUT", "VALUE_EXPANSION", "LEAVING_VALUE", "REJECTION"}: score += 8
        if flow in {"BULLISH", "BEARISH", "ACCELERATING"}: score += 7; why.append("Directional flow supports the selected side.")
    elif style == "SCALP_30M":
        score += (structure - 50) * 0.25 + (flow_score - 50) * 0.20 + (dealer_score - 50) * 0.16
        if trend in {"STRONG", "PERSISTENT"}: score += 12; why.append("Sustained trend improves 30-minute follow-through.")
        if auction in {"VALUE_EXPANSION", "LEAVING_VALUE", "ACCEPTING_HIGHER", "ACCEPTING_LOWER"}: score += 10; why.append("Value migration supports sustained structure.")
        if volatility in {"EXPANDING", "NORMAL"}: score += 6
        if auction in {"BALANCED", "ROTATION"} and trend not in {"STRONG", "PERSISTENT"}: score -= 8; blockers.append("Balanced auction without persistence weakens a 30-minute directional hold.")
    elif style == "INTRADAY":
        score += (structure - 50) * 0.20 + (flow_score - 50) * 0.16 + (dealer_score - 50) * 0.18 + (htf - 50) * 0.16
        if trend in {"STRONG", "PERSISTENT"}: score += 13; why.append("Session trend persistence supports an intraday hold.")
        if auction in {"VALUE_EXPANSION", "LEAVING_VALUE", "ACCEPTING_HIGHER", "ACCEPTING_LOWER"}: score += 11; why.append("Sustained value migration supports the session thesis.")
        if gamma == "NEGATIVE": score += 6; why.append("Negative gamma can amplify directional continuation.")
        if gamma == "POSITIVE" and auction in {"BALANCED", "ROTATION"}: score -= 9; blockers.append("Positive gamma and balance reduce session trend persistence.")
    elif style == "SWING":
        score += (htf - 50) * 0.32 + (fundamental - 50) * 0.16 + (dealer_score - 50) * 0.08
        if trend in {"STRONG", "PERSISTENT"}: score += 10; why.append("Higher-timeframe persistence supports a multi-day thesis.")
        if volatility in {"NORMAL", "COMPRESSED"}: score += 6; why.append("Controlled volatility supports defined-risk swing construction.")
        if not bool(e.get("daily_confirmation", False)): score -= 15; blockers.append("Daily timeframe confirmation is required for a swing entry.")
        if not bool(e.get("catalyst_context_available", False)): score -= 7; blockers.append("Catalyst context is incomplete.")
    elif style == "LEAP":
        score += (htf - 50) * 0.28 + (fundamental - 50) * 0.30
        if bool(e.get("secular_thesis_available", False)): score += 13; why.append("A documented secular thesis supports long-duration exposure.")
        else: score -= 18; blockers.append("A documented secular thesis is required for LEAP evaluation.")
        if bool(e.get("valuation_context_available", False)): score += 8
        else: score -= 10; blockers.append("Valuation context is unavailable.")
        if not bool(e.get("daily_confirmation", False)): score -= 8

    return round(max(0.0, min(100.0, score)), 1), why, blockers


def build_trade_function_router(evidence: Optional[Mapping[str, Any]] = None,
                                selected_function: Optional[str] = None) -> Dict[str, Any]:
    evidence = dict(evidence or {})
    evidence_fields = (
        "gamma_regime", "auction_state", "flow_state", "volatility_regime",
        "trend_persistence", "liquidity_state", "structure_score", "flow_score",
        "dealer_score", "higher_timeframe_score", "fundamental_score",
    )
    supplied = sum(1 for k in evidence_fields if evidence.get(k) not in (None, "", "UNKNOWN"))
    coverage = round(100.0 * supplied / len(evidence_fields), 1)
    rankings = []
    for function in FUNCTIONS:
        score, reasons, blockers = _score_style(function, evidence)
        grade = _grade(score, coverage)
        rankings.append({
            "function": function,
            **FUNCTION_META[function],
            "style_fit_score": score,
            "style_fit_grade": grade,
            "reasons": reasons[:4],
            "blockers": blockers[:4],
        })
    rankings.sort(key=lambda x: x["style_fit_score"], reverse=True)
    requested = _norm(selected_function) if selected_function else None
    selected = next((x for x in rankings if x["function"] == requested), rankings[0])
    return {
        "version": "PHASE_35",
        "advisory_only": True,
        "confirmation_gated": True,
        "empirical_status": "HEURISTIC_PRIOR_PENDING_CALIBRATION",
        "evidence_coverage_pct": coverage,
        "selected_function": selected,
        "best_fit_function": rankings[0],
        "rankings": rankings,
        "limitations": [
            "Style-fit scores are transparent priors, not validated probabilities.",
            "Phase 31/32 graded outcomes must calibrate thresholds by function.",
            "Missing evidence fails closed and cannot be labeled A+.",
        ],
    }
