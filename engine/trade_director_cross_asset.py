"""APEX Trade Director Phase 13 — Cross-Asset Intelligence & Lead-Lag Engine.

Pure analytics over already-cached payloads. This module never performs provider requests,
starts workers, opens broker connections, or transmits orders.
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _nested(payload: Mapping[str, Any], *paths: str, default: Any = None) -> Any:
    for path in paths:
        current: Any = payload
        found = True
        for part in path.split("."):
            if not isinstance(current, Mapping) or part not in current:
                found = False
                break
            current = current[part]
        if found and current is not None:
            return current
    return default


def _direction(value: Any) -> str:
    text = str(value or "").upper().strip()
    if any(token in text for token in ("BULL", "CALL", "UP", "RISK_ON", "RISING", "POSITIVE", "BUY")):
        return "BULLISH"
    if any(token in text for token in ("BEAR", "PUT", "DOWN", "RISK_OFF", "FALLING", "NEGATIVE", "SELL")):
        return "BEARISH"
    return "NEUTRAL"


def _asset_record(symbol: str, payload: Mapping[str, Any], inverted: bool = False) -> Dict[str, Any]:
    change = _f(_nested(payload, "change_pct", "percent_change", "pct_change", "return_pct", default=0.0))
    trend = _direction(_nested(payload, "bias", "trend", "direction", "state", default=""))
    if trend == "NEUTRAL":
        trend = "BULLISH" if change > 0.05 else "BEARISH" if change < -0.05 else "NEUTRAL"
    effective = trend
    if inverted:
        effective = "BEARISH" if trend == "BULLISH" else "BULLISH" if trend == "BEARISH" else "NEUTRAL"
    freshness = str(_nested(payload, "freshness", "data_state", default="UNKNOWN")).upper()
    available = bool(payload) and not bool(payload.get("unavailable"))
    return {
        "symbol": symbol,
        "available": available,
        "raw_direction": trend,
        "spx_effect": effective,
        "change_pct": round(change, 3),
        "freshness": freshness,
        "source": str(payload.get("source") or "CACHED"),
    }


def _find_asset(cached: Mapping[str, Any], aliases: Iterable[str]) -> Dict[str, Any]:
    aliases_upper = {a.upper() for a in aliases}
    candidate_paths = (
        "cross_asset", "cross_assets", "market_state.cross_asset", "market_state.cross_assets",
        "institutional_os.cross_asset", "institutional_os.market_state.cross_asset",
        "macro", "intermarket", "symbols", "quotes", "market_data",
    )
    containers: List[Mapping[str, Any]] = [cached]
    for path in candidate_paths:
        value = _nested(cached, path, default=None)
        if isinstance(value, Mapping):
            containers.append(value)
    for container in containers:
        for key, value in container.items():
            if str(key).upper() in aliases_upper and isinstance(value, Mapping):
                return dict(value)
        rows = container.get("assets") if isinstance(container, Mapping) else None
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, Mapping) and str(row.get("symbol") or row.get("ticker") or "").upper() in aliases_upper:
                    return dict(row)
    return {}


def build_cross_asset_snapshot(cached: Optional[Dict[str, Any]], monitor: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    cached = dict(cached or {})
    monitor = dict(monitor or {})
    merged = {**cached, **monitor}
    definitions: List[Tuple[str, Tuple[str, ...], bool, float]] = [
        ("ES", ("ES", "ES1!", "SPX_FUTURES"), False, 1.35),
        ("NQ", ("NQ", "NQ1!", "NASDAQ_FUTURES"), False, 1.15),
        ("SPY", ("SPY",), False, 1.00),
        ("QQQ", ("QQQ",), False, 0.85),
        ("VIX", ("VIX", "VIX1D"), True, 1.20),
        ("BREADTH", ("BREADTH", "ADVANCE_DECLINE", "AD_LINE"), False, 1.10),
        ("HYG", ("HYG", "CREDIT"), False, 0.90),
        ("DXY", ("DXY", "USD", "DOLLAR"), True, 0.65),
        ("US10Y", ("US10Y", "TNX", "10Y", "YIELD_10Y"), True, 0.75),
        ("XLK", ("XLK", "TECH"), False, 0.60),
        ("XLF", ("XLF", "FINANCIALS"), False, 0.45),
    ]
    assets = []
    for symbol, aliases, inverted, weight in definitions:
        record = _asset_record(symbol, _find_asset(merged, aliases), inverted=inverted)
        record["weight"] = weight
        assets.append(record)
    return {"as_of": _now(), "assets": assets, "source": "CACHED_ONLY", "version": "13.0"}


def _spx_bias(monitor: Mapping[str, Any]) -> str:
    return _direction(
        _nested(
            monitor,
            "expected_path", "institutional_analysis.engines.expected_path.state",
            "flow_snapshot.bias", "side", default="NEUTRAL",
        )
    )


def _lead_lag(assets: List[Dict[str, Any]], spx_bias: str) -> Dict[str, Any]:
    available = [a for a in assets if a.get("available")]
    if not available:
        return {"leader": None, "laggard": None, "status": "DATA_LIMITED", "evidence": []}
    ranked = sorted(available, key=lambda a: (abs(_f(a.get("change_pct"))) * _f(a.get("weight"), 1), _f(a.get("weight"))), reverse=True)
    leader = ranked[0]
    contradictors = [a for a in available if spx_bias != "NEUTRAL" and a.get("spx_effect") not in (spx_bias, "NEUTRAL")]
    laggard = contradictors[0] if contradictors else ranked[-1]
    evidence = [f"{leader['symbol']} has the strongest cached weighted move"]
    if contradictors:
        evidence.append(f"{laggard['symbol']} is not confirming the SPX directional bias")
    return {"leader": leader.get("symbol"), "laggard": laggard.get("symbol"), "status": "ACTIVE", "evidence": evidence}


def _divergences(assets: List[Dict[str, Any]], spx_bias: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for asset in assets:
        if not asset.get("available") or spx_bias == "NEUTRAL" or asset.get("spx_effect") == "NEUTRAL":
            continue
        if asset.get("spx_effect") != spx_bias:
            severity = "HIGH" if asset.get("symbol") in ("ES", "VIX", "BREADTH", "HYG") else "MEDIUM"
            out.append({
                "asset": asset.get("symbol"), "severity": severity,
                "type": "DIRECTIONAL_DIVERGENCE",
                "message": f"{asset.get('symbol')} contradicts the {spx_bias.lower()} SPX bias.",
            })
    return out


def _regime(assets: List[Dict[str, Any]], score: float, divergences: List[Dict[str, Any]]) -> str:
    by_symbol = {a.get("symbol"): a for a in assets}
    vix = by_symbol.get("VIX", {}).get("spx_effect")
    rates = by_symbol.get("US10Y", {}).get("raw_direction")
    nq = by_symbol.get("NQ", {}).get("spx_effect")
    credit = by_symbol.get("HYG", {}).get("spx_effect")
    if any(d.get("asset") == "VIX" and d.get("severity") == "HIGH" for d in divergences):
        return "VOLATILITY_CONFLICT"
    if rates == "BULLISH" and score < 45:
        return "RATES_LED_PRESSURE"
    if nq == "BULLISH" and score >= 60:
        return "TECH_LED_RISK_ON"
    if credit == "BEARISH" and score >= 50:
        return "CREDIT_DIVERGENCE"
    if score >= 68 and vix == "BULLISH":
        return "RISK_ON_EXPANSION"
    if score <= 32:
        return "RISK_OFF_COMPRESSION"
    return "MIXED_CONFLICTED" if divergences else "BALANCED_CONFIRMATION"


def _transmission_map(assets: List[Dict[str, Any]]) -> Dict[str, Any]:
    available = {a.get("symbol") for a in assets if a.get("available")}
    chain = ["US10Y", "DXY", "NQ", "ES", "SPX", "OPTIONS_FLOW"]
    nodes = []
    for node in chain:
        nodes.append({"node": node, "available": node in available or node in ("SPX", "OPTIONS_FLOW")})
    intact = sum(1 for n in nodes if n["available"])
    return {"chain": nodes, "coverage_pct": round(100 * intact / len(nodes), 1), "status": "INTACT" if intact >= 5 else "PARTIAL" if intact >= 3 else "DATA_LIMITED"}


def build_cross_asset_intelligence(snapshot: Dict[str, Any], monitor: Optional[Dict[str, Any]] = None, historical_sessions: Iterable[Dict[str, Any]] = ()) -> Dict[str, Any]:
    monitor = dict(monitor or {})
    assets = list(snapshot.get("assets") or [])
    spx_bias = _spx_bias(monitor)
    available = [a for a in assets if a.get("available")]
    weighted_total = sum(_f(a.get("weight"), 1) for a in available) or 1.0
    bullish = sum(_f(a.get("weight"), 1) for a in available if a.get("spx_effect") == "BULLISH")
    bearish = sum(_f(a.get("weight"), 1) for a in available if a.get("spx_effect") == "BEARISH")
    raw = 50.0 + 50.0 * (bullish - bearish) / weighted_total
    coverage = len(available) / max(1, len(assets))
    score = _clamp(50 + (raw - 50) * coverage)
    divergences = _divergences(assets, spx_bias)
    high_divergences = sum(1 for d in divergences if d.get("severity") == "HIGH")
    confidence = _clamp(35 + coverage * 55 - high_divergences * 12 - max(0, len(divergences) - high_divergences) * 4)
    bias = "BULLISH" if score >= 58 else "BEARISH" if score <= 42 else "NEUTRAL"
    lead_lag = _lead_lag(assets, spx_bias)
    regime = _regime(assets, score, divergences)
    history = list(historical_sessions or [])
    comparable = []
    for row in history:
        snap = dict(row.get("snapshot") or {})
        historical_regime = str(snap.get("cross_asset_regime") or "")
        historical_score = _f(snap.get("spx_confirmation_score"), 50)
        if historical_regime == regime or abs(historical_score - score) <= 10:
            comparable.append({"session_date": row.get("session_date"), "regime": historical_regime or "UNKNOWN", "confirmation_score": historical_score, "outcome": row.get("outcome")})
    return {
        "version": "PHASE_13", "as_of": snapshot.get("as_of") or _now(),
        "data_policy": "CACHED_ONLY", "spx_bias": spx_bias,
        "spx_confirmation_score": round(score, 1), "cross_asset_bias": bias,
        "confidence": round(confidence, 1), "coverage_pct": round(coverage * 100, 1),
        "regime": regime, "lead_lag": lead_lag, "divergences": divergences,
        "transmission_map": _transmission_map(assets), "signal_matrix": assets,
        "historical_cross_asset_memory": {"comparable_sessions": comparable[:5], "sample_count": len(comparable), "status": "LEARNING" if len(comparable) < 30 else "ACTIVE"},
        "trade_director_effect": {
            "health_adjustment": -min(20, high_divergences * 10 + max(0, len(divergences) - high_divergences) * 3),
            "sizing_posture": "REDUCED" if high_divergences or confidence < 55 else "NORMAL",
            "execution_note": "Phase 13 is advisory. Phase 9 and Phase 10 remain authoritative for risk and execution.",
        },
        "safety_note": "No provider requests were made. Results use only data already cached inside APEX.",
    }
