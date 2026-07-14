"""
engine/premium_strategy.py — APEX 7.6.0 Institutional Premium Strategy Engine.

WHAT THIS IS
------------
A READ-ONLY assembler that answers a question the existing stack does not:

    "Given everything APEX already knows, HOW should this market be traded —
     buy premium, sell premium, or stand aside — and with WHICH options
     structure?"

Current APEX resolves DIRECTION (CALL / PUT / stand-aside) via
`decision_intelligence` + `confluence`. This engine layers STRUCTURE SELECTION
on top: it maps the already-composed regime (trend, volatility, dealer
positioning, auction, flow, range) onto the highest-expectancy options
structure and recommends one of:

    DEBIT_CALL_SPREAD · DEBIT_PUT_SPREAD ·
    BULL_PUT_CREDIT_SPREAD · BEAR_CALL_CREDIT_SPREAD ·
    IRON_CONDOR · NO_TRADE

…complete with modeled strikes, probability, risk, an exit plan, and a
plain-English story of WHY.

HARD RULES (mirrors the 7.5 confluence/decision engines)
--------------------------------------------------------
- Consumes the composed Data Bus (`last_result`) plus the already-built
  `confluence` and `events` outputs. It NEVER re-fetches or recomputes gamma,
  flow, auction, VIX, expected move, or trend — it reads what those engines
  published. (ARCHITECTURE.md §1: "consume the bus".)
- Never raises into the caller — returns an {"available": False, ...} envelope
  on any problem so it can never 500 the dashboard.
- Every recommendation is traceable to named source fields → the `reason`
  list and `factor_notes` are the audit trail.

PRICING HONESTY
---------------
The canonical bus carries EXPECTED MOVE and the GAMMA WALLS, not a live
per-strike option quote. So strikes are placed off expected move + dealer
walls, and credit / POP are MODELED with a transparent normal-distribution
approximation (expected_move ≈ 1σ). Every pricing field is stamped
`pricing_basis: "modeled_from_expected_move"`. Live-chain pricing (via the
existing options chain) supersedes these at execution time; the model exists
so the recommendation is complete and testable, not a fabricated fill.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

VERSION = "7.6.0_PREMIUM_STRATEGY"

# ── Strategy constants ───────────────────────────────────────────────────────
DEBIT_CALL = "DEBIT_CALL_SPREAD"
DEBIT_PUT = "DEBIT_PUT_SPREAD"
BULL_PUT = "BULL_PUT_CREDIT_SPREAD"
BEAR_CALL = "BEAR_CALL_CREDIT_SPREAD"
IRON_CONDOR = "IRON_CONDOR"
NO_TRADE = "NO_TRADE"

_STRATEGY_LABEL = {
    DEBIT_CALL: "Debit Call Spread",
    DEBIT_PUT: "Debit Put Spread",
    BULL_PUT: "Bull Put Credit Spread",
    BEAR_CALL: "Bear Call Credit Spread",
    IRON_CONDOR: "Iron Condor",
    NO_TRADE: "No Trade",
}
_PREMIUM_KIND = {
    DEBIT_CALL: "DEBIT", DEBIT_PUT: "DEBIT",
    BULL_PUT: "CREDIT", BEAR_CALL: "CREDIT", IRON_CONDOR: "CREDIT",
    NO_TRADE: "NONE",
}

# Default SPX vertical width (points) and the strike grid.
_DEFAULT_WIDTH = 10.0
_STRIKE_STEP = 5.0

# VIX regime cut-points (from the master prompt's VIX strategy filter).
_VIX_LOW = 16.0
_VIX_HIGH = 20.0

# Credit-quality floors. Calibrated to realistic ~16-delta SPX credit-spread
# economics: a 10-wide at ~1σ short typically collects ~1.2-1.8 (RR ~0.15-0.22).
# The master-prompt's own worked example (credit 1.55 / max-risk 845 → RR 0.18)
# sits inside these floors by design.
_MIN_POP = 0.65          # reject CREDIT structures whose modeled POP is below this
_MIN_CREDIT_RATIO = 0.12  # credit must be >= 12% of width
_MIN_RR = 0.15           # reward/risk floor for credit structures


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


def _phi(x: float) -> float:
    """Standard normal CDF via erf (dependency-free)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _round_strike(x: float, step: float = _STRIKE_STEP) -> float:
    if step <= 0:
        return round(x, 2)
    return round(x / step) * step


