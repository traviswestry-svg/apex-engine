"""engine/premarket.py — Pre-Market Forecast Engine.

Between 6:00 and 9:30 ET the cash index is closed but SPY, QQQ, and ES are
live. This engine turns that data into an opening forecast instead of a
"market closed" shrug:

  * per-instrument pre-market read (change, range, trend, participation)
  * projected SPX open (ES primary, SPY-implied as a cross-check)
  * gap classification and a gap-fill vs gap-and-go probability estimate
  * SPY/QQQ agreement (tech-led confirmation or divergence warning)
  * an opening playbook keyed to yesterday's value area and the walls

HONESTY GUARDRAILS
------------------
Pre-market liquidity is thin and the fill/go probabilities are HEURISTIC
PRIORS (documented base rates by gap size, nudged by trend/agreement), not
learned statistics — every payload says so. Confidence is hard-capped at 65.
Advisory only; never touches execution permissions. Read-only; never raises
into the compose loop — any internal error returns available=False.
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List, Optional

VERSION = "1.0.0_PREMARKET_FORECAST"

# Heuristic gap-fill base rates by gap class (documented priors, not learned).
# Small opening gaps on index products historically fill the same day far more
# often than large ones; these are deliberately round, clearly-labeled priors.
_FILL_PRIORS = {"FLAT": 50.0, "SMALL": 72.0, "MODERATE": 58.0, "LARGE": 40.0}
_CONFIDENCE_CAP = 65.0


def _sf(v: Any, d: float = 0.0) -> float:
    try:
        x = float(v)
        return x if x == x and x not in (float("inf"), float("-inf")) else d
    except (TypeError, ValueError):
        return d


def _fmt(v: float) -> str:
    return f"{v:,.2f}"


def _today_session_bars(bars: List[Dict[str, Any]], now_et: dt.datetime,
                        start_hour: int) -> List[Dict[str, Any]]:
    """Bars from today's pre-market window (>= start_hour ET, < 9:30 ET)."""
    tz = now_et.tzinfo
    start = now_et.replace(hour=start_hour, minute=0, second=0, microsecond=0)
    open_930 = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    out = []
    for b in bars:
        t_ms = _sf(b.get("t"))
        if t_ms <= 0:
            continue
        ts = dt.datetime.fromtimestamp(t_ms / 1000.0, tz=tz)
        if ts.date() == now_et.date() and start <= ts < open_930:
            out.append(b)
    return out


def _instrument_read(name: str, bars: List[Dict[str, Any]],
                     prior_close: float) -> Dict[str, Any]:
    if not bars:
        return {"instrument": name, "available": False, "state": "NO_PREMARKET_BARS"}
    closes = [_sf(b.get("c")) for b in bars if _sf(b.get("c")) > 0]
    highs = [_sf(b.get("h")) for b in bars if _sf(b.get("h")) > 0]
    lows = [_sf(b.get("l")) for b in bars if _sf(b.get("l")) > 0]
    vols = [_sf(b.get("v")) for b in bars]
    if not closes:
        return {"instrument": name, "available": False, "state": "NO_PREMARKET_BARS"}
    last = closes[-1]
    first = closes[0]
    chg_pct = round((last - prior_close) / prior_close * 100, 3) if prior_close > 0 else None
    drift_pct = round((last - first) / first * 100, 3) if first > 0 else 0.0
    if drift_pct > 0.08:
        trend = "RISING"
    elif drift_pct < -0.08:
        trend = "FALLING"
    else:
        trend = "FLAT"
    return {
        "instrument": name,
        "available": True,
        "last": last,
        "prior_close": prior_close if prior_close > 0 else None,
        "change_pct_vs_prior_close": chg_pct,
        "premarket_high": max(highs) if highs else None,
        "premarket_low": min(lows) if lows else None,
        "premarket_drift_pct": drift_pct,
        "trend": trend,
        "bar_count": len(bars),
        "volume": round(sum(vols), 0),
        "state": "READY",
    }


def _gap_class(gap_pct_abs: float) -> str:
    if gap_pct_abs < 0.10:
        return "FLAT"
    if gap_pct_abs < 0.30:
        return "SMALL"
    if gap_pct_abs < 0.75:
        return "MODERATE"
    return "LARGE"


