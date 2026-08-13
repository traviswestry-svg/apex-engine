"""engine/confirmation_scanner.py — APEX 11.0C Module 8.

Monitors confirmation assets — ES, SPY, VIX, VVIX, breadth (ADD/TICK), sector
rotation, yields, the dollar — and reports whether they CONFIRM or DIVERGE from
the SPX decision already made.

THE ONE HARD RULE
-----------------
This scanner may only STRENGTHEN or WEAKEN confidence in an existing SPX view. It
must never originate a direction, and never replace SPX. VIX does not decide the
trade; it can only agree or disagree with a trade SPX already justified. The output
is a bounded multiplier in [0.75, 1.15] and a list of confirmations/divergences —
never a standalone signal.

This is enforced structurally: the scanner takes the SPX direction as an INPUT and
scores each asset's agreement with THAT direction. With no SPX direction supplied
there is nothing to confirm, and the scanner returns a neutral 1.0 with every asset
marked "no SPX view to confirm" — it cannot manufacture a lean of its own.

LIVE-STATE ONLY
---------------
Every reading is current. No historical base rates, no "VIX usually does X." Just:
does this asset, right now, agree with the SPX decision right now.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

CONFIRMATION_SCANNER_VERSION = "11.0.0_CONFIRMATION_SCANNER"

# The multiplier is deliberately asymmetric and bounded. Confirmation can only nudge
# confidence up a little (1.15 ceiling); divergence can pull it down more (0.75
# floor). Agreement is the base case and shouldn't inflate much; disagreement is
# information and should be heard. It can never zero a trade or double it.
_MULT_FLOOR = 0.75
_MULT_CEIL = 1.15


def _f(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        out = float(v)
        return out if math.isfinite(out) else None
    except (TypeError, ValueError):
        return None


def _dir(text: Any) -> int:
    t = str(text or "").upper()
    if "BULL" in t or t in ("LONG", "UP", "POSITIVE", "1"):
        return 1
    if "BEAR" in t or t in ("SHORT", "DOWN", "NEGATIVE", "-1"):
        return -1
    return 0


def _asset_signals(assets: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Read each confirmation asset's CURRENT directional implication for SPX.

    Each returns a signed direction (+1 bullish for SPX, -1 bearish, 0 neutral) and
    a weight. Note the inversions: VIX and VVIX UP is bearish for SPX; yields and
    dollar are contextual. Nothing here reads history.
    """
    out: List[Dict[str, Any]] = []

    def sig(name: str, direction: int, weight: float, detail: str):
        if direction != 0:
            out.append({"asset": name, "implies": direction, "weight": weight,
                        "detail": detail})

    # ES / SPY: the most direct confirmations — same underlying, should agree.
    es = _f(assets.get("es_change_pct"))
    if es is not None:
        sig("ES", 1 if es > 0 else -1, 1.4,
            f"ES {'up' if es>0 else 'down'} {abs(es):.2f}% — direct index confirmation.")
    spy = _f(assets.get("spy_change_pct"))
    if spy is not None:
        sig("SPY", 1 if spy > 0 else -1, 1.2,
            f"SPY {'up' if spy>0 else 'down'} {abs(spy):.2f}%.")

    # VIX / VVIX: INVERTED. Falling vol confirms upside; rising vol confirms downside.
    vix = _f(assets.get("vix_change_pct"))
    if vix is not None and abs(vix) > 0.5:
        sig("VIX", -1 if vix > 0 else 1, 1.0,
            f"VIX {'up' if vix>0 else 'down'} {abs(vix):.1f}% — {'risk-off' if vix>0 else 'risk-on'} (inverse to SPX).")
    vvix = _f(assets.get("vvix_change_pct"))
    if vvix is not None and abs(vvix) > 1.0:
        sig("VVIX", -1 if vvix > 0 else 1, 0.6,
            f"VVIX {'up' if vvix>0 else 'down'} {abs(vvix):.1f}% — vol-of-vol (inverse to SPX).")

    # Breadth: ADD (advance-decline) and TICK. Positive = broad participation up.
    add = _f(assets.get("add"))
    if add is not None and abs(add) > 200:
        sig("ADD", 1 if add > 0 else -1, 1.1,
            f"Advance/Decline {add:+.0f} — breadth {'supports' if add>0 else 'opposes'} upside.")
    tick = _f(assets.get("tick"))
    if tick is not None and abs(tick) > 400:
        sig("TICK", 1 if tick > 0 else -1, 0.7,
            f"TICK {tick:+.0f} — intraday breadth {'positive' if tick>0 else 'negative'}.")

    # Sector rotation: risk-on/risk-off as a directional tell.
    rot = str(assets.get("rotation") or "").upper()
    if "RISK_ON" in rot or "OFFENSIVE" in rot:
        sig("Rotation", 1, 0.8, "Sector rotation risk-on (offensive leadership).")
    elif "RISK_OFF" in rot or "DEFENSIVE" in rot:
        sig("Rotation", -1, 0.8, "Sector rotation risk-off (defensive leadership).")

    # Treasury yields & dollar: contextual, lighter weight. Rising yields and a
    # rising dollar are typically headwinds for equities intraday.
    yld = _f(assets.get("yield_change_bps"))
    if yld is not None and abs(yld) > 3:
        sig("Yields", -1 if yld > 0 else 1, 0.5,
            f"10Y yield {yld:+.0f}bps — {'headwind' if yld>0 else 'tailwind'} for equities.")
    dxy = _f(assets.get("dollar_change_pct"))
    if dxy is not None and abs(dxy) > 0.2:
        sig("Dollar", -1 if dxy > 0 else 1, 0.4,
            f"Dollar {'up' if dxy>0 else 'down'} {abs(dxy):.2f}% — {'headwind' if dxy>0 else 'tailwind'}.")

    return out


