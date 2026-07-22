"""APEX Trade Director Phase 18 — Institutional Flow Intelligence.

Cached-only interpretation of normalized option-flow and market-microstructure
signals. The engine never contacts providers or brokers, starts no workers, and
fails closed when evidence is insufficient. It interprets—not fabricates—flow.
"""
from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _f(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def _text(value: Any) -> str:
    return str(value or "").strip()


def _upper(value: Any) -> str:
    return _text(value).upper().replace(" ", "_")


def _direction(value: Any) -> str:
    text = _upper(value)
    if any(x in text for x in ("BULL", "CALL", "UP", "BUY", "ASK", "LONG", "RISK_ON")):
        return "BULLISH"
    if any(x in text for x in ("BEAR", "PUT", "DOWN", "SELL", "BID", "SHORT", "RISK_OFF")):
        return "BEARISH"
    if any(x in text for x in ("NEUTRAL", "MIXED", "BALANCED", "FLAT", "CHOP")):
        return "NEUTRAL"
    return "UNAVAILABLE"


def _event_type(value: Any) -> str:
    text = _upper(value)
    if "SWEEP" in text: return "SWEEP"
    if "BLOCK" in text: return "BLOCK"
    if "SPLIT" in text: return "SPLIT"
    if "TRADE" in text or "PRINT" in text: return "TRADE"
    return "UNKNOWN"


def _side(row: Mapping[str, Any]) -> str:
    cp = _upper(row.get("option_type") or row.get("put_call") or row.get("side") or row.get("contract_type"))
    if cp in ("C", "CALL", "CALLS") or "CALL" in cp: return "CALL"
    if cp in ("P", "PUT", "PUTS") or "PUT" in cp: return "PUT"
    symbol = _upper(row.get("symbol") or row.get("contract") or row.get("option_symbol"))
    if "CALL" in symbol: return "CALL"
    if "PUT" in symbol: return "PUT"
    return "UNKNOWN"


def _aggressor(row: Mapping[str, Any]) -> str:
    direct = _upper(row.get("aggressor") or row.get("execution_side") or row.get("trade_side"))
    if any(x in direct for x in ("ASK", "BUY", "BOUGHT", "LIFT")): return "ASK"
    if any(x in direct for x in ("BID", "SELL", "SOLD", "HIT")): return "BID"
    price, bid, ask = _f(row.get("price") or row.get("fill_price")), _f(row.get("bid")), _f(row.get("ask"))
    if price and ask and price >= ask * 0.995: return "ASK"
    if price and bid and price <= bid * 1.005: return "BID"
    return "MID"


def _intent(side: str, aggressor: str) -> str:
    if side == "CALL" and aggressor == "ASK": return "BULLISH"
    if side == "PUT" and aggressor == "ASK": return "BEARISH"
    if side == "CALL" and aggressor == "BID": return "BEARISH"
    if side == "PUT" and aggressor == "BID": return "BULLISH"
    return "NEUTRAL"


def _normalize_event(row: Mapping[str, Any], index: int) -> Dict[str, Any]:
    side = _side(row)
    aggressor = _aggressor(row)
    premium = _f(row.get("premium") or row.get("notional") or row.get("dollar_value"))
    if not premium:
        premium = _f(row.get("price") or row.get("fill_price")) * _f(row.get("size") or row.get("quantity") or row.get("contracts")) * 100
    size = int(max(0, _f(row.get("size") or row.get("quantity") or row.get("contracts"))))
    strike = _f(row.get("strike"), 0) or None
    expiration = _text(row.get("expiration") or row.get("expiry") or row.get("expiration_date")) or None
    etype = _event_type(row.get("type") or row.get("trade_type") or row.get("kind") or row.get("condition"))
    opening = _upper(row.get("position_effect") or row.get("open_close") or row.get("intent"))
    opening_state = "OPENING" if "OPEN" in opening else "CLOSING" if "CLOS" in opening else "UNKNOWN"
    intent = _intent(side, aggressor)
    quality = 0.0
    quality += min(35.0, math.log10(max(1.0, premium)) * 5.5)
    quality += {"SWEEP": 28, "BLOCK": 22, "SPLIT": 16, "TRADE": 10}.get(etype, 4)
    quality += 15 if aggressor in ("ASK", "BID") else 4
    quality += 12 if opening_state == "OPENING" else 5 if opening_state == "UNKNOWN" else 0
    quality += min(10.0, size / 100.0)
    return {
        "event_id": _text(row.get("id") or row.get("event_id") or f"FLOW-{index+1}"),
        "timestamp": _text(row.get("timestamp") or row.get("time") or row.get("executed_at")) or None,
        "symbol": _text(row.get("symbol") or row.get("contract") or row.get("option_symbol")),
        "event_type": etype,
        "side": side,
        "aggressor": aggressor,
        "intent": intent,
        "opening_state": opening_state,
        "premium": round(premium, 2),
        "size": size,
        "strike": strike,
        "expiration": expiration,
        "quality_score": round(min(100.0, quality), 1),
        "source": _text(row.get("source") or "CACHED_APEX"),
    }


def _collect_events(source: Any) -> List[Mapping[str, Any]]:
    rows: List[Mapping[str, Any]] = []
    seen = set()
    flow_keys = {"flow", "flow_tape", "options_flow", "unusual_activity", "trades", "prints", "events", "sweeps", "blocks", "splits"}

    def visit(node: Any, in_flow: bool = False) -> None:
        if isinstance(node, Mapping):
            looks_like_event = any(k in node for k in ("premium", "notional", "option_type", "put_call", "trade_type", "aggressor")) and any(k in node for k in ("size", "quantity", "contracts", "price", "fill_price"))
            if in_flow and looks_like_event:
                marker = (id(node), _text(node.get("id") or node.get("event_id")))
                if marker not in seen:
                    rows.append(node); seen.add(marker)
            for key, value in node.items():
                child_flow = in_flow or _upper(key).lower() in flow_keys or any(x in _upper(key) for x in ("FLOW", "SWEEP", "BLOCK", "SPLIT"))
                if isinstance(value, (Mapping, list, tuple)):
                    visit(value, child_flow)
        elif isinstance(node, (list, tuple)):
            for item in node:
                visit(item, in_flow)

    visit(source, True)
    return rows


def _cluster(events: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    groups: Dict[Tuple[Any, ...], List[Mapping[str, Any]]] = defaultdict(list)
    for e in events:
        key = (e.get("side"), e.get("expiration"), e.get("strike"), e.get("intent"))
        groups[key].append(e)
    clusters = []
    for key, members in groups.items():
        premium = sum(_f(x.get("premium")) for x in members)
        quality = sum(_f(x.get("quality_score")) * max(1.0, _f(x.get("premium"))) for x in members) / max(1.0, premium)
        clusters.append({
            "side": key[0], "expiration": key[1], "strike": key[2], "intent": key[3],
            "event_count": len(members), "premium": round(premium, 2),
            "quality_score": round(min(100.0, quality), 1),
            "dominant_type": max((x.get("event_type") for x in members), key=lambda t: sum(1 for m in members if m.get("event_type") == t)),
        })
    return sorted(clusters, key=lambda x: (x["premium"], x["quality_score"]), reverse=True)[:12]


def _dealer_context(context: Mapping[str, Any]) -> Dict[str, Any]:
    dealer = context.get("dealer") or context.get("dealer_positioning") or context.get("gamma") or {}
    if not isinstance(dealer, Mapping): dealer = {}
    gamma_state = _upper(dealer.get("regime") or dealer.get("gamma_regime") or dealer.get("state") or context.get("gamma_regime"))
    net_gamma = _f(dealer.get("net_gamma") or dealer.get("gex") or dealer.get("gamma_exposure"))
    if "NEG" in gamma_state or "SHORT_GAMMA" in gamma_state or net_gamma < 0:
        regime, behavior = "SHORT_GAMMA", "Dealer hedging can amplify directional moves."
    elif "POS" in gamma_state or "LONG_GAMMA" in gamma_state or net_gamma > 0:
        regime, behavior = "LONG_GAMMA", "Dealer hedging can dampen moves and favor mean reversion."
    else:
        regime, behavior = "UNKNOWN", "Dealer hedging behavior is unavailable."
    return {"regime": regime, "net_gamma": net_gamma or None, "interpretation": behavior}


def _profile_context(context: Mapping[str, Any]) -> Dict[str, Any]:
    vp = context.get("volume_profile") or context.get("profile") or {}
    if not isinstance(vp, Mapping): vp = {}
    migration = _upper(vp.get("poc_migration") or vp.get("migration") or vp.get("poc_direction"))
    location = _upper(vp.get("location") or vp.get("auction_location") or context.get("auction_state"))
    return {
        "poc_migration": migration or "UNKNOWN",
        "location": location or "UNKNOWN",
        "poc": _f(vp.get("poc"), 0) or None,
        "vah": _f(vp.get("vah"), 0) or None,
        "val": _f(vp.get("val"), 0) or None,
    }


def build_flow_intelligence(context: Optional[Mapping[str, Any]], flow_data: Optional[Any] = None) -> Dict[str, Any]:
    context = dict(context or {})
    raw = _collect_events(flow_data if flow_data is not None else context)
    events = [_normalize_event(row, i) for i, row in enumerate(raw[:1500])]
    actionable = [e for e in events if e["side"] != "UNKNOWN" and e["premium"] > 0]
    clusters = _cluster(actionable)

    bull = sum(e["premium"] * e["quality_score"] / 100 for e in actionable if e["intent"] == "BULLISH")
    bear = sum(e["premium"] * e["quality_score"] / 100 for e in actionable if e["intent"] == "BEARISH")
    neutral = sum(e["premium"] * 0.25 for e in actionable if e["intent"] == "NEUTRAL")
    total = bull + bear + neutral
    directional = bull + bear
    bias = "BULLISH" if bull > bear * 1.15 else "BEARISH" if bear > bull * 1.15 else "MIXED"
    imbalance = abs(bull - bear) / max(1.0, directional) * 100
    institutional_score = min(100.0, (directional / max(1.0, total)) * 55 + imbalance * 0.45) if actionable else 0.0

    sweeps = [e for e in actionable if e["event_type"] == "SWEEP"]
    blocks = [e for e in actionable if e["event_type"] == "BLOCK"]
    splits = [e for e in actionable if e["event_type"] == "SPLIT"]
    opening = [e for e in actionable if e["opening_state"] == "OPENING"]
    dealer = _dealer_context(context)
    profile = _profile_context(context)

    mtf = context.get("multi_timeframe_intelligence") or {}
    mtf_dir = _upper(mtf.get("dominant_direction")) if isinstance(mtf, Mapping) else ""
    cross = context.get("cross_asset_intelligence") or {}
    cross_bias = _upper(cross.get("bias") or cross.get("cross_asset_bias")) if isinstance(cross, Mapping) else ""
    conflicts = []
    if bias in ("BULLISH", "BEARISH") and mtf_dir in ("BULLISH", "BEARISH") and bias != mtf_dir:
        conflicts.append("Institutional flow conflicts with the multi-timeframe direction")
    if bias in ("BULLISH", "BEARISH") and cross_bias in ("BULLISH", "BEARISH") and bias != cross_bias:
        conflicts.append("Institutional flow conflicts with cross-asset confirmation")
    if bias == "BULLISH" and profile["poc_migration"] in ("FALLING", "LOWER", "DOWN"):
        conflicts.append("Bullish flow is not confirmed by POC migration")
    if bias == "BEARISH" and profile["poc_migration"] in ("RISING", "HIGHER", "UP"):
        conflicts.append("Bearish flow is not confirmed by POC migration")

    strategy_gate = _upper((context.get("strategy_orchestration") or {}).get("decision_gate"))
    session_mode = _upper(((context.get("session_intelligence") or {}).get("session") or {}).get("mode"))
    blockers = []
    if strategy_gate == "STAND_DOWN" or session_mode == "STOP_TRADING":
        gate = "STAND_DOWN"; blockers.append("Upstream strategy or session authority requires stand down")
    elif len(actionable) < 3 or total < 50000:
        gate = "DATA_LIMITED"; blockers.append("At least three actionable prints and $50,000 classified premium are required")
    elif bias == "MIXED" or institutional_score < 45:
        gate = "MIXED_FLOW"
    elif conflicts:
        gate = "FLOW_CONFLICT"
    elif institutional_score >= 68 and imbalance >= 30:
        gate = "INSTITUTIONAL_CONFIRMATION"
    else:
        gate = "MONITOR_FLOW"

    dealer_effect = "AMPLIFY" if dealer["regime"] == "SHORT_GAMMA" and bias in ("BULLISH", "BEARISH") else "DAMPEN" if dealer["regime"] == "LONG_GAMMA" else "UNKNOWN"
    setup = "DIRECTIONAL_EXPANSION" if gate == "INSTITUTIONAL_CONFIRMATION" and dealer_effect == "AMPLIFY" else "DIRECTIONAL_CONFIRMATION" if gate == "INSTITUTIONAL_CONFIRMATION" else "WAIT_FOR_RESOLUTION"
    confidence = min(96.0, institutional_score * 0.7 + min(25.0, len(actionable) * 1.5) - len(conflicts) * 12)
    health_effect = 7 if gate == "INSTITUTIONAL_CONFIRMATION" else -10 if gate == "FLOW_CONFLICT" else -5 if gate == "DATA_LIMITED" else 0

    return {
        "version": "PHASE_18",
        "as_of": _now(),
        "mode": "CACHED_ONLY_FLOW_INTERPRETATION",
        "decision_gate": gate,
        "institutional_bias": bias,
        "institutional_score": round(institutional_score, 1),
        "confidence": round(max(0.0, confidence), 1),
        "classified_premium": round(total, 2),
        "bullish_premium_score": round(bull, 2),
        "bearish_premium_score": round(bear, 2),
        "imbalance_pct": round(imbalance, 1),
        "event_summary": {
            "total": len(events), "actionable": len(actionable), "sweeps": len(sweeps),
            "blocks": len(blocks), "splits": len(splits), "opening": len(opening),
        },
        "flow_clusters": clusters,
        "top_events": sorted(actionable, key=lambda e: (e["premium"], e["quality_score"]), reverse=True)[:10],
        "dealer_hedging": {**dealer, "flow_effect": dealer_effect},
        "volume_profile_confirmation": profile,
        "liquidity_intelligence": {
            "state": "DIRECTIONAL_LIQUIDITY_SEEK" if gate == "INSTITUTIONAL_CONFIRMATION" else "TWO_WAY_AUCTION" if bias == "MIXED" else "UNCONFIRMED",
            "interpretation": "Aggressive flow may seek the next liquidity pocket." if gate == "INSTITUTIONAL_CONFIRMATION" else "No one-sided liquidity migration is confirmed.",
        },
        "preferred_playbook": setup,
        "conflicts": conflicts,
        "blockers": blockers,
        "trade_director_effect": {
            "health_adjustment": health_effect,
            "sizing_posture": "NORMAL" if gate == "INSTITUTIONAL_CONFIRMATION" and confidence >= 65 else "ZERO" if gate in ("STAND_DOWN", "FLOW_CONFLICT") else "REDUCED",
            "advisory_only": True,
        },
        "interpretation": (
            f"{bias.title()} institutional flow with {round(imbalance,1)}% directional imbalance. "
            f"Dealer context is {dealer['regime'].lower().replace('_',' ')} and the preferred playbook is {setup.lower().replace('_',' ')}."
        ),
        "safety_note": "Phase 18 interprets cached evidence only. It cannot infer opening intent when unavailable, fabricate flow, override Phase 9 risk limits, bypass Phase 10 confirmation, override Phase 14 STAND_DOWN, or bypass Phase 16 execution controls.",
    }
