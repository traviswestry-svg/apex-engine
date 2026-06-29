"""engine/trade_coach.py — APEX 6.3.5 Trade Coach 3.0.

Upgrades the Trade Coach into a full decision assistant that produces:
  - Decision state and approved side
  - Trade readiness score (0–100)
  - Entry zone, invalidation level, stop, targets
  - Scale-out plan
  - "Do not trade because..." blockers
  - Confirmation checklist

Inputs consumed:
  ICI, consensus, Pine/execution, flow tape summary, gamma regime,
  volume profile levels, auction state, VWAP, POC, VAH/VAL.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional


def _sf(v: Any, d: float = 0.0) -> float:
    try:
        f = float(v) if v is not None else d
        return d if (math.isnan(f) or math.isinf(f)) else f
    except Exception:
        return d


def build_trade_coach_v3(
    *,
    decision_state: str,
    consensus: Dict[str, Any],
    execution: Dict[str, Any],
    risk: Dict[str, Any],
    gamma_regime: Dict[str, Any],
    flow: Dict[str, Any],
    structure: Dict[str, Any],
    ici: Dict[str, Any],
    # New 6.3.5 inputs
    auction: Optional[Dict[str, Any]] = None,
    volume_profile: Optional[Dict[str, Any]] = None,
    flow_tape_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Trade Coach 3.0 — actionable decision assistant."""
    confidence = _sf(ici.get("ici"), 0.0)
    consensus_dir = consensus.get("consensus_direction", "NEUTRAL")
    side = (
        risk.get("approved_side")
        or ("CALL" if consensus_dir == "BULLISH" else "PUT" if consensus_dir == "BEARISH" else "NONE")
    )

    # ── Volume Profile / Auction context ──
    vp  = volume_profile or {}
    au  = auction or {}
    vp_levels = (vp.get("levels") or {}) if isinstance(vp, dict) else {}
    poc  = _sf(au.get("poc") or vp_levels.get("poc"))
    vah  = _sf(au.get("vah") or vp_levels.get("vah"))
    val_ = _sf(au.get("val") or vp_levels.get("val"))
    mig  = au.get("poc_migration", "UNKNOWN")
    au_state = au.get("auction_state", "")
    profile_ok = au.get("available", False)
    vwap = _sf(structure.get("vwap"))
    price = _sf(structure.get("current_price") or au.get("current_price"))

    # ── Flow Tape context ──
    tape = flow_tape_summary or {}
    tape_bias = tape.get("tape_bias", "MIXED")
    tape_net = _sf(tape.get("net_premium"))
    tape_sweeps = int(_sf(tape.get("sweep_count")))

    # ── Blockers ──
    blockers: List[str] = []
    exec_state = execution.get("execution_state", "WAITING_FOR_PINE")
    if exec_state in ("WAITING_FOR_PINE", "SIGNAL_EXPIRED", "NO_SIGNAL"):
        blockers.append("Fresh Pine confirmation missing")
    if flow.get("divergence_type") == "A_PLUS":
        d_dir = flow.get("divergence_direction", "")
        blockers.append(f"A+ {d_dir} flow divergence active — trade with caution")
    if gamma_regime.get("flip_risk"):
        blockers.append("Price near zero-gamma flip — regime unstable")
    if confidence < 50:
        blockers.append(f"Institutional Confidence at {confidence:.0f} (minimum 50 required)")
    if profile_ok and poc > 0 and price > 0:
        if side == "CALL" and price < val_:
            blockers.append(f"Price below VAL ({val_:.2f}) — not accepting higher prices yet")
        elif side == "PUT" and price > vah:
            blockers.append(f"Price above VAH ({vah:.2f}) — not accepting lower prices yet")
    if tape_sweeps > 0:
        if side == "CALL" and tape_bias == "BEARISH":
            blockers.append("Flow tape shows bearish sweep aggression opposing call bias")
        elif side == "PUT" and tape_bias == "BULLISH":
            blockers.append("Flow tape shows bullish sweep aggression opposing put bias")

    # ── Confirmation checklist ──
    checklist: List[Dict[str, Any]] = []

    def _check(label, met, note=""):
        checklist.append({"label": label, "met": met, "note": note})

    _check("Pine signal confirmed",
           "CONFIRMED" in exec_state,
           exec_notes_first(execution))
    _check("Flow bias aligned with side",
           (flow.get("bias","MIXED") == "BULLISH" and side == "CALL") or
           (flow.get("bias","MIXED") == "BEARISH" and side == "PUT"),
           f"Flow bias: {flow.get('bias','MIXED')}")
    _check("Tape aggression aligned",
           (tape_bias in ("BULLISH","MIXED") and side == "CALL") or
           (tape_bias in ("BEARISH","MIXED") and side == "PUT"),
           f"Tape bias: {tape_bias}, sweeps: {tape_sweeps}")
    if profile_ok and poc > 0:
        poc_ok = (side == "CALL" and price >= poc) or (side == "PUT" and price <= poc)
        _check("Price on correct side of POC",
               poc_ok, f"POC: {poc:.2f}, price: {price:.2f}")
    _check("Gamma regime supports trade",
           not gamma_regime.get("flip_risk", False),
           gamma_regime.get("regime_display",""))
    _check("ICI ≥ 65",
           confidence >= 65,
           f"ICI: {confidence:.0f}")
    _check("Session is tradeable",
           execution.get("session_is_tradeable", True),
           "")

    # ── Action / narrative ──
    entry_zone = risk.get("entry_zone", "--")
    stop = risk.get("stop")
    t1 = risk.get("target1")
    t2 = risk.get("target2")

    # Enrich entry zone with POC/VWAP context
    entry_note = ""
    if profile_ok and poc > 0 and vwap > 0:
        if side == "CALL":
            support_level = max(poc, vwap) if poc and vwap else poc or vwap
            entry_note = f"Watch for pullback into POC/VWAP confluence near {support_level:.2f} for entry."
        elif side == "PUT":
            resist_level = min(poc, vwap) if poc and vwap else poc or vwap
            entry_note = f"Watch for bounce into POC/VWAP near {resist_level:.2f} for put entry."

    # Scale-out plan
    scale_out: List[str] = []
    if t1 is not None:
        scale_out.append(f"Scale 50% at T1 ({t1:.2f})")
    if t2 is not None:
        scale_out.append(f"Let 50% run to T2 ({t2:.2f})")
    if vah > 0 and val_ > 0 and side == "CALL":
        scale_out.append(f"Watch VAH ({vah:.2f}) and Call Wall as additional scale targets")
    elif vah > 0 and val_ > 0 and side == "PUT":
        scale_out.append(f"Watch VAL ({val_:.2f}) and Put Wall as additional scale targets")
    if not scale_out:
        scale_out.append("No scale plan available — risk module requires position sizing input")

    # Invalidation level
    invalidation = None
    if stop is not None:
        invalidation = stop
    elif poc > 0 and vwap > 0:
        if side == "CALL":
            invalidation = round(min(poc, vwap) - 2.0, 2)
        elif side == "PUT":
            invalidation = round(max(poc, vwap) + 2.0, 2)

    # Build action narrative
    if decision_state in ("ENTER_CALL", "ENTER_PUT"):
        action = (
            f"Enter {side.lower()} now. "
            f"Entry zone: {entry_zone}. "
            f"Stop: {'$'+f'{stop:.2f}' if stop is not None else 'see risk plan'}. "
            f"T1: {'$'+f'{t1:.2f}' if t1 is not None else '--'}, "
            f"T2: {'$'+f'{t2:.2f}' if t2 is not None else '--'}."
        )
        if profile_ok and poc > 0:
            price_vs_poc = "above" if price > poc else "below"
            action += f" Price is {price_vs_poc} POC ({poc:.2f})."
        if tape_sweeps > 0 and tape_bias != "MIXED":
            action += f" {tape_sweeps} {tape_bias.lower()} sweeps confirm institutional aggression."
    elif decision_state == "READY":
        action = (
            f"Setup ready for {side.lower()}s. "
            f"Wait for fresh Pine confirmation before entering. "
            f"{entry_note}"
        )
    elif decision_state in ("WATCH_CALLS", "WATCH_PUTS"):
        action = (
            f"Watch {side.lower()}s — do not front-run confirmation. "
            f"{entry_note} "
            f"Confirm Pine signal before entering."
        )
    elif decision_state == "NO_TRADE":
        reasons = blockers[:2] if blockers else ["flow, structure, gamma, and execution not aligned"]
        action = f"No trade. {'; '.join(reasons)}. Wait for all gates to align."
    else:
        action = "Prepare only. Let the engines build cleaner alignment before entering."

    # Trade readiness score (0–100)
    checks_met = sum(1 for c in checklist if c["met"])
    readiness = int(round(checks_met / max(len(checklist), 1) * 100))

    return {
        "state":              decision_state,
        "action":             action.strip(),
        "entry_note":         entry_note,
        "approved_side":      side,
        "contract_hint":      risk.get("contract_hint"),
        "entry_zone":         entry_zone,
        "invalidation":       invalidation,
        "stop":               stop,
        "target1":            t1,
        "target2":            t2,
        "scale_out_plan":     scale_out,
        "gamma_management":   gamma_regime.get("trade_rules", {}).get("expected_behavior"),
        "blockers":           blockers,
        "checklist":          checklist,
        "readiness":          readiness,
        "next_confirmation":  (
            f"Fresh Pine trigger matching {side} side"
            if exec_state not in (f"CONFIRMED_{side}",) and side in ("CALL","PUT")
            else "Manage active decision from risk plan"
        ),
        # Context fields for UI display
        "poc":   round(poc, 2) if poc else None,
        "vah":   round(vah, 2) if vah else None,
        "val":   round(val_, 2) if val_ else None,
        "vwap":  round(vwap, 2) if vwap else None,
        "poc_migration":  mig,
        "auction_state":  au_state,
        "tape_bias":      tape_bias,
        "tape_sweeps":    tape_sweeps,
    }


def exec_notes_first(execution: Dict[str, Any]) -> str:
    notes = execution.get("notes") or []
    return notes[0] if notes else ""


# Legacy re-export shim
try:
    from apex_engines import build_trade_coach  # noqa: F401
except Exception:
    def build_trade_coach(*a, **kw): return {}   # type: ignore[misc]
