from __future__ import annotations

import datetime as dt
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")


def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _basis(es_price: Any, spx_price: Any) -> Dict[str, Any]:
    es = _safe_float(es_price)
    spx = _safe_float(spx_price)
    if es is None or spx is None:
        return {"points": None, "label": "UNAVAILABLE", "valid": False}
    points = round(es - spx, 2)
    return {
        "points": points,
        "label": "PREMIUM" if points > 0 else "DISCOUNT" if points < 0 else "FLAT",
        "valid": True,
    }


def build_market_state(
    *,
    es_chart: Optional[Dict[str, Any]] = None,
    spx_chart: Optional[Dict[str, Any]] = None,
    spx_gamma: Optional[Dict[str, Any]] = None,
    spx_flow: Optional[Dict[str, Any]] = None,
    session: Optional[str] = None,
) -> Dict[str, Any]:
    """APEX 6.0.1 single market-state contract consumed by dashboard endpoints."""
    es_chart = es_chart or {}
    spx_chart = spx_chart or {}
    spx_gamma = spx_gamma or {}
    spx_flow = spx_flow or {}

    es_price = es_chart.get("currentClose")
    spx_price = spx_chart.get("currentClose") or spx_gamma.get("stock_price")
    gamma = {
        "ticker": "SPX",
        "stock_price": spx_gamma.get("stock_price"),
        "call_wall": spx_gamma.get("call_wall"),
        "put_wall": spx_gamma.get("put_wall"),
        "zero_gamma": spx_gamma.get("zero_gamma"),
        "gex_score": spx_gamma.get("gex_score"),
        "gex_status": spx_gamma.get("gex_status"),
        "quality_flags": spx_gamma.get("quality_flags", []),
        "diagnostics": spx_gamma.get("diagnostics"),
    }

    return {
        "version": "6.0.1_DATA_BUS_GAMMA_DIAGNOSTICS",
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "updated_at_et": dt.datetime.now(EASTERN).strftime("%Y-%m-%d %H:%M:%S ET"),
        "session": session,
        "instruments": {
            "ES": {
                "role": "FUTURES_LEAD",
                "symbol": es_chart.get("symbol", "ES Futures"),
                "polygonTicker": es_chart.get("polygonTicker"),
                "price": es_price,
                "chartSource": "Polygon futures" if es_chart.get("isFutures") else "fallback",
            },
            "SPX": {
                "role": "CASH_GAMMA_ANCHOR",
                "symbol": spx_chart.get("symbol", "SPX Cash Index"),
                "polygonTicker": spx_chart.get("polygonTicker"),
                "price": spx_price,
                "chartSource": "Polygon cash index",
            },
        },
        "basis": _basis(es_price, spx_price),
        "gamma": gamma,
        "flow": spx_flow,
        "diagnostics": {
            "gamma": gamma.get("diagnostics"),
            "data_contract": "market_state_v6_0_1",
        },
    }
