"""engine/range_intelligence.py — APEX 7.2 Range Intelligence Engine.

Projects probable SPX high/low ZONES for the day from prior SPX structure, ES
overnight structure (basis-adjusted), dealer positioning, auction behaviour,
volume profile, a VIX-derived expected move, strike magnets, and institutional
flow. Answers: probable high zone, probable low zone, how much of the expected
range is used, which scenario is active, whether price is near exhaustion,
whether to avoid chasing near the edge, and what would invalidate the projection.

Design rules honoured:
  * NOT a rewrite — consumes the already-composed Data Bus object
    (STATE["last_result"]); never re-fetches or recomputes existing engine output.
  * NEVER compares raw ES levels to SPX. ES is converted with the live basis
    (basis = ES_price - SPX_price;  spx_equiv = es_level - basis).
  * Zone language, not point-precise prediction. No fake certainty.
  * Every unavailable input is explicitly labelled with a quality flag.

Pure computation + optional SQLite self-evaluation. Non-fatal throughout: any
missing input degrades to a flagged, still-structured response.
"""
from __future__ import annotations

import datetime as dt
import math
import os
import sqlite3
import threading
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

VERSION = "7.2_RANGE_INTELLIGENCE_ENGINE"
_ET = ZoneInfo("America/New_York")

SCENARIOS = (
    "BASE_CASE", "BULL_EXPANSION", "BEAR_EXPANSION", "BALANCED_ROTATION",
    "RANGE_EXHAUSTION", "WAITING_FOR_OPEN", "INSUFFICIENT_DATA",
)


# ── small helpers ─────────────────────────────────────────────────────────────

def _f(v: Any, d: Optional[float] = None) -> Optional[float]:
    try:
        if v is None or v == "":
            return d
        return float(v)
    except (TypeError, ValueError):
        return d


def _u(v: Any) -> str:
    return str(v or "").upper()


def _cluster_tol(price: float) -> float:
    """Confluence tolerance in points — ~0.09% of price, floor 4 pts."""
    return max(4.0, price * 0.0009)


# ── level clustering ──────────────────────────────────────────────────────────

def _cluster(candidates: List[Tuple[str, float]], price: float, side: str
             ) -> Optional[Dict[str, Any]]:
    """Group nearby candidate levels on one side of price into the most
    convincing confluence zone. `side` is 'HIGH' (levels above) or 'LOW' (below).

    Returns {low, high, mid, members:[(label,level)], count} or None.
    """
    pts = [(lbl, lv) for (lbl, lv) in candidates if lv is not None]
    if side == "HIGH":
        pts = [(l, v) for (l, v) in pts if v >= price - 1.0]
    else:
        pts = [(l, v) for (l, v) in pts if v <= price + 1.0]
    if not pts:
        return None

    pts.sort(key=lambda x: x[1])
    tol = _cluster_tol(price)

    # build clusters of levels within `tol` of the running cluster span
    clusters: List[List[Tuple[str, float]]] = []
    cur: List[Tuple[str, float]] = [pts[0]]
    for lbl, lv in pts[1:]:
        if lv - cur[0][1] <= tol:
            cur.append((lbl, lv))
        else:
            clusters.append(cur)
            cur = [(lbl, lv)]
    clusters.append(cur)

    def score(cl: List[Tuple[str, float]]) -> Tuple[int, float]:
        mid = sum(v for _, v in cl) / len(cl)
        # prefer denser clusters, then the one nearest price (first shelf)
        return (len(cl), -abs(mid - price))

    best = max(clusters, key=score)
    lvls = [v for _, v in best]
    lo, hi = min(lvls), max(lvls)
    if hi - lo < 3.0:  # pad a single/tight level into a real zone
        pad = 3.0 - (hi - lo)
        lo -= pad / 2
        hi += pad / 2
    return {"low": round(lo, 2), "high": round(hi, 2), "mid": round((lo + hi) / 2, 2),
            "members": [(l, round(v, 2)) for l, v in best], "count": len(best)}


def _zone_confidence(zone: Dict[str, Any], *, price: float, dealer_ok: bool,
                     auction_ok: bool, flow_ok: bool, vol_calm: bool,
                     driver_ok: bool) -> int:
    """Confidence 0-100 from confluence count + confirmations. Deliberately
    capped — this is a zone, not a prediction."""
    n = zone["count"]
    conf = 45 + min(4, n) * 9              # 2 levels ~63, 3 ~72, 4+ ~81
    conf += 6 if dealer_ok else 0
    conf += 5 if auction_ok else 0
    conf += 5 if flow_ok else 0
    conf += 4 if vol_calm else 0
    conf += 4 if driver_ok else 0
    dist = abs(zone["mid"] - price)
    if dist > price * 0.012:               # far zones are less certain
        conf -= 8
    return int(max(30, min(90, conf)))


def _zone_out(side: str, zone: Dict[str, Any]) -> Dict[str, Any]:
    """Shape a reaction cluster for the API."""
    return {
        "side": side,
        "low": zone["low"], "high": zone["high"], "mid": zone["mid"],
        "confidence": zone.get("confidence"),
        "reasons": [f"{l} near {v}" for l, v in zone.get("members", [])],
    }


