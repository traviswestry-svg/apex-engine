"""engine/story.py — APEX 6.4.1 Story Engine 3.1

Produces institutional-grade narrative that reasons across inputs
simultaneously rather than describing each metric in sequence.

The output should read like an experienced trader explaining to a junior
trader what is happening right now and why it matters for the next trade.

Core principles:
  - Lead with WHAT IS HAPPENING, not what the numbers are
  - One clear insight per chapter, not a recitation of values
  - The executive summary must be tradeable in one read
  - If market is closed, say so and context-label everything
  - Never overstate certainty; hedge appropriately

Canonical input: the market_state dict from engine/market_state.py
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Any, Dict, List, Optional


# ── Helpers ─────────────────────────────────────────────────────────────────

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


def _fmt(v: float, decimals: int = 2) -> str:
    return f"{v:,.{decimals}f}"


def _prem(v: float) -> str:
    """Format dollar premium for narrative: $2.4M, $840K, $125K."""
    av = abs(v)
    if av >= 1_000_000:
        return f"${av/1_000_000:.1f}M"
    if av >= 1_000:
        return f"${av/1_000:.0f}K"
    return f"${av:.0f}"


# ── Chapter builders — each returns one sentence or None ─────────────────────

def _chapter_regime(ms: Dict[str, Any], gamma_regime: Dict[str, Any],
                    market_regime: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Gamma + market regime: what kind of day is this?"""
    g_regime = ms.get("gamma_regime", "MIXED")
    flip_risk = ms.get("flip_risk", False)
    flip_prox = ms.get("flip_proximity")
    g_display = gamma_regime.get("regime_display", "Mixed Gamma")
    vix = _sf(market_regime.get("vix"), 0.0)
    regime_key = str(market_regime.get("regime", "")).upper()
    regime_desc = market_regime.get("regime_description", "")

    # Build the insight: what does the gamma regime mean for how the day trades?
    if g_regime == "NEGATIVE" and not flip_risk:
        text = (
            f"Dealers are in negative gamma — they are forced to buy weakness "
            f"and sell strength, which amplifies moves in both directions. "
            f"Momentum trades work better than mean-reversion today."
        )
        color = "#e34948"
    elif g_regime == "POSITIVE" and not flip_risk:
        text = (
            f"Dealers are in positive gamma — they are hedging against the "
            f"market, which dampens volatility and pins price near key strikes. "
            f"Mean-reversion and range strategies are favored."
        )
        color = "#2a78d6"
    elif flip_risk and flip_prox is not None:
        text = (
            f"Price is within {_fmt(flip_prox)} points of the zero-gamma flip level. "
            f"A breach would shift dealer hedging from dampening to amplifying moves — "
            f"be prepared for a volatility expansion if the level breaks."
        )
        color = "#fab219"
    else:
        text = f"Gamma regime is mixed. {g_display}."
        color = "#fab219"

    # Add market regime context if notable
    if regime_key in ("HIGH_VOLATILITY", "DEFENSIVE") and vix > 20:
        text += f" VIX is elevated at {vix:.1f} — size down and widen stops."
    elif regime_key == "TREND_DAY":
        text += f" Market regime is trend-day — favor continuation over fade."

    return {"chapter": "Regime", "text": text, "color": color, "significance": 1.0, "category": "KNOWS"}


