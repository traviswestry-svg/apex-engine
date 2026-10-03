"""APEX 69.10.29 — Unified Structural Map & Reversal Path Orchestration.

Read-only orchestration over existing APEX evidence. It does not invent levels,
probabilities, trade authority, or execution authority. It consolidates canonical
range context, existing market-state levels, 69.10.26 reversal timing, and any
already-present LTPE path evidence into four operator-facing objects:

1. regime_pivot
2. reaction_zones
3. destination_magnets
4. session_path_scenarios
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple

VERSION = "69.10.29_UNIFIED_STRUCTURAL_MAP_REVERSAL_PATH_ORCHESTRATION"


def _f(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _nested(m: Mapping[str, Any], *paths: str) -> Any:
    for path in paths:
        cur: Any = m
        ok = True
        for part in path.split("."):
            if not isinstance(cur, Mapping) or part not in cur:
                ok = False
                break
            cur = cur[part]
        if ok and cur is not None:
            return cur
    return None


def _unique_levels(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen = set()
    for row in rows:
        p = _f(row.get("price"))
        if p is None:
            continue
        key = (round(p, 2), str(row.get("label") or row.get("kind") or ""))
        if key in seen:
            continue
        seen.add(key)
        item = dict(row)
        item["price"] = round(p, 2)
        out.append(item)
    return out


def _pivot(last: Mapping[str, Any], ri: Mapping[str, Any]) -> Dict[str, Any]:
    ms = last.get("market_state") if isinstance(last.get("market_state"), Mapping) else {}
    dealer = last.get("dealer_positioning") if isinstance(last.get("dealer_positioning"), Mapping) else {}
    esr = ri.get("expected_session_range") if isinstance(ri.get("expected_session_range"), Mapping) else {}
    mid = _f(esr.get("mid"))
    width = None
    lo, hi = _f(esr.get("low")), _f(esr.get("high"))
    if lo is not None and hi is not None and hi > lo:
        width = hi - lo
    candidates: List[Tuple[str, float, str, int]] = []
    specs = [
        ("Gamma flip", _nested(ms, "gamma_flip"), "GAMMA_FLIP", 100),
        ("Zero gamma", _nested(ms, "zero_gamma"), "ZERO_GAMMA", 96),
        ("Gamma flip", _nested(dealer, "gamma_flip"), "GAMMA_FLIP", 100),
        ("VWAP", _nested(ms, "vwap"), "VWAP", 90),
        ("Developing POC", _nested(ms, "poc"), "POC", 86),
        ("Expected range midpoint", mid, "EXPECTED_RANGE_MID", 72),
    ]
    for label, value, kind, priority in specs:
        p = _f(value)
        if p is not None:
            candidates.append((label, p, kind, priority))
    if not candidates:
        return {"available": False, "price": None, "reason": "NO_CANONICAL_PIVOT_LEVELS"}
    tol = max(4.0, (width or 80.0) * 0.05)
    def score(c: Tuple[str, float, str, int]):
        _, price, _, priority = c
        support = sum(1 for _, p, _, _ in candidates if abs(p - price) <= tol)
        center_penalty = abs(price - mid) if mid is not None else 0.0
        return (support, priority, -center_penalty)
    label, price, kind, priority = max(candidates, key=score)
    supporters = [
        {"label": l, "price": round(p, 2), "kind": k}
        for l, p, k, _ in candidates if abs(p - price) <= tol
    ]
    spot = _f(_nested(ri, "canonical.spot"))
    state = "AT_PIVOT"
    band = max(2.0, tol * 0.5)
    if spot is not None:
        state = "ABOVE_PIVOT" if spot > price + band else "BELOW_PIVOT" if spot < price - band else "AT_PIVOT"
    return {
        "available": True, "price": round(price, 2), "kind": kind, "label": label,
        "selection_policy": "EXISTING_CANONICAL_LEVEL_ONLY",
        "confluence_count": len(supporters), "confluence_radius_points": round(tol, 2),
        "supporting_levels": supporters, "spot_state": state,
        "interpretation": "Selected from existing APEX levels; no synthetic pivot price is created.",
    }


def _reaction_zones(ri: Mapping[str, Any]) -> Dict[str, Any]:
    esr = ri.get("expected_session_range") if isinstance(ri.get("expected_session_range"), Mapping) else {}
    rr = ri.get("reversal_timing_intelligence") if isinstance(ri.get("reversal_timing_intelligence"), Mapping) else {}
    bands = rr.get("extension_bands") if isinstance(rr.get("extension_bands"), Mapping) else {}
    lo, hi = _f(esr.get("low")), _f(esr.get("high"))
    if lo is None or hi is None:
        return {"available": False, "upper": None, "lower": None}
    upper_ext = [
        x for x in (bands.get("upper") or [])
        if isinstance(x, Mapping) and _f(x.get("price")) is not None
    ]
    lower_ext = [
        x for x in (bands.get("lower") or [])
        if isinstance(x, Mapping) and _f(x.get("price")) is not None
    ]
    upper_high = max([hi] + [float(x["price"]) for x in upper_ext])
    lower_low = min([lo] + [float(x["price"]) for x in lower_ext])
    existing = ri.get("immediate_reaction_zones") if isinstance(ri.get("immediate_reaction_zones"), list) else []
    def existing_for(side: str):
        return next((z for z in existing if str(z.get("side") or "").upper() == side), None)
    u0, l0 = existing_for("UPPER"), existing_for("LOWER")
    upper = {
        "side": "UPPER", "low": round(min(hi, _f((u0 or {}).get("low")) or hi), 2),
        "high": round(max(upper_high, _f((u0 or {}).get("high")) or hi), 2),
        "canonical_boundary": round(hi, 2), "extension_limit_percent": 30,
        "state": rr.get("state") if rr.get("side") == "UPPER" else "INACTIVE",
        "reasons": list((u0 or {}).get("reasons") or []) + ["Expected Session Range upper boundary", "10/20/30% range extensions"],
    }
    lower = {
        "side": "LOWER", "low": round(min(lower_low, _f((l0 or {}).get("low")) or lo), 2),
        "high": round(max(lo, _f((l0 or {}).get("high")) or lo), 2),
        "canonical_boundary": round(lo, 2), "extension_limit_percent": 30,
        "state": rr.get("state") if rr.get("side") == "LOWER" else "INACTIVE",
        "reasons": list((l0 or {}).get("reasons") or []) + ["Expected Session Range lower boundary", "10/20/30% range extensions"],
    }
    return {"available": True, "upper": upper, "lower": lower,
            "policy": "SEARCH_ZONE_NOT_ENTRY_SIGNAL"}


def _destination_magnets(last: Mapping[str, Any], ri: Mapping[str, Any]) -> Dict[str, Any]:
    spot = _f(_nested(ri, "canonical.spot"))
    if spot is None:
        return {"available": False, "direction": None, "targets": []}
    rr = ri.get("reversal_timing_intelligence") if isinstance(ri.get("reversal_timing_intelligence"), Mapping) else {}
    side, state = str(rr.get("side") or "NONE"), str(rr.get("state") or "")
    direction = "DOWN" if side == "UPPER" and state in {"REVERSAL_DEVELOPING", "REVERSAL_CONFIRMED_ADVISORY"} else \
                "UP" if side == "LOWER" and state in {"REVERSAL_DEVELOPING", "REVERSAL_CONFIRMED_ADVISORY"} else None
    ms = last.get("market_state") if isinstance(last.get("market_state"), Mapping) else {}
    esr = ri.get("expected_session_range") if isinstance(ri.get("expected_session_range"), Mapping) else {}
    rows: List[Dict[str, Any]] = []
    for label, value, kind, rank in [
        ("VWAP", ms.get("vwap"), "VWAP", 100),
        ("Developing POC", ms.get("poc"), "POC", 96),
        ("Expected range midpoint", esr.get("mid"), "EXPECTED_RANGE_MID", 92),
        ("VAL", ms.get("val"), "VAL", 88), ("VAH", ms.get("vah"), "VAH", 88),
        ("Put wall", ms.get("put_wall"), "PUT_WALL", 84), ("Call wall", ms.get("call_wall"), "CALL_WALL", 84),
        ("Expected range low", esr.get("low"), "EXPECTED_RANGE_LOW", 80),
        ("Expected range high", esr.get("high"), "EXPECTED_RANGE_HIGH", 80),
    ]:
        p = _f(value)
        if p is not None:
            rows.append({"label": label, "price": p, "kind": kind, "base_rank": rank, "source": "CANONICAL_CONTEXT"})
    for item in ri.get("intermediate_targets") or []:
        if not isinstance(item, Mapping):
            continue
        p = _f(item.get("price"))
        if p is not None:
            rows.append({"label": item.get("label") or item.get("kind") or "Intermediate level", "price": p,
                         "kind": item.get("kind") or "INTERMEDIATE", "base_rank": 82, "source": "RANGE_INTELLIGENCE"})
    mags = last.get("strike_magnets") or {}
    mag_rows = mags.get("magnets") if isinstance(mags, Mapping) else mags if isinstance(mags, list) else []
    for m in mag_rows or []:
        if not isinstance(m, Mapping):
            continue
        p = _f(m.get("strike"))
        if p is not None:
            rows.append({"label": f"Strike magnet {m.get('type') or ''}".strip(), "price": p,
                         "kind": "STRIKE_MAGNET", "base_rank": 90, "source": "STRIKE_MAGNETS"})
    rows = _unique_levels(rows)
    if direction:
        rows = [r for r in rows if (r["price"] < spot if direction == "DOWN" else r["price"] > spot)]
    for r in rows:
        r["distance_points"] = round(abs(r["price"] - spot), 2)
        r["orchestration_score"] = round(float(r.pop("base_rank", 70)) - min(35.0, r["distance_points"] * 0.35), 1)
    rows.sort(key=lambda r: (-r["orchestration_score"], r["distance_points"]))
    targets = rows[:3]
    for i, r in enumerate(targets, 1):
        r["ordinal"] = i
    return {"available": bool(targets), "direction": direction or "BOTH_SIDES_MONITOR",
            "targets": targets, "probability_policy": "NO_NEW_PROBABILITY_INFERENCE"}


def _scenarios(ri: Mapping[str, Any], pivot: Mapping[str, Any], zones: Mapping[str, Any], magnets: Mapping[str, Any]) -> List[Dict[str, Any]]:
    rr = ri.get("reversal_timing_intelligence") if isinstance(ri.get("reversal_timing_intelligence"), Mapping) else {}
    return [
        {"name": "UPPER_REJECTION", "trigger_state": "REVERSAL_DEVELOPING_OR_CONFIRMED",
         "zone": zones.get("upper"), "path_direction": "DOWN",
         "active": rr.get("side") == "UPPER" and rr.get("state") in {"REVERSAL_DEVELOPING", "REVERSAL_CONFIRMED_ADVISORY"},
         "destinations": magnets.get("targets") if magnets.get("direction") == "DOWN" else []},
        {"name": "LOWER_REJECTION", "trigger_state": "REVERSAL_DEVELOPING_OR_CONFIRMED",
         "zone": zones.get("lower"), "path_direction": "UP",
         "active": rr.get("side") == "LOWER" and rr.get("state") in {"REVERSAL_DEVELOPING", "REVERSAL_CONFIRMED_ADVISORY"},
         "destinations": magnets.get("targets") if magnets.get("direction") == "UP" else []},
        {"name": "RANGE_ACCEPTANCE_CONTINUATION", "trigger_state": "EXTENSION_WITHOUT_REJECTION",
         "active": rr.get("state") == "EXTENSION_ACTIVE", "pivot": pivot,
         "note": "Do not force a reversal while price is accepted outside the canonical envelope."},
    ]


def build_unified_structural_map(last_result: Mapping[str, Any], range_intelligence: Mapping[str, Any]) -> Dict[str, Any]:
    last = last_result if isinstance(last_result, Mapping) else {}
    ri = range_intelligence if isinstance(range_intelligence, Mapping) else {}
    if not ri.get("available"):
        return {"available": False, "version": VERSION, "state": "UNAVAILABLE",
                "quality_flags": ["RANGE_INTELLIGENCE_UNAVAILABLE"]}
    pivot = _pivot(last, ri)
    zones = _reaction_zones(ri)
    magnets = _destination_magnets(last, ri)
    scenarios = _scenarios(ri, pivot, zones, magnets)
    rr = ri.get("reversal_timing_intelligence") if isinstance(ri.get("reversal_timing_intelligence"), Mapping) else {}
    return {
        "available": True, "version": VERSION,
        "regime_pivot": pivot,
        "reaction_zones": zones,
        "destination_magnets": magnets,
        "session_path_scenarios": scenarios,
        "reversal_path": {
            "state": rr.get("state"), "side": rr.get("side"),
            "timing": rr.get("timing"), "contract_horizon_advisory": rr.get("contract_horizon_advisory"),
            "evidence_score": _nested(rr, "reversal_evidence.normalized_score"),
        },
        "governance": {
            "orchestration_only": True, "uses_existing_levels_only": True,
            "creates_new_probability": False, "changes_trade_decisions": False,
            "execution_authority": False, "automatic_order_submission": False,
        },
    }


def refresh_unified_structural_map(range_intelligence: Dict[str, Any]) -> Dict[str, Any]:
    """Refresh timing/state fields after 69.10.26 attaches price-history dwell."""
    ri = range_intelligence if isinstance(range_intelligence, dict) else {}
    sm = ri.get("unified_structural_map") if isinstance(ri.get("unified_structural_map"), dict) else None
    rr = ri.get("reversal_timing_intelligence") if isinstance(ri.get("reversal_timing_intelligence"), Mapping) else {}
    if sm is not None:
        sm["reversal_path"] = {
            "state": rr.get("state"), "side": rr.get("side"), "timing": rr.get("timing"),
            "contract_horizon_advisory": rr.get("contract_horizon_advisory"),
            "evidence_score": _nested(rr, "reversal_evidence.normalized_score"),
        }
        zones = sm.get("reaction_zones") if isinstance(sm.get("reaction_zones"), dict) else {}
        if isinstance(zones.get("upper"), dict):
            zones["upper"]["state"] = rr.get("state") if rr.get("side") == "UPPER" else "INACTIVE"
        if isinstance(zones.get("lower"), dict):
            zones["lower"]["state"] = rr.get("state") if rr.get("side") == "LOWER" else "INACTIVE"
    return ri