def _classify_outliers(levels: List[Tuple[str, float, str]], price: float,
                       direction: str, edge: Optional[float], env_tol: float
                       ) -> List[Dict[str, Any]]:
    """Classify levels beyond the expected-move envelope by purpose.

    A level well outside the envelope is never part of the normal projected
    range — it is an expansion target (breakout continuation) or a tail-risk
    level (a wall/magnet that only matters on an outsized move). Nearby outliers
    of a non-structural kind become secondary support/resistance.
    """
    out: List[Dict[str, Any]] = []
    seen_prices = set()
    for (l, v, k) in sorted(levels, key=lambda x: x[1], reverse=(direction == "ABOVE")):
        pr = round(v, 2)
        if pr in seen_prices:
            continue
        seen_prices.add(pr)
        structural = k in ("WALL", "GAMMA", "MAGNET")
        if direction == "ABOVE":
            cls = "EXPANSION_TARGET" if structural else "SECONDARY_RESISTANCE"
        else:
            cls = "TAIL_RISK_LEVEL" if structural else "SECONDARY_SUPPORT"
        out.append({
            "label": l, "price": round(v, 2), "kind": k, "classification": cls,
            "direction": "UP" if direction == "ABOVE" else "DOWN",
            "distance": round(v - price, 2),
            "beyond_envelope": round(abs(v - edge), 2) if edge is not None else None,
        })
    # Merge a tight cluster of same-classification levels into one zone label.
    return out


# ── main build ────────────────────────────────────────────────────────────────