def _first_num(*vals) -> float:
    for v in vals:
        f = _sf(v)
        if f:
            return f
    return 0.0


# ── bus extraction ───────────────────────────────────────────────────────────
def _pull(last_result: Dict[str, Any]) -> Dict[str, Any]:
    """Read the canonical sub-blocks off the composed bus. Recompute nothing."""
    lr = last_result if isinstance(last_result, dict) else {}
    inst = lr.get("institutional_intelligence") or {}
    ms = lr.get("market_state") or {}
    vol = lr.get("volatility") or {}
    rng = ((lr.get("range_intelligence") or {}).get("range_intelligence")
           if isinstance(lr.get("range_intelligence"), dict) else {}) or {}

    price = _first_num(ms.get("price"), rng.get("mid"))
    vix = _first_num(vol.get("vix"), ms.get("vix"))
    em = _first_num(rng.get("expected_move"), vol.get("expected_next"))
    # Fallback expected move from VIX if the range engine hasn't published one.
    if em <= 0 and price > 0 and vix > 0:
        em = price * (vix / 100.0) / math.sqrt(252.0)

    return {
        "price": price,
        "vix": vix,
        "expected_move": em,
        "iv_rank": _sf(vol.get("iv_rank_estimate")),
        "vwap": _sf(ms.get("vwap")),
        "poc": _sf(ms.get("poc")),
        "vah": _sf(ms.get("vah")),
        "val": _sf(ms.get("val")),
        "call_wall": _sf(ms.get("call_wall")),
        "put_wall": _sf(ms.get("put_wall")),
        "zero_gamma": _sf(ms.get("zero_gamma")),
        "nearest_support": _sf(ms.get("nearest_support")),
        "nearest_resistance": _sf(ms.get("nearest_resistance")),
        "minutes_open": _sf(ms.get("minutes_open")),
        "session_state": _u(ms.get("session_state")),
        "price_vs_poc": _u(ms.get("price_vs_poc")),
        # institutional read
        "institutional_bias": _u(inst.get("institutional_bias")),
        "gamma_regime": _u(inst.get("gamma_regime") or ms.get("gamma_regime")),
        "dealer_bias": _u(inst.get("dealer_bias")),
        "delta_bias": _u(inst.get("delta_bias")),
        "flow_bias": _u(inst.get("flow_bias") or ms.get("flow_bias")),
        "flow_conviction": _sf(inst.get("flow_conviction")),
        "flow_contradictions": list(inst.get("flow_contradictions") or []),
        "auction_state": _u(inst.get("auction_state") or ms.get("auction_state")),
        "acceptance": _u(inst.get("acceptance")),
        "momentum_probability": _sf(inst.get("momentum_probability")),
        "direction": _u(inst.get("direction")),
        "ici_score": _sf(inst.get("ici_score")),
        "pin_probability": _first_num(inst.get("pin_probability"), rng.get("pin_probability")),
        "vol_regime": _u(inst.get("vol_regime") or vol.get("regime")),
        "primary_risk": inst.get("primary_risk"),
        "overall_score": _sf(inst.get("overall_score")),
        "nearest_magnet": inst.get("nearest_magnet"),
        # range read
        "range_bias": _u(rng.get("bias")),
        "expansion_probability": _sf(rng.get("expansion_probability")),
        "mean_reversion_probability": _sf(rng.get("mean_reversion_probability")),
        "range_invalidation": list(rng.get("invalidation") or []),
        "session_high": _sf(rng.get("session_high")),
        "session_low": _sf(rng.get("session_low")),
        "opening_context": rng.get("opening_context"),
        "projected_high_zone": rng.get("projected_high_zone"),
        "projected_low_zone": rng.get("projected_low_zone"),
    }


