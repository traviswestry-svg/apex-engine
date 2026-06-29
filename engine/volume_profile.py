from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple
import math


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        v = float(value)
        if math.isnan(v) or math.isinf(v):
            return default
        return v
    except Exception:
        return default


def _round_to_step(price: float, step: float) -> float:
    if step <= 0:
        return round(price, 2)
    return round(round(price / step) * step, 4)


def _infer_tick_size(prices: List[float], ticker: str = "SPX") -> float:
    t = (ticker or "").upper()
    if t in {"SPX", "SPXW", "I:SPX", "$SPX", "ES", "ES1!", "/ES"}:
        return 1.0
    if t in {"SPY", "QQQ", "IWM"}:
        return 0.05
    if not prices:
        return 0.25
    p = max(prices)
    if p >= 1000:
        return 1.0
    if p >= 200:
        return 0.25
    return 0.05


def _extract_bar(row: Dict[str, Any]) -> Optional[Dict[str, float]]:
    # Supports Polygon bars (o/h/l/c/v/t) and frontend chart bars (open/high/low/close/volume/ts/time).
    high = _safe_float(row.get("h", row.get("high")), 0.0)
    low = _safe_float(row.get("l", row.get("low")), 0.0)
    close = _safe_float(row.get("c", row.get("close")), 0.0)
    open_ = _safe_float(row.get("o", row.get("open")), close)
    vol = _safe_float(row.get("v", row.get("volume")), 0.0)
    ts = _safe_float(row.get("t", row.get("ts", row.get("time"))), 0.0)
    if high <= 0 or low <= 0 or close <= 0 or high < low:
        return None
    return {"open": open_, "high": high, "low": low, "close": close, "volume": vol, "ts": ts}


def _profile_from_bars(
    bars: Iterable[Dict[str, Any]],
    *,
    ticker: str = "SPX",
    tick_size: Optional[float] = None,
    value_area_pct: float = 0.70,
    max_nodes: int = 8,
) -> Dict[str, Any]:
    parsed = [b for b in (_extract_bar(x) for x in bars or []) if b]
    if not parsed:
        return {
            "available": False,
            "status": "NO_BARS",
            "profile_type": "UNAVAILABLE",
            "message": "No usable bars supplied to volume profile engine.",
            "levels": {},
            "profile": [],
        }

    prices = [p for b in parsed for p in (b["high"], b["low"], b["close"])]
    step = float(tick_size or _infer_tick_size(prices, ticker))
    has_real_volume = sum(1 for b in parsed if b["volume"] > 0) >= max(3, int(len(parsed) * 0.25))
    profile_type = "VOLUME_PROFILE" if has_real_volume else "ACTIVITY_PROFILE_NO_VOLUME"

    profile: Dict[float, float] = {}
    total_activity = 0.0

    for b in parsed:
        low_bucket = _round_to_step(b["low"], step)
        high_bucket = _round_to_step(b["high"], step)
        if high_bucket < low_bucket:
            high_bucket, low_bucket = low_bucket, high_bucket
        levels = []
        cur = low_bucket
        # Guard against excessive loops if step is tiny.
        guard = 0
        while cur <= high_bucket + step * 0.5 and guard < 2500:
            levels.append(round(cur, 4))
            cur += step
            guard += 1
        if not levels:
            levels = [_round_to_step((b["high"] + b["low"] + b["close"]) / 3.0, step)]

        if has_real_volume:
            activity = max(b["volume"], 0.0)
        else:
            # Honest fallback for SPX index candles where exchange volume is zero:
            # treat wider candles and directional participation as higher activity.
            activity = max(b["high"] - b["low"], step) / step
        total_activity += activity
        per_level = activity / len(levels) if levels else 0.0
        for level in levels:
            profile[level] = profile.get(level, 0.0) + per_level

    if not profile:
        return {
            "available": False,
            "status": "EMPTY_PROFILE",
            "profile_type": profile_type,
            "message": "No usable profile bins produced.",
            "levels": {},
            "profile": [],
        }

    sorted_levels = sorted(profile)
    poc = max(profile.items(), key=lambda kv: kv[1])[0]
    total = sum(profile.values()) or 1.0

    # Value Area: expand from POC until 70% of total activity is covered.
    target = total * max(0.50, min(value_area_pct, 0.90))
    idx = sorted_levels.index(poc)
    lo = hi = idx
    included = profile[poc]
    while included < target and (lo > 0 or hi < len(sorted_levels) - 1):
        lo_vol = profile[sorted_levels[lo - 1]] if lo > 0 else -1
        hi_vol = profile[sorted_levels[hi + 1]] if hi < len(sorted_levels) - 1 else -1
        if hi_vol >= lo_vol and hi < len(sorted_levels) - 1:
            hi += 1
            included += profile[sorted_levels[hi]]
        elif lo > 0:
            lo -= 1
            included += profile[sorted_levels[lo]]
        else:
            break

    val = sorted_levels[lo]
    vah = sorted_levels[hi]

    rows = [
        {"price": round(price, 2), "activity": round(activity, 4), "pct": round(activity / total * 100, 3)}
        for price, activity in sorted(profile.items())
    ]
    rows_desc = sorted(rows, key=lambda x: x["activity"], reverse=True)
    hvn = [r["price"] for r in rows_desc[:max_nodes]]
    # LVN: low activity nodes inside the value area, useful as rejection/fast-travel zones.
    inside_va = [r for r in rows if val <= r["price"] <= vah]
    lvn = [r["price"] for r in sorted(inside_va, key=lambda x: x["activity"])[:max_nodes]]

    return {
        "available": True,
        "status": "OK",
        "ticker": ticker,
        "profile_type": profile_type,
        "bar_count": len(parsed),
        "tick_size": step,
        "value_area_percent": round(value_area_pct * 100, 1),
        "has_real_volume": has_real_volume,
        "total_activity": round(total_activity, 4),
        "levels": {
            "poc": round(poc, 2),
            "vah": round(vah, 2),
            "val": round(val, 2),
            "hvn": hvn,
            "lvn": lvn,
        },
        "profile": rows,
        "message": "Volume profile from real bar volume." if has_real_volume else "SPX/index volume unavailable; using transparent activity profile fallback.",
    }


def build_volume_profile(
    bars: Iterable[Dict[str, Any]],
    *,
    ticker: str = "SPX",
    profile_range: str = "session",
    tick_size: Optional[float] = None,
    value_area_pct: float = 0.70,
) -> Dict[str, Any]:
    result = _profile_from_bars(
        bars,
        ticker=ticker,
        tick_size=tick_size,
        value_area_pct=value_area_pct,
    )
    result["range"] = profile_range
    return result


def build_previous_day_profile(
    bars: Iterable[Dict[str, Any]],
    *,
    ticker: str = "SPX",
    tick_size: Optional[float] = None,
) -> Dict[str, Any]:
    return build_volume_profile(bars, ticker=ticker, profile_range="previous_day", tick_size=tick_size)