def build_range_intelligence(last_result: Dict[str, Any], *, market_open: bool,
                             ticker: str = "SPX",
                             canonical: Optional[Dict[str, Any]] = None,
                             runtime: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Compute the range-intelligence block from the composed Data Bus object.

    `last_result` is STATE["last_result"] (as built by /api/institutional_os).
    Returns the {version, ticker, range_intelligence:{...}} envelope.
    """
    lr = last_result or {}
    ms = lr.get("market_state") or {}
    st = lr.get("structure") or {}
    on = lr.get("overnight_game_plan") or {}
    vol = lr.get("volatility") or {}
    mags = lr.get("strike_magnets") or {}
    dealer = lr.get("dealer_positioning") or {}
    drivers = lr.get("market_drivers") or {}
    inst = lr.get("institutional_intelligence") or {}

    flags: List[str] = []

    price = _f(ms.get("price")) or _f(st.get("current_price"))
    session_state = _u(ms.get("session_state") or lr.get("session", {}).get("session_state"))

    # Cash-closed / ES-open fallback: with no live SPX quote, anchor to the prior
    # SPX cash close and treat ES structure as offsets from current ES (the way an
    # overnight game plan is built). Honest and flagged — no fabricated basis.
    _on_es = _f((lr.get("overnight_game_plan") or {}).get("es_price"))
    _prev_close = _f((lr.get("structure") or {}).get("prev_close")) or \
        _f((lr.get("structure") or {}).get("prev_day_close")) or \
        _f((lr.get("overnight_game_plan") or {}).get("prior_close"))
    price_estimated = False
    if price is None and _on_es is not None and _prev_close is not None:
        price = _prev_close
        price_estimated = True
        flags.append("SPX_PRICE_ESTIMATED_FROM_PRIOR_CLOSE")

    if price is None:
        return _envelope(ticker, {
            "available": False, "active_scenario": "INSUFFICIENT_DATA",
            "interpretation": "No SPX price available yet — run a scan once ES/cash data is live to project a range.",
            "quality_flags": ["INSUFFICIENT_DATA"],
        })

    if not market_open:
        flags.append("MARKET_CLOSED_PROJECTION_ONLY")

    # ── ES/SPX basis conversion (never compare raw ES to SPX) ────────────────
    es_price = _f(on.get("es_price"))
    es_on_high = _f(on.get("overnight_high"))
    es_on_low = _f(on.get("overnight_low"))
    basis_block: Dict[str, Any]
    spx_equiv_on_high = spx_equiv_on_low = None
    if es_price is not None and (es_on_high is not None or es_on_low is not None):
        # When anchored to prior close (cash dark), basis is the ES-vs-prior-close
        # spread (carry + weekend drift); ES levels map to cash-anchored offsets.
        basis = round(es_price - price, 2)
        if es_on_high is not None:
            spx_equiv_on_high = round(es_on_high - basis, 2)
        if es_on_low is not None:
            spx_equiv_on_low = round(es_on_low - basis, 2)
        basis_block = {
            "es_available": True, "basis": basis,
            "basis_method": "ES_MINUS_PRIOR_CLOSE" if price_estimated else "ES_MINUS_SPX",
            "es_overnight_high": es_on_high, "spx_equivalent_overnight_high": spx_equiv_on_high,
            "es_overnight_low": es_on_low, "spx_equivalent_overnight_low": spx_equiv_on_low,
        }
    else:
        basis_block = {"es_available": False,
                       "quality_flags": ["ES_FEED_UNAVAILABLE_USING_SPX_ONLY"]}
        flags.append("ES_FEED_UNAVAILABLE_USING_SPX_ONLY")

    # ── previous-day + session levels ────────────────────────────────────────
    pdh = _f(st.get("prev_day_high"))
    pdl = _f(st.get("prev_day_low"))
    prev_close = _f(st.get("prev_close")) or _f(st.get("prev_day_close")) or _f(on.get("prior_close"))
    sess_high = _f(st.get("session_high"))
    sess_low = _f(st.get("session_low"))
    if pdh is None or pdl is None:
        flags.append("SPX_PREVIOUS_DAY_LEVELS_UNAVAILABLE")

    vah = _f(ms.get("vah")) or _f(on.get("prior_vah"))
    val = _f(ms.get("val")) or _f(on.get("prior_val"))
    vwap = _f(ms.get("vwap"))
    poc = _f(ms.get("poc")) or _f(on.get("prior_poc"))
    call_wall = _f(ms.get("call_wall"))
    put_wall = _f(ms.get("put_wall"))
    zero_gamma = _f(ms.get("zero_gamma"))

    # ── canonical session context (Morning Brief) is authoritative ──────────
    # The Morning Brief is the single source of truth for spot + expected-move.
    # Range Intelligence must consume it and must NOT independently recompute an
    # expected move from VIX when canonical values exist. Confluence levels
    # SUPPLEMENT the envelope; they never overwrite it.
    canon = canonical if isinstance(canonical, dict) else {}
    canon_spot = _f(canon.get("spot"))
    canon_em_low = _f(canon.get("em_low"))
    canon_em_high = _f(canon.get("em_high"))
    if canon_em_low is None or canon_em_high is None:
        _cem = canon.get("expected_move") or {}
        canon_em_low = canon_em_low if canon_em_low is not None else _f(_cem.get("low") or _cem.get("lower"))
        canon_em_high = canon_em_high if canon_em_high is not None else _f(_cem.get("high") or _cem.get("upper"))

    if canon_spot is not None:
        price = canon_spot                      # authoritative session spot
        flags.append("SPX_SPOT_FROM_MORNING_BRIEF")

    # ── expected-move envelope ───────────────────────────────────────────────
    em_source = None
    if canon_em_low is not None and canon_em_high is not None and canon_em_high > canon_em_low:
        em_low, em_high = round(canon_em_low, 2), round(canon_em_high, 2)
        em_pts = round((em_high - em_low) / 2.0, 2)
        em_source = "MORNING_BRIEF_CANONICAL"
        flags.append("EXPECTED_MOVE_CANONICAL")
    else:
        # Fallback only when canonical values are absent (flagged, never silent).
        vix = _f(vol.get("vix"))
        em_pts = em_high = em_low = None
        if vix is not None and vix > 0:
            em_pts = round(price * (vix / 100.0) / math.sqrt(252.0), 2)
            em_high = round(price + em_pts, 2)
            em_low = round(price - em_pts, 2)
            em_source = "VIX_DERIVED_FALLBACK"
            flags.append("EXPECTED_MOVE_DERIVED_FROM_VIX")
        else:
            flags.append("EXPECTED_MOVE_UNAVAILABLE")

    # ── previous-day range (context only; not an envelope substitute) ────────
    adr = round(pdh - pdl, 2) if (pdh is not None and pdl is not None) else None

    # ── strike magnets (above/below spot) ────────────────────────────────────
    mag_list = mags.get("magnets") if isinstance(mags, dict) else (mags if isinstance(mags, list) else [])
    mags_above = [(f"Magnet {m.get('type','')}", _f(m.get("strike")), "MAGNET")
                  for m in mag_list if _u(m.get("side")) == "ABOVE" and _f(m.get("strike"))]
    mags_below = [(f"Magnet {m.get('type','')}", _f(m.get("strike")), "MAGNET")
                  for m in mag_list if _u(m.get("side")) == "BELOW" and _f(m.get("strike"))]

    # ── typed candidate levels (label, price, kind) ──────────────────────────
    # kind drives out-of-envelope classification: WALL/GAMMA/VALUE/PRIOR/OVERNIGHT/MAGNET.
    candidates: List[Tuple[str, Optional[float], str]] = [
        ("Previous day high", pdh, "PRIOR"),
        ("Previous day low", pdl, "PRIOR"),
        ("SPX-equiv ES overnight high", spx_equiv_on_high, "OVERNIGHT"),
        ("SPX-equiv ES overnight low", spx_equiv_on_low, "OVERNIGHT"),
        ("VAH", vah, "VALUE"),
        ("VAL", val, "VALUE"),
        ("POC", poc, "VALUE"),
        ("Call wall", call_wall, "WALL"),
        ("Put wall", put_wall, "WALL"),
        ("Gamma node", zero_gamma, "GAMMA"),
    ] + mags_above + mags_below
    candidates = [(l, v, k) for (l, v, k) in candidates if v is not None]

    # Confirmations (shared by confidence + scenario).
    gamma_regime = _u(ms.get("gamma_regime") or dealer.get("gamma_regime"))
    poc_mig = _u(ms.get("poc_migration"))
    flow_bias = _u(ms.get("flow_bias") or inst.get("flow_bias"))
    driver_bias = _u(drivers.get("bias") or drivers.get("driver_bias") or inst.get("market_driver_bias"))
    vol_regime = _u(vol.get("regime"))
    vol_calm = vol_regime in ("LOW", "NORMAL", "SUBDUED", "COMPRESSED")
    dealer_ok = gamma_regime in ("POSITIVE_GAMMA", "POSITIVE", "MIXED")
    auction_state = _u(ms.get("auction_state"))
    auction_ok = auction_state in ("BALANCED", "ROTATIONAL", "ACCEPTING_HIGHER", "ACCEPTING_LOWER", "NEUTRAL DAY")

    # ── envelope-constrained classification ──────────────────────────────────
    # Expected Session Range = the canonical envelope. Levels are separated by
    # PURPOSE relative to it; a level well outside the envelope is never allowed
    # into the normal projected range — it is an expansion target or tail risk.
    tol = _cluster_tol(price)
    if em_low is not None and em_high is not None:
        env_tol = max(tol, (em_high - em_low) * 0.10)   # slightly outside allowed, ~71pt outliers excluded
        in_env = [(l, v, k) for (l, v, k) in candidates if (em_low - env_tol) <= v <= (em_high + env_tol)]
        above_env = [(l, v, k) for (l, v, k) in candidates if v > em_high + env_tol]
        below_env = [(l, v, k) for (l, v, k) in candidates if v < em_low - env_tol]
    else:
        env_tol = tol
        in_env, above_env, below_env = candidates, [], []

    # Immediate reaction zones: confluence clusters INSIDE the envelope, nearest
    # spot on each side.
    in_above = [(l, v) for (l, v, k) in in_env if v >= price - 1.0]
    in_below = [(l, v) for (l, v, k) in in_env if v <= price + 1.0]
    upper_reaction = _cluster(in_above, price, "HIGH")
    lower_reaction = _cluster(in_below, price, "LOW")

    immediate_reaction_zones: List[Dict[str, Any]] = []
    if upper_reaction:
        upper_reaction["confidence"] = _zone_confidence(
            upper_reaction, price=price, dealer_ok=dealer_ok, auction_ok=auction_ok,
            flow_ok=flow_bias == "BULLISH", vol_calm=vol_calm, driver_ok=driver_bias == "BULLISH")
        immediate_reaction_zones.append(_zone_out("UPPER", upper_reaction))
    if lower_reaction:
        lower_reaction["confidence"] = _zone_confidence(
            lower_reaction, price=price, dealer_ok=dealer_ok, auction_ok=auction_ok,
            flow_ok=flow_bias == "BEARISH", vol_calm=vol_calm, driver_ok=driver_bias == "BEARISH")
        immediate_reaction_zones.append(_zone_out("LOWER", lower_reaction))

    # Intermediate targets: notable in-envelope levels beyond the reaction zone,
    # toward the envelope edge (e.g. previous-day high).
    reaction_members = {round(v, 2) for z in (upper_reaction, lower_reaction) if z for _, v in z["members"]}
    intermediate_targets: List[Dict[str, Any]] = []
    for (l, v, k) in sorted(in_env, key=lambda x: x[1]):
        if round(v, 2) in reaction_members:
            continue
        if k in ("VALUE", "MAGNET") and abs(v - price) <= env_tol:
            continue  # too close / minor — already represented by a reaction zone
        intermediate_targets.append({
            "label": l, "price": round(v, 2), "kind": k,
            "direction": "UP" if v >= price else "DOWN",
            "distance": round(v - price, 2),
        })

    # Expansion targets (above envelope) and tail-risk levels (below envelope).
    expansion_targets = _classify_outliers(above_env, price, "ABOVE", em_high, env_tol)
    tail_risk_levels = _classify_outliers(below_env, price, "BELOW", em_low, env_tol)

    # ── expected session range block ─────────────────────────────────────────
    if em_low is not None and em_high is not None:
        expected_session_range = {
            "low": em_low, "high": em_high, "mid": round((em_low + em_high) / 2, 2),
            "source": em_source, "points": em_pts,
        }
    else:
        expected_session_range = {"low": None, "high": None, "mid": None,
                                  "source": em_source, "points": None}

    # ── range used / exhaustion — gated on a REAL RTH session ────────────────
    # Before an actual RTH high and low exist, "range used" and "exhaustion" are
    # not defined. Do not estimate them from pre-open price position.
    rth_live = sess_high is not None and sess_low is not None and sess_high > sess_low
    if rth_live and em_low is not None and em_high is not None:
        projected_range = max(1.0, em_high - em_low)
        range_used = int(max(0, min(140, round((sess_high - sess_low) / projected_range * 100.0))))
        range_used_method = "SESSION_RANGE"
        range_used_evaluated = True
    else:
        range_used = None
        range_used_method = "WAITING_FOR_RTH"
        range_used_evaluated = False
        flags.append("RANGE_USED_NOT_EVALUATED_PRE_RTH")

    # Upside/downside remaining are measured from the EXPECTED-MOVE ENVELOPE,
    # not from asymmetric confluence clusters.
    if em_low is not None and em_high is not None:
        upside_remaining = round(em_high - price, 2)
        downside_remaining = round(price - em_low, 2)
    else:
        upside_remaining = downside_remaining = None

    near_high = em_high is not None and price >= em_high - env_tol
    near_low = em_low is not None and price <= em_low + env_tol

    # ── scenario (unchanged inputs; envelope zones stand in for legacy zones) ─
    legacy_high_zone = upper_reaction or (
        {"low": em_high, "high": em_high, "mid": em_high, "members": [], "count": 0}
        if em_high is not None else {"low": price, "high": price, "mid": price, "members": [], "count": 0})
    legacy_low_zone = lower_reaction or (
        {"low": em_low, "high": em_low, "mid": em_low, "members": [], "count": 0}
        if em_low is not None else {"low": price, "high": price, "mid": price, "members": [], "count": 0})

    scenario = _classify_scenario(
        price=price, market_open=market_open, session_state=session_state,
        high_zone=legacy_high_zone, low_zone=legacy_low_zone,
        range_used=range_used if range_used is not None else 50,
        near_high=near_high, near_low=near_low, poc_mig=poc_mig, vwap=vwap, vah=vah, val=val,
        gamma_regime=gamma_regime, flow_bias=flow_bias, driver_bias=driver_bias,
        sweep_count=_f(ms.get("sweep_count"), 0) or 0, mags_above=mags_above, mags_below=mags_below,
        auction_state=auction_state,
    )

    # Exhaustion is only a real reading once the session range is real.
    if range_used_evaluated:
        exhaustion = _exhaustion_risk(range_used, near_high, near_low, gamma_regime,
                                      auction_state, poc_mig)
    else:
        exhaustion = "NOT_EVALUATED"

    opening_context = _opening_context(price, prev_close, vah, val, on)
    bias = _bias(flow_bias, driver_bias, _u(inst.get("institutional_bias")), scenario)
    interpretation = _interpretation(scenario, legacy_high_zone, legacy_low_zone,
                                     range_used if range_used is not None else 0,
                                     near_high, near_low, exhaustion)
    invalidation = _invalidation(scenario)

    _pin_prob = _f(inst.get("pin_probability"))
    if range_used_evaluated:
        expansion_prob, mean_reversion_prob = _expansion_probabilities(
            range_used=range_used, gamma_regime=gamma_regime, poc_mig=poc_mig,
            near_high=near_high, near_low=near_low, exhaustion=exhaustion,
            auction_state=auction_state, pin_probability=_pin_prob,
        )
    else:
        expansion_prob = mean_reversion_prob = None

    # ── runtime gating (degraded / pre-open) ─────────────────────────────────
    rt = runtime if isinstance(runtime, dict) else {}
    rt_state = _u(rt.get("state"))
    data_fresh = rt.get("data_fresh")
    degraded = bool(rt.get("degraded")) or rt_state in ("DEGRADED", "STALE")
    stale_inputs: List[str] = []
    if em_source != "MORNING_BRIEF_CANONICAL":
        stale_inputs.append("expected_move" if em_source else "expected_move_missing")
    if degraded:
        stale_inputs.append("live_scanner")
        flags.append("RUNTIME_DEGRADED_PROJECTION_PRESERVED")
        # Withhold new range/exhaustion conclusions when degraded.
        range_used = None
        range_used_evaluated = False
        range_used_method = "WITHHELD_DEGRADED"
        exhaustion = "NOT_EVALUATED"
        expansion_prob = mean_reversion_prob = None
    if not market_open:
        runtime_state = "DEGRADED_PREOPEN" if degraded else "PRE_OPEN"
    else:
        runtime_state = "DEGRADED" if degraded else "LIVE"

    ri = {
        "available": True,
        "version": VERSION,
        "active_scenario": scenario,
        "canonical": {
            "spot": price, "em_low": em_low, "em_high": em_high,
            "source": em_source, "used": em_source == "MORNING_BRIEF_CANONICAL",
        },
        # ── four purpose-separated sections ──────────────────────────────────
        "expected_session_range": expected_session_range,
        "immediate_reaction_zones": immediate_reaction_zones,
        "intermediate_targets": intermediate_targets,
        "expansion_targets": expansion_targets,
        "tail_risk_levels": tail_risk_levels,
        # ── legacy fields (kept for back-compat; now envelope-correct) ───────
        "projected_high_zone": {**{k: legacy_high_zone[k] for k in ("low", "high", "mid")},
                                "confidence": legacy_high_zone.get("confidence", upper_reaction.get("confidence") if upper_reaction else None),
                                "reasons": [f"{l} near {v}" for l, v in legacy_high_zone.get("members", [])]},
        "projected_low_zone": {**{k: legacy_low_zone[k] for k in ("low", "high", "mid")},
                               "confidence": legacy_low_zone.get("confidence", lower_reaction.get("confidence") if lower_reaction else None),
                               "reasons": [f"{l} near {v}" for l, v in legacy_low_zone.get("members", [])]},
        "range_used_percent": range_used,
        "range_used_method": range_used_method,
        "range_used_evaluated": range_used_evaluated,
        "range_exhaustion_risk": exhaustion,
        "expansion_probability": expansion_prob,
        "mean_reversion_probability": mean_reversion_prob,
        "pin_probability": round(_pin_prob, 1) if _pin_prob is not None else None,
        "upside_remaining_points": upside_remaining,
        "downside_remaining_points": downside_remaining,
        "opening_context": opening_context,
        "bias": bias,
        "interpretation": interpretation,
        "invalidation": invalidation,
        "basis_diagnostics": basis_block,
        "expected_move": {"points": em_pts, "high": em_high, "low": em_low,
                          "source": em_source} if em_high is not None else None,
        "session_high": sess_high, "session_low": sess_low,
        "runtime_state": runtime_state,
        "stale_inputs": list(dict.fromkeys(stale_inputs)),
        "quality_flags": list(dict.fromkeys(flags)),
    }
    return _envelope(ticker, ri)

def _envelope(ticker: str, ri: Dict[str, Any]) -> Dict[str, Any]:
    return {"ok": True, "ticker": (ticker or "SPX").upper(),
            "version": VERSION, "range_intelligence": ri}


# ── scenario / risk / context helpers ────────────────────────────────────────

def _classify_scenario(*, price, market_open, session_state, high_zone, low_zone,
                       range_used, near_high, near_low, poc_mig, vwap, vah, val,
                       gamma_regime, flow_bias, driver_bias, sweep_count,
                       mags_above, mags_below, auction_state) -> str:
    if not market_open and session_state in ("OVERNIGHT", "PREMARKET", "CLOSED", ""):
        # still return a projection, but tag the pre-open state
        if session_state in ("OVERNIGHT", "PREMARKET"):
            return "WAITING_FOR_OPEN"

    above_high = price > high_zone["high"]
    below_low = price < low_zone["low"]

    bull_pts = sum([
        above_high, poc_mig == "RISING",
        (vwap is not None and price > vwap), (vah is not None and price > vah),
        gamma_regime in ("NEGATIVE_GAMMA", "NEGATIVE"),
        flow_bias == "BULLISH", driver_bias == "BULLISH",
        sweep_count and sweep_count > 0 and flow_bias == "BULLISH",
        len(mags_above) > len(mags_below),
    ])
    bear_pts = sum([
        below_low, poc_mig == "FALLING",
        (vwap is not None and price < vwap), (val is not None and price < val),
        gamma_regime in ("NEGATIVE_GAMMA", "NEGATIVE"),
        flow_bias == "BEARISH", driver_bias == "BEARISH",
        sweep_count and sweep_count > 0 and flow_bias == "BEARISH",
        len(mags_below) > len(mags_above),
    ])

    # exhaustion takes priority when range is nearly spent at an edge
    if range_used > 85 and (near_high or near_low) and \
       gamma_regime in ("POSITIVE_GAMMA", "POSITIVE") and poc_mig in ("STABLE", "FLAT", ""):
        return "RANGE_EXHAUSTION"
    # Expansion needs SEVERAL of the listed conditions (price-position is one of
    # them, not a hard gate): acceptance beyond the zone with confirmation, OR an
    # overwhelming signal majority even while still testing the edge.
    if (above_high and bull_pts >= 3) or bull_pts >= 5:
        return "BULL_EXPANSION"
    if (below_low and bear_pts >= 3) or bear_pts >= 5:
        return "BEAR_EXPANSION"
    if abs(bull_pts - bear_pts) <= 1 and not above_high and not below_low:
        return "BALANCED_ROTATION"
    return "BASE_CASE"


def _exhaustion_risk(range_used, near_high, near_low, gamma_regime, auction_state, poc_mig) -> str:
    at_edge = near_high or near_low
    if range_used >= 85 and at_edge:
        return "HIGH"
    if range_used >= 70 and at_edge:
        return "MODERATE"
    if range_used >= 90:
        return "MODERATE"
    return "LOW"


def _expansion_probabilities(range_used, gamma_regime, poc_mig, near_high, near_low,
                             exhaustion, auction_state, pin_probability):
    """Estimate range EXPANSION vs MEAN-REVERSION likelihood from signals the engine
    already has. Returns (expansion_pct, mean_reversion_pct) summing to 100.

    Reasoning (all evidence the range engine already computes elsewhere):
      - Negative gamma -> dealers amplify -> expansion more likely.
      - Positive gamma / high pin probability -> dealers dampen -> reversion more likely.
      - Migrating POC (trend structure) favours expansion; flat POC favours reversion.
      - Low range-used early favours expansion; high range-used at an edge favours
        reversion (the move is largely spent).
      - BALANCED/rotational auction favours reversion; trending auction favours expansion.
    This is a transparent heuristic score, NOT a fitted model -- it is labelled as an
    estimate in the payload and is meant to be calibrated against realised outcomes
    via the existing projection scorecard, not trusted as ground truth.
    """
    score = 50.0  # neutral prior

    g = _u(gamma_regime)
    if "NEGATIVE" in g:
        score += 18
    elif "POSITIVE" in g:
        score -= 15

    pin = _f(pin_probability)
    if pin is not None:
        # High pin probability is a strong reversion/containment signal.
        if pin >= 70:
            score -= 18
        elif pin >= 50:
            score -= 10
        elif pin <= 20:
            score += 6

    pm = _u(poc_mig)
    if "RISING" in pm or "FALLING" in pm or "MIGRAT" in pm:
        score += 12
    elif "FLAT" in pm or "STABLE" in pm:
        score -= 8

    if range_used is not None:
        if range_used <= 35:
            score += 10          # lots of range left, early
        elif range_used >= 85 and (near_high or near_low):
            score -= 16          # move largely spent, sitting at an edge
        elif range_used >= 70:
            score -= 6

    a = _u(auction_state)
    if "TREND" in a:
        score += 10
    elif "BALANC" in a or "ROTAT" in a:
        score -= 10

    if exhaustion == "HIGH":
        score -= 12
    elif exhaustion == "MODERATE":
        score -= 5

    expansion = max(5.0, min(95.0, score))
    return (round(expansion, 1), round(100.0 - expansion, 1))


def _opening_context(price, prev_close, vah, val, on) -> str:
    gap = None
    if prev_close is not None:
        gap = price - prev_close
    inside_value = (vah is not None and val is not None and val <= price <= vah)
    if gap is None:
        return "INSIDE_VALUE" if inside_value else "UNDETERMINED"
    direction = "GAP_UP" if gap > 1.0 else ("GAP_DOWN" if gap < -1.0 else "FLAT_OPEN")
    if direction == "FLAT_OPEN":
        return "INSIDE_VALUE" if inside_value else "FLAT_OPEN"
    zone = "INSIDE_VALUE" if inside_value else "OUTSIDE_VALUE"
    return f"{direction}_{zone}"


def _bias(flow_bias, driver_bias, inst_bias, scenario) -> str:
    votes = [b for b in (flow_bias, driver_bias, inst_bias) if b in ("BULLISH", "BEARISH")]
    bulls = votes.count("BULLISH")
    bears = votes.count("BEARISH")
    if scenario == "BULL_EXPANSION":
        return "BULLISH"
    if scenario == "BEAR_EXPANSION":
        return "BEARISH"
    if bulls > bears:
        return "BALANCED_TO_BULLISH"
    if bears > bulls:
        return "BALANCED_TO_BEARISH"
    return "BALANCED"


def _interpretation(scenario, high_zone, low_zone, range_used, near_high, near_low, exhaustion) -> str:
    hz = f"{high_zone['low']}\u2013{high_zone['high']}"
    lz = f"{low_zone['low']}\u2013{low_zone['high']}"
    if scenario == "RANGE_EXHAUSTION":
        return (f"Range is ~{range_used}% used near a projected edge with pinning conditions. "
                f"Do not chase 0DTE into the {'upper' if near_high else 'lower'} zone; "
                f"favour fades or wait for a fresh expansion trigger.")
    if scenario == "BULL_EXPANSION":
        return (f"Bull expansion: price is accepting above the projected high zone ({hz}) with "
                f"supportive structure. Upside extension is valid while POC keeps migrating higher.")
    if scenario == "BEAR_EXPANSION":
        return (f"Bear expansion: price is accepting below the projected low zone ({lz}) with "
                f"supportive structure. Downside extension is valid while POC keeps migrating lower.")
    if scenario == "WAITING_FOR_OPEN":
        return (f"Pre-RTH projection: today's likely range zones are {lz} (low) and {hz} (high). "
                f"Levels are projections, not live RTH confirmations — wait for the open.")
    if scenario == "BALANCED_ROTATION":
        return (f"Balanced rotation inside {lz} \u2013 {hz}. Trade the edges toward the mid; "
                f"avoid chasing breakouts without POC migration and flow confirmation.")
    edge = ""
    if near_high:
        edge = " Price is near the upper zone — do not chase calls without expansion confirmation."
    elif near_low:
        edge = " Price is near the lower zone — do not chase puts without expansion confirmation."
    return (f"SPX is trading inside the projected range ({lz} low, {hz} high); ~{range_used}% used."
            f"{edge}")


def _invalidation(scenario: str) -> List[str]:
    base = [
        "Price accepts above the upper projected zone with rising POC (upside expansion).",
        "Price breaks below the lower projected zone with falling POC (downside expansion).",
        "Dealer positioning flips strongly negative (gamma regime change).",
    ]
    if scenario == "BULL_EXPANSION":
        return ["POC stops migrating higher and price falls back inside the projected high zone.",
                "Call sweep pressure fades and gamma flips positive (pinning).",
                "Price loses VWAP with acceptance back inside value."]
    if scenario == "BEAR_EXPANSION":
        return ["POC stops migrating lower and price recovers back inside the projected low zone.",
                "Put sweep pressure fades and gamma flips positive (pinning).",
                "Price reclaims VWAP with acceptance back inside value."]
    if scenario == "RANGE_EXHAUSTION":
        return ["A fresh expansion trigger appears: POC migration resumes with accelerating sweeps.",
                "Price accepts beyond the edge zone rather than rejecting it."]
    return base


# ════════════════════════════════════════════════════════════════════════════
#  Self-evaluation — range_projection_history
# ════════════════════════════════════════════════════════════════════════════

def _db_path() -> str:
    """Resolve the DB path at CALL time, not import time.

    Binding at import makes the module's storage depend on which importer wins the
    race: a test that sets RANGE_DB_PATH in its own header is silently ignored if
    anything imported this module first (app.py, another test). The result is a
    suite that passes or fails on collection order — which is how this surfaced.
    """
    return os.getenv("RANGE_DB_PATH",
                     os.getenv("DIRECTOR_DB_PATH", os.getenv("DB_PATH", "apex_tracking.db")))


# Back-compat: some callers read the module attribute directly.
_DB_PATH = _db_path()
_LOCK = threading.RLock()
_INIT = False


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_history() -> bool:
    global _INIT
    with _LOCK:
        if _INIT:
            return True
        try:
            d = os.path.dirname(_db_path())
            if d:
                os.makedirs(d, exist_ok=True)
            conn = _connect()
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS range_projection_history (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    date                TEXT,
                    ticker              TEXT,
                    projected_high_low  REAL,
                    projected_high_high REAL,
                    projected_low_low   REAL,
                    projected_low_high  REAL,
                    actual_high         REAL,
                    actual_low          REAL,
                    high_error_points   REAL,
                    low_error_points    REAL,
                    scenario_at_open    TEXT,
                    scenario_final      TEXT,
                    range_used_max      INTEGER,
                    created_at          TEXT,
                    UNIQUE(date, ticker)
                )
                """
            )
            conn.commit()
            conn.close()
            _INIT = True
            return True
        except Exception as e:  # pragma: no cover
            print(f"Range history DISABLED — table init failed: {e}", flush=True)
            return False