def build_premarket_forecast(
    *,
    spy_bars: List[Dict[str, Any]],
    qqq_bars: List[Dict[str, Any]],
    es_price: Optional[float],
    spy_prior_close: Optional[float],
    qqq_prior_close: Optional[float],
    spx_prior_close: Optional[float],
    prior_poc: Optional[float] = None,
    prior_vah: Optional[float] = None,
    prior_val: Optional[float] = None,
    call_wall: Optional[float] = None,
    put_wall: Optional[float] = None,
    now_et: Optional[dt.datetime] = None,
    premarket_start_hour: int = 6,
) -> Dict[str, Any]:
    try:
        return _build(spy_bars=spy_bars, qqq_bars=qqq_bars, es_price=es_price,
                      spy_prior_close=spy_prior_close, qqq_prior_close=qqq_prior_close,
                      spx_prior_close=spx_prior_close, prior_poc=prior_poc,
                      prior_vah=prior_vah, prior_val=prior_val, call_wall=call_wall,
                      put_wall=put_wall, now_et=now_et,
                      premarket_start_hour=premarket_start_hour)
    except Exception as err:  # never break the compose loop
        return {"ok": True, "available": False, "version": VERSION,
                "state": "ERROR", "error": f"{type(err).__name__}: {err!r}"}


