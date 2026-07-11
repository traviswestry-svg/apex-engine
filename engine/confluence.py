"""
engine/confluence.py — APEX 7.5.3 Confluence Synthesizer.

WHAT THIS IS
------------
A READ-ONLY synthesizer that answers a question the existing stack does not:
"How COMPLETE is the long setup, how complete is the short setup, and what
confirmations are still MISSING from each?"

It is deliberately NOT a second consensus engine. engine_consensus() already
produces the directional vote tally (which way the engines lean). Confluence is
a checklist-completeness view layered on top of the already-composed
Institutional Intelligence Layer: it maps each ALREADY-COMPUTED factor to whether
it supports a LONG setup, a SHORT setup, or neither, then reports two setup
scores plus the evidence and the missing confirmations for each side.

HARD RULES (mirrors the 7.5 master-prompt principles)
-----------------------------------------------------
- Consumes the composed Data Bus (last_result). NEVER re-fetches or recomputes
  gamma, flow, auction, drivers, pin, expected move, or trend — it reads the
  values those engines already published.
- Never raises into the caller; returns an {"available": False, ...} envelope on
  any problem so it can never 500 the dashboard.
- Every factor it scores is traceable to a named source field, so the output is
  auditable ("why did long score 70?" -> read the evidence list).

OUTPUT
------
{
  "available": true,
  "version": "...",
  "long_setup_score": 0-100,
  "short_setup_score": 0-100,
  "dominant_side": "LONG" | "SHORT" | "NEITHER",
  "conviction": "A+" | "STRONG" | "MODERATE" | "WEAK" | "NONE",
  "long_evidence":  [ "…supporting factor…", … ],
  "short_evidence": [ … ],
  "long_missing":   [ "…confirmation not yet present…", … ],
  "short_missing":  [ … ],
  "factor_table":   [ {factor, reads, long, short, note}, … ],  # audit trail
  "summary": "one-line plain-English read"
}
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

VERSION = "7.5.3_CONFLUENCE_SYNTHESIZER"


# ── tiny local helpers (same convention as sibling engines) ──────────────────
def _sf(v: Any, d: float = 0.0) -> float:
    try:
        if v is None:
            return d
        return float(v)
    except (TypeError, ValueError):
        return d


def _u(v: Any) -> str:
    return str(v or "").strip().upper()


# Each factor contributes up to `weight` points to whichever side it supports.
# Weights reflect how decisive each factor is for a 0DTE directional setup.
# They are transparent and hand-set — NOT fitted — so they can later be tuned or
# handed to an adaptive-weighting layer once real outcome history exists.
_WEIGHTS = {
    "institutional_bias": 18,
    "gamma_regime":       14,
    "flow":               16,
    "auction_acceptance": 14,
    "market_drivers":     12,
    "momentum":           10,
    "ici":                 8,
    "pine":                8,
}
_MAX = sum(_WEIGHTS.values())  # 100


def build_confluence(last_result: Dict[str, Any]) -> Dict[str, Any]:
    """Synthesize a long/short setup scorecard from the composed Data Bus.

    `last_result` is the same object /api/institutional_os composes; we read the
    already-published sub-blocks and never recompute them.
    """
    try:
        if not isinstance(last_result, dict) or not last_result:
            return _empty("No composed result on the bus yet.")

        inst = last_result.get("institutional_intelligence") or {}
        ms = last_result.get("market_state") or {}
        rng = ((last_result.get("range_intelligence") or {}).get("range_intelligence")
               if isinstance(last_result.get("range_intelligence"), dict) else {}) or {}

        if not inst:
            return _empty("Institutional Intelligence layer not populated yet.")

        long_pts = 0.0
        short_pts = 0.0
        long_ev: List[str] = []
        short_ev: List[str] = []
        long_missing: List[str] = []
        short_missing: List[str] = []
        table: List[Dict[str, Any]] = []

        def _apply(factor: str, side: str, note: str, reads: str):
            nonlocal long_pts, short_pts
            w = _WEIGHTS.get(factor, 0)
            row = {"factor": factor, "reads": reads, "long": 0, "short": 0, "note": note}
            if side == "LONG":
                long_pts += w
                long_ev.append(note)
                row["long"] = w
                short_missing.append(f"{factor}: {note}")
            elif side == "SHORT":
                short_pts += w
                short_ev.append(note)
                row["short"] = w
                long_missing.append(f"{factor}: {note}")
            else:  # NEUTRAL — not yet confirming either side
                long_missing.append(f"{factor}: neutral/undetermined")
                short_missing.append(f"{factor}: neutral/undetermined")
            table.append(row)

        # ── 1. Institutional bias ────────────────────────────────────────────
        ib = _u(inst.get("institutional_bias"))
        if "BULL" in ib:
            _apply("institutional_bias", "LONG", f"Institutional bias {ib}", "institutional_bias")
        elif "BEAR" in ib:
            _apply("institutional_bias", "SHORT", f"Institutional bias {ib}", "institutional_bias")
        else:
            _apply("institutional_bias", "NEUTRAL", "Institutional bias neutral", "institutional_bias")

        # ── 2. Dealer gamma regime ───────────────────────────────────────────
        gr = _u(inst.get("gamma_regime"))
        db = _u(inst.get("dealer_bias"))
        if "NEGATIVE" in gr:
            # negative gamma amplifies the prevailing direction; lean with dealer_bias
            if "BULL" in db:
                _apply("gamma_regime", "LONG", "Negative gamma amplifies upside (dealer bias bullish)", "gamma_regime+dealer_bias")
            elif "BEAR" in db:
                _apply("gamma_regime", "SHORT", "Negative gamma amplifies downside (dealer bias bearish)", "gamma_regime+dealer_bias")
            else:
                _apply("gamma_regime", "NEUTRAL", "Negative gamma but dealer bias unclear", "gamma_regime")
        elif "POSITIVE" in gr:
            _apply("gamma_regime", "NEUTRAL", "Positive gamma dampens/pins — favours neither breakout side", "gamma_regime")
        else:
            _apply("gamma_regime", "NEUTRAL", "Gamma regime undetermined", "gamma_regime")

        # ── 3. Options flow ──────────────────────────────────────────────────
        fb = _u(inst.get("flow_bias"))
        conv = _sf(inst.get("flow_conviction"))
        if "BULL" in fb and conv >= 40:
            _apply("flow", "LONG", f"Bullish net flow (conviction {conv:.0f})", "flow_bias+flow_conviction")
        elif "BEAR" in fb and conv >= 40:
            _apply("flow", "SHORT", f"Bearish net flow (conviction {conv:.0f})", "flow_bias+flow_conviction")
        else:
            _apply("flow", "NEUTRAL", f"Flow mixed/low-conviction ({fb or 'NONE'} {conv:.0f})", "flow_bias")

        # ── 4. Auction / acceptance ──────────────────────────────────────────
        au = _u(inst.get("auction_state"))
        acc = _u(inst.get("acceptance"))
        ab = _u(inst.get("auction_bias"))
        if "TREND" in au and "UP" in (au + ab):
            _apply("auction_acceptance", "LONG", "Trending auction, upside acceptance", "auction_state+auction_bias")
        elif "TREND" in au and "DOWN" in (au + ab):
            _apply("auction_acceptance", "SHORT", "Trending auction, downside acceptance", "auction_state+auction_bias")
        elif "ACCEPT" in acc and "BULL" in ab:
            _apply("auction_acceptance", "LONG", "Value accepting higher", "acceptance+auction_bias")
        elif "ACCEPT" in acc and "BEAR" in ab:
            _apply("auction_acceptance", "SHORT", "Value accepting lower", "acceptance+auction_bias")
        else:
            _apply("auction_acceptance", "NEUTRAL", f"Auction balanced/rotational ({au or 'NONE'})", "auction_state")

        # ── 5. Market drivers (mega-cap leadership) ──────────────────────────
        mdb = _u(inst.get("market_driver_bias"))
        if "BULL" in mdb:
            _apply("market_drivers", "LONG", "Mega-cap drivers supportive (bullish)", "market_driver_bias")
        elif "BEAR" in mdb:
            _apply("market_drivers", "SHORT", "Mega-cap drivers pressing (bearish)", "market_driver_bias")
        else:
            _apply("market_drivers", "NEUTRAL", "Driver breadth mixed", "market_driver_bias")

        # ── 6. Momentum probability ──────────────────────────────────────────
        mom = _sf(inst.get("momentum_probability"))
        direction = _u(inst.get("direction"))
        if mom >= 60 and "BULL" in direction:
            _apply("momentum", "LONG", f"Momentum probability {mom:.0f}% (up)", "momentum_probability+direction")
        elif mom >= 60 and "BEAR" in direction:
            _apply("momentum", "SHORT", f"Momentum probability {mom:.0f}% (down)", "momentum_probability+direction")
        else:
            _apply("momentum", "NEUTRAL", f"Momentum probability {mom:.0f}% — not decisive", "momentum_probability")

        # ── 7. ICI (institutional conviction index) ──────────────────────────
        ici = _sf(inst.get("ici_score"))
        # ICI is a conviction *gate*, not a direction — it reinforces whichever
        # side already leads, and only when it clears a meaningful floor.
        if ici >= 65:
            if long_pts > short_pts:
                _apply("ici", "LONG", f"ICI {ici:.0f} clears conviction floor", "ici_score")
            elif short_pts > long_pts:
                _apply("ici", "SHORT", f"ICI {ici:.0f} clears conviction floor", "ici_score")
            else:
                _apply("ici", "NEUTRAL", f"ICI {ici:.0f} strong but no directional lead", "ici_score")
        else:
            _apply("ici", "NEUTRAL", f"ICI {ici:.0f} below conviction floor (65)", "ici_score")

        # ── 8. Pine execution confirmation ───────────────────────────────────
        pine = inst.get("pine_confirmed")
        if pine is True or _u(pine) in ("CALL", "TRUE", "LONG"):
            _apply("pine", "LONG", "Pine execution confirmed long", "pine_confirmed")
        elif _u(pine) in ("PUT", "SHORT"):
            _apply("pine", "SHORT", "Pine execution confirmed short", "pine_confirmed")
        else:
            _apply("pine", "NEUTRAL", "No fresh Pine confirmation", "pine_confirmed")

        long_score = round(100.0 * long_pts / _MAX, 1)
        short_score = round(100.0 * short_pts / _MAX, 1)

        # Dominant side + conviction band from the leading score and the spread.
        lead = max(long_score, short_score)
        spread = abs(long_score - short_score)
        if lead < 25 or spread < 8:
            dominant, conv_band = "NEITHER", "NONE"
        else:
            dominant = "LONG" if long_score > short_score else "SHORT"
            if lead >= 75 and spread >= 30:
                conv_band = "A+"
            elif lead >= 60:
                conv_band = "STRONG"
            elif lead >= 45:
                conv_band = "MODERATE"
            else:
                conv_band = "WEAK"

            # GATE: an "A+" or "STRONG" grade is NOT allowed while the two decisive
            # confirmations — ICI clearing its floor, and gamma confirming direction —
            # are still missing. A confident grade on an unconfirmed setup is exactly
            # the over-confidence trap this whole system is built to avoid. Missing a
            # key confirmation caps the grade regardless of raw score.
            _dom_missing = long_missing if dominant == "LONG" else short_missing
            _ici_unmet = any("ici" in m.lower() for m in _dom_missing)
            _gamma_unmet = any("gamma_regime" in m.lower() for m in _dom_missing)
            if conv_band in ("A+", "STRONG") and (_ici_unmet or _gamma_unmet):
                conv_band = "MODERATE"
            if conv_band == "MODERATE" and _ici_unmet and _gamma_unmet:
                conv_band = "WEAK"

        # Trim missing lists to the dominant side's gaps (most useful), dedup.
        long_missing = _dedup(long_missing)
        short_missing = _dedup(short_missing)

        summary = _summarize(dominant, conv_band, long_score, short_score,
                             long_missing if dominant == "LONG" else short_missing)

        return {
            "available": True,
            "version": VERSION,
            "long_setup_score": long_score,
            "short_setup_score": short_score,
            "dominant_side": dominant,
            "conviction": conv_band,
            "long_evidence": long_ev,
            "short_evidence": short_ev,
            "long_missing": long_missing,
            "short_missing": short_missing,
            "factor_table": table,
            "summary": summary,
        }
    except Exception as e:  # never 500 the dashboard
        return _empty(f"Confluence synthesis error (recovered): {e}")


def _dedup(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for it in items:
        if it not in seen:
            seen.add(it)
            out.append(it)
    return out


def _summarize(dominant: str, conv: str, ls: float, ss: float,
               missing: List[str]) -> str:
    if dominant == "NEITHER":
        return (f"No confluent setup — long {ls:.0f} / short {ss:.0f}. "
                f"Factors are split or weak; stand aside until one side builds.")
    side_word = "long" if dominant == "LONG" else "short"
    base = f"{conv} {side_word} setup ({ls:.0f} long / {ss:.0f} short)."
    if missing:
        base += f" Missing: {'; '.join(missing[:3])}."
    return base


def _empty(note: str) -> Dict[str, Any]:
    return {
        "available": False,
        "version": VERSION,
        "note": note,
        "long_setup_score": 0.0,
        "short_setup_score": 0.0,
        "dominant_side": "NEITHER",
        "conviction": "NONE",
        "long_evidence": [], "short_evidence": [],
        "long_missing": [], "short_missing": [],
        "factor_table": [],
        "summary": note,
    }