def _chapter_auction(ms: Dict[str, Any], auction_intel: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Auction / volume profile: what is the market accepting?"""
    if not ms.get("profile_available"):
        return {
            "chapter": "Auction",
            "text": "Volume profile is not yet available — session is too early to read auction context.",
            "color": "#475569",
            "significance": 2.0,
        }

    price  = _sf(ms.get("price"))
    poc    = _sf(ms.get("poc"))
    vah    = _sf(ms.get("vah"))
    val    = _sf(ms.get("val"))
    vwap   = _sf(ms.get("vwap"))
    mig    = ms.get("poc_migration", "UNKNOWN")
    poc_delta = _sf(ms.get("poc_delta"))
    pvp    = ms.get("price_vs_poc", "UNKNOWN")
    pva    = ms.get("price_vs_va",  "UNKNOWN")
    conf   = ms.get("poc_vwap_confluent", False)
    conf_level = ms.get("confluence_level")
    mins   = ms.get("minutes_open", 0)

    # Core read: where is price relative to value?
    if pva == "ABOVE_VAH" and mig == "RISING":
        core = (
            f"Price is trading above Value Area High ({_fmt(vah)}) with POC migrating "
            f"higher — buyers are accepting these levels as fair value. "
            f"This is a bullish auction in progress."
        )
        color = "#0ca30c"
    elif pva == "ABOVE_VAH" and mig != "RISING":
        core = (
            f"Price has broken above Value Area High ({_fmt(vah)}) but POC has not "
            f"yet migrated — this could be a probe or a breakout. "
            f"Watch whether price holds above VAH into the next 15 minutes."
        )
        color = "#fab219"
    elif pva == "BELOW_VAL" and mig == "FALLING":
        core = (
            f"Price is trading below Value Area Low ({_fmt(val)}) with POC migrating "
            f"lower — sellers are accepting these levels as fair value. "
            f"This is a bearish auction in progress."
        )
        color = "#e34948"
    elif pva == "BELOW_VAL" and mig != "FALLING":
        core = (
            f"Price has broken below Value Area Low ({_fmt(val)}) but POC has not "
            f"yet migrated lower — may be a probe that reverts. "
            f"A reclaim of VAL would be bullish; sustained break would be bearish."
        )
        color = "#fab219"
    elif pva == "INSIDE" and pvp == "ABOVE" and mig == "RISING":
        core = (
            f"Price is inside value and above POC ({_fmt(poc)}), with POC migrating "
            f"higher. Buyers are in control of the auction. "
            f"Value Area: {_fmt(val)}–{_fmt(vah)}."
        )
        color = "#0ca30c"
    elif pva == "INSIDE" and pvp == "BELOW" and mig == "FALLING":
        core = (
            f"Price is inside value and below POC ({_fmt(poc)}), with POC migrating "
            f"lower. Sellers are in control of the auction. "
            f"Value Area: {_fmt(val)}–{_fmt(vah)}."
        )
        color = "#e34948"
    elif pva == "INSIDE" and mig == "STABLE":
        core = (
            f"Price is balanced inside the Value Area ({_fmt(val)}–{_fmt(vah)}) "
            f"with POC stable at {_fmt(poc)}. The market is in equilibrium — "
            f"wait for a break of VAH or VAL before taking a directional position."
        )
        color = "#2a78d6"
    else:
        core = (
            f"Price ({_fmt(price)}) is {'above' if pvp == 'ABOVE' else 'below' if pvp == 'BELOW' else 'at'} "
            f"POC ({_fmt(poc)}). POC migration: {mig.lower().replace('_',' ')}. "
            f"Value area: {_fmt(val)}–{_fmt(vah)}."
        )
        color = "#fab219"

    # Add confluence note
    if conf and conf_level:
        core += (
            f" POC and VWAP are confluent near {_fmt(conf_level)} — "
            f"this level is the primary institutional reference."
        )

    # Enrich with auction intelligence if available
    if auction_intel and auction_intel.get("available"):
        ai_state = auction_intel.get("auction_state") or {}
        ai_excess = auction_intel.get("excess") or {}
        ai_hvbo = auction_intel.get("hvbo") or {}
        ai_acc = auction_intel.get("acceptance") or {}
        ai_poc = auction_intel.get("poc_migration") or {}

        state_name = ai_state.get("state", "")
        if state_name and state_name not in ("WAITING_FOR_PROFILE",):
            day_type = ai_state.get("day_type", "")
            participant = ai_state.get("participant_type", "")
            conf_score = ai_state.get("confidence", 0)
            would_trade = ai_state.get("would_trade", False)
            core += (
                f" Auction state: {state_name.replace('_',' ')} "
                f"({'initiative' if ai_state.get('is_initiative') else 'responsive' if ai_state.get('is_responsive') else 'balanced'} "
                f"participants, {conf_score}% confidence)."
            )
            if not would_trade:
                core += " Institutional traders would not participate here — wait for better structure."

        if ai_excess.get("detected"):
            core += f" ⚠ {ai_excess.get('type','').replace('_',' ')}: {ai_excess.get('narrative','')}"

        if ai_acc.get("primary_note"):
            core += f" {ai_acc['primary_note']}"

        if ai_poc.get("acceleration") == "ACCELERATING":
            core += " POC migration is accelerating — institutional urgency is rising."

    return {"chapter": "Auction", "text": core, "color": color, "significance": 2.0, "category": "KNOWS"}


def _chapter_flow(ms: Dict[str, Any], flow_intel: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Institutional flow intelligence: what are smart money doing?"""
    bias        = ms.get("flow_bias", "MIXED")
    net         = _sf(ms.get("net_premium"))
    sweeps      = ms.get("sweep_count", 0) or 0
    momentum    = ms.get("flow_momentum", "STABLE")
    div_type    = ms.get("divergence_type")
    div_dir     = flow_intel.get("divergence_direction", "")
    div_desc    = flow_intel.get("divergence_description", "")
    flow_flip   = flow_intel.get("flow_flip", False)
    flip_dir    = flow_intel.get("flow_flip_direction", "")
    absorption  = flow_intel.get("absorption", False)
    absorb_desc = flow_intel.get("absorption_description", "")

    # A+ divergence is the highest-priority signal — lead with it
    if div_type == "A_PLUS" and div_dir:
        text = (
            f"A+ {div_dir.lower()} divergence detected. {div_desc} "
            f"This is a high-conviction institutional signal — do not trade against it."
        )
        color = "#e34948" if div_dir == "BEARISH" else "#0ca30c"
        return {"chapter": "Flow Intelligence", "text": text, "color": color, "significance": 3.5, "category": "KNOWS"}

    # Flow flip is the next priority
    if flow_flip and flip_dir:
        text = (
            f"Institutional flow just flipped {flip_dir.lower()} — "
            f"a meaningful change in smart money positioning. "
            f"Net premium is {'positive' if net > 0 else 'negative'} at {_prem(net)}."
        )
        color = "#0ca30c" if "BULL" in flip_dir.upper() else "#e34948"
        return {"chapter": "Flow Intelligence", "text": text, "color": color, "significance": 3.0, "category": "KNOWS"}

    # Absorption
    if absorption and absorb_desc:
        text = absorb_desc
        return {"chapter": "Flow Intelligence", "text": text, "color": "#fab219", "significance": 2.8, "category": "KNOWS"}

    # Standard flow read
    if abs(net) > 2_000_000:
        direction = "Aggressive institutional buying" if net > 0 else "Aggressive institutional selling"
        text = (
            f"{direction} — net premium {_prem(net)} with {sweeps} sweeps. "
            f"Flow bias is {bias.lower()}."
        )
    elif abs(net) > 500_000:
        text = (
            f"Moderate {bias.lower()} flow — net premium {_prem(net)}, "
            f"{sweeps} sweeps. Momentum: {momentum.lower().replace('_',' ')}."
        )
    else:
        text = (
            f"Flow is {bias.lower()} and light — net premium {_prem(net)}. "
            f"No strong institutional conviction yet."
        )

    color = "#0ca30c" if bias == "BULLISH" else "#e34948" if bias == "BEARISH" else "#fab219"
    return {"chapter": "Flow Intelligence", "text": text, "color": color, "significance": 2.5, "category": "KNOWS"}


def _chapter_tape(ms: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Institutional flow tape: what is the sweep tape showing right now?"""
    tape_bias   = ms.get("tape_bias", "MIXED")
    tape_net    = _sf(ms.get("tape_net"))
    tape_sweeps = ms.get("tape_sweeps", 0) or 0
    tape_blocks = ms.get("tape_blocks", 0) or 0

    if tape_sweeps == 0 and tape_blocks == 0:
        return None  # No tape data — skip chapter

    total_orders = tape_sweeps + tape_blocks
    if tape_sweeps > 0 and tape_net > 1_000_000:
        text = (
            f"The sweep tape is showing {tape_sweeps} call sweep{'s' if tape_sweeps != 1 else ''} "
            f"with {_prem(tape_net)} net buy premium — institutions are paying the ask. "
            f"This confirms the bullish bias in flow intelligence."
        )
        color = "#0ca30c"
    elif tape_sweeps > 0 and tape_net < -1_000_000:
        text = (
            f"The sweep tape is showing {tape_sweeps} put sweep{'s' if tape_sweeps != 1 else ''} "
            f"with {_prem(abs(tape_net))} net sell premium — institutions are hitting the bid. "
            f"This confirms the bearish bias in flow intelligence."
        )
        color = "#e34948"
    elif tape_blocks > 0 and abs(tape_net) > 500_000:
        direction = "bullish" if tape_net > 0 else "bearish"
        text = (
            f"{tape_blocks} large block trade{'s' if tape_blocks != 1 else ''} on tape "
            f"with {_prem(abs(tape_net))} net {direction} premium. "
            f"Blocks suggest positioning rather than urgency."
        )
        color = "#0ca30c" if tape_net > 0 else "#e34948"
    else:
        text = (
            f"Flow tape has {total_orders} institutional order{'s' if total_orders != 1 else ''} "
            f"({tape_sweeps} sweep{'s' if tape_sweeps != 1 else ''}, {tape_blocks} block{'s' if tape_blocks != 1 else ''}) "
            f"with mixed directionality."
        )
        color = "#fab219"

    return {"chapter": "Flow Tape", "category": "KNOWS", "text": text, "color": color, "significance": 2.7}


def _chapter_execution(ms: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Pine execution state: what is the signal telling us?"""
    pine    = ms.get("pine_state", "WAITING")
    fresh   = ms.get("signal_fresh", False)
    secs    = ms.get("signal_secs", 0) or 0
    matches = ms.get("signal_matches", False)
    side    = ms.get("approved_side", "NONE")
    decision= ms.get("decision_state", "NO_TRADE")

    if pine == "CONFIRMED" and fresh and matches:
        mins = secs // 60
        secs_rem = secs % 60
        time_str = f"{mins}m {secs_rem}s" if mins > 0 else f"{secs_rem}s"
        text = (
            f"Pine has confirmed a {side.lower()} signal that aligns with "
            f"institutional flow. Signal expires in {time_str}. "
            f"APEX is ready to upgrade to ENTER_{side} if all gates are clear."
        )
        color = "#0ca30c"
    elif pine == "CONFIRMED" and not matches:
        text = (
            f"Pine signal is confirmed but does not align with the current "
            f"institutional flow bias. APEX will not enter against the flow — "
            f"waiting for signal and flow to align."
        )
        color = "#fab219"
    elif pine == "EXPIRED" or (pine == "WAITING" and "WATCH" in decision):
        text = (
            f"Pine confirmation is missing. APEX is in {decision.replace('_',' ')} "
            f"— all conditions are aligned except for the execution trigger. "
            f"Wait for a fresh Pine signal before entering."
        )
        color = "#fab219"
    else:
        text = (
            f"No Pine signal active. APEX is watching but will not enter "
            f"until Pine confirms and flow aligns."
        )
        color = "#475569"

    return {"chapter": "Pine Execution", "text": text, "color": color, "significance": 3.0, "category": "KNOWS"}


def _chapter_verdict(
    ms: Dict[str, Any],
    consensus: Dict[str, Any],
    risk: Dict[str, Any],
) -> Dict[str, Any]:
    """Verdict: the single most important thing to know right now."""
    decision    = ms.get("decision_state", "NO_TRADE")
    ici         = ms.get("ici", 0.0)
    side        = ms.get("approved_side", "NONE")
    pine        = ms.get("pine_state", "WAITING")
    poc         = ms.get("poc")
    vwap        = ms.get("vwap")
    pva         = ms.get("price_vs_va", "UNKNOWN")
    mig         = ms.get("poc_migration", "UNKNOWN")
    tape_bias   = ms.get("tape_bias", "MIXED")
    flow_bias   = ms.get("flow_bias", "MIXED")
    is_tradeable= ms.get("is_tradeable", False)
    n_bull      = consensus.get("n_bullish", 0)
    n_bear      = consensus.get("n_bearish", 0)
    n_total     = consensus.get("n_engines", 6)

    # Entry signals
    if decision in ("ENTER_CALL", "ENTER_PUT"):
        entry = risk.get("entry_zone", "--")
        stop  = risk.get("stop")
        t1    = risk.get("target1")
        t2    = risk.get("target2")
        contract = risk.get("contract_hint", "")
        stop_str = f"${_fmt(stop)}" if stop is not None else "see risk plan"
        t1_str   = f"${_fmt(t1)}"  if t1   is not None else "--"
        t2_str   = f"${_fmt(t2)}"  if t2   is not None else "--"
        text = (
            f"APEX is signaling ENTER {side}. {contract}. "
            f"Entry: {entry}. Stop: {stop_str}. T1: {t1_str}, T2: {t2_str}. "
            f"ICI: {ici:.0f}. {n_bull if side=='CALL' else n_bear} of {n_total} engines agree."
        )
        color = "#0ca30c"

    # High-conviction watch states
    elif "WATCH" in decision:
        side_label = "calls" if "CALL" in decision else "puts"
        poc_note = f" Price is {'above' if ms.get('price_vs_poc')=='ABOVE' else 'below'} POC ({_fmt(poc)})." if poc else ""
        pine_note = " Waiting for Pine confirmation to enter." if pine == "WAITING" else ""
        text = (
            f"APEX is in {decision.replace('_',' ')} — conditions favor {side_label} "
            f"but not all gates are clear.{poc_note}{pine_note}"
        )
        color = "#fab219"

    # Ready (all aligned except execution)
    elif decision == "READY":
        text = (
            f"Setup is ready for {side.lower()}s — {n_bull if side=='CALL' else n_bear} of {n_total} engines aligned. "
            f"Waiting for a fresh Pine confirmation. "
            f"Do not front-run the signal."
        )
        color = "#fab219"

    # No trade
    else:
        if not is_tradeable:
            text = "Market is closed. This is a pre-session or after-hours read — no live trading."
            color = "#475569"
        elif n_bull == n_bear:
            text = (
                f"No institutional consensus — {n_bull} engines bullish, {n_bear} bearish. "
                f"Sit out until the market shows its hand."
            )
            color = "#e34948"
        else:
            dominant = "bullish" if n_bull > n_bear else "bearish"
            weak_side = n_bear if n_bull > n_bear else n_bull
            text = (
                f"Weak {dominant} lean ({n_bull} bull / {n_bear} bear / "
                f"{n_total - n_bull - n_bear} neutral) — not enough to act on. "
                f"Wait for stronger alignment before entering."
            )
            color = "#fab219"

    return {"chapter": "Verdict", "category": "RECOMMENDS", "text": text, "color": color, "significance": 4.0}


# ── Executive summary builder ────────────────────────────────────────────────

def _executive_summary(
    ms: Dict[str, Any],
    consensus: Dict[str, Any],
    risk: Dict[str, Any],
    flow_intel: Dict[str, Any],
) -> str:
    """One paragraph a trader can act from.

    Synthesizes auction location, tape signal, gamma context, and decision state
    into a coherent read — not a list of metrics.
    """
    decision     = ms.get("decision_state", "NO_TRADE")
    side         = ms.get("approved_side", "NONE")
    ici          = ms.get("ici", 0.0)
    poc          = ms.get("poc")
    vwap         = ms.get("vwap")
    pva          = ms.get("price_vs_va", "UNKNOWN")
    pvp          = ms.get("price_vs_poc", "UNKNOWN")
    mig          = ms.get("poc_migration", "UNKNOWN")
    conf         = ms.get("poc_vwap_confluent", False)
    conf_level   = ms.get("confluence_level")
    tape_bias    = ms.get("tape_bias", "MIXED")
    tape_sweeps  = ms.get("tape_sweeps", 0) or 0
    flow_bias    = ms.get("flow_bias", "MIXED")
    g_regime     = ms.get("gamma_regime", "MIXED")
    flip_risk    = ms.get("flip_risk", False)
    pine         = ms.get("pine_state", "WAITING")
    secs         = ms.get("signal_secs", 0) or 0
    session_state= ms.get("session_state", "MARKET_OPEN")
    is_tradeable = ms.get("is_tradeable", False)
    div_type     = ms.get("divergence_type")
    n_bull       = consensus.get("n_bullish", 0)
    n_bear       = consensus.get("n_bearish", 0)
    n_total      = consensus.get("n_engines", 6)

    # Session label prefix
    if not is_tradeable:
        prefix = {"PREMARKET": "[PRE-MARKET] ", "AFTER_HOURS": "[AFTER-HOURS] ",
                  "CLOSED": "[CLOSED] "}.get(session_state, "[CLOSED] ")
    else:
        prefix = ""

    # A+ divergence — always leads
    if div_type == "A_PLUS":
        div_dir  = flow_intel.get("divergence_direction", "")
        div_desc = flow_intel.get("divergence_description", "")
        return (
            f"{prefix}A+ {div_dir.lower()} divergence is active. {div_desc} "
            f"This is a high-conviction institutional signal. "
            f"{'Do not take ' + ('call' if div_dir == 'BEARISH' else 'put') + ' positions against it.' if decision == 'NO_TRADE' else decision.replace('_',' ') + ' — follow the signal.'}"
        )

    # Entry signal — full trade plan
    if decision in ("ENTER_CALL", "ENTER_PUT"):
        contract = risk.get("contract_hint", "")
        entry    = risk.get("entry_zone", "--")
        stop     = risk.get("stop")
        t1       = risk.get("target1")
        t2       = risk.get("target2")

        # Build the context sentence
        parts = []
        if poc and pvp != "UNKNOWN":
            poc_str = f"above POC ({_fmt(poc)})" if pvp == "ABOVE" else f"below POC ({_fmt(poc)})"
            if mig == "RISING" and pvp == "ABOVE":
                parts.append(f"Price is {poc_str} with POC migrating higher — buyers are accepting these prices")
            elif mig == "FALLING" and pvp == "BELOW":
                parts.append(f"Price is {poc_str} with POC migrating lower — sellers are in control")
            else:
                parts.append(f"Price is {poc_str}")
        if conf and conf_level:
            parts.append(f"VWAP and POC confluent near {_fmt(conf_level)}")
        if tape_sweeps > 0 and tape_bias in ("BULLISH", "BEARISH"):
            tape_word = "call" if tape_bias == "BULLISH" else "put"
            parts.append(f"{tape_sweeps} {tape_word} sweep{'s' if tape_sweeps != 1 else ''} on tape")
        if g_regime == "NEGATIVE":
            parts.append("negative gamma amplifies momentum")

        context = ". ".join(p.capitalize() for p in parts) + "." if parts else ""

        stop_str = f"${_fmt(stop)}" if stop is not None else "see risk plan"
        t1_str   = f"${_fmt(t1)}"  if t1   is not None else "--"
        t2_str   = f"${_fmt(t2)}"  if t2   is not None else "--"
        pine_str = f" Pine confirmed ({secs//60}m {secs%60}s remaining)." if pine == "CONFIRMED" and secs > 0 else ""

        return (
            f"{prefix}{context}{pine_str} "
            f"APEX is signaling ENTER {side} — {contract}. "
            f"Entry: {entry}. Stop: {stop_str}. T1: {t1_str}, T2: {t2_str}. "
            f"ICI: {ici:.0f}."
        ).strip()

    # Watch / Ready states — explain what's waiting
    if "WATCH" in decision or decision == "READY":
        side_label = "calls" if "CALL" in decision or side == "CALL" else "puts"

        # Explain the current auction context
        auction_context = ""
        if poc and pva != "UNKNOWN":
            if pva == "ABOVE_VAH" and mig == "RISING":
                auction_context = f"Buyers are accepting prices above VAH ({_fmt(ms.get('vah',0))}) with POC migrating higher. "
            elif pva == "INSIDE" and pvp == "ABOVE" and mig == "RISING":
                auction_context = f"Price is above POC ({_fmt(poc)}) inside value with migration rising. "
            elif pva == "BELOW_VAL" and mig == "FALLING":
                auction_context = f"Sellers are accepting prices below VAL ({_fmt(ms.get('val',0))}) with POC migrating lower. "
            elif pva == "INSIDE" and mig == "STABLE":
                auction_context = f"Price is inside balanced value ({_fmt(ms.get('val',0))}–{_fmt(ms.get('vah',0))}). "

        # Tape context
        tape_context = ""
        if tape_sweeps > 0 and tape_bias != "MIXED":
            tape_word = "call sweep" if tape_bias == "BULLISH" else "put sweep"
            tape_context = f"QuantData tape shows {tape_sweeps} {tape_word}{'s' if tape_sweeps != 1 else ''} confirming {tape_bias.lower()} bias. "

        # What's missing
        if pine == "WAITING":
            blocker = f"APEX is in {decision.replace('_',' ')} — waiting for Pine confirmation before entering {side_label}."
        else:
            blocker = f"APEX is in {decision.replace('_',' ')} — {n_bull if 'CALL' in decision else n_bear} of {n_total} engines aligned."

        return f"{prefix}{auction_context}{tape_context}{blocker}".strip()

    # No trade — be specific about why
    if not is_tradeable:
        return f"{prefix}Market is closed. Review only — no live trading signals."

    if n_bull == n_bear:
        return (
            f"{prefix}No institutional consensus — {n_bull} engines bullish, "
            f"{n_bear} bearish, {n_total - n_bull - n_bear} neutral. "
            f"Sit out until the market shows a clear direction."
        )

    dominant     = "bullish" if n_bull > n_bear else "bearish"
    dominant_n   = n_bull if n_bull > n_bear else n_bear
    return (
        f"{prefix}Weak {dominant} lean ({dominant_n} of {n_total} engines). "
        f"Conditions are not clean enough to enter — wait for stronger alignment "
        f"across flow, auction, gamma, and Pine before taking a position."
    )


# ── Public API ───────────────────────────────────────────────────────────────

def build_story_v3(
    *,
    ticker: str,
    market_regime: Dict[str, Any],
    gamma_regime:  Dict[str, Any],
    flow:          Dict[str, Any],
    structure:     Dict[str, Any],
    trend:         Dict[str, Any],
    execution:     Dict[str, Any],
    consensus:     Dict[str, Any],
    risk:          Dict[str, Any],
    auction:       Optional[Dict[str, Any]] = None,
    volume_profile:Optional[Dict[str, Any]] = None,
    flow_tape_summary: Optional[Dict[str, Any]] = None,
    session_state: str = "MARKET_OPEN",
    # 6.4.1: canonical market state preferred over individual args
    market_state:  Optional[Dict[str, Any]] = None,
    auction_intel: Optional[Dict[str, Any]] = None,
    # 7.0: institutional intelligence canonical object
    institutional_intelligence: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Story Engine 3.1 — reasoning prose, not metric descriptions.

    Accepts either:
    - market_state (canonical dict from engine/market_state.py) — preferred
    - Individual engine output dicts — legacy compat path
    """
    now = _now_et()

    # ── Build a local market-state-like view if canonical not provided ──
    if market_state is not None:
        ms = market_state
    else:
        # Lightweight compat shim — build a minimal ms from legacy args
        vp  = (volume_profile or {})
        au  = (auction or {})
        vpl = (vp.get("levels") or {}) if isinstance(vp, dict) else {}
        tape = flow_tape_summary or {}
        poc  = _sf(vpl.get("poc") or au.get("poc") or structure.get("session_poc"))
        vah  = _sf(vpl.get("vah") or au.get("vah"))
        val_ = _sf(vpl.get("val") or au.get("val"))
        vwap = _sf(structure.get("vwap"))
        price= _sf(structure.get("current_price") or au.get("current_price"))
        mig  = au.get("poc_migration","UNKNOWN")

        from engine.market_state import _price_vs_poc, _price_vs_va, _poc_vwap_confluent
        pvp = _price_vs_poc(price, poc)
        pva = _price_vs_va(price, vah, val_)
        conf= _poc_vwap_confluent(poc, vwap)
        g_label = str(gamma_regime.get("regime_label","")).upper()
        g_reg = "POSITIVE" if "POSITIVE" in g_label else "NEGATIVE" if "NEGATIVE" in g_label else "MIXED"

        exec_state = str(execution.get("execution_state","")).upper()
        pine_st = "CONFIRMED" if "CONFIRMED" in exec_state else "WAITING"

        ms = {
            "ticker": ticker,
            "price": price, "vwap": vwap, "poc": poc, "vah": vah, "val": val_,
            "poc_migration": mig, "auction_state": au.get("auction_state",""),
            "profile_available": bool((vp.get("available") if vp else False) or (au.get("available"))),
            "poc_vwap_confluent": conf,
            "confluence_level": round((poc+vwap)/2,2) if conf and poc and vwap else None,
            "price_vs_poc": pvp, "price_vs_va": pva,
            "call_wall": gamma_regime.get("call_wall"), "put_wall": gamma_regime.get("put_wall"),
            "gamma_regime": g_reg, "flip_risk": bool(gamma_regime.get("flip_risk")),
            "flip_proximity": None,
            "flow_bias": flow.get("bias","MIXED"),
            "net_premium": _sf(flow.get("net_premium")),
            "sweep_count": int(_sf(flow.get("sweep_count"))),
            "flow_momentum": flow.get("flow_momentum","STABLE"),
            "divergence_type": flow.get("divergence_type"),
            "tape_bias": tape.get("tape_bias","MIXED"),
            "tape_net": _sf(tape.get("net_premium")),
            "tape_sweeps": int(_sf(tape.get("sweep_count"))),
            "tape_blocks": int(_sf(tape.get("block_count"))),
            "pine_state": pine_st,
            "signal_fresh": bool(execution.get("signal_fresh")),
            "signal_secs": int(_sf(execution.get("signal_seconds_remaining"))),
            "signal_matches": bool(execution.get("signal_matches_flow")),
            "ici": _sf(consensus.get("leading_conviction",0)),
            "decision_state": "",
            "approved_side": risk.get("approved_side","NONE"),
            "session_state": session_state,
            "is_tradeable": session_state == "MARKET_OPEN",
            "minutes_open": 0,
            "poc_delta": _sf(au.get("poc_delta")),
            "entry_zone": risk.get("entry_zone"),
            "stop": risk.get("stop"), "target1": risk.get("target1"), "target2": risk.get("target2"),
            "contract_hint": risk.get("contract_hint"),
        }

    ts = now.strftime("%H:%M")
    chapters: List[Dict[str, Any]] = []

    # ── Build chapters ──
    def add(ch: Optional[Dict[str, Any]]) -> None:
        if ch:
            ch["time"] = ts
            chapters.append(ch)

    # APEX 7.0: institutional intelligence chapters (if available)
    _ii = institutional_intelligence if isinstance(institutional_intelligence, dict) else None
    if _ii:
        add(_chapter_market_drivers(_ii))
        add(_chapter_dealer_institutional(_ii))
        add(_chapter_strike_magnets(_ii))

    add(_chapter_regime(ms, gamma_regime, market_regime))
    add(_chapter_auction(ms, auction_intel=auction_intel))
    add(_chapter_flow(ms, flow))
    add(_chapter_tape(ms))
    add(_chapter_execution(ms))
    add(_chapter_verdict(ms, consensus, risk))

    # Optional: trend context (low significance, added if non-neutral)
    trend_dir   = trend.get("trend_direction", "NEUTRAL")
    trend_score = _sf(trend.get("trend_score"), 50.0)
    atr_regime  = trend.get("atr_regime", "NORMAL")
    if trend_dir != "NEUTRAL" or atr_regime != "NORMAL":
        if atr_regime == "COMPRESSED":
            trend_text = f"Daily trend is {trend_dir.lower()} (score {trend_score:.0f}). ATR is compressed — a breakout expansion may be building."
        elif atr_regime == "EXPANDING":
            trend_text = f"Daily trend is {trend_dir.lower()} (score {trend_score:.0f}). ATR is expanding — momentum is active."
        else:
            trend_text = f"Daily trend is {trend_dir.lower()} (score {trend_score:.0f}/100)."
        tc = "#0ca30c" if trend_dir=="BULLISH" else "#e34948" if trend_dir=="BEARISH" else "#fab219"
        chapters.append({"time": ts, "chapter": "Daily Trend", "text": trend_text, "color": tc, "significance": 1.3})

    chapters.sort(key=lambda c: c["significance"])

    exec_summary = _executive_summary(ms, consensus, risk, flow)
    full_narrative = " ".join(c["text"] for c in sorted(chapters, key=lambda x: x["significance"]))

    knows_chs = [c for c in chapters if c.get("category") != "RECOMMENDS"]
    rec_chs   = [c for c in chapters if c.get("category") == "RECOMMENDS"]

    return {
        "ticker":            ticker,
        "chapters":          chapters,
        "knows_chapters":    knows_chs,
        "recommends_chapters": rec_chs,
        "full_narrative":    full_narrative,
        "executive_summary": exec_summary,
        "chapter_count":     len(chapters),
        "generated_at":      now.strftime("%Y-%m-%d %H:%M:%S ET"),
        "generated_at_iso":  dt.datetime.now(dt.timezone.utc).isoformat(),
        "engine":            "STORY_3.1",
        "has_auction_chapter": ms.get("profile_available", False),
        "has_tape_chapter":    (ms.get("tape_sweeps", 0) or 0) + (ms.get("tape_blocks", 0) or 0) > 0,
    }


# ── Legacy shim ──────────────────────────────────────────────────────────────
try:
    from apex_engines import engine_story, build_story_timeline  # noqa: F401
except Exception:
    def engine_story(*a, **kw): return {}        # type: ignore[misc]
    def build_story_timeline(s): return []       # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════════════
# APEX 7.0 — NEW CHAPTERS
# ═══════════════════════════════════════════════════════════════════════════

def _chapter_market_drivers(ii: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Chapter: SPX Market Drivers — what is actually moving the index."""
    if not ii:
        return None
    md = ii.get("market_driver_story") or ""
    lead = ii.get("market_driver_leadership") or ""
    breadth = ii.get("market_driver_breadth") or ""
    bias = ii.get("market_driver_bias_raw") or "MIXED"
    if not md and not lead:
        return None

    color = "#22c55e" if bias == "BULLISH" else "#ef4444" if bias == "BEARISH" else "#94a3b8"

    # Breadth context
    breadth_note = ""
    if breadth == "NARROW_BULLISH":
        breadth_note = " However, participation is narrow — a few large caps are driving the index while the broader market lags."
    elif breadth == "BROAD_BULLISH":
        breadth_note = " Participation is broad — multiple sectors and constituents are contributing."
    elif breadth == "NARROW_BEARISH":
        breadth_note = " The weakness is concentrated in a few key names rather than broad deterioration."

    text = f"{md}{breadth_note}" if md else f"{lead} theme is leading. Breadth: {breadth.lower().replace('_', ' ')}."

    return {
        "chapter":      "SPX Market Drivers",
        "text":         text,
        "color":        color,
        "significance": 1.5,
        "category":     "KNOWS",
        "time":         _now_et().strftime("%H:%M ET"),
    }


def _chapter_dealer_institutional(ii: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Chapter: Dealer Positioning — what dealers are doing and why."""
    if not ii:
        return None
    gr     = ii.get("gamma_regime") or "NEUTRAL_GAMMA"
    db     = ii.get("delta_bias") or "NEUTRAL"
    pin    = ii.get("pin_probability") or 0
    mom    = ii.get("momentum_probability") or 50
    vol    = ii.get("vol_regime") or "NORMAL"
    dr_bias = ii.get("dealer_bias") or ""

    # Write like an institutional strategist
    gamma_line = (
        "Dealers remain in negative gamma — they must buy strength and sell weakness, amplifying directional moves." if gr == "NEGATIVE_GAMMA"
        else "Dealers are in positive gamma — they fade extremes, suppressing volatility and creating mean-reversion conditions." if gr == "POSITIVE_GAMMA"
        else "Dealers are approximately gamma-neutral with no strong directional amplification."
    )
    delta_line = (
        " Estimated delta hedging pressure is to the buy side — dealer futures buying provides structural support." if db == "BUYING"
        else " Estimated delta hedging pressure is to the sell side — dealer futures selling creates overhead resistance." if db == "SELLING"
        else " Delta hedging is approximately balanced."
    )
    pin_line = (
        f" Pin probability is {pin:.0f}% — expiration gravity may limit directional range into close." if pin >= 50
        else f" Pin probability is {pin:.0f}% — price is free to trade directionally." if pin < 30
        else f" Moderate pin probability ({pin:.0f}%) — watch for gravitational pull toward high-OI strikes."
    )
    mom_line = (
        f" Momentum probability is {mom:.0f}% — trend continuation is the highest-probability scenario." if mom >= 70
        else f" Momentum probability is {mom:.0f}% — wait for additional confirmation before trend entries."
    )

    text = gamma_line + delta_line + pin_line + mom_line
    color = "#22c55e" if db == "BUYING" else "#ef4444" if db == "SELLING" else "#94a3b8"

    return {
        "chapter":      "Dealer Positioning",
        "text":         text,
        "color":        color,
        "significance": 1.8,
        "category":     "KNOWS",
        "time":         _now_et().strftime("%H:%M ET"),
    }


def _chapter_strike_magnets(ii: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Chapter: Options Chain + Strike Magnets."""
    if not ii:
        return None
    pin_risk = ii.get("pin_risk") or "LOW"
    nearest  = ii.get("nearest_magnet")
    watch    = ii.get("strike_magnet_watch") or ""
    if not watch and not nearest:
        return None

    color = "#f59e0b" if pin_risk == "HIGH" else "#94a3b8"
    text  = watch or f"Nearest magnet strike: {nearest:.2f}. Pin risk: {pin_risk.lower()}."

    return {
        "chapter":      "Strike Magnets",
        "text":         text,
        "color":        color,
        "significance": 2.2,
        "category":     "KNOWS",
        "time":         _now_et().strftime("%H:%M ET"),
    }
