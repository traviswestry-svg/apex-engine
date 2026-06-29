"""engine/overnight.py — APEX Overnight Game Plan Engine.

When ES is trading but the cash market is closed, APEX switches into
Overnight Monitor mode. This engine produces a structured game plan
by comparing the current ES price against Friday's key levels:
  - Friday's POC, VAH, VAL
  - Overnight high/low and range
  - Gamma levels (Call Wall, Put Wall, Zero Gamma)
  - Futures basis (ES vs. SPX close)
  - Session trend (trending up/down/ranging)

The output is a prose game plan the trader reads before the RTH open.
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


def _fmt(v: float) -> str:
    return f"{v:,.2f}"


def _pct(a: float, b: float) -> str:
    if b == 0:
        return "0.0%"
    return f"{abs((a - b) / b * 100):.2f}%"


def build_overnight_game_plan(
    *,
    es_price: float,
    es_bars: List[Dict[str, Any]],          # intraday bars for overnight session
    prior_poc: Optional[float],
    prior_vah: Optional[float],
    prior_val: Optional[float],
    prior_close: Optional[float],           # Friday SPX close
    call_wall: Optional[float],
    put_wall: Optional[float],
    zero_gamma: Optional[float],
    session_state: str = "OVERNIGHT",
    next_rth: str = "9:30 AM ET",
) -> Dict[str, Any]:
    """Synthesize all available overnight data into a structured game plan."""

    # ── Overnight range from bars ──
    on_high = on_low = on_open = None
    if es_bars:
        highs  = [_sf(b.get("h")) for b in es_bars if b.get("h")]
        lows   = [_sf(b.get("l")) for b in es_bars if b.get("l")]
        opens  = [_sf(b.get("o")) for b in es_bars if b.get("o")]
        on_high  = max(highs)  if highs  else None
        on_low   = min(lows)   if lows   else None
        on_open  = opens[0]    if opens  else None

    on_range = round(on_high - on_low, 2) if (on_high and on_low) else None

    # ── ES vs prior levels ──
    poc   = _sf(prior_poc)
    vah   = _sf(prior_vah)
    val_  = _sf(prior_val)
    close = _sf(prior_close)

    price_vs_poc = ""
    poc_context  = ""
    if poc > 0:
        diff = es_price - poc
        if abs(diff) <= 1.0:
            price_vs_poc = "AT"
            poc_context  = f"ES is hovering at Friday's POC ({_fmt(poc)}) — balanced auction."
        elif diff > 0:
            price_vs_poc = "ABOVE"
            poc_context  = f"ES is trading {_fmt(diff)} points above Friday's POC ({_fmt(poc)}) — buyers have accepted higher prices overnight."
        else:
            price_vs_poc = "BELOW"
            poc_context  = f"ES is trading {_fmt(abs(diff))} points below Friday's POC ({_fmt(poc)}) — sellers pushed price lower overnight."

    va_context = ""
    price_vs_va = ""
    if vah > 0 and val_ > 0:
        if es_price > vah:
            price_vs_va = "ABOVE_VAH"
            va_context  = f"ES has broken above Friday's Value Area High ({_fmt(vah)}) — buyers are accepting higher prices as fair value."
        elif es_price < val_:
            price_vs_va = "BELOW_VAL"
            va_context  = f"ES has broken below Friday's Value Area Low ({_fmt(val_)}) — sellers pushing outside value."
        else:
            price_vs_va = "INSIDE"
            va_context  = f"ES is inside Friday's Value Area ({_fmt(val_)}–{_fmt(vah)}) — balanced overnight session."

    # ── Gap projection ──
    gap_context = ""
    if close > 0 and es_price > 0:
        gap = es_price - close
        gap_pct = abs(gap / close * 100)
        if abs(gap) < 2.0:
            gap_context = f"ES is near Friday's SPX close ({_fmt(close)}) — flat gap expected at open."
        elif gap > 0:
            gap_context = f"ES is {_fmt(gap)} points above Friday's SPX close ({_fmt(close)}) — gap up of ~{gap_pct:.1f}% projected at RTH open."
        else:
            gap_context = f"ES is {_fmt(abs(gap))} points below Friday's SPX close ({_fmt(close)}) — gap down of ~{gap_pct:.1f}% projected at RTH open."

    # ── Gamma context ──
    gamma_context = ""
    call_w = _sf(call_wall)
    put_w  = _sf(put_wall)
    zero_g = _sf(zero_gamma)
    if call_w > 0 and es_price > 0:
        dist_call = call_w - es_price
        if 0 < dist_call < 10:
            gamma_context += f"ES is within {_fmt(dist_call)} points of the Call Wall ({_fmt(call_w)}) — expect resistance. "
        elif dist_call <= 0:
            gamma_context += f"ES is trading above the Call Wall ({_fmt(call_w)}) — gamma squeeze territory. "
    if put_w > 0 and es_price > 0:
        dist_put = es_price - put_w
        if 0 < dist_put < 10:
            gamma_context += f"Only {_fmt(dist_put)} points above the Put Wall ({_fmt(put_w)}) — downside buffer is thin. "
    if zero_g > 0 and es_price > 0:
        dist_flip = abs(es_price - zero_g)
        if dist_flip < 5:
            gamma_context += f"ES is within {_fmt(dist_flip)} points of the zero-gamma flip ({_fmt(zero_g)}) — expect a volatility regime shift on a breach. "

    # ── Overnight trend ──
    trend = "RANGING"
    trend_context = ""
    if on_open and es_price > 0:
        move = es_price - on_open
        if abs(move) < 3:
            trend = "RANGING"
            trend_context = f"ES has ranged {on_range or '?'} points overnight — low conviction session."
        elif move > 0:
            trend = "TRENDING_UP"
            trend_context = f"ES has trended {_fmt(move)} points higher since the overnight open — buyers in control."
        else:
            trend = "TRENDING_DOWN"
            trend_context = f"ES has trended {_fmt(abs(move))} points lower since the overnight open — sellers in control."

    # ── Overnight high/low vs gamma ──
    key_levels = []
    if on_high:
        key_levels.append({"label": "Overnight High", "price": round(on_high, 2)})
    if on_low:
        key_levels.append({"label": "Overnight Low",  "price": round(on_low,  2)})
    if poc > 0:
        key_levels.append({"label": "Fri POC",  "price": round(poc, 2)})
    if vah > 0:
        key_levels.append({"label": "Fri VAH",  "price": round(vah, 2)})
    if val_ > 0:
        key_levels.append({"label": "Fri VAL",  "price": round(val_, 2)})
    if call_w > 0:
        key_levels.append({"label": "Call Wall", "price": round(call_w, 2)})
    if put_w > 0:
        key_levels.append({"label": "Put Wall",  "price": round(put_w, 2)})
    if zero_g > 0:
        key_levels.append({"label": "Zero Gamma","price": round(zero_g, 2)})
    key_levels.sort(key=lambda x: x["price"], reverse=True)

    # ── Build the game plan prose ──
    parts = []
    if poc_context:
        parts.append(poc_context)
    if va_context:
        parts.append(va_context)
    if trend_context:
        parts.append(trend_context)
    if on_high and on_low:
        parts.append(f"Overnight range: {_fmt(on_low)}–{_fmt(on_high)} ({on_range} pts).")
    if gap_context:
        parts.append(gap_context)
    if gamma_context:
        parts.append(gamma_context.strip())

    # ── Opening bias ──
    bias = "NEUTRAL"
    if price_vs_poc == "ABOVE" and price_vs_va in ("ABOVE_VAH", "INSIDE") and trend == "TRENDING_UP":
        bias = "BULLISH"
        bias_note = "Monitor for continuation above overnight high at the RTH open. Bullish bias if price holds above POC after 9:30."
    elif price_vs_poc == "BELOW" and price_vs_va in ("BELOW_VAL", "INSIDE") and trend == "TRENDING_DOWN":
        bias = "BEARISH"
        bias_note = "Monitor for continuation below overnight low. Bearish bias if price fails to reclaim POC after the open."
    elif price_vs_va == "ABOVE_VAH":
        bias = "BULLISH_LEAN"
        bias_note = "Gap up scenario — watch whether buyers defend the gap or price fills back into value."
    elif price_vs_va == "BELOW_VAL":
        bias = "BEARISH_LEAN"
        bias_note = "Gap down scenario — watch whether sellers continue or price reclaims VAL."
    else:
        bias_note = "No strong overnight directional conviction. Watch for ORB or POC acceptance in the first 15 minutes of RTH."

    parts.append(bias_note)

    # Opening watch levels
    watch_levels = []
    if poc > 0:
        watch_levels.append(f"POC {_fmt(poc)}")
    if price_vs_va == "ABOVE_VAH" and vah > 0:
        watch_levels.append(f"VAH {_fmt(vah)} as support")
    elif price_vs_va == "BELOW_VAL" and val_ > 0:
        watch_levels.append(f"VAL {_fmt(val_)} as resistance")
    if on_high:
        watch_levels.append(f"Overnight high {_fmt(on_high)}")
    if on_low:
        watch_levels.append(f"Overnight low {_fmt(on_low)}")

    watch_str = f"Key opening levels: {', '.join(watch_levels)}." if watch_levels else ""
    if watch_str:
        parts.append(watch_str)

    parts.append(f"No entries until RTH open ({next_rth}) and Pine confirmation. Institutional options flow is quiet until the cash market opens.")

    game_plan = " ".join(parts)

    # ── Executive summary (one sentence) ──
    if bias in ("BULLISH", "BULLISH_LEAN"):
        exec_summary = (
            f"[OVERNIGHT] ES has traded {'above Friday\'s POC' if price_vs_poc == 'ABOVE' else 'inside value'} overnight "
            f"with a {'bullish' if bias == 'BULLISH' else 'mild bullish'} lean. "
            f"Prepare for a potential {'bullish' if bias == 'BULLISH' else 'gap-up'} opening. "
            f"Wait for POC acceptance and Pine confirmation at the RTH open."
        )
    elif bias in ("BEARISH", "BEARISH_LEAN"):
        exec_summary = (
            f"[OVERNIGHT] ES has traded {'below Friday\'s POC' if price_vs_poc == 'BELOW' else 'inside value'} overnight "
            f"with a {'bearish' if bias == 'BEARISH' else 'mild bearish'} lean. "
            f"Prepare for a potential {'bearish' if bias == 'BEARISH' else 'gap-down'} opening. "
            f"Watch for POC rejection and Pine confirmation at RTH open."
        )
    else:
        exec_summary = (
            f"[OVERNIGHT] ES is ranging near Friday's value area with no directional conviction. "
            f"Institutional options flow is quiet. "
            f"Wait for the first 15 minutes of RTH to establish direction before entering."
        )

    return {
        "mode":          "OVERNIGHT",
        "session_state": session_state,
        "bias":          bias,
        "trend":         trend,
        "executive_summary": exec_summary,
        "game_plan":     game_plan,
        "price_vs_poc":  price_vs_poc,
        "price_vs_va":   price_vs_va,
        "es_price":      round(es_price, 2),
        "overnight_high": round(on_high, 2) if on_high else None,
        "overnight_low":  round(on_low,  2) if on_low  else None,
        "overnight_range": on_range,
        "prior_poc":     round(poc, 2) if poc else None,
        "prior_vah":     round(vah, 2) if vah else None,
        "prior_val":     round(val_, 2) if val_ else None,
        "projected_gap": round(es_price - close, 2) if close > 0 else None,
        "key_levels":    key_levels,
        "next_rth":      next_rth,
        "bars_used":     len(es_bars),
    }
