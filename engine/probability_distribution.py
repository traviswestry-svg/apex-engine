"""engine/probability_distribution.py — APEX 11.0C Module 3.

Replaces a single directional bias with a probability distribution over session
outcomes. Instead of "BULLISH, confidence 71", it answers:

    Large Rally        12%
    Moderate Rally     34%
    Balanced Auction   38%
    Moderate Selloff   11%
    Trend Selloff       5%

WHAT THIS IS — AND ISN'T
------------------------
These are STRUCTURAL probabilities, derived entirely from the CURRENT market state
on the bus: gamma regime, auction state, trend, flow bias, dealer positioning,
volatility regime. They are an honest reading of "given what the tape looks like
right now, how is the session likely to resolve."

They are NOT historical frequencies. This engine makes no claim of the form "in 200
past sessions like this, 34% rallied" — that is Phase 11.1, and it needs production
history this engine does not have. The distinction is surfaced in the payload
(`basis: "structural_current_state"`) so the number is never mistaken for a
backtested edge.

The probabilities are a transform of live evidence, not a frequency count. They
sum to 1.0 by construction (softmax over scenario scores), update every time the
bus updates, and widen toward uniform when evidence is weak — an honest "we don't
know" rather than a confident flat line.
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

PROBABILITY_DISTRIBUTION_VERSION = "11.0.0_PROBABILITY_DISTRIBUTION"

# The five session outcomes, ordered bearish -> bullish so the distribution reads
# like a spectrum. Balanced sits in the middle: the 0DTE base case.
SCENARIOS: Tuple[str, ...] = (
    "TREND_SELLOFF",
    "MODERATE_SELLOFF",
    "BALANCED_AUCTION",
    "MODERATE_RALLY",
    "LARGE_RALLY",
)

_LABELS = {
    "TREND_SELLOFF": "Trend Selloff",
    "MODERATE_SELLOFF": "Moderate Selloff",
    "BALANCED_AUCTION": "Balanced Auction",
    "MODERATE_RALLY": "Moderate Rally",
    "LARGE_RALLY": "Large Rally",
}

# Directional index of each scenario, -2..+2, used to translate a directional
# signal into scenario scores.
_DIR = {"TREND_SELLOFF": -2, "MODERATE_SELLOFF": -1, "BALANCED_AUCTION": 0,
        "MODERATE_RALLY": 1, "LARGE_RALLY": 2}


def _f(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        out = float(v)
        return out if math.isfinite(out) else None
    except (TypeError, ValueError):
        return None


def _u(v: Any) -> str:
    return str(v or "").upper()


def _bias_to_direction(text: str) -> int:
    t = _u(text)
    if "BULL" in t or t in ("LONG", "UP", "POSITIVE"):
        return 1
    if "BEAR" in t or t in ("SHORT", "DOWN", "NEGATIVE"):
        return -1
    return 0


def _pull(bus: Dict[str, Any]) -> Dict[str, Any]:
    """Extract the live evidence the distribution is built from. Every field is
    current-state; nothing here reads history."""
    gamma = bus.get("gamma_regime") if isinstance(bus.get("gamma_regime"), dict) else {}
    vol = bus.get("volatility") if isinstance(bus.get("volatility"), dict) else {}
    trend = bus.get("trend") if isinstance(bus.get("trend"), dict) else {}
    flow = bus.get("flow") if isinstance(bus.get("flow"), dict) else {}
    auction = bus.get("auction") if isinstance(bus.get("auction"), dict) else {}
    structure = bus.get("structure") if isinstance(bus.get("structure"), dict) else {}

    return {
        "gamma_regime": _u(gamma.get("regime") or bus.get("gamma_regime_label")),
        "dealer_behavior": _u(gamma.get("dealer_behavior")),
        "auction_state": _u(auction.get("state") or structure.get("auction_state")),
        "trend_direction": _bias_to_direction(trend.get("direction") or trend.get("bias")),
        "trend_strength": _f(trend.get("strength")) or _f(trend.get("adx")) or 0.0,
        "compression": bool(trend.get("compression")),
        "flow_direction": _bias_to_direction(flow.get("bias") or flow.get("approved_side")),
        "flow_conviction": _f(flow.get("conviction")) or 0.0,
        "vol_regime": _u(vol.get("regime")),
        "vix": _f(vol.get("vix")) or 0.0,
        "leading_conviction": _f(bus.get("leading_conviction")) or 0.0,
    }


def _scenario_scores(ev: Dict[str, Any]) -> Tuple[Dict[str, float], List[Dict[str, Any]]]:
    """Score each scenario from live evidence. Returns raw scores + the evidence
    trail, so the distribution can explain itself rather than being a black box."""
    scores = {s: 0.0 for s in SCENARIOS}
    trail: List[Dict[str, Any]] = []

    def add(scenario_pred, weight: float, source: str, detail: str):
        for s in SCENARIOS:
            scores[s] += weight * scenario_pred(s)
        trail.append({"source": source, "weight": round(weight, 2), "detail": detail})

    # Positive (long) gamma pins price -> mass toward BALANCED. Negative gamma
    # amplifies moves -> mass toward the tails.
    if "POSITIVE" in ev["gamma_regime"] or "LONG" in ev["gamma_regime"]:
        add(lambda s: 1.0 if s == "BALANCED_AUCTION" else -0.25 * abs(_DIR[s]),
            1.4, "gamma_regime", "Positive dealer gamma pins price toward balance.")
    elif "NEGATIVE" in ev["gamma_regime"] or "SHORT" in ev["gamma_regime"]:
        add(lambda s: 0.6 * abs(_DIR[s]) - 0.4 * (1 if s == "BALANCED_AUCTION" else 0),
            1.4, "gamma_regime", "Negative dealer gamma amplifies directional moves toward the tails.")

    # Auction state.
    if "BALANCED" in ev["auction_state"] or "ROTATION" in ev["auction_state"]:
        add(lambda s: 1.0 if s == "BALANCED_AUCTION" else -0.2 * abs(_DIR[s]),
            1.2, "auction_state", "Balanced/rotational auction favours mean reversion.")
    elif "TREND" in ev["auction_state"]:
        adir = 1 if "UP" in ev["auction_state"] else -1 if "DOWN" in ev["auction_state"] else 0
        if adir:
            add(lambda s: max(0.0, _DIR[s] * adir),
                1.2, "auction_state", f"Trend auction ({'up' if adir>0 else 'down'}) favours continuation.")

    # Trend direction, scaled by strength.
    if ev["trend_direction"] and ev["trend_strength"] >= 0:
        w = 0.8 + min(1.0, ev["trend_strength"] / 40.0)
        d = ev["trend_direction"]
        add(lambda s: max(0.0, _DIR[s] * d), w, "trend",
            f"Trend points {'up' if d>0 else 'down'} (strength {ev['trend_strength']:.0f}).")

    # Flow bias, scaled by conviction.
    if ev["flow_direction"] and ev["flow_conviction"] > 0:
        w = 0.5 + min(1.0, ev["flow_conviction"] / 100.0)
        d = ev["flow_direction"]
        add(lambda s: max(0.0, _DIR[s] * d), w, "flow",
            f"Order flow leans {'bullish' if d>0 else 'bearish'} (conviction {ev['flow_conviction']:.0f}).")

    # Volatility regime shapes the TAILS. Compression thins them toward balance.
    # Expansion fattens the tail IN THE DIRECTION the rest of the evidence leans —
    # high vol makes a *bigger* move more likely, not a reversal. Fattening both
    # tails symmetrically would rate "trend selloff" as a top outcome inside a
    # clean bull, which is wrong.
    net_dir = ev["trend_direction"] + ev["flow_direction"]
    if "COMPRESSION" in ev["vol_regime"] or ev["compression"]:
        add(lambda s: 0.5 if s == "BALANCED_AUCTION" else (-0.3 if abs(_DIR[s]) == 2 else 0.0),
            0.8, "volatility", "Volatility compression favours a contained, balanced session.")
    elif "EXPANSION" in ev["vol_regime"] or ev["vix"] >= 22:
        if net_dir > 0:
            add(lambda s: 0.6 if s == "LARGE_RALLY" else 0.0,
                0.8, "volatility", "Elevated volatility fattens the upside tail (evidence leans up).")
        elif net_dir < 0:
            add(lambda s: 0.6 if s == "TREND_SELLOFF" else 0.0,
                0.8, "volatility", "Elevated volatility fattens the downside tail (evidence leans down).")
        else:
            add(lambda s: 0.4 if abs(_DIR[s]) == 2 else 0.0,
                0.8, "volatility", "Elevated volatility fattens both tails (no directional lean).")

    return scores, trail


def _softmax(scores: Dict[str, float], temperature: float) -> Dict[str, float]:
    """Convert scenario scores to a probability distribution.

    Two safeguards keep the result honest as a session forecast:
    1. Each score is tanh-squashed first, so no single scenario can run away to a
       near-certainty however many signals align. A 0DTE session is never 100% one
       outcome; a strong tilt should read ~55-65%, not 95%.
    2. Temperature widens the distribution when evidence is weak, so little signal
       returns near-uniform — an honest "unsure" rather than a fake-confident spike.
    """
    t = max(1.2, temperature)
    squashed = {s: 2.5 * math.tanh(v / 2.5) for s, v in scores.items()}
    mx = max(squashed.values())
    exps = {s: math.exp((v - mx) / t) for s, v in squashed.items()}
    total = sum(exps.values()) or 1.0
    return {s: exps[s] / total for s in SCENARIOS}


def build_probability_distribution(bus: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Build the live scenario distribution from the current bus. Never raises."""
    out: Dict[str, Any] = {
        "available": False,
        "version": PROBABILITY_DISTRIBUTION_VERSION,
        "basis": "structural_current_state",
        "basis_note": ("Probabilities are a structural reading of the current market "
                       "state, not historical frequencies. They answer 'given how the "
                       "tape looks now, how is the session likely to resolve' — not "
                       "'how often did sessions like this resolve that way'. Historical "
                       "frequencies are Phase 11.1 and require production history."),
        "scenarios": [],
    }
    try:
        if not isinstance(bus, dict) or not bus:
            out["note"] = "No composed bus available."
            return out

        ev = _pull(bus)
        scores, trail = _scenario_scores(ev)

        # Evidence strength drives the temperature: the total absolute score is a
        # proxy for how much the live state actually says. Weak evidence -> wide,
        # near-uniform. But even maximal evidence must stay a DISTRIBUTION, not a
        # point estimate — a 0DTE session is never 100% one outcome — so the band
        # is 2.6 (very unsure) down to 1.5 (strong tilt), never sharp enough to
        # collapse to a near-certainty.
        strength = sum(abs(v) for v in scores.values())
        temperature = 2.6 - min(1.1, strength / 6.0)
        probs = _softmax(scores, temperature)

        ranked = sorted(SCENARIOS, key=lambda s: probs[s], reverse=True)
        scenarios = [{
            "scenario": s,
            "label": _LABELS[s],
            "probability_pct": round(probs[s] * 100, 1),
            "direction_index": _DIR[s],
        } for s in ranked]

        # Concentration: how far from uniform (0.2 each), normalized to [0,1].
        # Max deviation is a single certain scenario: (0.8)^2 + 4*(0.2)^2 = 0.80.
        _MAX_DEV = 0.8 ** 2 + 4 * (0.2 ** 2)
        concentration = round(sum((probs[s] - 0.2) ** 2 for s in SCENARIOS) / _MAX_DEV, 3)
        # "Informative" means the grouped directional lean is decisive, OR one
        # scenario clearly leads. Post-squash, a strong aligned tilt shows as a
        # dominant bullish/bearish GROUP (~65%) even when its two sibling scenarios
        # split the primary slot — so the grouped lean, not the single top cell, is
        # the honest test of whether the distribution says anything.
        lean_info = _directional_lean(probs)
        grouped_max = max(lean_info["bullish_pct"], lean_info["bearish_pct"],
                          lean_info["balanced_pct"])
        primary = scenarios[0]
        confident = grouped_max >= 55.0 or primary["probability_pct"] >= 45.0

        out.update({
            "available": True,
            "scenarios": scenarios,
            "primary_scenario": primary["scenario"],
            "primary_label": primary["label"],
            "primary_probability_pct": primary["probability_pct"],
            "directional_lean": lean_info,
            "concentration": concentration,
            "distribution_is_informative": confident,
            "evidence": trail,
            "evidence_strength": round(strength, 2),
            "note": ("Distribution is near-uniform — current evidence is ambiguous, so no "
                     "scenario is meaningfully favoured."
                     if not confident else
                     f"{primary['label']} is the current structural favourite at "
                     f"{primary['probability_pct']:.0f}%."),
        })
        return out
    except Exception as e:  # pragma: no cover
        out["note"] = f"probability distribution recovered: {e}"
        return out


def _directional_lean(probs: Dict[str, float]) -> Dict[str, Any]:
    """Collapse the distribution to a single signed lean in [-1, 1] — a bridge for
    consumers that still want one number, without hiding the full distribution."""
    lean = sum(probs[s] * _DIR[s] for s in SCENARIOS) / 2.0  # /2 normalizes to [-1,1]
    bullish = probs["MODERATE_RALLY"] + probs["LARGE_RALLY"]
    bearish = probs["MODERATE_SELLOFF"] + probs["TREND_SELLOFF"]
    balanced = probs["BALANCED_AUCTION"]
    return {
        "lean": round(lean, 3),
        "bullish_pct": round(bullish * 100, 1),
        "bearish_pct": round(bearish * 100, 1),
        "balanced_pct": round(balanced * 100, 1),
        "label": ("BULLISH" if lean > 0.15 else "BEARISH" if lean < -0.15 else "BALANCED"),
    }
