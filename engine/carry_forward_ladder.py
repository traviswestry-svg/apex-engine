"""engine/carry_forward_ladder.py — Carry-Forward Levels Ladder.

WHAT THIS IS
------------
A READ-ONLY reshaper. It takes the already-computed Daily Key Levels
``structured`` payload (the exact object the Morning Brief and Evening Recap are
built from — ``DailyKeyLevels.to_dict()``) and arranges the levels into a single
top-to-bottom ladder relative to spot:

    overhead (resistance)  ->  value (the shelf around price)  ->  below (support)

It recomputes nothing and invents nothing. Every price, label and distance comes
straight from the structured levels; a level with no usable price is dropped.
Because it reads the same source the brief renders, the ladder always agrees
with the brief a trader read that morning.

This is decision-support context, not a trade call: it describes where reactions
are likely, it never says which way to bet.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


# Human labels + a one-word role for each level kind. The engine already ships a
# ``label`` on every level; this map is the fallback and also drives the role tag
# (wall / gamma / value / prior-session / opening / expected-move) the UI colors.
_KIND_META: Dict[str, Dict[str, str]] = {
    "prev_day_high":   {"label": "Prev Day High",   "role": "prior"},
    "prev_day_low":    {"label": "Prev Day Low",    "role": "prior"},
    "prev_close":      {"label": "Prev Close",      "role": "prior"},
    "prev_open":       {"label": "Prev Open",       "role": "prior"},
    "prev_settlement": {"label": "Prev Settlement", "role": "prior"},
    "overnight_high":  {"label": "Overnight High",  "role": "overnight"},
    "overnight_low":   {"label": "Overnight Low",   "role": "overnight"},
    "overnight_mid":   {"label": "Overnight Mid",   "role": "overnight"},
    "overnight_vwap":  {"label": "Overnight VWAP",  "role": "overnight"},
    "or5_high":        {"label": "OR5 High",        "role": "opening"},
    "or5_low":         {"label": "OR5 Low",         "role": "opening"},
    "or15_high":       {"label": "OR15 High",       "role": "opening"},
    "or15_low":        {"label": "OR15 Low",        "role": "opening"},
    "ib_high":         {"label": "IB High",         "role": "opening"},
    "ib_low":          {"label": "IB Low",          "role": "opening"},
    "developing_poc":  {"label": "Developing POC",  "role": "value"},
    "prev_poc":        {"label": "Prev POC",        "role": "value"},
    "composite_poc":   {"label": "Composite POC",   "role": "value"},
    "vah":             {"label": "VAH",             "role": "value"},
    "val":             {"label": "VAL",             "role": "value"},
    "composite_vah":   {"label": "Composite VAH",   "role": "value"},
    "composite_val":   {"label": "Composite VAL",   "role": "value"},
    "gamma_flip":      {"label": "Gamma Flip",      "role": "gamma"},
    "zero_gamma":      {"label": "Zero Gamma",      "role": "gamma"},
    "call_wall":       {"label": "Call Wall",       "role": "wall"},
    "put_wall":        {"label": "Put Wall",        "role": "wall"},
    "high_gamma_strike": {"label": "High Gamma Strike", "role": "gamma"},
    "low_gamma_strike":  {"label": "Low Gamma Strike",  "role": "gamma"},
    "volatility_trigger": {"label": "Volatility Trigger", "role": "gamma"},
    "em_upper":        {"label": "Expected Move Upper", "role": "expected"},
    "em_lower":        {"label": "Expected Move Lower", "role": "expected"},
}


def _num(v: Any) -> Optional[float]:
    """Coerce to float, rejecting the engine's FEED_REQUIRED sentinel and NaN."""
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):  # NaN / inf
        return None
    return f


def _meta(kind: str) -> Dict[str, str]:
    return _KIND_META.get(kind, {"label": kind.replace("_", " ").title(), "role": "level"})


def _row(level: Dict[str, Any], spot: Optional[float]) -> Optional[Dict[str, Any]]:
    price = _num(level.get("price"))
    if price is None:
        return None
    kind = str(level.get("kind") or "")
    meta = _meta(kind)
    label = str(level.get("label") or "").strip() or meta["label"]
    dist = _num(level.get("distance"))
    if dist is None and spot is not None:
        dist = round(price - spot, 2)
    return {
        "kind": kind,
        "label": label,
        "price": round(price, 2),
        "role": meta["role"],
        "distance": dist,
        "touches": _num(level.get("prior_reactions")),
        "strength": _num(level.get("strength")),
    }