def scan_confirmation(
    *,
    spx_direction: Any,
    assets: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Score confirmation-asset agreement with an EXISTING SPX direction.

    `spx_direction`: the direction SPX has already justified (bullish/bearish or
    +1/-1). This is an INPUT — the scanner confirms or disputes it, it does not
    form it. Returns a bounded confidence multiplier plus the confirming and
    diverging assets. Never raises.
    """
    out: Dict[str, Any] = {
        "available": False,
        "version": CONFIRMATION_SCANNER_VERSION,
        "confidence_multiplier": 1.0,
        "confirmations": [],
        "divergences": [],
        "role": "modifier_only",
        "role_note": ("This scanner only strengthens or weakens confidence in an "
                      "SPX decision. It never originates a direction and never "
                      "replaces SPX. With no SPX view supplied it returns a neutral "
                      "1.0 — it cannot manufacture a lean of its own."),
    }
    try:
        spx = _dir(spx_direction)
        signals = _asset_signals(assets or {})
        out["assets_read"] = len(signals)

        if spx == 0:
            # Nothing to confirm. The scanner explicitly refuses to lead.
            out["available"] = True
            out["note"] = ("No SPX direction supplied, so there is nothing to confirm. "
                           "The scanner does not form a view of its own.")
            out["assets"] = [{**s, "agrees": None} for s in signals]
            return out

        confirms: List[Dict[str, Any]] = []
        diverges: List[Dict[str, Any]] = []
        agree_weight = 0.0
        disagree_weight = 0.0
        for s in signals:
            agrees = (s["implies"] == spx)
            entry = {"asset": s["asset"], "detail": s["detail"], "weight": s["weight"],
                     "agrees": agrees}
            if agrees:
                confirms.append(entry)
                agree_weight += s["weight"]
            else:
                diverges.append(entry)
                disagree_weight += s["weight"]

        # Net agreement in [-1, 1], scaled to the bounded multiplier. Confirmation
        # lifts toward the (low) ceiling; divergence pulls toward the (deeper) floor.
        total = agree_weight + disagree_weight
        net = ((agree_weight - disagree_weight) / total) if total > 0 else 0.0
        if net >= 0:
            mult = 1.0 + net * (_MULT_CEIL - 1.0)
        else:
            mult = 1.0 + net * (1.0 - _MULT_FLOOR)
        mult = round(max(_MULT_FLOOR, min(_MULT_CEIL, mult)), 3)

        strongest_div = max(diverges, key=lambda d: d["weight"], default=None)
        out.update({
            "available": True,
            "spx_direction": "BULLISH" if spx > 0 else "BEARISH",
            "confidence_multiplier": mult,
            "net_agreement": round(net, 3),
            "confirmations": confirms,
            "divergences": diverges,
            "confirm_count": len(confirms),
            "divergence_count": len(diverges),
            "verdict": _verdict(net, len(signals)),
            "headline_divergence": (strongest_div["detail"] if strongest_div else None),
            "note": _note(net, confirms, diverges, signals),
        })
        return out
    except Exception as e:  # pragma: no cover
        out["available"] = True
        out["note"] = f"confirmation scan recovered: {e}"
        return out


def _verdict(net: float, n: int) -> str:
    if n == 0:
        return "NO_CONFIRMATION_DATA"
    if net >= 0.5:
        return "STRONGLY_CONFIRMED"
    if net >= 0.15:
        return "CONFIRMED"
    if net <= -0.5:
        return "STRONGLY_DIVERGENT"
    if net <= -0.15:
        return "DIVERGENT"
    return "MIXED"


def _note(net: float, confirms, diverges, signals) -> str:
    if not signals:
        return "No confirmation assets were readable — confidence is unchanged."
    if net >= 0.15:
        return (f"{len(confirms)} of {len(signals)} confirmation assets agree with the "
                f"SPX view — confidence strengthened.")
    if net <= -0.15:
        return (f"{len(diverges)} of {len(signals)} confirmation assets diverge from the "
                f"SPX view — confidence reduced. Divergence is information, not noise.")
    return ("Confirmation assets are mixed — they neither strengthen nor materially "
            "weaken the SPX view.")