def _vix_regime(vix: float, vol_regime: str) -> str:
    """LOW / MID / HIGH — prefer numeric VIX, fall back to the published label."""
    if vix > 0:
        if vix < _VIX_LOW:
            return "LOW"
        if vix > _VIX_HIGH:
            return "HIGH"
        return "MID"
    if "HIGH" in vol_regime or "ELEVATED" in vol_regime or "EXPANSION" in vol_regime:
        return "HIGH"
    if "LOW" in vol_regime or "COMPRESS" in vol_regime or "CRUSH" in vol_regime:
        return "LOW"
    return "MID"


# ── the decision tree (structure selection) ──────────────────────────────────
_CONV_BASE = {"A+": 90.0, "STRONG": 78.0, "MODERATE": 62.0, "WEAK": 45.0, "NONE": 30.0}


def _select_strategy(
    b: Dict[str, Any],
    conf: Dict[str, Any],
    ev: Dict[str, Any],
    vixreg: str,
) -> Tuple[str, float, List[str], str]:
    """Return (strategy, base_confidence, reasons, case_label).

    Implements the master-prompt decision tree:
      CASE 1  strong direction + momentum + confidence   -> debit spread
      CASE 2  directional but no huge move expected       -> credit spread (dir)
      CASE 3  balanced auction + high vol + pinning        -> iron condor
      CASE 4  contradicting / mixed / weak                 -> no trade
    Then the VIX strategy filter re-expresses direction as debit vs credit.
    """
    dom = _u(conf.get("dominant_side"))
    conv = _u(conf.get("conviction")) or "NONE"
    reasons: List[str] = []

    ici = b["ici_score"]
    mom = b["momentum_probability"]
    gamma = b["gamma_regime"]
    pin = b["pin_probability"]
    auction = b["auction_state"]
    contra = b["flow_contradictions"]
    event_regime = _u(ev.get("event_regime"))
    headline = (ev.get("headline_event") or {}).get("label") if ev.get("headline_event") else None

    # ── Event gate — a high-impact print pre/at open is a trap for structure. ─
    if event_regime == "EVENT_DAY":
        return (NO_TRADE, 40.0,
                [f"High-impact event today{(' (' + headline + ')') if headline else ''} — "
                 "stand aside until the print and post-event expansion resolve."],
                "EVENT_GATE")

    # ── CASE 4 (contradiction) — mixed flow / weak trend beats any structure. ─
    if contra and conv not in ("A+", "STRONG"):
        return (NO_TRADE, 45.0,
                [f"Flow contradiction unresolved: {str(contra[0])[:120]}",
                 "Conflicting signals — no structure has positive expectancy here."],
                "CASE_4_CONTRADICTION")

    # ── CASE 3 (balanced + pinning + high vol) — iron condor territory. ───────
    balanced = (dom == "NEITHER" or conv == "NONE"
                or "BALANC" in auction or "ROTAT" in auction)
    dealer_pinning = ("POSITIVE" in gamma) or (pin >= 60)
    if balanced and dealer_pinning:
        base = 55.0 + 0.25 * pin
        reasons += [
            "Balanced / rotational auction — no directional edge.",
            ("Dealers long gamma — moves get dampened toward magnets."
             if "POSITIVE" in gamma else f"Elevated pin probability ({pin:.0f}%)."),
        ]
        if vixreg in ("MID", "HIGH"):
            reasons.append(f"Volatility {vixreg} — premium is rich enough to sell both wings.")
            return (IRON_CONDOR, min(base, 88.0), reasons, "CASE_3_CONDOR")
        # Low vol + pinning: condor premium is thin; only take it if pin is strong.
        if pin >= 68:
            reasons.append("Low VIX but strong pin — tight condor around the magnet.")
            return (IRON_CONDOR, min(base, 78.0), reasons, "CASE_3_CONDOR_LOWVOL")
        return (NO_TRADE, 50.0,
                reasons + ["Low volatility — condor premium too thin to justify the risk."],
                "CASE_3_NO_PREMIUM")

    # ── No directional lead and not a clean condor → stand aside. ─────────────
    if dom not in ("LONG", "SHORT") or conv == "NONE":
        return (NO_TRADE, 40.0,
                ["No confluent direction and no clean pinning setup — stand aside."],
                "NO_SETUP")

    side_word = "long" if dom == "LONG" else "short"
    base = _CONV_BASE.get(conv, 45.0)
    # ICI and momentum nudge confidence within the band.
    base += min(8.0, max(-8.0, (ici - 65.0) * 0.15))
    base += min(6.0, max(-6.0, (mom - 60.0) * 0.10))
    reasons.append(f"{conv} {side_word} confluence "
                   f"(long {_sf(conf.get('long_setup_score')):.0f} / "
                   f"short {_sf(conf.get('short_setup_score')):.0f}).")

    strong_dir = conv in ("A+", "STRONG")
    elite_trend = (conv == "A+" and mom >= 75.0 and "TREND" in auction)

    # ── CASE 1 vs CASE 2 — governed by the VIX strategy filter. ───────────────
    #   LOW  VIX -> buy premium (debit) when direction is strong.
    #   HIGH VIX -> sell premium (credit) unless the trend is ELITE.
    #   MID  VIX -> let confidence + momentum decide.
    if strong_dir and vixreg == "LOW":
        reasons.append("VIX < 16 — cheap premium favours buying a directional debit spread.")
        return ((DEBIT_CALL if dom == "LONG" else DEBIT_PUT),
                min(base + 3.0, 96.0), reasons, "CASE_1_DEBIT")

    if vixreg == "HIGH" and not elite_trend:
        reasons.append("VIX > 20 — rich premium favours SELLING into the direction "
                       "(defined-risk credit spread) rather than paying up for a debit.")
        return ((BULL_PUT if dom == "LONG" else BEAR_CALL),
                min(base, 92.0), reasons, "CASE_2_CREDIT_HIGHVOL")

    if elite_trend and vixreg == "HIGH":
        reasons.append("Elite trend day overrides the high-VIX credit preference — "
                       "debit spread keeps full upside on a directional expansion.")
        return ((DEBIT_CALL if dom == "LONG" else DEBIT_PUT),
                min(base + 2.0, 96.0), reasons, "CASE_1_DEBIT_ELITE")

    # MID VIX — confidence + momentum decide debit vs credit.
    if strong_dir and mom >= 62.0:
        reasons.append("Strong direction with momentum — debit spread captures the expansion.")
        return ((DEBIT_CALL if dom == "LONG" else DEBIT_PUT),
                min(base, 92.0), reasons, "CASE_1_DEBIT_MID")

    if conv in ("MODERATE", "STRONG"):
        reasons.append("Directional lean but no high-probability big move — "
                       "credit spread monetises theta while staying on the right side.")
        return ((BULL_PUT if dom == "LONG" else BEAR_CALL),
                min(base, 86.0), reasons, "CASE_2_CREDIT")

    # WEAK lead — forming, not tradeable as a structure yet.
    return (NO_TRADE, 45.0,
            reasons + ["Direction is forming but unconfirmed — wait for the trigger."],
            "CASE_4_WEAK")


