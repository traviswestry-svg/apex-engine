"""APEX 26.0 — Execution Intelligence Core (the Execution Director).

APEX already decides WHAT to trade (the 25.x line). 26.0 is the advisory brain
for HOW to execute it like an institutional desk: it assesses execution
readiness, selects an execution strategy, optimizes order quality, sizes the
position within the existing risk envelope, frames exits, and grades execution
quality after the fact.

Safety contract (non-negotiable)
--------------------------------
* This engine NEVER places, previews-and-confirms, or submits an order. It emits
  recommendations only. ``places_orders`` is ``False`` and ``production_effect``
  is ``NONE`` on every response.
* All real order flow stays behind the repository's existing confirmation-gated
  execution path (``engine/execution/trade_routes`` + ``trade_risk_guard`` +
  broker adapter). 26.0 hands a recommendation to that path; a human confirms.
* Position sizing ENFORCES the existing ``RiskLimits`` (max contracts, max risk
  per trade). It can only ever recommend a size at or below those limits.
* Deterministic: every number is a pure function of the supplied snapshot. No
  randomness.
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Any, Mapping, Optional

from . import institutional_decision_integrity_v250 as integrity

try:  # Reuse the existing risk envelope; degrade to conservative defaults if absent.
    from .execution.trade_risk_guard import RiskLimits  # type: ignore
    _RISK_LIMITS_AVAILABLE = True
except Exception:  # pragma: no cover - defensive import guard
    RiskLimits = None  # type: ignore
    _RISK_LIMITS_AVAILABLE = False

VERSION = "26.0.0_EXECUTION_INTELLIGENCE_CORE"
SCHEMA_VERSION = "apex.execution_core.v260.v1"

READINESS_STATES = ("READY", "NOT_READY", "BLOCKED")
ORDER_TYPES = ("MARKET", "LIMIT", "LIMIT_OFFSET", "STOP_LIMIT")
STRATEGIES = ("DIRECTIONAL_DEBIT", "DEBIT_SPREAD", "STAND_DOWN", "WAIT_FOR_PULLBACK")

# Conservative fallback limits if the risk guard module is unavailable.
_FALLBACK_LIMITS = {
    "max_contracts": 10, "max_risk_per_trade": 1000.0, "max_daily_loss": 2500.0,
    "max_spread_pct": 12.0, "require_confirmation": True,
}


# --------------------------------------------------------------------------- #
# Helpers.
# --------------------------------------------------------------------------- #
def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso_now() -> str:
    return _now().isoformat()


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


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _round(v: Any, p: int = 2) -> Optional[float]:
    return None if v is None else round(float(v), p)


def _limits() -> dict[str, Any]:
    if _RISK_LIMITS_AVAILABLE and RiskLimits is not None:
        try:
            rl = RiskLimits.from_env()
            return {
                "max_contracts": int(getattr(rl, "max_contracts", 10)),
                "max_risk_per_trade": float(getattr(rl, "max_risk_per_trade", 1000.0)),
                "max_daily_loss": float(getattr(rl, "max_daily_loss", 2500.0)),
                "max_spread_pct": float(getattr(rl, "max_spread_pct", 12.0)),
                "require_confirmation": bool(getattr(rl, "require_confirmation", True)),
                "source": "trade_risk_guard",
            }
        except Exception:
            pass
    return {**_FALLBACK_LIMITS, "source": "fallback_defaults"}


# --------------------------------------------------------------------------- #
# Quote / liquidity extraction.
# --------------------------------------------------------------------------- #
def _quote(root: Mapping[str, Any]) -> dict[str, Any]:
    q = _mapping(root.get("quote") or root.get("option_quote") or root.get("contract_quote"))
    bid = _number(q.get("bid"))
    ask = _number(q.get("ask"))
    mid = _number(q.get("mid"), (bid + ask) / 2 if (bid or ask) else 0.0)
    spread = ask - bid if (ask and bid) else _number(q.get("spread"))
    spread_pct = (spread / mid * 100) if mid > 0 else None
    return {
        "bid": bid, "ask": ask, "mid": _round(mid, 4),
        "spread": _round(spread, 4),
        "spread_pct": _round(spread_pct, 3) if spread_pct is not None else None,
        "volume": _number(q.get("volume")),
        "open_interest": _number(q.get("open_interest") or q.get("oi")),
        "quote_age_seconds": _number(q.get("age_seconds"), None) if q.get("age_seconds") is not None else None,
    }


# --------------------------------------------------------------------------- #
# 26.0-a Execution readiness.
# --------------------------------------------------------------------------- #
def assess_readiness(root: Mapping[str, Any], decision: Mapping[str, Any]) -> dict[str, Any]:
    decision_block = _mapping(decision.get("decision"))
    eligibility = _text(decision_block.get("execution_eligibility")).upper()
    limits = _limits()
    quote = _quote(root)
    blockers: list[str] = []
    warnings: list[str] = []

    if eligibility != "ELIGIBLE":
        # A non-eligible decision (WATCH / STAND_DOWN) is a legitimate "wait",
        # not a hard failure — it makes execution NOT_READY, not BLOCKED.
        warnings.append(f"Decision integrity eligibility is {eligibility or 'UNKNOWN'} (not ELIGIBLE).")
    if quote["spread_pct"] is not None and quote["spread_pct"] > limits["max_spread_pct"]:
        blockers.append(f"Spread {quote['spread_pct']}% exceeds max {limits['max_spread_pct']}%.")
    if quote["bid"] <= 0 or quote["ask"] <= 0:
        warnings.append("Incomplete quote (missing bid/ask); size and slippage are estimates.")
    if quote["quote_age_seconds"] is not None and quote["quote_age_seconds"] > 20:
        blockers.append(f"Quote age {quote['quote_age_seconds']}s is stale.")

    if blockers:
        state = "BLOCKED"
    elif warnings or eligibility != "ELIGIBLE":
        state = "NOT_READY"
    else:
        state = "READY"

    return {
        "state": state,
        "eligibility": eligibility,
        "blockers": blockers,
        "warnings": warnings,
        "requires_human_confirmation": True,   # READY never means auto-trade
        "confirmation_gated": bool(limits["require_confirmation"]),
        "quote": quote,
    }


# --------------------------------------------------------------------------- #
# 26.0-b Strategy selection.
# --------------------------------------------------------------------------- #
def select_strategy(root: Mapping[str, Any], decision: Mapping[str, Any]) -> dict[str, Any]:
    decision_block = _mapping(decision.get("decision"))
    direction = _text(decision_block.get("direction")).upper()
    eligibility = _text(decision_block.get("execution_eligibility")).upper()
    conf = _number(decision_block.get("integrity_adjusted_confidence"))
    forecast = _mapping(root.get("forecast"))
    expected_move = _number(forecast.get("expected_move_points"))

    if eligibility != "ELIGIBLE" or direction not in {"BULLISH", "BEARISH"}:
        strategy = "STAND_DOWN"
        moneyness = None
        rationale = "Not eligible or no directional thesis; stand down."
    elif conf >= 75 and expected_move >= 8:
        strategy = "DIRECTIONAL_DEBIT"
        moneyness = "ATM" if conf >= 82 else "ATM/ITM"
        rationale = "High-confidence directional read with room to target; single-leg debit."
    else:
        strategy = "DEBIT_SPREAD"
        moneyness = "OTM_DEBIT_SPREAD"
        rationale = "Moderate confidence or limited expected move; defined-risk debit spread."

    return {
        "strategy": strategy,
        "recommended_moneyness": moneyness,
        "direction": direction,
        "rationale": rationale,
        "note": "Full contract selection is delivered by 26.2 Contract Intelligence.",
    }


# --------------------------------------------------------------------------- #
# 26.0-c Entry / order quality.
# --------------------------------------------------------------------------- #
def optimize_entry(root: Mapping[str, Any], readiness: Mapping[str, Any]) -> dict[str, Any]:
    quote = _mapping(readiness.get("quote"))
    mid = _number(quote.get("mid"))
    spread = _number(quote.get("spread"))
    spread_pct = _number(quote.get("spread_pct"), 0.0)
    momentum = _number(_mapping(root.get("momentum")).get("score"), 50.0)

    # Patience vs chase: wide spread or extended momentum favors patience (limit).
    chase_score = _clamp(momentum)                       # high momentum tempts chasing
    patience_score = _clamp(100 - momentum + spread_pct * 2)

    if spread_pct <= 3 and momentum >= 70:
        order_type = "MARKET"
        limit_price = None
        expected_slippage = _round(spread / 2, 4)
    elif spread_pct <= 8:
        order_type = "LIMIT"
        limit_price = _round(mid, 4)
        expected_slippage = _round(spread * 0.25, 4)
    else:
        order_type = "LIMIT_OFFSET"
        limit_price = _round(mid - spread * 0.1, 4) if mid else None
        expected_slippage = _round(spread * 0.15, 4)

    entry_confidence = _clamp(70 - spread_pct * 2 + (momentum - 50) * 0.2)
    return {
        "recommended_order_type": order_type,
        "recommended_limit_price": limit_price,
        "expected_slippage": expected_slippage,
        "patience_score": _round(patience_score),
        "chase_score": _round(chase_score),
        "entry_confidence": _round(entry_confidence),
        "liquidity_note": "Full liquidity/slippage modeling is delivered by 26.3.",
    }


# --------------------------------------------------------------------------- #
# 26.0-d Position sizing (enforces existing RiskLimits).
# --------------------------------------------------------------------------- #
def size_position(root: Mapping[str, Any], *, entry_premium: Optional[float] = None,
                  stop_premium: Optional[float] = None,
                  confidence: Optional[float] = None) -> dict[str, Any]:
    limits = _limits()
    quote = _quote(root)
    entry = _number(entry_premium if entry_premium is not None else quote["mid"] or root.get("entry_premium"))
    stop = _number(stop_premium if stop_premium is not None else root.get("stop_premium"))
    conf = _number(confidence if confidence is not None else _mapping(root.get("decision")).get("integrity_adjusted_confidence"), 60.0)

    per_contract_risk = max(0.0, (entry - stop)) * 100.0  # options multiplier
    max_risk = limits["max_risk_per_trade"]
    reasons: list[str] = []

    if per_contract_risk <= 0:
        contracts_by_risk = 0
        reasons.append("Cannot size: entry/stop premium missing or non-positive risk.")
    else:
        contracts_by_risk = int(max_risk // per_contract_risk)

    # Capped Kelly fraction from confidence (win prob proxy), never above 0.25.
    win_p = _clamp(conf) / 100.0
    payoff = 1.5  # conservative reward:risk assumption for fraction only
    kelly = max(0.0, (win_p * (payoff + 1) - 1) / payoff)
    kelly_capped = min(0.25, kelly)

    contracts = min(contracts_by_risk, limits["max_contracts"])
    # Kelly can only *reduce* the risk-based size, never increase it.
    kelly_contracts = int(math.floor(contracts * (kelly_capped / 0.25))) if contracts else 0
    recommended = max(0, min(contracts, kelly_contracts if kelly_contracts else contracts))
    if recommended > limits["max_contracts"]:
        recommended = limits["max_contracts"]
        reasons.append("Capped at max_contracts.")

    dollar_risk = _round(recommended * per_contract_risk, 2)
    if dollar_risk and dollar_risk > max_risk:
        reasons.append("Risk-based cap enforced; size reduced to respect max_risk_per_trade.")

    return {
        "recommended_contracts": recommended,
        "max_contracts_limit": limits["max_contracts"],
        "per_contract_risk": _round(per_contract_risk),
        "estimated_dollar_risk": dollar_risk,
        "max_risk_per_trade": max_risk,
        "kelly_fraction_capped": _round(kelly_capped, 4),
        "portfolio_risk_enforced": True,
        "limits_source": limits["source"],
        "reasons": reasons,
        "note": "Actual placement still passes trade_risk_guard.validate_entry and the confirmation gate.",
    }


# --------------------------------------------------------------------------- #
# 26.0-e Exit framing (advisory; dynamic management is 26.5).
# --------------------------------------------------------------------------- #
def frame_exits(root: Mapping[str, Any], readiness: Mapping[str, Any]) -> dict[str, Any]:
    quote = _mapping(readiness.get("quote"))
    entry = _number(quote.get("mid") or root.get("entry_premium"))
    forecast = _mapping(root.get("forecast"))
    rr = _number(forecast.get("expected_risk_reward"), 1.5)
    stop = _round(entry * 0.6, 4) if entry else None            # 40% premium stop (advisory default)
    target = _round(entry * (1 + max(0.5, rr) * 0.4), 4) if entry else None
    return {
        "initial_stop_premium": stop,
        "primary_target_premium": target,
        "breakeven_trigger_premium": _round(entry * 1.2, 4) if entry else None,
        "expected_risk_reward": _round(rr),
        "note": "Static advisory frame; adaptive stops/scaling are delivered by 26.5.",
    }


# --------------------------------------------------------------------------- #
# 26.0-f Execution grading (advisory; full review is 26.8).
# --------------------------------------------------------------------------- #
def grade_execution(plan: Mapping[str, Any], fill: Mapping[str, Any]) -> dict[str, Any]:
    """Grade execution quality independent of forecast/trade outcome."""
    entry = _mapping(plan.get("entry"))
    recommended_price = _number(entry.get("recommended_limit_price"), _number(_mapping(plan.get("readiness")).get("quote", {}).get("mid")))
    expected_slippage = _number(entry.get("expected_slippage"))
    fill_price = _number(fill.get("fill_price"))
    fill_slippage = abs(fill_price - recommended_price) if (fill_price and recommended_price) else None

    if fill_slippage is None:
        return {"ok": True, "execution_grade": "NOT_GRADEABLE",
                "reason": "No fill price supplied.", "production_effect": "NONE"}

    slippage_ratio = fill_slippage / expected_slippage if expected_slippage > 0 else (0 if fill_slippage == 0 else 2)
    score = _clamp(100 - slippage_ratio * 30)
    grade = ("A" if score >= 90 else "B" if score >= 78 else "C" if score >= 65 else "D" if score >= 50 else "F")
    return {
        "ok": True,
        "execution_grade": grade,
        "execution_score": _round(score),
        "expected_slippage": _round(expected_slippage, 4),
        "realized_slippage": _round(fill_slippage, 4),
        "graded_on": "EXECUTION_QUALITY_INDEPENDENT_OF_FORECAST",
        "production_effect": "NONE",
    }


# --------------------------------------------------------------------------- #
# Director: assemble the full execution plan.
# --------------------------------------------------------------------------- #
def build_execution_plan(payload: Optional[Mapping[str, Any]], *,
                         decision: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    root = payload if isinstance(payload, Mapping) else {}
    evaluated = decision if isinstance(decision, Mapping) else integrity.evaluate_decision(root)
    decision_block = _mapping(evaluated.get("decision"))

    readiness = assess_readiness(root, evaluated)
    strategy = select_strategy(root, evaluated)

    # Prefer the full 26.1-26.4 engines when present; fall back to the built-in
    # lightweight assessments otherwise. Existing plan keys are preserved either
    # way (the full engines are supersets).
    entry = optimize_entry(root, readiness)
    sizing = size_position(root, confidence=decision_block.get("integrity_adjusted_confidence"))
    contract = None
    liquidity_block = None
    try:
        from . import entry_optimization_v261 as _entry_opt
        entry = _entry_opt.optimize(root)
    except Exception:
        pass
    try:
        from . import position_sizing_v264 as _sizing
        sizing = _sizing.size(root, confidence=decision_block.get("integrity_adjusted_confidence"))
    except Exception:
        pass
    try:
        from . import contract_intelligence_v262 as _contract
        contract = _contract.recommend(root)
    except Exception:
        pass
    try:
        from . import liquidity_slippage_v263 as _liquidity
        liquidity_block = _liquidity.analyze(root)
    except Exception:
        pass

    exits = frame_exits(root, readiness)

    execution_plan = {
        "readiness": readiness,
        "strategy": strategy,
        "entry": entry,
        "position_sizing": sizing,
        "exits": exits,
    }
    if contract is not None:
        execution_plan["contract"] = contract
    if liquidity_block is not None:
        execution_plan["liquidity"] = liquidity_block

    return {
        "ok": True,
        "status": readiness["state"],
        "version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "generated_at": _iso_now(),
        "symbol": _text(root.get("symbol") or _mapping(root.get("market_state")).get("symbol") or "SPX"),
        "direction": _text(decision_block.get("direction")),
        "execution_plan": execution_plan,
        "guardrails": {
            "places_orders": False,
            "auto_submits": False,
            "confirmation_gated": True,
            "advisory_only": True,
            "risk_limits_enforced": True,
            "routes_through_existing_execution": "engine/execution/trade_routes",
        },
        "production_effect": "NONE",
    }


# --------------------------------------------------------------------------- #
# Mission Control + status.
# --------------------------------------------------------------------------- #
def mission_control_group(result: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    plan = _mapping((result or {}).get("execution_plan"))
    readiness = _mapping(plan.get("readiness"))
    sizing = _mapping(plan.get("position_sizing"))
    entry = _mapping(plan.get("entry"))
    return {
        "group": "EXECUTION_INTELLIGENCE",
        "panel_state": "READY" if plan else "EMPTY",
        "readiness_state": readiness.get("state"),
        "strategy": _mapping(plan.get("strategy")).get("strategy"),
        "recommended_order_type": entry.get("recommended_order_type"),
        "recommended_contracts": sizing.get("recommended_contracts"),
        "entry_confidence": entry.get("entry_confidence"),
        "places_orders": False,
        "confirmation_gated": True,
        "production_effect": "NONE",
    }


def status() -> dict[str, Any]:
    limits = _limits()
    return {
        "status": "READY",
        "engine": "EXECUTION_INTELLIGENCE_CORE",
        "version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "readiness_states": list(READINESS_STATES),
        "order_types": list(ORDER_TYPES),
        "strategies": list(STRATEGIES),
        "risk_limits": limits,
        "places_orders": False,
        "auto_submits": False,
        "confirmation_gated": True,
        "advisory_only": True,
        "production_effect": "NONE",
    }