def _today_et() -> str:
    return dt.datetime.now(_ET).strftime("%Y-%m-%d")


def capture_projection(envelope: Dict[str, Any], ticker: str = "SPX") -> bool:
    """Store today's morning projection (once per date/ticker; idempotent)."""
    if not init_history():
        return False
    ri = (envelope or {}).get("range_intelligence") or {}
    if not ri.get("available"):
        return False
    hz = ri.get("projected_high_zone") or {}
    lz = ri.get("projected_low_zone") or {}
    try:
        with _LOCK:
            conn = _connect()
            conn.execute(
                """
                INSERT OR IGNORE INTO range_projection_history
                (date, ticker, projected_high_low, projected_high_high,
                 projected_low_low, projected_low_high, scenario_at_open,
                 range_used_max, created_at)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (_today_et(), ticker.upper(), hz.get("low"), hz.get("high"),
                 lz.get("low"), lz.get("high"), ri.get("active_scenario"),
                 ri.get("range_used_percent") or 0,
                 dt.datetime.now(dt.timezone.utc).isoformat()),
            )
            # keep the running max range_used for the day
            conn.execute(
                """UPDATE range_projection_history
                   SET range_used_max = MAX(COALESCE(range_used_max,0), ?)
                   WHERE date=? AND ticker=?""",
                (ri.get("range_used_percent") or 0, _today_et(), ticker.upper()),
            )
            conn.commit()
            conn.close()
        return True
    except Exception as e:  # pragma: no cover
        print(f"capture_projection failed: {e}", flush=True)
        return False


def record_actuals(ticker: str, *, actual_high: float, actual_low: float,
                   scenario_final: str = "", date: Optional[str] = None) -> bool:
    """After close, record the session's actual high/low and grade the projection."""
    if not init_history():
        return False
    date = date or _today_et()
    try:
        with _LOCK:
            conn = _connect()
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM range_projection_history WHERE date=? AND ticker=?",
                (date, ticker.upper()),
            ).fetchone()
            if not row:
                conn.close()
                return False
            # error = distance from actual extreme to nearest edge of its projected zone
            hi_err = _edge_error(actual_high, row["projected_high_low"], row["projected_high_high"])
            lo_err = _edge_error(actual_low, row["projected_low_low"], row["projected_low_high"])
            conn.execute(
                """UPDATE range_projection_history
                   SET actual_high=?, actual_low=?, high_error_points=?, low_error_points=?,
                       scenario_final=? WHERE date=? AND ticker=?""",
                (round(actual_high, 2), round(actual_low, 2), hi_err, lo_err,
                 scenario_final, date, ticker.upper()),
            )
            conn.commit()
            conn.close()
        return True
    except Exception as e:  # pragma: no cover
        print(f"record_actuals failed: {e}", flush=True)
        return False


