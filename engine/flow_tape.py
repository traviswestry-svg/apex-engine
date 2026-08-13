"""engine/flow_tape.py — APEX 6.3.2 Institutional Flow Tape Engine.

Fetches QuantData consolidated order-flow for multiple tickers, classifies
each row into tape labels (BUY_SWEEP / SELL_SWEEP / BUY_BLOCK / SELL_BLOCK /
BUY_SPLIT / SELL_SPLIT), computes importance scores, and returns a structured
tape payload suitable for the /api/flow_tape endpoint and dashboard panel.

Terminology used throughout:
  - Institutional Options Flow Tape
  - Sweep Tape / Block Tape / Premium Tape / Aggressive Flow

This module NEVER calls it a DOM or cumulative delta.
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        f = float(v)
        return default if (math.isnan(f) or math.isinf(f)) else f
    except Exception:
        return default


def _now_et_str() -> str:
    try:
        import zoneinfo
        tz = zoneinfo.ZoneInfo("America/New_York")
    except Exception:
        tz = dt.timezone(dt.timedelta(hours=-4))
    return dt.datetime.now(tz).strftime("%H:%M:%S")


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

# trade_side_code values returned by QuantData consolidated order-flow:
#   ABOVE_ASK  → aggressive buy sweep / block
#   AT_ASK     → buy at ask (still bullish aggression)
#   AT_BID     → sell at bid (bearish aggression)
#   BELOW_BID  → aggressive sell sweep / block
#   MID        → neutral / passive fill

_SIDE_CODE_AGGRESSOR: Dict[str, str] = {
    "ABOVE_ASK": "BUY",
    "AT_ASK":    "BUY",
    "AT_BID":    "SELL",
    "BELOW_BID": "SELL",
    "MID":       "NEUTRAL",
}

_CONSOLIDATION_SUFFIX: Dict[str, str] = {
    "SWEEP": "SWEEP",
    "BLOCK": "BLOCK",
    "SPLIT": "SPLIT",
}


def _classify_row(row: Dict[str, Any]) -> Tuple[str, str]:
    """Return (aggressor_side, tape_label) for a single QuantData order-flow row."""
    trade_side_code = str(row.get("tradeSideCode") or row.get("trade_side_code") or "").upper().strip()
    consolidation_type = str(row.get("tradeConsolidationType") or row.get("consolidation_type") or "").upper().strip()

    aggressor = _SIDE_CODE_AGGRESSOR.get(trade_side_code, "NEUTRAL")

    # Fallback: if tradeSideCode is missing, infer from contractType
    if not trade_side_code:
        contract_type = str(row.get("contractType") or row.get("contract_type") or "").upper()
        aggressor = "BUY" if contract_type == "CALL" else "SELL" if contract_type == "PUT" else "NEUTRAL"

    suffix = _CONSOLIDATION_SUFFIX.get(consolidation_type, "")
    if suffix:
        label = f"{aggressor}_{suffix}" if aggressor in ("BUY", "SELL") else f"UNKNOWN_{suffix}"
    else:
        label = "UNKNOWN"

    return aggressor, label


# ---------------------------------------------------------------------------
# Importance scoring
# ---------------------------------------------------------------------------

def _importance_score(premium: float, aggressor: str, consolidation_type: str) -> int:
    """0–100 importance score based on premium size, aggression, and trade type."""
    base = 50.0
    # Premium tiers
    if premium >= 5_000_000:
        base += 30
    elif premium >= 2_000_000:
        base += 22
    elif premium >= 1_000_000:
        base += 15
    elif premium >= 500_000:
        base += 8
    elif premium >= 250_000:
        base += 2
    else:
        base -= 10

    # Aggression bonus
    if aggressor in ("BUY", "SELL"):
        base += 5

    # Trade type
    if consolidation_type == "SWEEP":
        base += 10
    elif consolidation_type == "BLOCK":
        base += 5

    return max(0, min(100, int(round(base))))


# ---------------------------------------------------------------------------
# Premium extraction (handles varied QuantData field names)
# ---------------------------------------------------------------------------

def _extract_premium(row: Dict[str, Any]) -> float:
    """Extract dollar premium from a QuantData row, trying all known field names."""
    for field in ("premium", "notional", "totalPremium", "tradePremium", "value"):
        val = _safe_float(row.get(field), 0.0)
        if val > 0:
            return val
    # Compute from price × contracts × 100
    price = _safe_float(row.get("price") or row.get("optionPrice") or row.get("tradePrice"), 0.0)
    contracts = _safe_float(row.get("size") or row.get("quantity") or row.get("contracts"), 0.0)
    if price > 0 and contracts > 0:
        return price * contracts * 100.0
    return 0.0


# ---------------------------------------------------------------------------
# Row normalization
# ---------------------------------------------------------------------------

def _normalize_row(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Convert a raw QuantData order-flow row into a normalized tape row.

    Returns None if the row lacks minimum required fields.
    """
    ticker = str(raw.get("ticker") or raw.get("symbol") or "").upper().strip()
    contract_type = str(raw.get("contractType") or raw.get("contract_type") or raw.get("optionType") or "").upper().strip()
    if not ticker or contract_type not in ("CALL", "PUT"):
        return None

    premium = _extract_premium(raw)
    strike = _safe_float(raw.get("strike") or raw.get("strikePrice"), 0.0)
    trade_price = _safe_float(raw.get("price") or raw.get("optionPrice") or raw.get("tradePrice"), 0.0)
    contracts = int(_safe_float(raw.get("size") or raw.get("quantity") or raw.get("contracts"), 0))
    trade_side_code = str(raw.get("tradeSideCode") or raw.get("trade_side_code") or "").upper().strip()
    consolidation_type = str(raw.get("tradeConsolidationType") or raw.get("consolidation_type") or "").upper().strip()

    # Expiration: try several field names, normalize to YYYY-MM-DD
    exp_raw = str(raw.get("expiration") or raw.get("expirationDate") or raw.get("exp") or "")
    if len(exp_raw) == 8 and exp_raw.isdigit():
        # YYYYMMDD → YYYY-MM-DD
        exp_raw = f"{exp_raw[:4]}-{exp_raw[4:6]}-{exp_raw[6:]}"
    expiration = exp_raw[:10] if exp_raw else ""

    # Time (ET string)
    time_raw = str(raw.get("tradeTime") or raw.get("time") or raw.get("timestamp") or "")
    if "T" in time_raw:
        time_raw = time_raw.split("T")[-1][:8]
    elif len(time_raw) > 8:
        time_raw = time_raw[:8]
    time_et = time_raw if time_raw else _now_et_str()

    aggressor, tape_label = _classify_row(raw)
    importance = _importance_score(premium, aggressor, consolidation_type)

    return {
        "time_et":           time_et,
        "ticker":            ticker,
        "contract_type":     contract_type,
        "strike":            round(strike, 2) if strike else None,
        "expiration":        expiration,
        "premium":           round(premium, 0),
        "trade_price":       round(trade_price, 4) if trade_price else None,
        "contracts":         contracts if contracts else None,
        "trade_side_code":   trade_side_code,
        "consolidation_type": consolidation_type,
        "aggressor_side":    aggressor,
        "tape_label":        tape_label,
        "importance_score":  importance,
        # Preserve optional provider Greeks/quote context for later confirmation.
        # Missing values stay None; they are never inferred.
        "delta": _safe_float(raw.get("delta") or (raw.get("greeks") or {}).get("delta"), None),
        "bid": _safe_float(raw.get("bid") or raw.get("bidPrice"), None),
        "ask": _safe_float(raw.get("ask") or raw.get("askPrice"), None),
    }