def _build(*, spy_bars, qqq_bars, es_price, spy_prior_close, qqq_prior_close,
           spx_prior_close, prior_poc, prior_vah, prior_val, call_wall,
           put_wall, now_et, premarket_start_hour) -> Dict[str, Any]:
    n = now_et or dt.datetime.now()
    open_930 = n.replace(hour=9, minute=30, second=0, microsecond=0)
    mins_to_open = max(0, int((open_930 - n).total_seconds() // 60))

    spx_close = _sf(spx_prior_close)
    spy = _instrument_read("SPY", _today_session_bars(spy_bars or [], n, premarket_start_hour), _sf(spy_prior_close))
    qqq = _instrument_read("QQQ", _today_session_bars(qqq_bars or [], n, premarket_start_hour), _sf(qqq_prior_close))

    # ── Projected SPX open: ES primary (already in SPX coordinates upstream),
    #    SPY-implied as an independent cross-check.
    es_projected = _sf(es_price) if _sf(es_price) > 0 else None
    spy_implied = None
    if spy.get("available") and spy.get("change_pct_vs_prior_close") is not None and spx_close > 0:
        spy_implied = round(spx_close * (1 + spy["change_pct_vs_prior_close"] / 100.0), 2)
    projected_open = es_projected or spy_implied
    projection_source = "ES" if es_projected else ("SPY_IMPLIED" if spy_implied else None)
    projection_divergence_pts = (round(abs(es_projected - spy_implied), 2)
                                 if es_projected and spy_implied else None)

    if projected_open is None or spx_close <= 0:
        return {"ok": True, "available": False, "version": VERSION,
                "state": "INSUFFICIENT_DATA",
                "reason": "No ES price or SPY pre-market bars to project the open.",
                "minutes_to_open": mins_to_open}

    # ── Gap ──
    gap_pts = round(projected_open - spx_close, 2)
    gap_pct = round(gap_pts / spx_close * 100, 3)
    gap_direction = "UP" if gap_pts > 0 else "DOWN" if gap_pts < 0 else "FLAT"
    gap_class = _gap_class(abs(gap_pct))

    # ── SPY/QQQ agreement ──
    agreement = "UNKNOWN"
    agreement_note = "Insufficient pre-market bars to compare SPY and QQQ."
    if spy.get("available") and qqq.get("available"):
        s_chg = _sf(spy.get("change_pct_vs_prior_close"))
        q_chg = _sf(qqq.get("change_pct_vs_prior_close"))
        if s_chg * q_chg > 0:
            leader = "QQQ" if abs(q_chg) > abs(s_chg) else "SPY"
            agreement = "TECH_LED_AGREEMENT" if leader == "QQQ" else "BROAD_AGREEMENT"
            agreement_note = (f"SPY {s_chg:+.2f}% and QQQ {q_chg:+.2f}% agree; "
                              f"{leader} is leading — "
                              f"{'tech is driving the move' if leader == 'QQQ' else 'broad participation'}.")
        elif s_chg == 0 or q_chg == 0:
            agreement = "MIXED"
            agreement_note = f"SPY {s_chg:+.2f}% / QQQ {q_chg:+.2f}% — one is flat; weak conviction."
        else:
            agreement = "DIVERGENCE"
            agreement_note = (f"SPY {s_chg:+.2f}% and QQQ {q_chg:+.2f}% disagree — "
                              f"index and tech are pointed in opposite directions; fade risk on the gap.")

    # ── Gap-fill vs gap-and-go estimate (heuristic priors, adjusted) ──
    fill_prob = _FILL_PRIORS[gap_class]
    adjustments: List[str] = []
    pm_trend = spy.get("trend") if spy.get("available") else None
    if gap_class != "FLAT" and pm_trend:
        trend_with_gap = ((gap_direction == "UP" and pm_trend == "RISING")
                          or (gap_direction == "DOWN" and pm_trend == "FALLING"))
        trend_against_gap = ((gap_direction == "UP" and pm_trend == "FALLING")
                             or (gap_direction == "DOWN" and pm_trend == "RISING"))
        if trend_with_gap:
            fill_prob -= 10
            adjustments.append("pre-market drift extends the gap (-10 fill)")
        elif trend_against_gap:
            fill_prob += 10
            adjustments.append("pre-market drift is already fading the gap (+10 fill)")
    if agreement in ("TECH_LED_AGREEMENT", "BROAD_AGREEMENT") and gap_class != "FLAT":
        fill_prob -= 5
        adjustments.append("SPY/QQQ agree with the gap direction (-5 fill)")
    elif agreement == "DIVERGENCE":
        fill_prob += 8
        adjustments.append("SPY/QQQ divergence (+8 fill)")
    # value-area context: gapping beyond yesterday's value un-filled less often
    vah = _sf(prior_vah); val_ = _sf(prior_val)
    if vah > 0 and gap_direction == "UP" and projected_open > vah:
        fill_prob -= 5
        adjustments.append("open projected above yesterday's VAH — acceptance risk (-5 fill)")
    if val_ > 0 and gap_direction == "DOWN" and projected_open < val_:
        fill_prob -= 5
        adjustments.append("open projected below yesterday's VAL — acceptance risk (-5 fill)")
    fill_prob = max(15.0, min(85.0, fill_prob))
    go_prob = round(100.0 - fill_prob, 1)

    if gap_class == "FLAT":
        expected_open = "BALANCED_OPEN"
    elif go_prob >= 55:
        expected_open = "GAP_AND_GO"
    elif fill_prob >= 60:
        expected_open = "GAP_FILL_ROTATION"
    else:
        expected_open = "TWO_SIDED_OPEN"

    bias = "NEUTRAL"
    if gap_class != "FLAT":
        if expected_open == "GAP_AND_GO":
            bias = "BULLISH" if gap_direction == "UP" else "BEARISH"
        elif expected_open == "GAP_FILL_ROTATION":
            bias = "BEARISH" if gap_direction == "UP" else "BULLISH"

    # confidence: starts from data completeness and agreement, hard-capped
    conf = 35.0
    if spy.get("available"):
        conf += 10
    if qqq.get("available"):
        conf += 5
    if es_projected and spy_implied:
        conf += 5
        if projection_divergence_pts is not None and projection_divergence_pts < max(2.0, spx_close * 0.0005):
            conf += 5
    if agreement in ("TECH_LED_AGREEMENT", "BROAD_AGREEMENT"):
        conf += 5
    confidence = min(_CONFIDENCE_CAP, round(conf, 1))

    # ── Key levels for the open (SPX coordinates) ──
    key_levels: List[Dict[str, Any]] = []
    pm_high = pm_low = None
    if spy.get("available") and spy.get("premarket_high") and spx_close > 0 and _sf(spy_prior_close) > 0:
        ratio = spx_close / _sf(spy_prior_close)
        pm_high = round(_sf(spy["premarket_high"]) * ratio, 2)
        pm_low = round(_sf(spy["premarket_low"]) * ratio, 2)
        key_levels.append({"label": "Pre-market High", "price": pm_high,
                           "role": "First resistance — break-and-hold above extends the gap"})
        key_levels.append({"label": "Pre-market Low", "price": pm_low,
                           "role": "First support — loss of it opens the gap-fill path"})
    for label, price, role in (
        ("Prior VAH", vah, "Acceptance above confirms breakout"),
        ("Prior POC", _sf(prior_poc), "Gap-fill magnet — primary institutional reference"),
        ("Prior VAL", val_, "Acceptance below confirms breakdown"),
        ("Prior Close", spx_close, "Full gap-fill target"),
        ("Call Wall", _sf(call_wall), "Dealer resistance"),
        ("Put Wall", _sf(put_wall), "Dealer support"),
    ):
        if price and price > 0:
            key_levels.append({"label": label, "price": round(price, 2), "role": role})

    # ── Opening playbook ──
    playbook: List[Dict[str, Any]] = []
    if gap_class == "FLAT":
        playbook.append({
            "name": "BALANCED_OPEN", "probability": 55,
            "path": f"Flat open near {_fmt(spx_close)}. Expect early rotation inside yesterday's value "
                    f"({_fmt(val_)}–{_fmt(vah)}) until initiative flow appears.",
            "confirmation": "Acceptance beyond VAH/VAL with directional flow and Pine confirmation."})
    else:
        go_name = "GAP_AND_GO_" + ("UP" if gap_direction == "UP" else "DOWN")
        fill_target = _sf(prior_poc) or spx_close
        playbook.append({
            "name": go_name, "probability": go_prob,
            "path": f"Gap {gap_direction.lower()} holds: buyers defend the pre-market "
                    f"{'low' if gap_direction == 'UP' else 'high'}"
                    + (f" ({_fmt(pm_low if gap_direction == 'UP' else pm_high)})" if pm_high else "")
                    + f" and price extends away from {_fmt(spx_close)}.",
            "confirmation": "First 15m holds beyond prior "
                            + ("VAH" if gap_direction == "UP" else "VAL")
                            + " with directional flow; Pine confirmation required to enter."})
        playbook.append({
            "name": "GAP_FILL", "probability": fill_prob,
            "path": f"Opening drive fails and price rotates back toward the POC magnet at {_fmt(fill_target)} "
                    f"and prior close {_fmt(spx_close)}.",
            "confirmation": "Loss of the pre-market "
                            + ("low" if gap_direction == "UP" else "high")
                            + " in the first 30m with fading breadth."})

    gap_word = ("flat" if gap_class == "FLAT"
                else f"{gap_class.lower()} gap {gap_direction.lower()} of {_fmt(abs(gap_pts))} pts ({abs(gap_pct):.2f}%)")
    summary = (
        f"[PREMARKET] {mins_to_open}m to the open. Projected SPX open ~{_fmt(projected_open)} "
        f"({projection_source}) vs prior close {_fmt(spx_close)} — {gap_word}. "
        f"{agreement_note} "
        f"Read: {expected_open.replace('_', ' ').title()} "
        f"(fill {fill_prob:.0f}% / go {go_prob:.0f}%, heuristic priors). "
        f"Key opening references: "
        + ", ".join(f"{k['label']} {_fmt(k['price'])}" for k in key_levels[:4])
        + ". Entries unlock at 9:30 ET with Pine confirmation."
    )

    return {
        "ok": True,
        "available": True,
        "version": VERSION,
        "state": "READY",
        "mode": "PREMARKET_FORECAST",
        "minutes_to_open": mins_to_open,
        "premarket_window": f"{premarket_start_hour:02d}:00–09:30 ET",
        "instruments": {"SPY": spy, "QQQ": qqq,
                        "ES": {"instrument": "ES", "available": bool(es_projected),
                               "price_spx_coords": es_projected}},
        "projected_spx_open": projected_open,
        "projection_source": projection_source,
        "projection_cross_check": {"es": es_projected, "spy_implied": spy_implied,
                                   "divergence_pts": projection_divergence_pts},
        "gap": {"points": gap_pts, "pct": gap_pct, "direction": gap_direction,
                "classification": gap_class},
        "spy_qqq_agreement": {"state": agreement, "note": agreement_note},
        "forecast": {
            "expected_open_type": expected_open,
            "bias": bias,
            "confidence": confidence,
            "confidence_cap": _CONFIDENCE_CAP,
            "gap_fill_probability_pct": fill_prob,
            "gap_and_go_probability_pct": go_prob,
            "probability_basis": "HEURISTIC_PRIORS_ADJUSTED",
            "adjustments": adjustments,
        },
        "key_levels": key_levels,
        "opening_playbook": playbook,
        "executive_summary": summary,
        "guardrails": {
            "advisory_only": True,
            "read_only": True,
            "broker_mutation": False,
            "probabilities_are_heuristic_priors": True,
            "thin_liquidity_warning": "Pre-market volume is a fraction of RTH; levels and probabilities are lower-confidence than intraday reads.",
            "entries_locked_until_rth": True,
        },
    }