def _edge_error(actual: float, zlow: Optional[float], zhigh: Optional[float]) -> Optional[float]:
    if actual is None or zlow is None or zhigh is None:
        return None
    if zlow <= actual <= zhigh:
        return 0.0
    return round(min(abs(actual - zlow), abs(actual - zhigh)), 2)


def history(ticker: str = "SPX", limit: int = 50) -> List[Dict[str, Any]]:
    if not init_history():
        return []
    try:
        with _LOCK:
            conn = _connect()
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM range_projection_history WHERE ticker=? ORDER BY date DESC LIMIT ?",
                (ticker.upper(), int(limit)),
            ).fetchall()
            conn.close()
            return [dict(r) for r in rows]
    except Exception:
        return []


def scorecard(ticker: str = "SPX") -> Dict[str, Any]:
    """Average high/low error, hit rates within zone / 5 / 10 pts, best/worst scenario."""
    if not init_history():
        return {"ok": False, "reason": "history disabled"}
    try:
        with _LOCK:
            conn = _connect()
            conn.row_factory = sqlite3.Row
            rows = [dict(r) for r in conn.execute(
                """SELECT * FROM range_projection_history
                   WHERE ticker=? AND actual_high IS NOT NULL""",
                (ticker.upper(),)).fetchall()]
            conn.close()
    except Exception as e:  # pragma: no cover
        return {"ok": False, "error": str(e)}

    n = len(rows)
    if n == 0:
        return {"ok": True, "ticker": ticker.upper(), "graded_days": 0,
                "note": "No completed sessions graded yet — projections are captured "
                        "at the open and scored after the close."}

    def _errs(key):
        return [r[key] for r in rows if r.get(key) is not None]

    hi_errs, lo_errs = _errs("high_error_points"), _errs("low_error_points")
    all_errs = hi_errs + lo_errs

    def _hit_rate(thresh):
        if not all_errs:
            return None
        return round(100.0 * sum(1 for e in all_errs if e <= thresh) / len(all_errs), 1)

    # per-scenario accuracy by mean combined error
    by_scn: Dict[str, List[float]] = {}
    for r in rows:
        scn = r.get("scenario_at_open") or "UNKNOWN"
        errs = [e for e in (r.get("high_error_points"), r.get("low_error_points")) if e is not None]
        if errs:
            by_scn.setdefault(scn, []).extend(errs)
    scn_avg = {k: round(sum(v) / len(v), 2) for k, v in by_scn.items() if v}
    best = min(scn_avg, key=scn_avg.get) if scn_avg else None
    worst = max(scn_avg, key=scn_avg.get) if scn_avg else None

    return {
        "ok": True, "ticker": ticker.upper(), "graded_days": n,
        "avg_high_error_points": round(sum(hi_errs) / len(hi_errs), 2) if hi_errs else None,
        "avg_low_error_points": round(sum(lo_errs) / len(lo_errs), 2) if lo_errs else None,
        "hit_rate_within_zone_pct": _hit_rate(0.0),
        "hit_rate_within_5pts_pct": _hit_rate(5.0),
        "hit_rate_within_10pts_pct": _hit_rate(10.0),
        "best_scenario": best, "worst_scenario": worst,
        "scenario_avg_error": scn_avg,
    }