# ---------------------------------------------------------------------------
# Summary computation
# ---------------------------------------------------------------------------

def _build_summary(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    buy_premium = sell_premium = 0.0
    sweep_count = block_count = split_count = 0
    call_premium = put_premium = 0.0

    for r in rows:
        p = _safe_float(r.get("premium"), 0.0)
        agg = r.get("aggressor_side", "NEUTRAL")
        ct = r.get("consolidation_type", "")
        ctype = r.get("contract_type", "")

        if agg == "BUY":
            buy_premium += p
        elif agg == "SELL":
            sell_premium += p

        if ct == "SWEEP":
            sweep_count += 1
        elif ct == "BLOCK":
            block_count += 1
        elif ct == "SPLIT":
            split_count += 1

        if ctype == "CALL":
            call_premium += p
        elif ctype == "PUT":
            put_premium += p

    net_premium = buy_premium - sell_premium
    total = buy_premium + sell_premium or 1.0
    net_pct = round((net_premium / total) * 100, 1)

    if net_pct >= 25:
        tape_bias = "BULLISH"
    elif net_pct <= -25:
        tape_bias = "BEARISH"
    else:
        tape_bias = "MIXED"

    return {
        "buy_premium":   round(buy_premium, 0),
        "sell_premium":  round(sell_premium, 0),
        "net_premium":   round(net_premium, 0),
        "net_premium_pct": net_pct,
        "call_premium":  round(call_premium, 0),
        "put_premium":   round(put_premium, 0),
        "sweep_count":   sweep_count,
        "block_count":   block_count,
        "split_count":   split_count,
        "row_count":     len(rows),
        "tape_bias":     tape_bias,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_flow_tape(
    raw_rows: List[Dict[str, Any]],
    tickers: List[str],
    *,
    min_premium: float = 0.0,
) -> Dict[str, Any]:
    """Build a structured institutional flow tape from raw QuantData rows.

    Args:
        raw_rows:    Raw rows from QuantData consolidated order-flow.
        tickers:     The list of tickers that were requested.
        min_premium: Minimum dollar premium filter (applied after normalization).

    Returns a dict with 'ok', 'tickers', 'rows', 'summary'.
    """
    if not raw_rows:
        return {
            "ok": True,
            "status": "NO_FLOW_ROWS",
            "tickers": tickers,
            "rows": [],
            "summary": _build_summary([]),
            "message": "No institutional flow rows returned by QuantData.",
        }

    normalized: List[Dict[str, Any]] = []
    for raw in raw_rows:
        row = _normalize_row(raw)
        if row is None:
            continue
        if min_premium > 0 and _safe_float(row.get("premium"), 0.0) < min_premium:
            continue
        normalized.append(row)

    # Sort by importance descending, then by time descending
    normalized.sort(key=lambda r: (-r["importance_score"], r.get("time_et", "") or ""))

    return {
        "ok":      True,
        "status":  "OK",
        "tickers": tickers,
        "rows":    normalized,
        "summary": _build_summary(normalized),
    }
