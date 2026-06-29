"""engine/story.py — APEX 6.3.4 Story Engine 3.0.

Synthesizes all engine outputs — including Auction / Volume Profile,
Institutional Flow Tape, Gamma Regime, Market Regime, Trend, and
Execution context — into:
  1. A timestamped chapter timeline
  2. A full prose narrative paragraph
  3. A one-sentence executive summary

Also re-exports apex_engines shims for backward compat.
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Any, Dict, List, Optional


def _sf(v: Any, d: float = 0.0) -> float:
    try:
        f = float(v) if v is not None else d
        return d if (math.isnan(f) or math.isinf(f)) else f
    except Exception:
        return d


def _now_et() -> dt.datetime:
    try:
        import zoneinfo
        return dt.datetime.now(zoneinfo.ZoneInfo("America/New_York"))
    except Exception:
        return dt.datetime.now(dt.timezone(dt.timedelta(hours=-4)))


def build_story_v3(
    *,
    ticker: str,
    market_regime: Dict[str, Any],
    gamma_regime: Dict[str, Any],
    flow: Dict[str, Any],
    structure: Dict[str, Any],
    trend: Dict[str, Any],
    execution: Dict[str, Any],
    consensus: Dict[str, Any],
    risk: Dict[str, Any],
    auction: Optional[Dict[str, Any]] = None,
    volume_profile: Optional[Dict[str, Any]] = None,
    flow_tape_summary: Optional[Dict[str, Any]] = None,
    session_state: str = "MARKET_OPEN",
) -> Dict[str, Any]:
    """Story Engine 3.0 — multi-chapter institutional narrative."""
    now = _now_et()
    chapters: List[Dict[str, Any]] = []
    prose: List[str] = []
    ts = now.strftime("%H:%M")
    closed_states = {"PREMARKET", "AFTER_HOURS", "CLOSED"}
    slabel = {"PREMARKET": "[PRE-MARKET] ", "AFTER_HOURS": "[AFTER-HOURS] ",
               "CLOSED": "[CLOSED SESSION] "}.get(session_state, "")

    def ch(chapter, text, color, significance):
        chapters.append({"time": ts, "chapter": chapter, "text": text,
                          "color": color, "significance": significance})
        prose.append(text)

    # ── 1: Market Regime ──
    regime = market_regime.get("regime", "NEUTRAL")
    vix = _sf(market_regime.get("vix"), 18.0)
    rc = ("#0ca30c" if regime in ("TREND_DAY","RISK_ON") else
          "#e34948" if regime in ("HIGH_VOLATILITY","DEFENSIVE") else "#2a78d6")
    ch("Market Regime",
       f"{slabel}{regime.replace('_',' ')}: {market_regime.get('regime_description','')} VIX {vix:.1f}.",
       rc, 1.0)

    # ── 2: Gamma Regime ──
    gk = gamma_regime.get("regime_label","")
    gc = ("#2a78d6" if "POSITIVE" in gk else "#e34948" if "NEGATIVE" in gk else "#fab219")
    gt = f"{gamma_regime.get('regime_display','Mixed Gamma')}: {gamma_regime.get('vol_description','')}"
    if gamma_regime.get("flip_risk"):
        gt += " Price near zero-gamma flip — regime may shift."
    ch("Gamma Regime", gt, gc, 1.5)

    # ── 3: Auction / Volume Profile ──
    vp = volume_profile or {}
    au = auction or {}
    vp_levels = (vp.get("levels") or {}) if isinstance(vp, dict) else {}
    poc  = _sf(au.get("poc") or vp_levels.get("poc"))
    vah  = _sf(au.get("vah") or vp_levels.get("vah"))
    val_ = _sf(au.get("val") or vp_levels.get("val"))
    mig  = au.get("poc_migration","UNKNOWN")
    price = _sf(structure.get("current_price") or au.get("current_price"))
    avail = au.get("available", False)
    if avail and poc > 0:
        pvp = "above" if price > poc else "below" if price < poc else "at"
        va = ""
        if vah > 0 and val_ > 0:
            va = (f" Above VAH {vah:.2f}." if price > vah else
                  f" Below VAL {val_:.2f}." if price < val_ else
                  f" Inside value area ({val_:.2f}–{vah:.2f}).")
        at = f"POC {poc:.2f}. Price {pvp} POC.{va} Migration: {mig.lower().replace('_',' ')}."
        if au.get("narrative"): at += f" {au['narrative']}"
        ac = ("#0ca30c" if mig=="RISING" else "#e34948" if mig=="FALLING" else "#fab219")
    else:
        at = "Volume profile not yet available — waiting for session bars."; ac = "#475569"
    ch("Auction / Volume Profile", at, ac, 2.0)

    # ── 4: Institutional Flow Intelligence ──
    bias = flow.get("bias","MIXED")
    net_p = _sf(flow.get("net_premium"))
    sw_agg = flow.get("sweep_aggression","NONE")
    sw_cnt = int(_sf(flow.get("sweep_count")))
    if abs(net_p) > 1_000_000:
        d = "accumulating" if net_p > 0 else "distributing"
        fp = f"Institutions {d} on {ticker} ({'+' if net_p>0 else ''}{net_p/1e6:.1f}M net)."
    elif abs(net_p) > 0:
        fp = f"Options flow bias is {bias.lower()} on {ticker}."
    else:
        fp = f"Options flow mixed or unavailable for {ticker}."
    if sw_agg in ("HIGH","VERY_HIGH"):
        fp += f" {sw_cnt} sweeps — urgency {sw_agg.lower().replace('_',' ')}."
    if flow.get("flow_flip"):
        fp += f" Flow flipped {flow.get('flow_flip_direction','').lower()} — momentum shift."
    fc = "#0ca30c" if bias=="BULLISH" else "#e34948" if bias=="BEARISH" else "#fab219"
    ch("Institutional Flow Intelligence", fp, fc, 2.5)

    # ── 5: Institutional Flow Tape ──
    tape = flow_tape_summary or {}
    tr = int(_sf(tape.get("row_count")))
    if tr > 0:
        tn = _sf(tape.get("net_premium"))
        ts2 = int(_sf(tape.get("sweep_count")))
        tb = int(_sf(tape.get("block_count")))
        tb2 = tape.get("tape_bias","MIXED")
        sign = "+" if tn >= 0 else ""
        tt = (f"Flow tape: {tr} orders — {ts2} sweeps, {tb} blocks. "
              f"Net {sign}${abs(tn)/1e6:.1f}M. Bias: {tb2}.")
        if tn > 2_000_000: tt += " Aggressive call sweep activity."
        elif tn < -2_000_000: tt += " Aggressive put/sell sweep activity."
        tc = "#0ca30c" if tb2=="BULLISH" else "#e34948" if tb2=="BEARISH" else "#fab219"
        ch("Institutional Flow Tape", tt, tc, 2.7)

    # ── 6: Divergence / Absorption ──
    div_type = flow.get("divergence_type")
    div_desc = flow.get("divergence_description","")
    if div_type and div_desc:
        dd = flow.get("divergence_direction","")
        dlabel = f"{'A+' if div_type=='A_PLUS' else 'B'} Divergence"
        ch(dlabel, div_desc,
           "#e34948" if dd=="BEARISH" else "#0ca30c",
           3.5 if div_type=="A_PLUS" else 2.0)
    if flow.get("absorption") and flow.get("absorption_description"):
        ch("Absorption", flow["absorption_description"], "#fab219", 3.0)

    # ── 7: Market Structure ──
    sp = structure.get("structure_position") or []
    if sp:
        cp = structure.get("current_price")
        st = f"Price ({cp}) is " + "; ".join(str(x) for x in sp[:3]) + "."
        vwap = _sf(structure.get("vwap"))
        if poc > 0 and vwap > 0 and abs(poc - vwap) < 3.0:
            st += f" POC/VWAP confluent near {min(poc,vwap):.2f} — strong level."
        ch("Market Structure", st, "#2a78d6", 2.0)

    # ── 8: Trend ──
    td = trend.get("trend_direction","NEUTRAL")
    ts_ = _sf(trend.get("trend_score"),50.0)
    atr = trend.get("atr_regime","NORMAL")
    tt2 = f"Daily trend {td.lower()} (score {ts_:.0f}/100). EMA21 {trend.get('ema21_slope','FLAT').lower()}."
    if atr=="COMPRESSED": tt2 += " ATR compressed — breakout may be building."
    elif atr=="EXPANDING": tt2 += " ATR expanding — momentum active."
    ch("Trend", tt2,
       "#0ca30c" if td=="BULLISH" else "#e34948" if td=="BEARISH" else "#fab219", 1.8)

    # ── 9: Pine Execution ──
    es = execution.get("execution_state","WAITING_FOR_PINE")
    en = (execution.get("notes") or [])
    pt = en[0] if en else f"Pine state: {es.replace('_',' ')}."
    pc = ("#0ca30c" if "CONFIRMED" in es else "#e34948" if "REJECTED" in es else "#fab219")
    ch("Pine Execution", pt, pc, 3.0)

    # ── 10: Verdict ──
    nb = consensus.get("n_bullish",0)
    nbe = consensus.get("n_bearish",0)
    nt = consensus.get("n_engines",6)
    rec = consensus.get("recommendation","NO_TRADE")
    act = consensus.get("action","")
    cl = consensus.get("consensus_label","")
    vc = ("#0ca30c" if "ENTER" in rec and "NO_TRADE" not in rec else
          "#e34948" if "NO_TRADE" in rec or "BLOCKED" in rec else "#fab219")
    ch("Institutional Verdict", f"{cl}. {act}", vc, 4.0)

    chapters.sort(key=lambda c: c["significance"])

    # ── Executive summary ──
    contract = risk.get("contract_hint","")
    if "ENTER" in rec and contract:
        stop = risk.get("stop"); t1 = risk.get("target1"); t2 = risk.get("target2")
        summ = (f"{slabel}{cl} — {contract}: entry {risk.get('entry_zone','--')}, "
                f"stop {'$'+f'{stop:.2f}' if stop is not None else '--'}, "
                f"targets {'$'+f'{t1:.2f}' if t1 is not None else '--'} / "
                f"{'$'+f'{t2:.2f}' if t2 is not None else '--'}.")
    elif avail and poc > 0:
        pvp2 = "above" if price > poc else "below" if price < poc else "at"
        va2 = (" Outside value area." if (vah > 0 and (price > vah or price < val_))
               else " Inside value area." if vah > 0 else "")
        summ = (f"{slabel}Price {pvp2} POC ({poc:.2f}).{va2}"
                f" Migration: {mig.lower().replace('_',' ')}."
                f" {nb}/{nt} engines bullish, {nbe}/{nt} bearish.")
    elif div_type == "A_PLUS":
        summ = (f"{slabel}A+ {flow.get('divergence_direction','')} divergence — "
                f"{consensus.get('action','Do not trade against this signal.')}.")
    elif "WATCH" in rec:
        side = "calls" if "CALL" in rec else "puts"
        summ = (f"{slabel}{nb if 'CALL' in rec else nbe}/{nt} engines favor {side} — "
                f"wait for Pine confirmation.")
    else:
        summ = (f"{slabel}No consensus ({nb} bull/{nbe} bear). "
                f"Sit out until alignment improves.")

    return {
        "ticker":            ticker,
        "chapters":          chapters,
        "full_narrative":    " ".join(prose),
        "executive_summary": summ,
        "chapter_count":     len(chapters),
        "generated_at":      now.strftime("%Y-%m-%d %H:%M:%S ET"),
        "generated_at_iso":  dt.datetime.now(dt.timezone.utc).isoformat(),
        "engine":            "STORY_3.0",
        "has_auction_chapter": avail,
        "has_tape_chapter":  tr > 0,
    }


# Legacy re-export shim
try:
    from apex_engines import engine_story, build_story_timeline  # noqa: F401
except Exception:
    def engine_story(*a, **kw): return {}        # type: ignore[misc]
    def build_story_timeline(s): return []       # type: ignore[misc]
