"""APEX 69.10.26 — Expected Range Reversal Timing Intelligence.

Advisory-only reversal context layered on top of the canonical Expected Session
Range.  The module does NOT authorize trades or orders.  It answers four narrow
questions for an already-computed range projection:

1. How far has SPX extended beyond the canonical session envelope?
2. Has price merely reached the edge, or has it rejected back through it?
3. Is existing flow/structure evidence beginning to agree with a reversal?
4. Which option horizon is mechanically better aligned with the amount of time
   the reversal may need to develop?

The range boundary is treated as a search zone, never as an exact reversal price.
Missing evidence remains unavailable rather than being synthesized.
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional
from zoneinfo import ZoneInfo

from .canonical_persistence import connect as canonical_connect
from .persistent_store import persistent_sqlite_path

VERSION = "69.10.26_EXPECTED_RANGE_REVERSAL_TIMING_INTELLIGENCE"
_ET = ZoneInfo("America/New_York")
_PRICE_DB = persistent_sqlite_path("APEX_EVIDENCE_PIPELINE_DB", "apex_evidence_pipeline.db")


def _f(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _u(value: Any) -> str:
    return str(value or "").strip().upper()


def _nested(mapping: Mapping[str, Any], *paths: str) -> Any:
    for path in paths:
        cur: Any = mapping
        ok = True
        for part in path.split("."):
            if not isinstance(cur, Mapping) or part not in cur:
                ok = False
                break
            cur = cur[part]
        if ok and cur is not None:
            return cur
    return None


def build_extension_bands(low: Any, high: Any) -> Dict[str, Any]:
    """Return 10/20/30% full-range extensions above and below the envelope."""
    lo, hi = _f(low), _f(high)
    if lo is None or hi is None or hi <= lo:
        return {"available": False, "range_points": None, "upper": [], "lower": []}
    width = hi - lo
    upper = []
    lower = []
    for pct in (10, 20, 30):
        step = width * (pct / 100.0)
        upper.append({"percent": pct, "price": round(hi + step, 2)})
        lower.append({"percent": pct, "price": round(lo - step, 2)})
    return {
        "available": True,
        "range_points": round(width, 2),
        "upper": upper,
        "lower": lower,
        "method": "FULL_EXPECTED_SESSION_RANGE_PERCENT",
    }


def _location(price: float, lo: float, hi: float, width: float) -> Dict[str, Any]:
    edge_buffer = max(1.0, width * 0.02)
    if price > hi:
        ext = (price - hi) / width * 100.0
        bucket = 1 if ext < 10 else 2 if ext < 20 else 3 if ext < 30 else 4
        return {"side": "UPPER", "state": f"UPPER_EXTENSION_{bucket}",
                "extension_points": round(price - hi, 2), "extension_percent": round(ext, 1)}
    if price < lo:
        ext = (lo - price) / width * 100.0
        bucket = 1 if ext < 10 else 2 if ext < 20 else 3 if ext < 30 else 4
        return {"side": "LOWER", "state": f"LOWER_EXTENSION_{bucket}",
                "extension_points": round(lo - price, 2), "extension_percent": round(ext, 1)}
    if price >= hi - edge_buffer:
        return {"side": "UPPER", "state": "UPPER_EDGE", "extension_points": 0.0, "extension_percent": 0.0}
    if price <= lo + edge_buffer:
        return {"side": "LOWER", "state": "LOWER_EDGE", "extension_points": 0.0, "extension_percent": 0.0}
    return {"side": "NONE", "state": "INSIDE_RANGE", "extension_points": 0.0, "extension_percent": 0.0}


def _flow_confirmation(last: Mapping[str, Any], reversal_side: str) -> Dict[str, Any]:
    flow = _u(_nested(last, "market_state.flow_bias", "institutional_intelligence.flow_bias", "flow_bias"))
    wanted = "BEARISH" if reversal_side == "UPPER" else "BULLISH"
    available = flow in ("BULLISH", "BEARISH", "NEUTRAL", "BALANCED")
    return {"available": available, "observed": flow or None, "wanted": wanted,
            "confirmed": bool(available and flow == wanted)}


def _structure_confirmation(last: Mapping[str, Any], reversal_side: str) -> Dict[str, Any]:
    direction = _u(_nested(
        last,
        "institutional_market_structure.acceptance_rejection.direction",
        "institutional_market_structure.direction",
        "market_structure.direction",
        "market_state.structure_direction",
    ))
    wanted = "BEARISH" if reversal_side == "UPPER" else "BULLISH"
    available = direction in ("BULLISH", "BEARISH", "NEUTRAL")
    return {"available": available, "observed": direction or None, "wanted": wanted,
            "confirmed": bool(available and direction == wanted)}


def _absorption_confirmation(last: Mapping[str, Any], reversal_side: str) -> Dict[str, Any]:
    absorption = _nested(last, "market_microstructure.interaction.absorption_candidate",
                         "microstructure.interaction.absorption_candidate")
    if not isinstance(absorption, Mapping):
        return {"available": False, "observed": None, "wanted": None, "confirmed": False}
    side = _u(absorption.get("side"))
    detected = bool(absorption.get("detected"))
    wanted = "ASK_SELLER" if reversal_side == "UPPER" else "BID_BUYER"
    eligible = bool(absorption.get("eligible", detected))
    return {"available": eligible, "observed": side or None, "wanted": wanted,
            "confirmed": bool(eligible and detected and side == wanted)}


def _displacement_confirmation(price: float, session_high: Optional[float], session_low: Optional[float],
                               width: float, reversal_side: str) -> Dict[str, Any]:
    threshold = max(4.0, width * 0.06)
    if reversal_side == "UPPER" and session_high is not None:
        moved = max(0.0, session_high - price)
    elif reversal_side == "LOWER" and session_low is not None:
        moved = max(0.0, price - session_low)
    else:
        return {"available": False, "points": None, "threshold_points": round(threshold, 2), "confirmed": False}
    return {"available": True, "points": round(moved, 2), "threshold_points": round(threshold, 2),
            "confirmed": moved >= threshold}


def _rejection_proxy(price: float, session_high: Optional[float], session_low: Optional[float],
                     lo: float, hi: float, reversal_side: str) -> Dict[str, Any]:
    """Conservative sweep/rejection proxy based only on observed RTH extremes.

    Upper: session traded through/at the upper envelope and current price returned
    back below it.  Lower is symmetric.  This is labelled PROXY because it does
    not claim exact resting-liquidity execution.
    """
    if reversal_side == "UPPER":
        touched = session_high is not None and session_high >= hi
        rejected = bool(touched and price < hi)
        extreme = session_high
    elif reversal_side == "LOWER":
        touched = session_low is not None and session_low <= lo
        rejected = bool(touched and price > lo)
        extreme = session_low
    else:
        touched = rejected = False
        extreme = None
    return {
        "available": session_high is not None or session_low is not None,
        "method": "SESSION_EXTREME_RETURN_THROUGH_ENVELOPE_PROXY",
        "touched": bool(touched),
        "rejected_back_inside": bool(rejected),
        "session_extreme": round(extreme, 2) if extreme is not None else None,
    }


def _score_evidence(location: Mapping[str, Any], rejection: Mapping[str, Any],
                    flow: Mapping[str, Any], structure: Mapping[str, Any],
                    absorption: Mapping[str, Any], displacement: Mapping[str, Any]) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []

    def add(name: str, weight: int, available: bool, confirmed: bool, detail: str) -> None:
        rows.append({"name": name, "weight": weight, "available": bool(available),
                     "confirmed": bool(confirmed), "points": weight if available and confirmed else 0,
                     "detail": detail})

    side = location.get("side")
    at_edge = side in ("UPPER", "LOWER")
    add("range_location", 20, True, at_edge, str(location.get("state") or "UNKNOWN"))
    add("edge_rejection_proxy", 20, bool(rejection.get("available")), bool(rejection.get("rejected_back_inside")),
        "returned through canonical envelope" if rejection.get("rejected_back_inside") else "not yet rejected through envelope")
    add("order_flow_shift", 20, bool(flow.get("available")), bool(flow.get("confirmed")),
        str(flow.get("observed") or "UNAVAILABLE"))
    add("structure_shift", 15, bool(structure.get("available")), bool(structure.get("confirmed")),
        str(structure.get("observed") or "UNAVAILABLE"))
    # Absorption is combined with displacement as the final 25-point evidence family.
    add("absorption", 10, bool(absorption.get("available")), bool(absorption.get("confirmed")),
        str(absorption.get("observed") or "UNAVAILABLE"))
    add("displacement", 15, bool(displacement.get("available")), bool(displacement.get("confirmed")),
        f"{displacement.get('points')} pts" if displacement.get("points") is not None else "UNAVAILABLE")

    score = sum(int(r["points"]) for r in rows)
    available_points = sum(int(r["weight"]) for r in rows if r["available"])
    normalized = round(score / available_points * 100.0, 1) if available_points else None
    return {"score": score, "available_points": available_points,
            "normalized_score": normalized, "evidence": rows}


def _state(side: str, location: Mapping[str, Any], rejection: Mapping[str, Any], score: Mapping[str, Any]) -> str:
    if side not in ("UPPER", "LOWER"):
        return "RANGE_MONITOR"
    rejected = bool(rejection.get("rejected_back_inside"))
    norm = _f(score.get("normalized_score"), 0.0) or 0.0
    if rejected and norm >= 70:
        return "REVERSAL_CONFIRMED_ADVISORY"
    if rejected and norm >= 50:
        return "REVERSAL_DEVELOPING"
    if str(location.get("state") or "").startswith(("UPPER_EXTENSION", "LOWER_EXTENSION")):
        return "EXTENSION_ACTIVE"
    return "EXHAUSTION_WATCH"


def _contract_horizon(state: str) -> Dict[str, Any]:
    """Strategy-alignment advisory; never an order or execution instruction."""
    if state == "REVERSAL_CONFIRMED_ADVISORY":
        return {"preferred_dte": 1, "delta_range": [0.45, 0.60],
                "rationale": "Reversal evidence is aligned; 1DTE preserves time while retaining directional response."}
    if state in ("REVERSAL_DEVELOPING", "EXTENSION_ACTIVE", "EXHAUSTION_WATCH"):
        return {"preferred_dte": 2, "delta_range": [0.50, 0.65],
                "rationale": "Timing remains uncertain; additional time is favored over low-delta 0DTE exposure."}
    return {"preferred_dte": None, "delta_range": None,
            "rationale": "No edge reversal is active; contract selection is not promoted."}


def build_range_reversal_intelligence(last_result: Mapping[str, Any], range_intelligence: Mapping[str, Any]) -> Dict[str, Any]:
    ri = range_intelligence if isinstance(range_intelligence, Mapping) else {}
    last = last_result if isinstance(last_result, Mapping) else {}
    esr = ri.get("expected_session_range") if isinstance(ri.get("expected_session_range"), Mapping) else {}
    lo, hi = _f(esr.get("low")), _f(esr.get("high"))
    price = _f(_nested(ri, "canonical.spot"))
    bands = build_extension_bands(lo, hi)
    if not bands.get("available") or price is None:
        return {
            "available": False, "version": VERSION, "state": "UNAVAILABLE",
            "extension_bands": bands,
            "quality_flags": ["CANONICAL_RANGE_OR_SPOT_UNAVAILABLE"],
            "governance": {"advisory_only": True, "changes_trade_decisions": False,
                           "execution_authority": False, "automatic_order_submission": False},
        }

    width = float(bands["range_points"])
    location = _location(price, float(lo), float(hi), width)
    session_high = _f(ri.get("session_high"))
    session_low = _f(ri.get("session_low"))

    # If current price is back inside after touching an edge, infer the relevant
    # reversal side from the observed session extreme rather than dropping to NONE.
    side = str(location.get("side") or "NONE")
    upper_touched = session_high is not None and session_high >= float(hi)
    lower_touched = session_low is not None and session_low <= float(lo)
    if side == "NONE":
        if upper_touched and not lower_touched:
            side = "UPPER"
        elif lower_touched and not upper_touched:
            side = "LOWER"
        elif upper_touched and lower_touched:
            # Use the latest/current half of the range as a deterministic tie-break.
            side = "UPPER" if price >= (float(lo) + float(hi)) / 2.0 else "LOWER"

    rejection = _rejection_proxy(price, session_high, session_low, float(lo), float(hi), side)
    flow = _flow_confirmation(last, side)
    structure = _structure_confirmation(last, side)
    absorption = _absorption_confirmation(last, side)
    displacement = _displacement_confirmation(price, session_high, session_low, width, side)
    scored = _score_evidence({**location, "side": side}, rejection, flow, structure, absorption, displacement)
    state = _state(side, location, rejection, scored)

    return {
        "available": True,
        "version": VERSION,
        "state": state,
        "side": side,
        "location": location,
        "extension_bands": bands,
        "reversal_evidence": {
            "score": scored["score"],
            "available_points": scored["available_points"],
            "normalized_score": scored["normalized_score"],
            "items": scored["evidence"],
            "rejection_proxy": rejection,
            "flow": flow,
            "structure": structure,
            "absorption": absorption,
            "displacement": displacement,
        },
        "contract_horizon_advisory": _contract_horizon(state),
        "timing": {"available": False, "source": "PRICE_HISTORY_NOT_ATTACHED"},
        "interpretation": _interpret(state, side, location, rejection),
        "quality_flags": ["LIQUIDITY_SWEEP_IS_CONSERVATIVE_PROXY"] if rejection.get("available") else ["RTH_EXTREMES_UNAVAILABLE"],
        "governance": {
            "advisory_only": True,
            "range_boundary_is_not_entry_signal": True,
            "reversal_state_is_not_trade_authorization": True,
            "changes_trade_decisions": False,
            "execution_authority": False,
            "automatic_order_submission": False,
        },
    }


def _interpret(state: str, side: str, location: Mapping[str, Any], rejection: Mapping[str, Any]) -> str:
    if state == "RANGE_MONITOR":
        return "Price remains inside the canonical range; monitor the envelope before evaluating reversal evidence."
    if state == "EXTENSION_ACTIVE":
        return "Price is extending beyond the expected range. Treat the boundary as a search zone, not an exact top/bottom; wait for rejection and confirmation."
    if state == "EXHAUSTION_WATCH":
        return f"{side.title()} edge is active, but reversal confirmation is incomplete. Avoid treating the range boundary itself as the entry trigger."
    if state == "REVERSAL_DEVELOPING":
        return f"{side.title()} edge has rejected back through the envelope and some confirming evidence is aligned; reversal remains developing."
    if state == "REVERSAL_CONFIRMED_ADVISORY":
        return f"{side.title()} edge rejection is accompanied by aligned evidence. This is advisory confirmation only, not execution authority."
    return "Reversal timing context unavailable."


def _parse_ts(value: Any) -> Optional[dt.datetime]:
    if not value:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        out = dt.datetime.fromisoformat(text)
        if out.tzinfo is None:
            out = out.replace(tzinfo=dt.timezone.utc)
        return out.astimezone(dt.timezone.utc)
    except Exception:
        return None


def timing_from_samples(samples: Iterable[Mapping[str, Any]], *, low: float, high: float,
                        now: Optional[dt.datetime] = None) -> Dict[str, Any]:
    """Compute edge timing from genuine price samples without fabricating gaps."""
    rows = []
    for row in samples:
        ts = _parse_ts(row.get("observed_at"))
        price = _f(row.get("price"))
        if ts is not None and price is not None:
            rows.append((ts, price))
    rows.sort(key=lambda x: x[0])
    if not rows:
        return {"available": False, "source": "PRICE_SAMPLES", "reason": "NO_SAMPLES"}

    now_utc = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    touched = [(ts, p, "UPPER" if p >= high else "LOWER" if p <= low else None) for ts, p in rows if p >= high or p <= low]
    if not touched:
        return {"available": True, "source": "PRICE_SAMPLES", "edge_touched": False,
                "first_touch_at": None, "minutes_since_first_touch": None,
                "observed_extreme_minutes": 0.0, "sample_count": len(rows)}

    first_ts = touched[0][0]
    # Sum only intervals where both adjacent observations remain beyond the same
    # edge, capped at 5 minutes so scan outages cannot fabricate dwell time.
    observed_seconds = 0.0
    for (ts1, p1), (ts2, p2) in zip(rows, rows[1:]):
        same_upper = p1 >= high and p2 >= high
        same_lower = p1 <= low and p2 <= low
        if same_upper or same_lower:
            observed_seconds += min(300.0, max(0.0, (ts2 - ts1).total_seconds()))
    return {
        "available": True,
        "source": "PRICE_SAMPLES",
        "edge_touched": True,
        "first_touch_at": first_ts.isoformat(),
        "minutes_since_first_touch": round(max(0.0, (now_utc - first_ts).total_seconds()) / 60.0, 1),
        "observed_extreme_minutes": round(observed_seconds / 60.0, 1),
        "sample_count": len(rows),
        "gap_cap_seconds": 300,
    }


def attach_price_history_timing(envelope: Dict[str, Any], ticker: str = "SPX",
                                path: str | Path = _PRICE_DB) -> Dict[str, Any]:
    """Attach timing evidence from canonical price_samples. Non-fatal/read-only."""
    try:
        ri = (envelope or {}).get("range_intelligence") or {}
        rr = ri.get("reversal_timing_intelligence") or {}
        esr = ri.get("expected_session_range") or {}
        lo, hi = _f(esr.get("low")), _f(esr.get("high"))
        if not rr.get("available") or lo is None or hi is None:
            return envelope

        now_et = dt.datetime.now(_ET)
        start_et = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
        if now_et < start_et:
            rr["timing"] = {"available": False, "source": "PRICE_SAMPLES", "reason": "PRE_RTH"}
            ri["reversal_timing_intelligence"] = rr
            return envelope
        start_utc = start_et.astimezone(dt.timezone.utc).isoformat()
        conn = canonical_connect(path)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT observed_at,price FROM price_samples WHERE ticker=? AND observed_at>=? ORDER BY observed_at",
                ((ticker or "SPX").upper(), start_utc),
            ).fetchall()
        finally:
            conn.close()
        rr["timing"] = timing_from_samples((dict(r) for r in rows), low=float(lo), high=float(hi))
        ri["reversal_timing_intelligence"] = rr
        try:
            from .structural_map_orchestration import refresh_unified_structural_map
            ri = refresh_unified_structural_map(ri)
        except Exception:
            pass
        envelope["range_intelligence"] = ri
        return envelope
    except Exception as exc:
        try:
            ri = (envelope or {}).get("range_intelligence") or {}
            rr = ri.get("reversal_timing_intelligence") or {}
            rr["timing"] = {"available": False, "source": "PRICE_SAMPLES", "reason": "PRICE_HISTORY_UNAVAILABLE"}
            rr["quality_flags"] = list(dict.fromkeys((rr.get("quality_flags") or []) + ["PRICE_HISTORY_TIMING_UNAVAILABLE"]))
            ri["reversal_timing_intelligence"] = rr
            envelope["range_intelligence"] = ri
        except Exception:
            pass
        return envelope