def build_carry_forward_ladder(structured: Optional[Dict[str, Any]],
                               spot: Any = None) -> Dict[str, Any]:
    """Reshape a Daily Key Levels ``structured`` dict into a spot-relative ladder.

    Returns a dict the dashboard renders directly. Never raises; on missing or
    empty input it returns ``available: False`` with an explanatory reason so the
    panel can show a governed empty state instead of erroring.
    """
    try:
        s = structured if isinstance(structured, dict) else {}
        raw_levels = s.get("levels") or []
        spot_val = _num(spot)
        if spot_val is None:
            spot_val = _num(s.get("spot"))

        rows: List[Dict[str, Any]] = []
        for lv in raw_levels:
            if isinstance(lv, dict):
                r = _row(lv, spot_val)
                if r is not None:
                    rows.append(r)

        # Fold the expected-move envelope in as two levels if the engine gave one
        # but didn't already emit em_upper/em_lower rows.
        em = s.get("expected_move") or {}
        have_em = {r["kind"] for r in rows} & {"em_upper", "em_lower"}
        if not have_em:
            for kind, key in (("em_upper", "upper"), ("em_lower", "lower")):
                p = _num(em.get(key))
                if p is not None:
                    meta = _meta(kind)
                    rows.append({
                        "kind": kind, "label": meta["label"], "price": round(p, 2),
                        "role": "expected",
                        "distance": round(p - spot_val, 2) if spot_val is not None else None,
                        "touches": None, "strength": None,
                    })

        if not rows:
            return {
                "available": False,
                "reason": "No carry-forward levels yet — generate the Morning Brief for this session.",
                "spot": spot_val,
                "gamma_regime": str(s.get("gamma_regime") or "").upper() or None,
                "overhead": [], "value": [], "below": [],
                "key_pivots": {}, "nearest_above": None, "nearest_below": None,
                "plan": None,
            }

        # De-duplicate identical (kind, price) rows the pipeline can emit twice.
        seen = set()
        deduped: List[Dict[str, Any]] = []
        for r in rows:
            key = (r["kind"], r["price"])
            if key not in seen:
                seen.add(key)
                deduped.append(r)
        rows = deduped

        # Classify relative to spot. The "value shelf" is the cluster hugging
        # price — a small band so the shelf reads as one zone, as the brief does.
        overhead: List[Dict[str, Any]] = []
        value: List[Dict[str, Any]] = []
        below: List[Dict[str, Any]] = []
        if spot_val is not None:
            band = max(2.0, spot_val * 0.001)  # ~0.1% or 2pts, whichever larger — the shelf hugging price
            for r in rows:
                delta = r["price"] - spot_val
                if abs(delta) <= band:
                    value.append(r)
                elif delta > 0:
                    overhead.append(r)
                else:
                    below.append(r)
        else:
            # No spot: still return a single ordered ladder (all in "overhead"
            # slot, high to low) so the panel is useful pre-open.
            overhead = list(rows)

        overhead.sort(key=lambda r: r["price"], reverse=True)
        value.sort(key=lambda r: r["price"], reverse=True)
        below.sort(key=lambda r: r["price"], reverse=True)

        by_kind: Dict[str, float] = {}
        for r in rows:
            by_kind.setdefault(r["kind"], r["price"])
        key_pivots = {
            "gamma_flip": by_kind.get("gamma_flip") or by_kind.get("zero_gamma"),
            "put_wall": by_kind.get("put_wall"),
            "call_wall": by_kind.get("call_wall"),
        }
        key_pivots = {k: v for k, v in key_pivots.items() if v is not None}

        nearest_above = overhead[-1] if overhead else None   # lowest overhead
        nearest_below = below[0] if below else None           # highest below

        # A neutral, evidence-only one-liner. No trade call — just the map.
        plan = _plan_line(spot_val, key_pivots, value, nearest_above, nearest_below)

        return {
            "available": True,
            "spot": spot_val,
            "gamma_regime": str(s.get("gamma_regime") or "").upper() or None,
            "overhead": overhead,
            "value": value,
            "below": below,
            "key_pivots": key_pivots,
            "nearest_above": nearest_above,
            "nearest_below": nearest_below,
            "plan": plan,
            "count": len(rows),
        }
    except Exception as e:  # never raise into the caller
        return {
            "available": False,
            "reason": f"Ladder unavailable: {type(e).__name__}",
            "overhead": [], "value": [], "below": [],
            "key_pivots": {}, "nearest_above": None, "nearest_below": None,
            "plan": None,
        }


def _fmt(v: Optional[float]) -> str:
    return f"{v:,.2f}" if isinstance(v, (int, float)) else "—"


def _plan_line(spot, pivots, value, nearest_above, nearest_below) -> Optional[str]:
    """Compose a neutral map summary from whatever pivots are present."""
    parts: List[str] = []
    flip = pivots.get("gamma_flip")
    if flip is not None and spot is not None:
        side = "below" if spot < flip else "above"
        parts.append(f"{side} gamma flip {_fmt(flip)}")
    if value:
        lo = min(r["price"] for r in value)
        hi = max(r["price"] for r in value)
        parts.append(f"value shelf {_fmt(lo)}–{_fmt(hi)}" if lo != hi else f"value {_fmt(lo)}")
    if nearest_above:
        parts.append(f"first resistance {_fmt(nearest_above['price'])}")
    if nearest_below:
        parts.append(f"first support {_fmt(nearest_below['price'])}")
    pw = pivots.get("put_wall")
    if pw is not None:
        parts.append(f"put wall {_fmt(pw)}")
    return " · ".join(parts) if parts else None