# ── strike selection + modeled pricing ───────────────────────────────────────
def _delta_from_distance(distance: float, sigma: float) -> float:
    """Approximate OTM option delta as the risk-neutral touch-ish probability."""
    if sigma <= 0:
        return 0.0
    return round(max(0.01, min(0.99, 1.0 - _phi(distance / sigma))), 2)


def _wall_inside(low: float, high: float, walls: List[float]) -> Optional[float]:
    for w in walls:
        if w and low < w < high:
            return w
    return None


def _build_legs(strategy: str, b: Dict[str, Any], width: float) -> Dict[str, Any]:
    """Place strikes off expected move + dealer walls; model credit/POP/risk.

    Everything here is stamped modeled — expected_move is treated as 1σ.
    """
    price = b["price"]
    em = b["expected_move"]
    sigma = em if em > 0 else max(price * 0.004, 1.0)
    iv_rank = b["iv_rank"]
    walls = [b["call_wall"], b["put_wall"], b["zero_gamma"]]
    quality: List[str] = []

    def _credit_estimate(distance: float) -> float:
        # credit ≈ width × P(short finishes ITM) × IV richness factor.
        # Richness centres near 1.0 so an absent/zero IV-rank (common on the bus)
        # doesn't systematically underprice; higher IV-rank enriches the credit.
        p_itm = 1.0 - _phi(distance / sigma)
        rich = 0.95 + 0.40 * min(1.0, max(0.0, iv_rank / 100.0))
        c = width * p_itm * rich
        return round(max(0.05, min(width * 0.60, c)), 2)

    legs: Dict[str, Any] = {"pricing_basis": "modeled_from_expected_move",
                            "expected_move": round(sigma, 2), "width": width}

    # Short-strike distance bounds (in σ): far enough for POP, near enough for
    # premium. ~1σ ≈ 16-delta, the credit-spread target. Barrier walls may tuck
    # the strike WITHIN this band, never outside it (that would kill the credit).
    _NEAR, _FAR = 0.80, 1.20

    def _put_short() -> float:
        base = price - sigma
        wall = b["put_wall"]
        # A put wall NEARER than 1σ is a barrier to sit just beyond.
        if wall and (price - sigma) < wall < price:
            base = min(base, wall - _STRIKE_STEP)
        base = min(base, price - _NEAR * sigma)   # at least 0.8σ OTM
        base = max(base, price - _FAR * sigma)    # at most 1.2σ OTM
        return _round_strike(base)

    def _call_short() -> float:
        base = price + sigma
        wall = b["call_wall"]
        if wall and price < wall < (price + sigma):
            base = max(base, wall + _STRIKE_STEP)
        base = max(base, price + _NEAR * sigma)
        base = min(base, price + _FAR * sigma)
        return _round_strike(base)

    if strategy in (BULL_PUT, BEAR_CALL):
        if strategy == BULL_PUT:
            short = _put_short()
            long = short - width
            dist = price - short
        else:  # BEAR_CALL
            short = _call_short()
            long = short + width
            dist = short - price

        pop = round(_phi(max(0.0, dist) / sigma), 3)
        credit = _credit_estimate(max(0.0, dist))
        max_profit = round(credit * 100.0, 0)
        max_loss = round((width - credit) * 100.0, 0)
        target_exit = round(credit * 0.25, 2)  # capture ~75% of the credit
        rr = round((max_profit / max_loss), 2) if max_loss > 0 else 0.0

        w_in = _wall_inside(min(short, long), max(short, long), walls)
        if w_in:
            quality.append(f"Gamma wall {w_in:.0f} sits inside the spread.")

        legs.update({
            "sell_leg": short, "buy_leg": long,
            "short_delta": _delta_from_distance(max(0.0, dist), sigma),
            "entry_credit": credit, "pop": pop,
            "max_profit": max_profit, "max_loss": max_loss,
            "target_exit": target_exit, "risk_reward": rr,
            "short_distance_pts": round(dist, 1),
            "short_vs_expected_move": round(dist / sigma, 2) if sigma else None,
        })

    elif strategy in (DEBIT_CALL, DEBIT_PUT):
        # Long ~ATM/slightly ITM (0.55-0.65 delta), short ~0.25-0.40 delta OTM.
        if strategy == DEBIT_CALL:
            long = _round_strike(price - 0.10 * sigma)
            short = long + width
            fav = price - long  # + when long is ITM
        else:  # DEBIT_PUT
            long = _round_strike(price + 0.10 * sigma)
            short = long - width
            fav = long - price

        # Modeled debit ≈ width × prob spread finishes past the long strike.
        p_itm = _phi(fav / sigma) if sigma else 0.5
        debit = round(max(width * 0.25, min(width * 0.70, width * p_itm)), 2)
        max_profit = round((width - debit) * 100.0, 0)
        max_loss = round(debit * 100.0, 0)
        # POP for a debit vertical ≈ prob of closing beyond breakeven.
        breakeven = (long + debit) if strategy == DEBIT_CALL else (long - debit)
        pop = round(_phi(((price - breakeven) if strategy == DEBIT_CALL
                          else (breakeven - price)) / sigma), 3) if sigma else 0.5
        target_exit = round(debit + (width - debit) * 0.75, 2)  # bank ~75% of max
        rr = round((max_profit / max_loss), 2) if max_loss > 0 else 0.0

        legs.update({
            "buy_leg": long, "sell_leg": short,
            "long_delta": round(_phi(fav / sigma), 2) if sigma else 0.5,
            "short_delta": _delta_from_distance(abs(short - price), sigma),
            "entry_debit": debit, "pop": pop,
            "max_profit": max_profit, "max_loss": max_loss,
            "target_exit": target_exit, "risk_reward": rr,
            "breakeven": round(breakeven, 1),
        })

    elif strategy == IRON_CONDOR:
        put_short = _put_short()
        call_short = _call_short()
        put_long = put_short - width
        call_long = call_short + width

        d_put = price - put_short
        d_call = call_short - price
        credit = round(_credit_estimate(max(0.0, d_put)) + _credit_estimate(max(0.0, d_call)), 2)
        credit = round(min(credit, width * 0.9), 2)
        pop = round(max(0.0, _phi(max(0.0, d_put) / sigma) + _phi(max(0.0, d_call) / sigma) - 1.0), 3)
        max_profit = round(credit * 100.0, 0)
        max_loss = round((width - credit) * 100.0, 0)
        target_exit = round(credit * 0.30, 2)
        rr = round((max_profit / max_loss), 2) if max_loss > 0 else 0.0

        legs.update({
            "put_short": put_short, "put_long": put_long,
            "call_short": call_short, "call_long": call_long,
            "entry_credit": credit, "pop": pop,
            "max_profit": max_profit, "max_loss": max_loss,
            "target_exit": target_exit, "risk_reward": rr,
            "short_distance_pts": round(min(d_put, d_call), 1),
        })

    legs["quality_flags"] = quality
    return legs


