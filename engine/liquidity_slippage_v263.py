"""APEX 26.3 — Liquidity & Slippage Engine (advisory, deterministic).

Given a contract quote and an intended size, it characterizes liquidity and
estimates execution friction: spread width, market depth, volume, open interest,
estimated slippage, fill probability, and a recommended order type. It places no
orders and reads no live broker; ``production_effect`` is ``NONE``.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Optional

VERSION = "26.3.0_LIQUIDITY_SLIPPAGE"
SCHEMA_VERSION = "apex.liquidity_slippage.v263.v1"

ORDER_TYPES = ("MARKET", "LIMIT", "LIMIT_OFFSET", "STOP_LIMIT")
LIQUIDITY_TIERS = ("HIGH", "MEDIUM", "LOW", "ILLIQUID")


def _number(value: Any, default: float = 0.0) -> float:
    try:
        n = float(value)
        return n if math.isfinite(n) else default
    except (TypeError, ValueError):
        return default


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _round(v: Any, p: int = 4) -> Optional[float]:
    return None if v is None else round(float(v), p)


def _quote(root: Mapping[str, Any]) -> dict[str, Any]:
    q = _mapping(root.get("quote") or root.get("option_quote") or root.get("contract_quote"))
    bid, ask = _number(q.get("bid")), _number(q.get("ask"))
    mid = _number(q.get("mid"), (bid + ask) / 2 if (bid or ask) else 0.0)
    spread = (ask - bid) if (ask and bid) else _number(q.get("spread"))
    return {
        "bid": bid, "ask": ask, "mid": _round(mid),
        "spread": _round(spread),
        "spread_pct": _round(spread / mid * 100, 3) if mid > 0 else None,
        "volume": _number(q.get("volume")),
        "open_interest": _number(q.get("open_interest") or q.get("oi")),
    }


def _liquidity_tier(volume: float, oi: float, spread_pct: Optional[float]) -> str:
    sp = spread_pct if spread_pct is not None else 99.0
    if volume >= 2000 and oi >= 5000 and sp <= 3:
        return "HIGH"
    if volume >= 500 and oi >= 1000 and sp <= 8:
        return "MEDIUM"
    if volume >= 100 and oi >= 200 and sp <= 15:
        return "LOW"
    return "ILLIQUID"


def analyze(root: Optional[Mapping[str, Any]], *, contracts: int = 1) -> dict[str, Any]:
    root = root if isinstance(root, Mapping) else {}
    q = _quote(root)
    contracts = max(1, int(_number(contracts, 1)))
    spread = _number(q.get("spread"))
    spread_pct = q.get("spread_pct")
    volume, oi = q.get("volume"), q.get("open_interest")
    tier = _liquidity_tier(volume, oi, spread_pct)

    # Depth proxy: how many contracts the displayed size can likely absorb.
    depth_contracts = max(1.0, min(volume, oi) / 20.0)
    size_pressure = min(2.0, contracts / depth_contracts)  # >1 means size strains depth

    # Deterministic slippage: half-spread base, scaled by tier and size pressure.
    tier_factor = {"HIGH": 0.15, "MEDIUM": 0.30, "LOW": 0.55, "ILLIQUID": 0.9}[tier]
    estimated_slippage = _round(spread * tier_factor * (1 + 0.5 * size_pressure))

    # Fill probability at mid/limit: higher liquidity + smaller size -> higher.
    base_fill = {"HIGH": 0.95, "MEDIUM": 0.85, "LOW": 0.65, "ILLIQUID": 0.4}[tier]
    fill_probability = _round(max(0.1, base_fill - 0.2 * max(0.0, size_pressure - 1)), 3)

    # Recommended order type from spread + tier.
    sp = spread_pct if spread_pct is not None else 99.0
    if tier == "HIGH" and sp <= 3:
        order_type = "MARKET"
    elif tier in {"HIGH", "MEDIUM"}:
        order_type = "LIMIT"
    elif tier == "LOW":
        order_type = "LIMIT_OFFSET"
    else:
        order_type = "STOP_LIMIT"

    return {
        "ok": True,
        "version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "quote": q,
        "liquidity_quality": tier,
        "spread_width": spread,
        "spread_pct": spread_pct,
        "volume": volume,
        "open_interest": oi,
        "market_depth_contracts": _round(depth_contracts, 1),
        "size_pressure": _round(size_pressure, 3),
        "estimated_slippage": estimated_slippage,
        "fill_probability": fill_probability,
        "recommended_order_type": order_type,
        "production_effect": "NONE",
    }


def status() -> dict[str, Any]:
    return {"status": "READY", "engine": "LIQUIDITY_SLIPPAGE", "version": VERSION,
            "order_types": list(ORDER_TYPES), "liquidity_tiers": list(LIQUIDITY_TIERS),
            "places_orders": False, "production_effect": "NONE"}
