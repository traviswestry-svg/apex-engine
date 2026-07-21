"""APEX 26.2 — Contract Intelligence Engine (advisory, deterministic).

Recommends the option structure (ITM / ATM / OTM / debit spread / credit spread /
butterfly / broken-wing / calendar / diagonal / iron condor) that best fits the
governed decision, given expected move, greeks, liquidity, bid/ask, risk, holding
time, and volatility. Explainable and order-free; ``production_effect`` NONE.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Optional

from . import liquidity_slippage_v263 as liquidity

VERSION = "26.2.0_CONTRACT_INTELLIGENCE"
SCHEMA_VERSION = "apex.contract_intelligence.v262.v1"

STRUCTURES = ("ITM", "ATM", "OTM", "DEBIT_SPREAD", "CREDIT_SPREAD", "BUTTERFLY",
              "BROKEN_WING", "CALENDAR", "DIAGONAL", "IRON_CONDOR")


def _number(value: Any, default: float = 0.0) -> float:
    try:
        n = float(value)
        return n if math.isfinite(n) else default
    except (TypeError, ValueError):
        return default


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _round(v: Any, p: int = 3) -> Optional[float]:
    return None if v is None else round(float(v), p)


def recommend(root: Optional[Mapping[str, Any]], *, contracts: int = 1) -> dict[str, Any]:
    root = root if isinstance(root, Mapping) else {}
    forecast = _mapping(root.get("forecast"))
    greeks = _mapping(root.get("greeks"))
    vol = _mapping(root.get("volatility") or root.get("vol"))
    liq = liquidity.analyze(root, contracts=contracts)

    direction = _text(_mapping(root.get("market_state")).get("bias") or root.get("direction")).upper()
    directional = direction in {"BULLISH", "BEARISH"}
    expected_move = _number(forecast.get("expected_move_points"))
    hold_seconds = _number(forecast.get("expected_hold_seconds"), 900)
    gamma = _number(greeks.get("gamma"))
    theta = _number(greeks.get("theta"))
    vix = _number(vol.get("vix") or vol.get("value"), 16.0)
    liquidity_tier = _text(liq.get("liquidity_quality"))

    reasons: list[str] = []

    # Non-directional / high-vol-crush contexts favor defined-risk neutral structures.
    if not directional:
        if vix >= 22:
            structure = "IRON_CONDOR"
            reasons.append("No directional thesis and elevated IV: premium-selling iron condor.")
        else:
            structure = "BUTTERFLY"
            reasons.append("No directional thesis, contained IV: cheap butterfly around value.")
    else:
        # Directional: size the aggressiveness by expected move, hold time, IV.
        if liquidity_tier in {"LOW", "ILLIQUID"}:
            structure = "DEBIT_SPREAD"
            reasons.append("Thin liquidity: defined-risk debit spread to limit slippage exposure.")
        elif expected_move >= 15 and hold_seconds <= 1800 and vix < 20:
            structure = "ATM"
            reasons.append("Large expected move, short hold, moderate IV: ATM single-leg for gamma.")
        elif expected_move >= 10 and vix < 25:
            structure = "OTM"
            reasons.append("Solid expected move: slightly OTM for convexity.")
        elif hold_seconds > 3600 and theta < 0:
            structure = "DIAGONAL"
            reasons.append("Longer hold with theta drag: diagonal to offset decay.")
        elif vix >= 25:
            structure = "DEBIT_SPREAD"
            reasons.append("High IV: debit spread caps vega and cost.")
        else:
            structure = "ITM"
            reasons.append("Moderate move, favor delta over gamma: ITM for higher probability.")

    # Greeks/holding guidance.
    guidance = {
        "prefer_gamma": bool(expected_move >= 15 and hold_seconds <= 1800),
        "theta_sensitive": bool(hold_seconds > 1800),
        "iv_regime": "HIGH" if vix >= 22 else "MODERATE" if vix >= 16 else "LOW",
    }

    return {
        "ok": True,
        "version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "recommended_structure": structure,
        "direction": direction,
        "rationale": reasons,
        "inputs": {
            "expected_move_points": _round(expected_move),
            "expected_hold_seconds": hold_seconds,
            "gamma": gamma, "theta": theta, "vix": vix,
            "liquidity_quality": liquidity_tier,
            "spread_pct": liq.get("spread_pct"),
        },
        "greeks_guidance": guidance,
        "estimated_slippage": liq.get("estimated_slippage"),
        "fill_probability": liq.get("fill_probability"),
        "production_effect": "NONE",
    }


def status() -> dict[str, Any]:
    return {"status": "READY", "engine": "CONTRACT_INTELLIGENCE", "version": VERSION,
            "structures": list(STRUCTURES), "places_orders": False, "production_effect": "NONE"}