def _credit_quality_check(strategy: str, legs: Dict[str, Any], b: Dict[str, Any],
                          ev: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Reject structures that fail the master-prompt credit-quality filter."""
    fails: List[str] = []
    kind = _PREMIUM_KIND.get(strategy)
    pop = _sf(legs.get("pop"))
    rr = _sf(legs.get("risk_reward"))
    width = _sf(legs.get("width"), _DEFAULT_WIDTH)

    if kind == "CREDIT":
        # POP floor applies to premium-SELLING structures (high-probability theta
        # plays). Debit spreads are directional bets — POP is naturally ~40-55%
        # with a favourable payoff skew, so the floor would wrongly reject them.
        if pop and pop < _MIN_POP:
            fails.append(f"Modeled POP {pop*100:.0f}% below the {_MIN_POP*100:.0f}% floor.")
        credit = _sf(legs.get("entry_credit"))
        if width > 0 and credit < _MIN_CREDIT_RATIO * width:
            fails.append(f"Credit {credit:.2f} is thin vs the {width:.0f}-pt width.")
        if rr and rr < _MIN_RR:
            fails.append(f"Reward/risk {rr:.2f} below the {_MIN_RR:.2f} floor.")
        # Short strike must sit outside 1σ (expected move) — else it's too close.
        svm = legs.get("short_vs_expected_move")
        if svm is not None and _sf(svm) < 0.9:
            fails.append("Short strike inside expected move — assignment risk too high.")

    if legs.get("quality_flags"):
        fails.extend(legs["quality_flags"])

    if _u(ev.get("event_regime")) in ("EVENT_DAY", "PRE_EVENT_COMPRESSION") and kind == "DEBIT":
        fails.append("Scheduled catalyst imminent — debit premium at risk of IV crush.")

    return (len(fails) == 0, fails)


# ── exit engine ──────────────────────────────────────────────────────────────
def _build_exit_plan(strategy: str, legs: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    kind = _PREMIUM_KIND.get(strategy)
    invalidation = list(b["range_invalidation"])
    if b["primary_risk"]:
        invalidation.append(f"Primary risk: {b['primary_risk']}")

    if kind == "CREDIT":
        target = f"Buy back at ~{_sf(legs.get('target_exit')):.2f} (capture 70–80% of credit)."
        if strategy == BULL_PUT:
            stop = ("Close if SPX closes below the short put "
                    f"({_sf(legs.get('sell_leg')):.0f}) or loses VWAP with bearish flow.")
        elif strategy == BEAR_CALL:
            stop = ("Close if SPX closes above the short call "
                    f"({_sf(legs.get('sell_leg')):.0f}) or reclaims VWAP with bullish flow.")
        else:  # IRON_CONDOR
            stop = ("Close the tested side if price breaks either short strike "
                    f"({_sf(legs.get('put_short')):.0f} / {_sf(legs.get('call_short')):.0f}) "
                    "or the balanced auction breaks into a trend.")
    elif kind == "DEBIT":
        target = f"Scale out near ~{_sf(legs.get('target_exit')):.2f} (bank 70–80% of max profit)."
        stop = ("Close if the directional thesis breaks — VWAP lost/reclaimed against you, "
                "flow flips, or price closes back through the long strike "
                f"({_sf(legs.get('buy_leg')):.0f}).")
    else:
        return {"target": None, "stop": None, "time_stop": None, "invalidation": invalidation}

    return {
        "target": target,
        "stop": stop,
        "time_stop": "Flatten by ~3:30 PM ET if neither target nor stop has triggered (0DTE theta/gamma cliff).",
        "invalidation": invalidation or ["No explicit invalidation levels published this cycle."],
    }


# ── opening-range credit model (session-range proxy) ─────────────────────────
def _opening_range_model(b: Dict[str, Any], conf: Dict[str, Any]) -> Dict[str, Any]:
    """The master-prompt Opening-Range Credit Spread model, expressed on canonical
    data. APEX does not publish a formal 15-min OR or EMA9/EMA20 on the bus, so
    this uses the developing SESSION range as the OR proxy and substitutes the
    canonical VWAP/auction/flow reads for the EMA-stack conditions. Flagged as a
    proxy so it's never mistaken for a true OR breakout signal.
    """
    minutes = b["minutes_open"]
    if minutes and minutes < 15:
        return {"active": False, "reason": "Opening range not yet complete (<15 min).",
                "basis": "session_range_proxy"}
    orh = b["session_high"]
    orl = b["session_low"]
    price = b["price"]
    if not (orh and orl and price):
        return {"active": False, "reason": "Session range not established yet.",
                "basis": "session_range_proxy"}

    below_vwap = bool(b["vwap"] and price < b["vwap"])
    above_vwap = bool(b["vwap"] and price > b["vwap"])
    below_poc = "BELOW" in b["price_vs_poc"]
    above_poc = "ABOVE" in b["price_vs_poc"]
    neg_gamma = "NEGATIVE" in b["gamma_regime"]
    dom = _u(conf.get("dominant_side"))

    # Bear-call version: acceptance below the developing range + selling pressure.
    if (price < orl and below_vwap and below_poc and "BEAR" in b["flow_bias"] and dom == "SHORT"):
        return {
            "active": True, "side": BEAR_CALL, "basis": "session_range_proxy",
            "confirmations": [
                f"Price {price:.0f} below developing range low {orl:.0f}",
                "Below VWAP", "Below session POC",
                "Bearish institutional flow" + (" · negative gamma amplifies" if neg_gamma else ""),
            ],
            "note": "Sell a Bear Call credit spread above the developing range on downside acceptance.",
        }
    # Bull-put version (mirror).
    if (price > orh and above_vwap and above_poc and "BULL" in b["flow_bias"] and dom == "LONG"):
        return {
            "active": True, "side": BULL_PUT, "basis": "session_range_proxy",
            "confirmations": [
                f"Price {price:.0f} above developing range high {orh:.0f}",
                "Above VWAP", "Above session POC",
                "Bullish institutional flow" + (" · negative gamma amplifies" if neg_gamma else ""),
            ],
            "note": "Sell a Bull Put credit spread below the developing range on upside acceptance.",
        }
    return {"active": False, "basis": "session_range_proxy",
            "reason": "No confirmed acceptance beyond the developing range yet."}


# ── plain-English story ──────────────────────────────────────────────────────
def _build_story(strategy: str, b: Dict[str, Any], reasons: List[str],
                 confidence: float) -> List[str]:
    if strategy == NO_TRADE:
        return reasons + [f"Recommended structure: No Trade. Confidence {confidence:.0f}."]
    story: List[str] = []
    if b["vwap"] and b["price"]:
        story.append(f"Price {b['price']:.0f} "
                     f"{'above' if b['price'] >= b['vwap'] else 'below'} VWAP {b['vwap']:.0f}.")
    if b["auction_state"]:
        story.append(f"Auction: {b['auction_state'].replace('_', ' ').title()}.")
    if b["gamma_regime"]:
        story.append("Dealer gamma "
                     + ("negative — moves amplify (trend-friendly)."
                        if "NEGATIVE" in b["gamma_regime"]
                        else "positive — moves dampen toward magnets." if "POSITIVE" in b["gamma_regime"]
                        else "regime unclear."))
    story += reasons
    story.append(f"Recommended structure: {_STRATEGY_LABEL[strategy]}. Confidence {confidence:.0f}.")
    return story


# ── main entrypoint ──────────────────────────────────────────────────────────
def build_premium_strategy(
    last_result: Dict[str, Any],
    confluence: Optional[Dict[str, Any]] = None,
    events: Optional[Dict[str, Any]] = None,
    width: float = _DEFAULT_WIDTH,
) -> Dict[str, Any]:
    """Assemble the premium-structure recommendation from already-composed output."""
    try:
        if not isinstance(last_result, dict) or not last_result:
            return _empty("No composed result on the bus yet.")

        inst = last_result.get("institutional_intelligence") or {}
        if not inst:
            return _empty("Institutional Intelligence layer not populated yet.")

        b = _pull(last_result)
        conf = confluence or {}
        ev = events or {}
        vixreg = _vix_regime(b["vix"], b["vol_regime"])

        strategy, confidence, reasons, case_label = _select_strategy(b, conf, ev, vixreg)

        legs: Dict[str, Any] = {}
        exit_plan: Dict[str, Any] = {}
        if strategy != NO_TRADE and b["price"] > 0:
            legs = _build_legs(strategy, b, width)
            ok, fails = _credit_quality_check(strategy, legs, b, ev)
            if not ok:
                # Quality gate failed → downgrade to No Trade with the reasons.
                reasons = reasons + ["Credit-quality filter rejected the structure:"] + fails
                strategy, confidence, legs = NO_TRADE, min(confidence, 50.0), {}
                case_label += "->QUALITY_REJECT"
            else:
                exit_plan = _build_exit_plan(strategy, legs, b)

        or_model = _opening_range_model(b, conf)
        # If the OR proxy fires and agrees with the chosen credit direction, note it.
        if or_model.get("active") and or_model.get("side") == strategy:
            confidence = min(99.0, confidence + 4.0)
            reasons.append("Opening-range acceptance confirms the credit direction (session-range proxy).")

        story = _build_story(strategy, b, reasons, confidence)

        return {
            "available": True,
            "version": VERSION,
            "strategy": strategy,
            "strategy_label": _STRATEGY_LABEL[strategy],
            "premium_kind": _PREMIUM_KIND[strategy],
            "confidence": round(confidence, 0),
            "case": case_label,
            "vix": round(b["vix"], 2) if b["vix"] else None,
            "vix_regime": vixreg,
            "expected_move": round(b["expected_move"], 2) if b["expected_move"] else None,
            "price": round(b["price"], 2) if b["price"] else None,
            "reason": reasons,
            "legs": legs,
            "exit_plan": exit_plan,
            "opening_range_model": or_model,
            "story": story,
            "headline": _headline(strategy, confidence),
        }
    except Exception as e:  # never 500 the dashboard
        return _empty(f"Premium strategy synthesis error (recovered): {e}")


def _headline(strategy: str, confidence: float) -> str:
    if strategy == NO_TRADE:
        return "NO TRADE — STAND ASIDE"
    return f"{_STRATEGY_LABEL[strategy].upper()}  ·  {confidence:.0f}"


def _empty(note: str) -> Dict[str, Any]:
    return {
        "available": False,
        "version": VERSION,
        "note": note,
        "strategy": NO_TRADE,
        "strategy_label": _STRATEGY_LABEL[NO_TRADE],
        "premium_kind": "NONE",
        "confidence": 0,
        "case": "UNAVAILABLE",
        "vix": None, "vix_regime": "MID", "expected_move": None, "price": None,
        "reason": [note],
        "legs": {}, "exit_plan": {},
        "opening_range_model": {"active": False, "basis": "session_range_proxy"},
        "story": [note],
        "headline": "NO TRADE — STAND ASIDE",
    }
