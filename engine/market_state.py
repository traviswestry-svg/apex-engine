"""engine/market_state.py — APEX 6.4.1 Canonical Market State Object.

Single source of truth assembled once per request cycle and passed to
every engine that needs it.  No engine fetches data independently.

The canonical state carries:
  - Price / session
  - Structure: VWAP, POC, VAH, VAL, POC migration, value-area location
  - Gamma / dealer positioning: call wall, put wall, zero gamma, regime
  - Flow: bias, net premium, sweep count, tape bias
  - Execution: Pine state, ICI, decision state
  - Signal remaining time
  - Derived location flags (price_vs_poc, price_vs_va, support/resistance labels)

Usage in app.py:
    ms = build_canonical_market_state(
        flow_snapshot=flow_snapshot,
        volume_bundle=volume_bundle,
        result=nine_engine_result,
        tape_summary=tape_summary,
        session_ctx=session_ctx,
    )
    result["market_state"] = ms
    # pass ms into story, coach, replay frame
"""
from __future__ import annotations

import math
from typing import Any, Dict, Optional


def _sf(v: Any, d: float = 0.0) -> float:
    try:
        f = float(v) if v is not None else d
        return d if (math.isnan(f) or math.isinf(f)) else f
    except Exception:
        return d


def _price_vs_poc(price: float, poc: float) -> str:
    if poc <= 0:
        return "UNKNOWN"
    diff = price - poc
    if abs(diff) <= 0.5:
        return "AT"
    return "ABOVE" if diff > 0 else "BELOW"


def _price_vs_va(price: float, vah: float, val: float) -> str:
    if vah <= 0 or val <= 0:
        return "UNKNOWN"
    if price > vah:
        return "ABOVE_VAH"
    if price < val:
        return "BELOW_VAL"
    return "INSIDE"


def _gamma_regime_label(gamma: Dict[str, Any]) -> str:
    """Normalize gamma regime to a simple 3-value string."""
    label = str(gamma.get("regime_label") or "").upper()
    if "POSITIVE" in label:
        return "POSITIVE"
    if "NEGATIVE" in label:
        return "NEGATIVE"
    return "MIXED"


def _pine_state(execution: Dict[str, Any]) -> str:
    """Normalize execution state to a short readable label."""
    es = str(execution.get("execution_state") or "WAITING").upper()
    if "CONFIRMED" in es:
        return "CONFIRMED"
    if "EXPIRED" in es or "WAITING" in es or "NO_SIGNAL" in es:
        return "WAITING"
    if "REJECTED" in es:
        return "REJECTED"
    return es


def _support_resistance_label(
    price: float,
    poc: float, vwap: float,
    vah: float, val: float,
    call_wall: Optional[float], put_wall: Optional[float],
) -> Dict[str, Any]:
    """Identify the nearest support and resistance levels with labels."""
    levels = []
    if poc > 0:
        levels.append(("POC", poc))
    if vwap > 0:
        levels.append(("VWAP", vwap))
    if vah > 0:
        levels.append(("VAH", vah))
    if val > 0:
        levels.append(("VAL", val))
    if call_wall and call_wall > 0:
        levels.append(("Call Wall", call_wall))
    if put_wall and put_wall > 0:
        levels.append(("Put Wall", put_wall))

    supports    = [(lbl, lvl) for lbl, lvl in levels if lvl < price]
    resistances = [(lbl, lvl) for lbl, lvl in levels if lvl > price]

    nearest_support    = max(supports,    key=lambda x: x[1]) if supports    else None
    nearest_resistance = min(resistances, key=lambda x: x[1]) if resistances else None

    return {
        "nearest_support":          nearest_support[1]   if nearest_support    else None,
        "nearest_support_label":    nearest_support[0]   if nearest_support    else None,
        "nearest_resistance":       nearest_resistance[1] if nearest_resistance else None,
        "nearest_resistance_label": nearest_resistance[0] if nearest_resistance else None,
    }


def _poc_vwap_confluent(poc: float, vwap: float, threshold: float = 3.0) -> bool:
    """True when POC and VWAP are within threshold points of each other."""
    if poc <= 0 or vwap <= 0:
        return False
    return abs(poc - vwap) <= threshold


