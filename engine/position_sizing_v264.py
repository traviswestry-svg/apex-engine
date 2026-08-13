"""APEX 26.4 — Position Sizing Engine (advisory, deterministic).

Superset of the 26.0 sizing stub. Determines position size, per-trade and
portfolio risk, capped Kelly fraction, expected drawdown and return, and honors
the daily risk limit — all within the repository's existing ``RiskLimits``. It
recommends only; actual placement still passes ``trade_risk_guard.validate_entry``
and the confirmation gate. ``production_effect`` is ``NONE``.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Optional

try:
    from .execution.trade_risk_guard import RiskLimits  # type: ignore
    _RISK_LIMITS_AVAILABLE = True
except Exception:  # pragma: no cover
    RiskLimits = None  # type: ignore
    _RISK_LIMITS_AVAILABLE = False

VERSION = "26.4.0_POSITION_SIZING"
SCHEMA_VERSION = "apex.position_sizing.v264.v1"

_FALLBACK = {"max_contracts": 10, "max_risk_per_trade": 1000.0, "max_daily_loss": 2500.0}
KELLY_CAP = 0.25


def _number(value: Any, default: float = 0.0) -> float:
    try:
        n = float(value)
        return n if math.isfinite(n) else default
    except (TypeError, ValueError):
        return default


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


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
                "source": "trade_risk_guard",
            }
        except Exception:
            pass
    return {**_FALLBACK, "source": "fallback_defaults"}


def size(root: Optional[Mapping[str, Any]], *, entry_premium: Optional[float] = None,
         stop_premium: Optional[float] = None, confidence: Optional[float] = None,
         reward_risk: Optional[float] = None) -> dict[str, Any]:
    root = root if isinstance(root, Mapping) else {}
    limits = _limits()
    quote = _mapping(root.get("quote"))
    entry = _number(entry_premium if entry_premium is not None else quote.get("mid") or root.get("entry_premium"))
    stop = _number(stop_premium if stop_premium is not None else root.get("stop_premium"))
    conf = _number(confidence if confidence is not None
                   else _mapping(root.get("decision")).get("integrity_adjusted_confidence"), 60.0)
    forecast = _mapping(root.get("forecast"))
    rr = _number(reward_risk if reward_risk is not None else forecast.get("expected_risk_reward"), 1.5)

    per_contract_risk = max(0.0, (entry - stop)) * 100.0
    max_risk = limits["max_risk_per_trade"]
    reasons: list[str] = []

    # Daily risk budget: remaining loss allowance shrinks the per-trade cap.
    daily_used = _number(_mapping(root.get("portfolio")).get("daily_loss_used"))
    daily_remaining = max(0.0, limits["max_daily_loss"] - daily_used)
    effective_cap = min(max_risk, daily_remaining) if daily_remaining > 0 else 0.0
    if daily_remaining <= 0:
        reasons.append("Daily loss limit reached: no new risk permitted.")
    elif effective_cap < max_risk:
        reasons.append("Per-trade risk reduced by remaining daily loss budget.")

    if per_contract_risk <= 0:
        contracts_by_risk = 0
        reasons.append("Cannot size: entry/stop premium missing or non-positive risk.")
    else:
        contracts_by_risk = int(effective_cap // per_contract_risk)

    # Capped Kelly (can only reduce size).
    win_p = _clamp(conf) / 100.0
    payoff = max(0.5, rr)
    kelly = max(0.0, (win_p * (payoff + 1) - 1) / payoff)
    kelly_capped = min(KELLY_CAP, kelly)

    contracts = min(contracts_by_risk, limits["max_contracts"])
    kelly_contracts = int(math.floor(contracts * (kelly_capped / KELLY_CAP))) if contracts else 0
    recommended = max(0, min(contracts, kelly_contracts if kelly_contracts else 0))
    if recommended > limits["max_contracts"]:
        recommended = limits["max_contracts"]
        reasons.append("Capped at max_contracts.")

    dollar_risk = _round(recommended * per_contract_risk, 2)
    if dollar_risk and dollar_risk > effective_cap + 1e-6:
        reasons.append("Risk cap enforced; size reduced.")

    # Portfolio exposure + expectancy.
    portfolio_capital = _number(_mapping(root.get("portfolio")).get("capital"), 0.0)
    portfolio_exposure_pct = _round(dollar_risk / portfolio_capital * 100, 3) if portfolio_capital > 0 else None
    expected_return = _round(recommended * per_contract_risk * payoff * win_p
                             - recommended * per_contract_risk * (1 - win_p), 2)
    expected_drawdown = _round(recommended * per_contract_risk, 2)  # worst-case at stop

    return {
        "ok": True,
        "version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "recommended_contracts": recommended,
        "max_contracts_limit": limits["max_contracts"],
        "per_contract_risk": _round(per_contract_risk),
        "estimated_dollar_risk": dollar_risk,
        "max_risk_per_trade": max_risk,
        "daily_risk_remaining": _round(daily_remaining),
        "effective_risk_cap": _round(effective_cap),
        "kelly_fraction_capped": _round(kelly_capped, 4),
        "portfolio_exposure_pct": portfolio_exposure_pct,
        "expected_return": expected_return,
        "expected_drawdown": expected_drawdown,
        "portfolio_risk_enforced": True,
        "limits_source": limits["source"],
        "reasons": reasons,
        "note": "Actual placement still passes trade_risk_guard.validate_entry and the confirmation gate.",
        "production_effect": "NONE",
    }


def status() -> dict[str, Any]:
    return {"status": "READY", "engine": "POSITION_SIZING", "version": VERSION,
            "kelly_cap": KELLY_CAP, "risk_limits": _limits(),
            "places_orders": False, "production_effect": "NONE"}
