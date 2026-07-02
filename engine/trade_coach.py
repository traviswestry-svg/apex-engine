"""engine/trade_coach.py — APEX 6.4.1 Trade Coach 3.1

The decision center. Produces a complete, actionable trade plan that
a trader can read once and execute from — not a dashboard of metrics.

Output at ENTER_CALL:
    "Enter call setup. Entry 7351–7354. Stop $7343.50 (below POC/VWAP
    confluence). Invalidation: close below VAL $7341. Target 1: $7362
    (VAH — scale 50% here). Target 2: $7375 (Call Wall — trail rest).
    Scale plan: take 50% at T1, move stop to entry, trail remainder.
    Do not enter if: price drops below VWAP before fill; Pine expires;
    tape flips to sell sweeps."

Canonical input: market_state from engine/market_state.py
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple


def _sf(v: Any, d: float = 0.0) -> float:
    try:
        f = float(v) if v is not None else d
        return d if (math.isnan(f) or math.isinf(f)) else f
    except Exception:
        return d


def _fmt(v: float, decimals: int = 2) -> str:
    return f"{v:,.{decimals}f}"


def _prem(v: float) -> str:
    av = abs(v)
    if av >= 1_000_000:
        return f"${av/1_000_000:.1f}M"
    if av >= 1_000:
        return f"${av/1_000:.0f}K"
    return f"${av:.0f}"


# ── Entry zone enrichment ────────────────────────────────────────────────────

def _build_entry_guidance(ms: Dict[str, Any], side: str) -> str:
    """Plain-language entry guidance based on auction structure."""
    poc   = _sf(ms.get("poc"))
    vwap  = _sf(ms.get("vwap"))
    vah   = _sf(ms.get("vah"))
    val_  = _sf(ms.get("val"))
    pva   = ms.get("price_vs_va", "UNKNOWN")
    pvp   = ms.get("price_vs_poc", "UNKNOWN")
    conf  = ms.get("poc_vwap_confluent", False)
    conf_level = ms.get("confluence_level")

    if side == "CALL":
        if conf and conf_level:
            return (
                f"Wait for a pullback into the POC/VWAP confluence near "
                f"{_fmt(conf_level)} — that is your optimal entry. "
                f"Alternatively, enter on a clean break above VAH ({_fmt(vah)}) "
                f"with volume if price is already holding above."
            )
        elif poc > 0 and pvp == "ABOVE":
            return (
                f"Enter on a pullback to or near POC ({_fmt(poc)}) or VWAP ({_fmt(vwap)}). "
                f"A reclaim of POC after a brief dip is the higher-probability entry."
            )
        elif pva == "ABOVE_VAH":
            return (
                f"Price is already above the Value Area. Enter on the current bar "
                f"or a small pullback into VAH ({_fmt(vah)}). "
                f"Do not chase if price extends more than 5 points above VAH."
            )
        else:
            return f"Enter near current price or a pullback toward POC ({_fmt(poc)})."

    elif side == "PUT":
        if conf and conf_level:
            return (
                f"Wait for a bounce into the POC/VWAP confluence near "
                f"{_fmt(conf_level)} — that is your optimal put entry. "
                f"Alternatively, enter on a clean break below VAL ({_fmt(val_)})."
            )
        elif poc > 0 and pvp == "BELOW":
            return (
                f"Enter on a bounce to or near POC ({_fmt(poc)}) or VWAP ({_fmt(vwap)}). "
                f"A rejection of POC after a bounce is the higher-probability entry."
            )
        elif pva == "BELOW_VAL":
            return (
                f"Price is already below the Value Area. Enter on the current bar "
                f"or a small bounce into VAL ({_fmt(val_)}). "
                f"Do not chase if price extends more than 5 points below VAL."
            )
        else:
            return f"Enter near current price or a bounce toward POC ({_fmt(poc)})."

    return "Entry zone from risk engine."


# ── Stop / invalidation ──────────────────────────────────────────────────────

def _build_stop_guidance(ms: Dict[str, Any], side: str, stop: Optional[float]) -> Tuple[str, Optional[float]]:
    """
    Returns (stop_narrative, invalidation_price).
    Invalidation is the structural level that ends the thesis entirely
    (e.g. close below VAL on a call setup).
    """
    poc   = _sf(ms.get("poc"))
    vwap  = _sf(ms.get("vwap"))
    vah   = _sf(ms.get("vah"))
    val_  = _sf(ms.get("val"))
    conf  = ms.get("poc_vwap_confluent", False)
    conf_level = ms.get("confluence_level")

    if stop is not None:
        stop_str = f"${_fmt(stop)}"
    else:
        stop = None
        stop_str = "see risk plan"

    if side == "CALL":
        if conf and conf_level:
            inv = round(conf_level - 3.0, 2)
            narrative = (
                f"Stop: {stop_str}. "
                f"Invalidation: close below POC/VWAP confluence ({_fmt(conf_level)}) "
                f"— a close below {_fmt(inv)} ends the bullish thesis."
            )
        elif poc > 0 and vwap > 0:
            inv = round(min(poc, vwap) - 2.0, 2)
            narrative = (
                f"Stop: {stop_str}. "
                f"Invalidation: price closes below both POC ({_fmt(poc)}) and VWAP ({_fmt(vwap)}) "
                f"— a close below {_fmt(inv)} invalidates the setup."
            )
        elif val_ > 0:
            inv = round(val_ - 1.0, 2)
            narrative = (
                f"Stop: {stop_str}. "
                f"Invalidation: close below VAL ({_fmt(val_)}) "
                f"— that signals the auction has turned bearish."
            )
        else:
            inv = round(stop - 2.0, 2) if stop else None
            narrative = f"Stop: {stop_str}."

    elif side == "PUT":
        if conf and conf_level:
            inv = round(conf_level + 3.0, 2)
            narrative = (
                f"Stop: {stop_str}. "
                f"Invalidation: close above POC/VWAP confluence ({_fmt(conf_level)}) "
                f"— a close above {_fmt(inv)} ends the bearish thesis."
            )
        elif poc > 0 and vwap > 0:
            inv = round(max(poc, vwap) + 2.0, 2)
            narrative = (
                f"Stop: {stop_str}. "
                f"Invalidation: price closes above both POC ({_fmt(poc)}) and VWAP ({_fmt(vwap)}) "
                f"— a close above {_fmt(inv)} invalidates the setup."
            )
        elif vah > 0:
            inv = round(vah + 1.0, 2)
            narrative = (
                f"Stop: {stop_str}. "
                f"Invalidation: close above VAH ({_fmt(vah)}) "
                f"— that signals the auction has turned bullish."
            )
        else:
            inv = round(stop + 2.0, 2) if stop else None
            narrative = f"Stop: {stop_str}."

    else:
        inv = None
        narrative = f"Stop: {stop_str}."

    return narrative, inv


# ── Target guidance ──────────────────────────────────────────────────────────

def _build_target_guidance(ms: Dict[str, Any], side: str, t1: Optional[float], t2: Optional[float]) -> str:
    vah       = _sf(ms.get("vah"))
    val_      = _sf(ms.get("val"))
    call_wall = _sf(ms.get("call_wall"))
    put_wall  = _sf(ms.get("put_wall"))

    parts = []

    if t1 is not None:
        t1_context = ""
        if side == "CALL" and vah > 0 and abs(t1 - vah) < 5.0:
            t1_context = f" ({_fmt(vah)} VAH — scale 50% here)"
        elif side == "PUT" and val_ > 0 and abs(t1 - val_) < 5.0:
            t1_context = f" ({_fmt(val_)} VAL — scale 50% here)"
        else:
            t1_context = " (scale 50% here)"
        parts.append(f"T1: ${_fmt(t1)}{t1_context}")

    if t2 is not None:
        t2_context = ""
        if side == "CALL" and call_wall > 0 and abs(t2 - call_wall) < 10.0:
            t2_context = f" ({_fmt(call_wall)} Call Wall — trail remainder)"
        elif side == "PUT" and put_wall > 0 and abs(t2 - put_wall) < 10.0:
            t2_context = f" ({_fmt(put_wall)} Put Wall — trail remainder)"
        else:
            t2_context = " (let remainder run)"
        parts.append(f"T2: ${_fmt(t2)}{t2_context}")

    if not parts:
        return "Targets from risk engine — check risk panel."

    return ". ".join(parts) + "."


# ── Scale-out plan ───────────────────────────────────────────────────────────

def _build_scale_plan(ms: Dict[str, Any], side: str, t1: Optional[float], t2: Optional[float]) -> List[str]:
    steps = []

    if t1 is not None:
        steps.append(f"At T1 (${_fmt(t1)}): exit 50% of the position")
        steps.append("Move stop to entry (breakeven)")

    if t2 is not None:
        steps.append(f"Above T1: trail stop 5 points below price")
        steps.append(f"At T2 (${_fmt(t2)}): exit remaining 50% unless momentum is accelerating")

    wall = _sf(ms.get("call_wall") if side == "CALL" else ms.get("put_wall"))
    if wall > 0 and t2 is not None and abs(wall - t2) > 10.0:
        wall_label = "Call Wall" if side == "CALL" else "Put Wall"
        steps.append(f"{wall_label} ({_fmt(wall)}) is an additional target if T2 breaks")

    if not steps:
        steps.append("Scale out in thirds at each risk level per your plan")

    return steps


# ── Do-not-trade conditions ──────────────────────────────────────────────────

def _build_dont_trade_list(ms: Dict[str, Any], side: str, secs_remaining: int) -> List[str]:
    """Specific, structural conditions that invalidate the setup in real time."""
    conditions = []

    poc  = _sf(ms.get("poc"))
    vwap = _sf(ms.get("vwap"))
    vah  = _sf(ms.get("vah"))
    val_ = _sf(ms.get("val"))
    pva  = ms.get("price_vs_va", "UNKNOWN")

    # Time-based
    if secs_remaining > 0:
        mins = secs_remaining // 60
        conditions.append(f"Pine signal expires in {mins}m — enter promptly or wait for next trigger")

    # Price structural
    if side == "CALL":
        if vwap > 0:
            conditions.append(f"Price drops below VWAP ({_fmt(vwap)}) before your fill")
        if poc > 0:
            conditions.append(f"Price closes below POC ({_fmt(poc)}) on a 5-minute bar")
        if pva == "ABOVE_VAH":
            conditions.append(f"Price fails to hold above VAH ({_fmt(vah)}) for more than 2 bars")
    elif side == "PUT":
        if vwap > 0:
            conditions.append(f"Price reclaims VWAP ({_fmt(vwap)}) before your fill")
        if poc > 0:
            conditions.append(f"Price closes above POC ({_fmt(poc)}) on a 5-minute bar")
        if pva == "BELOW_VAL":
            conditions.append(f"Price reclaims VAL ({_fmt(val_)}) for more than 2 bars")

    # Flow / tape
    tape_bias  = ms.get("tape_bias", "MIXED")
    tape_sweeps= ms.get("tape_sweeps", 0) or 0
    if side == "CALL" and tape_bias == "BEARISH" and tape_sweeps >= 3:
        conditions.append(f"Flow tape shows {tape_sweeps} active put sweeps against your direction")
    elif side == "PUT" and tape_bias == "BULLISH" and tape_sweeps >= 3:
        conditions.append(f"Flow tape shows {tape_sweeps} active call sweeps against your direction")

    # Gamma
    if ms.get("flip_risk") and ms.get("flip_proximity") is not None:
        fp = ms.get("flip_proximity")
        conditions.append(f"Zero-gamma flip is only {_fmt(fp)} points away — regime can shift fast")

    return conditions


# ── Confirmation checklist ───────────────────────────────────────────────────

def _build_checklist(ms: Dict[str, Any], side: str) -> List[Dict[str, Any]]:
    def check(label: str, met: bool, note: str = "") -> Dict[str, Any]:
        return {"label": label, "met": met, "note": note}

    poc   = _sf(ms.get("poc"))
    vwap  = _sf(ms.get("vwap"))
    price = _sf(ms.get("price"))
    pva   = ms.get("price_vs_va", "UNKNOWN")
    pvp   = ms.get("price_vs_poc", "UNKNOWN")
    mig   = ms.get("poc_migration", "UNKNOWN")
    pine  = ms.get("pine_state", "WAITING")
    fresh = ms.get("signal_fresh", False)
    matches = ms.get("signal_matches", False)
    ici   = ms.get("ici", 0.0)
    tape_bias = ms.get("tape_bias", "MIXED")
    flow_bias = ms.get("flow_bias", "MIXED")
    g_regime  = ms.get("gamma_regime", "MIXED")
    flip      = ms.get("flip_risk", False)
    is_trade  = ms.get("is_tradeable", False)

    items = [
        check("Market is open (RTH)",
               is_trade,
               "Market must be open for new entries" if not is_trade else ""),
        check("ICI ≥ 65", ici >= 65, f"Current: {ici:.0f}"),
        check("Pine signal confirmed and fresh", pine == "CONFIRMED" and fresh and matches,
              f"State: {pine}, Matches flow: {matches}"),
        check("Flow bias aligns with trade",
              (flow_bias == "BULLISH" and side == "CALL") or (flow_bias == "BEARISH" and side == "PUT"),
              f"Flow bias: {flow_bias}"),
        check("Tape bias aligns or neutral",
              tape_bias in ("MIXED",) or
              (tape_bias == "BULLISH" and side == "CALL") or
              (tape_bias == "BEARISH" and side == "PUT"),
              f"Tape bias: {tape_bias}"),
    ]

    if ms.get("profile_available"):
        if side == "CALL":
            poc_ok = pvp == "ABOVE" or pva == "ABOVE_VAH"
            items.append(check("Price above POC", poc_ok,
                               f"Price vs POC: {pvp}, vs VA: {pva}"))
            mig_ok = mig in ("RISING", "STABLE")
            items.append(check("POC not migrating against trade", mig_ok,
                               f"Migration: {mig}"))
        elif side == "PUT":
            poc_ok = pvp == "BELOW" or pva == "BELOW_VAL"
            items.append(check("Price below POC", poc_ok,
                               f"Price vs POC: {pvp}, vs VA: {pva}"))
            mig_ok = mig in ("FALLING", "STABLE")
            items.append(check("POC not migrating against trade", mig_ok,
                               f"Migration: {mig}"))

    items.append(check("No flip-risk / gamma instability", not flip,
                       "Gamma flip proximity: " + str(ms.get("flip_proximity"))))

    return items


# ── Public API ───────────────────────────────────────────────────────────────

def build_trade_coach_v3(
    *,
    decision_state:  str,
    consensus:       Dict[str, Any],
    execution:       Dict[str, Any],
    risk:            Dict[str, Any],
    gamma_regime:    Dict[str, Any],
    flow:            Dict[str, Any],
    structure:       Dict[str, Any],
    ici:             Dict[str, Any],
    auction:         Optional[Dict[str, Any]] = None,
    volume_profile:  Optional[Dict[str, Any]] = None,
    flow_tape_summary: Optional[Dict[str, Any]] = None,
    # 6.4.1: canonical market state preferred
    market_state:    Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Trade Coach 3.1 — the decision center.

    Returns a complete, actionable trade plan with:
    - Decision state and approved side
    - Trade readiness score (0–100)
    - Entry guidance
    - Stop narrative + invalidation level
    - Target guidance
    - Scale-out plan
    - Do-not-trade conditions
    - Confirmation checklist
    """
    # ── Resolve market state ──
    if market_state is not None:
        ms = market_state
    else:
        # Lightweight compat shim
        vp  = volume_profile or {}
        au  = auction or {}
        vpl = (vp.get("levels") or {}) if isinstance(vp, dict) else {}
        tape = flow_tape_summary or {}
        poc  = _sf(vpl.get("poc") or au.get("poc") or structure.get("session_poc"))
        vah  = _sf(vpl.get("vah") or au.get("vah"))
        val_ = _sf(vpl.get("val") or au.get("val"))
        vwap = _sf(structure.get("vwap"))
        price= _sf(structure.get("current_price") or au.get("current_price"))

        g_label = str(gamma_regime.get("regime_label","")).upper()
        g_reg   = "POSITIVE" if "POSITIVE" in g_label else "NEGATIVE" if "NEGATIVE" in g_label else "MIXED"
        exec_state = str(execution.get("execution_state","")).upper()
        pine_st = "CONFIRMED" if "CONFIRMED" in exec_state else "WAITING"

        try:
            from engine.market_state import _price_vs_poc, _price_vs_va, _poc_vwap_confluent
            pvp  = _price_vs_poc(price, poc)
            pva  = _price_vs_va(price, vah, val_)
            conf = _poc_vwap_confluent(poc, vwap)
        except Exception:
            pvp  = "UNKNOWN"; pva = "UNKNOWN"; conf = False

        ms = {
            "price": price, "vwap": vwap, "poc": poc, "vah": vah, "val": val_,
            "poc_migration": au.get("poc_migration","UNKNOWN"),
            "profile_available": bool(vp.get("available") or au.get("available")),
            "poc_vwap_confluent": conf,
            "confluence_level": round((poc+vwap)/2,2) if conf and poc and vwap else None,
            "price_vs_poc": pvp, "price_vs_va": pva,
            "call_wall": gamma_regime.get("call_wall"), "put_wall": gamma_regime.get("put_wall"),
            "gamma_regime": g_reg, "flip_risk": bool(gamma_regime.get("flip_risk")),
            "flip_proximity": None,
            "flow_bias": flow.get("bias","MIXED"),
            "net_premium": _sf(flow.get("net_premium")),
            "sweep_count": int(_sf(flow.get("sweep_count"))),
            "divergence_type": flow.get("divergence_type"),
            "tape_bias": tape.get("tape_bias","MIXED"),
            "tape_net": _sf(tape.get("net_premium")),
            "tape_sweeps": int(_sf(tape.get("sweep_count"))),
            "tape_blocks": int(_sf(tape.get("block_count"))),
            "pine_state": pine_st,
            "signal_fresh": bool(execution.get("signal_fresh")),
            "signal_secs": int(_sf(execution.get("signal_seconds_remaining"))),
            "signal_matches": bool(execution.get("signal_matches_flow")),
            "ici": _sf(ici.get("ici") or 0.0),
            "decision_state": decision_state,
            "approved_side": risk.get("approved_side","NONE"),
            "session_state": "MARKET_OPEN",
            "is_tradeable": True,
            "entry_zone": risk.get("entry_zone"),
            "stop": risk.get("stop"), "target1": risk.get("target1"),
            "target2": risk.get("target2"), "contract_hint": risk.get("contract_hint"),
        }

    # ── Core fields ──
    confidence  = _sf(ms.get("ici"))
    side = (
        ms.get("approved_side")
        or ("CALL" if consensus.get("consensus_direction") == "BULLISH"
            else "PUT" if consensus.get("consensus_direction") == "BEARISH"
            else "NONE")
    )
    stop  = risk.get("stop")
    t1    = risk.get("target1")
    t2    = risk.get("target2")
    entry = risk.get("entry_zone", "--")
    contract = risk.get("contract_hint", "")
    secs  = ms.get("signal_secs", 0) or 0

    # ── Build components ──
    entry_guidance   = _build_entry_guidance(ms, side)
    stop_narrative, invalidation = _build_stop_guidance(ms, side, stop)
    target_guidance  = _build_target_guidance(ms, side, t1, t2)
    scale_plan       = _build_scale_plan(ms, side, t1, t2)
    dont_trade       = _build_dont_trade_list(ms, side, secs)
    checklist        = _build_checklist(ms, side)

    # ── Readiness score ──
    checks_met = sum(1 for c in checklist if c["met"])
    readiness  = int(round(checks_met / max(len(checklist), 1) * 100))

    # ── Blockers (subset of checklist failures) ──
    blockers = [c["label"] for c in checklist if not c["met"]]

    # ── Main action narrative ──
    if decision_state in ("ENTER_CALL", "ENTER_PUT"):
        mins_str = f" ({secs//60}m {secs%60}s on clock)" if secs > 0 else ""
        action = (
            f"ENTER {side}. {contract}{mins_str}. "
            f"Entry: {entry}. {stop_narrative} {target_guidance}"
        ).strip()

    elif decision_state == "READY":
        action = (
            f"Setup is ready for {side.lower()}s — all structural gates are clear. "
            f"Waiting for Pine to confirm before entering. "
            f"{entry_guidance}"
        )

    elif "WATCH" in decision_state:
        side_label = "calls" if "CALL" in decision_state else "puts"
        primary_blocker = blockers[0] if blockers else "not all gates aligned"
        action = (
            f"Watch {side_label} — conditions are building but not ready. "
            f"Primary blocker: {primary_blocker}. {entry_guidance}"
        )

    elif decision_state == "NO_TRADE":
        if not ms.get("is_tradeable"):
            action = "Market is closed. No trade. Review the context for tomorrow's session."
        elif blockers:
            blocker_str = "; ".join(blockers[:3])
            action = f"No trade. Blocked by: {blocker_str}. Wait for all gates to align before entering."
        else:
            action = "No trade. Market structure and flow are not aligned enough to act on."
    else:
        action = "Monitoring — let the engines build cleaner alignment before entering."

    # ── Next confirmation ──
    pine = ms.get("pine_state", "WAITING")
    if pine == "CONFIRMED" and side in ("CALL", "PUT"):
        next_conf = "Manage active setup — Pine is confirmed. Respect your stop and scale plan."
    elif pine == "WAITING" and "WATCH" in decision_state:
        next_conf = f"Wait for a fresh Pine {side.lower()} trigger that aligns with the current flow."
    else:
        next_conf = f"Wait for Pine to confirm a {side.lower()} signal before entering."

    return {
        # ── Core ──
        "state":          decision_state,
        "action":         action,
        "approved_side":  side,
        "contract_hint":  contract,
        "readiness":      readiness,

        # ── Levels ──
        "entry_zone":     entry,
        "entry_guidance": entry_guidance,
        "stop":           stop,
        "stop_narrative": stop_narrative,
        "invalidation":   invalidation,
        "target1":        t1,
        "target2":        t2,
        "target_guidance":target_guidance,

        # ── Plan ──
        "scale_out_plan": scale_plan,
        "dont_trade_if":  dont_trade,
        "blockers":       blockers,
        "checklist":      checklist,

        # ── Meta ──
        "next_confirmation": next_conf,
        "gamma_management":  gamma_regime.get("trade_rules", {}).get("expected_behavior"),

        # ── APEX 7.0 Institutional context fields ──
        "dealer_behavior_expected":   (
            "Dealers in negative gamma — expect amplified moves in the direction of flow." if ms.get("gamma_regime") == "NEGATIVE"
            else "Dealers in positive gamma — expect mean-reversion and suppressed volatility." if ms.get("gamma_regime") == "POSITIVE"
            else "Dealer behavior is approximately neutral."
        ),
        "auction_behavior_expected":  (
            "Accepting higher — POC migrating higher confirms institutional value migration." if ms.get("poc_migration") == "RISING"
            else "Accepting lower — POC migrating lower confirms distribution." if ms.get("poc_migration") == "FALLING"
            else "Balanced auction — no directional acceptance confirmed yet."
        ),
        "flow_confirmation_needed":   (
            "Wait for bullish flow score ≥70 with fresh Pine confirmation." if side == "CALL"
            else "Wait for bearish flow score ≤30 with fresh Pine confirmation." if side == "PUT"
            else "Wait for directional flow alignment before entering."
        ),
        "market_driver_confirmation_needed": (
            "Confirm NVDA/MSFT or tech mega-cap leadership before SPX call entry." if side == "CALL"
            else "Confirm broad weakness in large-cap constituents before SPX put entry." if side == "PUT"
            else "Monitor market driver breadth for directional confirmation."
        ),
        "expected_holding_time": (
            "15–45 minutes (0DTE — exit before 3:30 PM ET to avoid gamma decay acceleration)."
        ),

        # ── Context pass-through for UI ──
        "poc":            round(_sf(ms.get("poc")), 2) or None,
        "vah":            round(_sf(ms.get("vah")), 2) or None,
        "val":            round(_sf(ms.get("val")), 2) or None,
        "vwap":           round(_sf(ms.get("vwap")), 2) or None,
        "poc_migration":  ms.get("poc_migration"),
        "auction_state":  ms.get("auction_state"),
        "tape_bias":      ms.get("tape_bias"),
        "tape_sweeps":    ms.get("tape_sweeps"),
        "price_vs_poc":   ms.get("price_vs_poc"),
        "price_vs_va":    ms.get("price_vs_va"),
        "ici":            round(confidence, 1),
    }


# ── Legacy shim ──────────────────────────────────────────────────────────────
try:
    from apex_engines import build_trade_coach  # noqa: F401
except Exception:
    def build_trade_coach(*a, **kw): return {}   # type: ignore[misc]