def _minutes_since_open() -> int:
    """Minutes elapsed since 09:30 ET. Returns 0 if before open."""
    try:
        import datetime as dt
        import zoneinfo
        now = dt.datetime.now(zoneinfo.ZoneInfo("America/New_York"))
        open_time = now.replace(hour=9, minute=30, second=0, microsecond=0)
        if now < open_time:
            return 0
        return int((now - open_time).total_seconds() / 60)
    except Exception:
        return 0


def build_canonical_market_state(
    *,
    flow_snapshot: Dict[str, Any],
    volume_bundle: Dict[str, Any],
    result: Dict[str, Any],
    tape_summary: Dict[str, Any],
    session_ctx: Dict[str, Any],
) -> Dict[str, Any]:
    """Assemble the canonical market state from already-fetched data.

    All inputs are the objects that app.py has already retrieved.
    This function NEVER makes a network call.

    Args:
        flow_snapshot:  Result of quantdata_flow_snapshot()
        volume_bundle:  Result of _volume_profile_bundle()
        result:         Output of _build_institutional_decision() (nine-engine)
        tape_summary:   Summary dict from build_flow_tape()
        session_ctx:    Output of market_session_context()

    Returns the canonical market state dict.
    """
    # ── Extract sub-objects ──────────────────────────────────────────────
    gamma     = result.get("gamma_regime")    or {}
    structure = result.get("structure")       or {}
    execution = result.get("execution")       or {}
    consensus = result.get("consensus")       or {}
    flow_intel= result.get("flow_intelligence") or {}
    risk      = result.get("risk")            or {}
    ici_obj   = result.get("ici")             or {}
    ribbon    = result.get("ribbon")          or {}

    vp_profile = volume_bundle.get("profile") or {}
    vp_levels  = vp_profile.get("levels")     or {}
    auction    = volume_bundle.get("auction")  or {}

    # ── Price ────────────────────────────────────────────────────────────
    price = (
        _sf(flow_snapshot.get("stock_price"))
        or _sf(structure.get("current_price"))
        or _sf(ribbon.get("spx_price"))
        or 0.0
    )

    # ── Structure levels ─────────────────────────────────────────────────
    vwap = _sf(structure.get("vwap"))
    poc  = _sf(vp_levels.get("poc") or auction.get("poc") or structure.get("session_poc"))
    vah  = _sf(vp_levels.get("vah") or auction.get("vah"))
    val  = _sf(vp_levels.get("val") or auction.get("val"))
    hvn  = vp_levels.get("hvn") or []
    lvn  = vp_levels.get("lvn") or []

    poc_migration   = str(auction.get("poc_migration") or "UNKNOWN")
    poc_delta       = _sf(auction.get("poc_delta"))
    auction_state   = str(auction.get("auction_state")  or "UNKNOWN")
    profile_available = bool(vp_profile.get("available"))
    poc_vwap_conf   = _poc_vwap_confluent(poc, vwap)
    confluence_level= round((poc + vwap) / 2.0, 2) if poc_vwap_conf else None

    # ── Location flags ───────────────────────────────────────────────────
    pvp = _price_vs_poc(price, poc)
    pva = _price_vs_va(price, vah, val)

    # ── Gamma / dealer ───────────────────────────────────────────────────
    call_wall   = flow_snapshot.get("call_wall")   or gamma.get("call_wall")
    put_wall    = flow_snapshot.get("put_wall")    or gamma.get("put_wall")
    zero_gamma  = flow_snapshot.get("zero_gamma")  or gamma.get("zero_gamma")
    gex_score   = _sf(flow_snapshot.get("gex_score") or gamma.get("gex_score"), 50.0)
    gamma_reg   = _gamma_regime_label(gamma)
    flip_risk   = bool(gamma.get("flip_risk"))
    flip_proximity: Optional[float] = None
    if zero_gamma and price > 0:
        flip_proximity = round(abs(_sf(zero_gamma) - price), 2)

    # ── Flow ─────────────────────────────────────────────────────────────
    flow_bias     = str(flow_snapshot.get("bias") or "MIXED")
    net_premium   = _sf(flow_snapshot.get("net_premium"))
    call_premium  = _sf(flow_snapshot.get("call_premium"))
    put_premium   = _sf(flow_snapshot.get("put_premium"))
    sweep_count   = int(_sf(flow_intel.get("sweep_count") or flow_snapshot.get("sweep_count")))
    flow_momentum = str(flow_intel.get("flow_momentum") or "STABLE")
    divergence_type = flow_intel.get("divergence_type")

    # Tape
    tape_bias    = str(tape_summary.get("tape_bias") or "MIXED")
    tape_net     = _sf(tape_summary.get("net_premium"))
    tape_sweeps  = int(_sf(tape_summary.get("sweep_count")))
    tape_blocks  = int(_sf(tape_summary.get("block_count")))

    # ── Execution / ICI ──────────────────────────────────────────────────
    pine_st       = _pine_state(execution)
    signal_fresh  = bool(execution.get("signal_fresh"))
    signal_secs   = int(_sf(execution.get("signal_seconds_remaining")))
    signal_matches= bool(execution.get("signal_matches_flow"))
    ici_value     = _sf(ici_obj.get("ici") or result.get("confidence"))
    decision_state= str(result.get("decision_state") or "NO_TRADE")
    approved_side = str(risk.get("approved_side") or consensus.get("consensus_direction") or "NONE")

    # ── Session ──────────────────────────────────────────────────────────
    session_state  = str(session_ctx.get("session_state") or "UNKNOWN")
    is_tradeable   = bool(session_ctx.get("is_tradeable_session"))
    minutes_open   = _minutes_since_open()

    # ── Nearest support / resistance ─────────────────────────────────────
    levels_proximity = _support_resistance_label(price, poc, vwap, vah, val,
                                                  _sf(call_wall) or None,
                                                  _sf(put_wall)  or None)

    return {
        # ── Identity ──
        "ticker":            result.get("ticker", "SPX"),
        "price":             round(price, 2) if price else None,
        "session_state":     session_state,
        "is_tradeable":      is_tradeable,
        "minutes_open":      minutes_open,

        # ── Structure ──
        "vwap":              round(vwap, 2) if vwap else None,
        "poc":               round(poc,  2) if poc  else None,
        "vah":               round(vah,  2) if vah  else None,
        "val":               round(val,  2) if val  else None,
        "hvn":               hvn,
        "lvn":               lvn,
        "poc_migration":     poc_migration,
        "poc_delta":         round(poc_delta, 2) if poc_delta else None,
        "auction_state":     auction_state,
        "profile_available": profile_available,
        "poc_vwap_confluent":poc_vwap_conf,
        "confluence_level":  confluence_level,

        # ── Location flags ──
        "price_vs_poc":      pvp,
        "price_vs_va":       pva,
        **levels_proximity,

        # ── Gamma / dealer ──
        "call_wall":         round(_sf(call_wall), 2) if call_wall else None,
        "put_wall":          round(_sf(put_wall),  2) if put_wall  else None,
        "zero_gamma":        round(_sf(zero_gamma),2) if zero_gamma else None,
        "gex_score":         round(gex_score, 1),
        "gamma_regime":      gamma_reg,       # POSITIVE / NEGATIVE / MIXED
        "flip_risk":         flip_risk,
        "flip_proximity":    flip_proximity,

        # ── Flow ──
        "flow_bias":         flow_bias,
        "net_premium":       round(net_premium,  0),
        "call_premium":      round(call_premium, 0),
        "put_premium":       round(put_premium,  0),
        "sweep_count":       sweep_count,
        "flow_momentum":     flow_momentum,
        "divergence_type":   divergence_type,

        # ── Flow tape ──
        "tape_bias":         tape_bias,
        "tape_net":          round(tape_net,    0),
        "tape_sweeps":       tape_sweeps,
        "tape_blocks":       tape_blocks,

        # ── Execution / ICI ──
        "pine_state":        pine_st,
        "signal_fresh":      signal_fresh,
        "signal_secs":       signal_secs,
        "signal_matches":    signal_matches,
        "ici":               round(ici_value, 1),
        "decision_state":    decision_state,
        "approved_side":     approved_side,

        # ── Risk levels (for coach + replay) ──
        "entry_zone":        risk.get("entry_zone"),
        "stop":              risk.get("stop"),
        "target1":           risk.get("target1"),
        "target2":           risk.get("target2"),
        "contract_hint":     risk.get("contract_hint"),
    }
