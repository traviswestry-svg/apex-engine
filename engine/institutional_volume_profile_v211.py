"""APEX 21.1 — Institutional Volume Profile Intelligence.

Read-only synthesis over existing profile/market data. It never fetches data or
mutates trading state. Colors describe activity state, not trade instructions.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List

VERSION = "14.1.0_INSTITUTIONAL_VOLUME_PROFILE_INTELLIGENCE"


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _profile(last: Dict[str, Any]) -> Dict[str, Any]:
    for key in ("volume_profile", "profile", "market_profile", "auction_profile"):
        value = last.get(key)
        if isinstance(value, dict):
            return value
    ms = last.get("market_structure") or last.get("institutional_market_structure") or {}
    return ms.get("profile") if isinstance(ms, dict) and isinstance(ms.get("profile"), dict) else {}


def _raw_levels(profile: Dict[str, Any]) -> Iterable[Any]:
    for key in ("levels", "bins", "nodes", "profile_levels", "volume_by_price"):
        value = profile.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            return [{"price": k, "volume": v} for k, v in value.items()]
    return []


def _normalise_levels(profile: Dict[str, Any], price: float) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for item in _raw_levels(profile):
        if isinstance(item, dict):
            p = _f(item.get("price") or item.get("level") or item.get("strike"))
            vol = _f(item.get("volume") or item.get("total_volume") or item.get("size"))
            previous = _f(item.get("previous_volume") or item.get("prior_volume") or item.get("volume_previous"), vol)
            delta = _f(item.get("delta") or item.get("net_delta") or item.get("imbalance"))
            bid = _f(item.get("bid_volume") or item.get("sell_volume"))
            ask = _f(item.get("ask_volume") or item.get("buy_volume"))
        else:
            continue
        if p <= 0:
            continue
        change = vol - previous
        change_pct = (change / previous * 100.0) if previous > 0 else (100.0 if vol > 0 else 0.0)
        directional = delta if delta else ask - bid
        if change_pct >= 5 or directional > max(1.0, vol * .08):
            state, color = "ACTIVE_BUILDING", "GREEN"
        elif change_pct <= -3 or (abs(change_pct) < 1 and vol > 0):
            state, color = "STALLED_OR_EXHAUSTED", "RED"
        else:
            state, color = "BALANCED", "GRAY"
        side = "BUYING" if directional > 0 else "SELLING" if directional < 0 else "NEUTRAL"
        rows.append({"price": round(p, 2), "volume": round(vol, 2), "previous_volume": round(previous, 2),
                     "change_pct": round(change_pct, 2), "delta": round(directional, 2), "side": side,
                     "state": state, "color": color, "distance_from_price": round(p-price, 2) if price else None})
    rows.sort(key=lambda x: x["price"], reverse=True)
    return rows


def _institutional_labels(levels: List[Dict[str, Any]], profile: Dict[str, Any], price: float) -> List[Dict[str, Any]]:
    labels: List[Dict[str, Any]] = []
    green = [x for x in levels if x["color"] == "GREEN"]
    red = [x for x in levels if x["color"] == "RED"]
    for row in green[:3]:
        name = "INITIATIVE_BUYERS" if row["side"] == "BUYING" else "INITIATIVE_SELLERS" if row["side"] == "SELLING" else "EXPANDING_ACCEPTANCE"
        labels.append({"type": name, "price": row["price"], "severity": "CONFIRMING"})
    for row in red[:3]:
        name = "BUYER_EXHAUSTION" if row["side"] == "BUYING" else "SELLER_EXHAUSTION" if row["side"] == "SELLING" else "STALLED_AUCTION"
        labels.append({"type": name, "price": row["price"], "severity": "CAUTION"})
    poc = _f(profile.get("poc") or profile.get("point_of_control"))
    vah = _f(profile.get("vah") or profile.get("value_area_high"))
    val = _f(profile.get("val") or profile.get("value_area_low"))
    if price and vah and price > vah:
        labels.append({"type": "ACCEPTANCE_ABOVE_VALUE" if any(x["price"] >= vah and x["color"] == "GREEN" for x in levels) else "TESTING_ABOVE_VALUE", "price": vah, "severity": "CONTEXT"})
    elif price and val and price < val:
        labels.append({"type": "ACCEPTANCE_BELOW_VALUE" if any(x["price"] <= val and x["color"] == "GREEN" for x in levels) else "TESTING_BELOW_VALUE", "price": val, "severity": "CONTEXT"})
    elif poc:
        labels.append({"type": "POC_ACCEPTANCE", "price": poc, "severity": "CONTEXT"})
    return labels


def build_volume_profile_intelligence(last: Dict[str, Any]) -> Dict[str, Any]:
    last = last if isinstance(last, dict) else {}
    profile = _profile(last)
    price = _f(last.get("price") or last.get("spx") or last.get("last") or (last.get("market_state") or {}).get("price"))
    levels = _normalise_levels(profile, price)
    green = sum(1 for x in levels if x["color"] == "GREEN")
    red = sum(1 for x in levels if x["color"] == "RED")
    state = "READY" if levels else "WARMING"
    heat = "STRONG_BUYING" if green and sum(x["delta"] for x in levels) > 0 else "STRONG_SELLING" if green and sum(x["delta"] for x in levels) < 0 else "BALANCED"
    ranked = []
    for name, keys, kind in (("POC", ("poc", "point_of_control"), "MAGNET"), ("VAH", ("vah", "value_area_high"), "RESISTANCE"), ("VAL", ("val", "value_area_low"), "SUPPORT")):
        value = next((_f(profile.get(k)) for k in keys if _f(profile.get(k)) > 0), 0)
        if value:
            ranked.append({"name": name, "price": round(value, 2), "type": kind, "rank": len(ranked)+1})
    for key, kind in (("hvn", "HVN"), ("lvn", "LVN"), ("hvns", "HVN"), ("lvns", "LVN")):
        values = profile.get(key)
        if not isinstance(values, list):
            values = [values] if values is not None else []
        for value in values[:4]:
            p = _f(value.get("price") if isinstance(value, dict) else value)
            if p:
                ranked.append({"name": kind, "price": round(p, 2), "type": "ACCEPTANCE" if kind == "HVN" else "FAST_TRAVEL", "rank": len(ranked)+1})
    return {"ok": True, "version": VERSION, "evaluated_at": _utcnow(), "ticker": last.get("ticker", "SPX"),
            "state": state, "price": price or None, "profile_available": bool(profile), "levels": levels,
            "summary": {"active_green": green, "stalled_red": red, "neutral_gray": max(0, len(levels)-green-red), "heat_state": heat},
            "institutional_labels": _institutional_labels(levels, profile, price), "ranked_levels": ranked,
            "legend": {"GREEN": "Actively building / initiative participation", "RED": "Stalled, exhausted, or no longer building", "GRAY": "Balanced / neutral auction"},
            "guardrails": {"advisory_only": True, "not_order_flow_truth": True, "broker_mutation": False}}
