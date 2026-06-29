from __future__ import annotations

from typing import Any, Dict, List, Optional


def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _direction(delta: Optional[float], threshold: float = 1.0) -> str:
    if delta is None:
        return "UNKNOWN"
    if delta >= threshold:
        return "RISING"
    if delta <= -threshold:
        return "FALLING"
    return "STABLE"


def build_auction_state(
    *,
    current_price: Any = None,
    current_profile: Optional[Dict[str, Any]] = None,
    prior_profile: Optional[Dict[str, Any]] = None,
    previous_day_profile: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Convert volume-profile levels into an auction/market-acceptance read.

    This module is intentionally data-honest. If no real volume exists, the
    upstream profile will identify itself as an ACTIVITY profile rather than a
    futures DOM or true volume profile.
    """
    cp = _safe_float(current_price)
    profile = current_profile or {}
    levels = profile.get("levels") or {}
    prior_levels = (prior_profile or {}).get("levels") or {}
    prev_day_levels = (previous_day_profile or {}).get("levels") or {}

    poc = _safe_float(levels.get("poc"))
    vah = _safe_float(levels.get("vah"))
    val = _safe_float(levels.get("val"))
    prior_poc = _safe_float(prior_levels.get("poc"))
    prev_poc = _safe_float(prev_day_levels.get("poc"))

    poc_delta = round(poc - prior_poc, 2) if poc is not None and prior_poc is not None else None
    poc_migration = _direction(poc_delta, threshold=1.0)

    if cp is None or poc is None or vah is None or val is None:
        auction_state = "WAITING_FOR_PROFILE"
        location = "UNKNOWN"
        narrative = "Auction state unavailable until price and profile levels are available."
    else:
        if cp > vah:
            location = "ABOVE_VALUE"
            auction_state = "ACCEPTING_HIGHER" if poc_migration == "RISING" else "TESTING_UPPER_VALUE"
            narrative = "Price is trading above value. Buyers are attempting higher-price acceptance."
        elif cp < val:
            location = "BELOW_VALUE"
            auction_state = "ACCEPTING_LOWER" if poc_migration == "FALLING" else "TESTING_LOWER_VALUE"
            narrative = "Price is trading below value. Sellers are attempting lower-price acceptance."
        elif cp >= poc:
            location = "UPPER_VALUE"
            auction_state = "BALANCED_BULLISH_LEAN" if poc_migration != "FALLING" else "BALANCED_WITH_SELLER_PRESSURE"
            narrative = "Price is inside value and above POC. Buyers have a mild auction advantage."
        else:
            location = "LOWER_VALUE"
            auction_state = "BALANCED_BEARISH_LEAN" if poc_migration != "RISING" else "BALANCED_WITH_BUYER_SUPPORT"
            narrative = "Price is inside value and below POC. Sellers have a mild auction advantage."

        if poc_migration == "RISING":
            narrative += " POC is migrating upward, indicating acceptance of higher prices."
        elif poc_migration == "FALLING":
            narrative += " POC is migrating downward, indicating acceptance of lower prices."
        elif poc_migration == "STABLE":
            narrative += " POC is stable, suggesting a balanced auction."

    return {
        "available": bool(profile.get("available")),
        "profile_type": profile.get("profile_type"),
        "auction_state": auction_state,
        "location": location,
        "current_price": cp,
        "poc": poc,
        "vah": vah,
        "val": val,
        "prior_poc": prior_poc,
        "previous_day_poc": prev_poc,
        "poc_delta": poc_delta,
        "poc_migration": poc_migration,
        "narrative": narrative,
        "quality_flags": [
            *(profile.get("quality_flags") or []),
            *([] if profile.get("has_real_volume") else ["NO_REAL_VOLUME_USING_ACTIVITY_PROFILE"]),
        ],
    }
