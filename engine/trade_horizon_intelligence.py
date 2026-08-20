"""APEX 66.4.0 — Trade Horizon Intelligence.

Canonical, read-only classification of APEX evidence into SCALP, INTRADAY, and
SWING horizons.  This layer explains *what horizon the data describes* and its
trend/bias relationship.  It never creates execution authority and never
bypasses existing Trade Director, risk, confirmation, or broker gates.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any, Dict, Iterable, Mapping, Optional

VERSION = "66.4.1"
SCHEMA_VERSION = "apex.trade_horizon_intelligence.v2"
HORIZONS = ("SCALP", "INTRADAY", "SWING")

HORIZON_META = {
    "SCALP": {"timeframe": "15s-5m", "expected_hold": "1-5 MIN", "role": "EXECUTION / MICROSTRUCTURE"},
    "INTRADAY": {"timeframe": "5m-65m", "expected_hold": "15-120 MIN", "role": "SESSION / AUCTION"},
    "SWING": {"timeframe": "65m-Daily", "expected_hold": "MULTI-DAY", "role": "STRUCTURE / REGIME"},
}

# Source relevance is deliberately explicit.  A source may inform more than one
# horizon, but its authority changes by horizon.
SOURCE_RELEVANCE = {
    "micro_structure": {"SCALP": 1.00, "INTRADAY": 0.30, "SWING": 0.00},
    "flow":            {"SCALP": 0.90, "INTRADAY": 0.75, "SWING": 0.20},
    "consensus":       {"SCALP": 0.70, "INTRADAY": 0.90, "SWING": 0.35},
    "auction":         {"SCALP": 0.35, "INTRADAY": 1.00, "SWING": 0.15},
    "session_structure":{"SCALP": 0.50, "INTRADAY": 1.00, "SWING": 0.35},
    "daily_structure": {"SCALP": 0.10, "INTRADAY": 0.45, "SWING": 1.00},
    "macro_regime":    {"SCALP": 0.05, "INTRADAY": 0.30, "SWING": 1.00},
    "cross_asset":     {"SCALP": 0.10, "INTRADAY": 0.55, "SWING": 0.85},
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _f(v: Any, default: float = 0.0) -> float:
    try:
        n = float(v)
        return n if math.isfinite(n) else default
    except (TypeError, ValueError):
        return default


def _direction(v: Any) -> str:
    t = str(v or "").strip().upper().replace(" ", "_")
    if any(x in t for x in ("BULL", "LONG", "CALL", "UPTREND", "RISK_ON", "HIGHER", "BUY")):
        return "BULLISH"
    if any(x in t for x in ("BEAR", "SHORT", "PUT", "DOWNTREND", "RISK_OFF", "LOWER", "SELL")):
        return "BEARISH"
    if any(x in t for x in ("NEUTRAL", "BALANCED", "RANGE", "CHOP", "FLAT", "MIXED", "WAIT")):
        return "NEUTRAL"
    return "UNAVAILABLE"


def _path(root: Mapping[str, Any], dotted: str) -> Any:
    cur: Any = root
    for key in dotted.split("."):
        if not isinstance(cur, Mapping):
            return None
        cur = cur.get(key)
    return cur


def _mapping(v: Any) -> Mapping[str, Any]:
    return v if isinstance(v, Mapping) else {}


def _session_state(root: Mapping[str, Any]) -> str:
    session = root.get("session")
    if isinstance(session, Mapping):
        session = session.get("session_state") or session.get("session")
    return str(
        root.get("session_state") or
        _mapping(root.get("market_state")).get("session_state") or
        session or "UNKNOWN"
    ).upper()


def _authoritative_decision(root: Mapping[str, Any]) -> Dict[str, Any]:
    """Read the canonical decision already present on this same snapshot."""
    obj = _mapping(root.get("institutional_decision_object"))
    if not obj.get("authoritative_contract"):
        return {"available": False, "direction": "UNAVAILABLE", "action": "NO_TRADE",
                "confidence": None, "as_of": None}
    conviction = _mapping(obj.get("conviction"))
    confidence = obj.get("calibrated_conviction")
    if confidence is None:
        confidence = obj.get("raw_conviction")
    if confidence is None:
        confidence = conviction.get("score") or conviction.get("raw_conviction")
    return {
        "available": True,
        "direction": _direction(obj.get("direction")),
        "action": str(obj.get("action") or obj.get("decision_state") or "NO_TRADE").upper(),
        "actionable": bool(obj.get("actionable")),
        "confidence": round(_f(confidence), 1) if confidence is not None else None,
        "as_of": obj.get("timestamp") or obj.get("generated_at"),
        "source": obj.get("decision_authority") or "institutional_decision_object",
    }


def _runtime_quality(root: Mapping[str, Any]) -> Dict[str, Any]:
    state = str(root.get("status") or root.get("engine_mode") or "").upper()
    timed_out = root.get("timed_out_components") or []
    degraded = bool(root.get("stale") or root.get("partial") or timed_out or "DEGRADED" in state)
    breadth = _mapping(root.get("breadth_regime"))
    breadth_limited = not breadth or str(breadth.get("state") or "DATA_LIMITED").upper() == "DATA_LIMITED"
    session = _session_state(root)
    market_open = session in ("MARKET_OPEN", "OPEN", "RTH")
    return {
        "runtime_degraded": degraded,
        "breadth_limited": breadth_limited,
        "session_state": session,
        "market_open": market_open,
        "timed_out_components": list(timed_out) if isinstance(timed_out, (list, tuple)) else [],
    }


def _first_direction(root: Mapping[str, Any], paths: Iterable[str]) -> str:
    for p in paths:
        d = _direction(_path(root, p))
        if d != "UNAVAILABLE":
            return d
    return "UNAVAILABLE"


def _bars_direction(rows: Any, lookback: int = 20) -> tuple[str, float]:
    if not isinstance(rows, list):
        return "UNAVAILABLE", 0.0
    closes = []
    for row in rows[-max(3, lookback):]:
        if isinstance(row, Mapping):
            c = _f(row.get("c") if row.get("c") is not None else row.get("close"), 0.0)
            if c > 0:
                closes.append(c)
    if len(closes) < 3:
        return "UNAVAILABLE", 0.0
    start = sum(closes[: min(3, len(closes))]) / min(3, len(closes))
    end = sum(closes[-min(3, len(closes)):]) / min(3, len(closes))
    pct = (end - start) / start * 100.0 if start else 0.0
    if abs(pct) < 0.05:
        return "NEUTRAL", min(65.0, 45.0 + abs(pct) * 100.0)
    return ("BULLISH" if pct > 0 else "BEARISH"), min(90.0, 52.0 + abs(pct) * 35.0)


def _add(evidence: list[dict[str, Any]], source: str, direction: str, confidence: float, detail: str) -> None:
    if direction == "UNAVAILABLE":
        return
    evidence.append({
        "source": source,
        "direction": direction,
        "confidence": round(max(0.0, min(100.0, confidence)), 1),
        "detail": detail,
    })


def _evidence_pool(context: Mapping[str, Any], daily_bars: Any, intraday_bars: Any) -> list[dict[str, Any]]:
    ev: list[dict[str, Any]] = []
    intra_dir, intra_conf = _bars_direction(intraday_bars, 18)
    daily_dir, daily_conf = _bars_direction(daily_bars, 30)
    _add(ev, "micro_structure", intra_dir, intra_conf, "Recent intraday bar structure")
    _add(ev, "daily_structure", daily_dir, daily_conf, "Recent daily bar structure")

    _add(ev, "flow", _first_direction(context, (
        "flow.bias", "flow_intelligence.bias", "flow_intelligence.direction",
        "options_flow.bias", "options_flow.direction")),
        _f(_path(context, "flow.flow_score"), 65.0), "Options/order-flow direction")
    _add(ev, "consensus", _first_direction(context, (
        "consensus.consensus_direction", "consensus.direction", "decision.approved_side")),
        _f(context.get("confidence"), 65.0), "Canonical institutional consensus")
    _add(ev, "auction", _first_direction(context, (
        "auction.direction", "auction.bias", "auction.acceptance.direction",
        "institutional_market_structure.acceptance_rejection.direction")),
        65.0, "Auction / acceptance state")
    _add(ev, "session_structure", _first_direction(context, (
        "structure.direction", "structure.bias", "market_state.direction",
        "institutional_market_structure.direction")),
        68.0, "Session market structure")
    _add(ev, "macro_regime", _first_direction(context, (
        "macro_regime.direction", "macro.bias", "regime.direction",
        "institutional_regime.direction", "institutional_regime.bias")),
        62.0, "Macro / regime context")
    _add(ev, "cross_asset", _first_direction(context, (
        "cross_asset_intelligence.direction", "cross_asset_intelligence.bias",
        "rotation.direction", "rotation.bias")),
        62.0, "Cross-asset / rotation context")
    return ev


def _govern_horizon(horizon: Dict[str, Any], authority: Mapping[str, Any],
                    quality: Mapping[str, Any]) -> Dict[str, Any]:
    out = dict(horizon)
    raw_confidence = _f(out.get("confidence"), 0.0)
    cap = 95.0
    reasons = []
    if quality.get("runtime_degraded"):
        cap = min(cap, 55.0); reasons.append("RUNTIME_DEGRADED")
    if quality.get("breadth_limited"):
        cap = min(cap, 65.0); reasons.append("BREADTH_DATA_LIMITED")
    if not quality.get("market_open"):
        cap = min(cap, 60.0); reasons.append("SESSION_NOT_TRADEABLE")

    auth_dir = authority.get("direction")
    horizon_dir = out.get("bias")
    directional_conflict = (
        authority.get("available") and auth_dir in ("BULLISH", "BEARISH") and
        horizon_dir in ("BULLISH", "BEARISH") and auth_dir != horizon_dir
    )
    if directional_conflict:
        cap = min(cap, 50.0); reasons.append("AUTHORITATIVE_DIRECTION_CONFLICT")
        relationship = "CONFLICT"
    elif authority.get("available") and auth_dir == horizon_dir and auth_dir in ("BULLISH", "BEARISH"):
        relationship = "ALIGNED"
    elif authority.get("available"):
        relationship = "UNRESOLVED"
    else:
        relationship = "AUTHORITY_UNAVAILABLE"

    governed = min(raw_confidence, cap)
    context_available = out.get("status") not in ("DATA_LIMITED", "UNKNOWN")
    if not context_available:
        status = "DATA_LIMITED"
    elif directional_conflict:
        status = "CONFLICT"
    elif not quality.get("market_open"):
        status = "CONTEXT_ONLY"
    elif quality.get("runtime_degraded"):
        status = "DEGRADED_CONTEXT"
    else:
        status = "CONTEXT_AVAILABLE"

    # A horizon is context, never an entry instruction. Preserve its directional
    # option translation separately while keeping the trade focus fail-closed.
    out["directional_context"] = out.get("trade_focus")
    out["trade_focus"] = "NO_TRADE"
    out["status"] = status
    out["raw_context_confidence"] = round(raw_confidence, 1)
    out["confidence"] = round(governed, 1)
    out["confidence_cap"] = round(cap, 1)
    out["confidence_cap_reasons"] = reasons
    out["relationship_to_authoritative"] = relationship
    out["authoritative_direction"] = auth_dir

    # Intraday describes the active session.  When the independently weighted
    # context conflicts with the same snapshot's authoritative decision, do not
    # leave a capped bullish label beside a bearish canonical decision. Preserve
    # the raw classifier result for diagnostics, but govern the displayed session
    # direction to the canonical state. Swing remains independent by design.
    if out.get("horizon") == "INTRADAY" and directional_conflict:
        out["raw_context_trend"] = out.get("trend")
        out["raw_context_bias"] = out.get("bias")
        out["trend"] = auth_dir
        out["bias"] = auth_dir
        out["directional_context"] = "CALL" if auth_dir == "BULLISH" else "PUT"
        out["status"] = "CONFLICT"
        out["relationship_to_authoritative"] = "GOVERNED_TO_AUTHORITY"
        out["confidence_cap_reasons"] = reasons + ["INTRADAY_USES_CANONICAL_SESSION_DIRECTION"]
    return out


def _classify_horizon(name: str, evidence: list[dict[str, Any]]) -> Dict[str, Any]:
    weighted = []
    bull = bear = neutral = total = 0.0
    for item in evidence:
        weight = SOURCE_RELEVANCE.get(item["source"], {}).get(name, 0.0)
        if weight <= 0:
            continue
        effective = weight * max(0.20, item["confidence"] / 100.0)
        weighted.append({**item, "relevance": round(weight, 2), "effective_weight": round(effective, 3)})
        total += effective
        if item["direction"] == "BULLISH": bull += effective
        elif item["direction"] == "BEARISH": bear += effective
        else: neutral += effective * 0.5

    directional = bull + bear
    coverage = min(100.0, total / 2.25 * 100.0)
    if len(weighted) < 2 or total < 0.55 or directional < 0.25:
        trend = bias = "UNKNOWN"
        confidence = 0.0
        status = "DATA_LIMITED"
    else:
        net = (bull - bear) / max(0.001, directional)
        trend = "BULLISH" if net > 0.16 else "BEARISH" if net < -0.16 else "NEUTRAL"
        bias = trend
        confidence = min(95.0, 50.0 + abs(net) * 35.0 + min(10.0, coverage * 0.10))
        status = "READY" if trend in ("BULLISH", "BEARISH") else "WAIT"

    focus = "CALL" if bias == "BULLISH" else "PUT" if bias == "BEARISH" else "NO_TRADE"
    opposition = [x for x in weighted if bias in ("BULLISH", "BEARISH") and x["direction"] not in (bias, "NEUTRAL")]
    return {
        "horizon": name,
        **HORIZON_META[name],
        "trend": trend,
        "bias": bias,
        "trade_focus": focus,
        "status": status,
        "confidence": round(confidence, 1),
        "coverage_pct": round(coverage, 1),
        "supporting_evidence": sorted(weighted, key=lambda x: x["effective_weight"], reverse=True),
        "opposing_evidence": sorted(opposition, key=lambda x: x["effective_weight"], reverse=True),
    }


def _relationship(scalp: Mapping[str, Any], intraday: Mapping[str, Any], swing: Mapping[str, Any]) -> Dict[str, Any]:
    s, i, w = scalp.get("bias"), intraday.get("bias"), swing.get("bias")
    conflict = s in ("BULLISH", "BEARISH") and i in ("BULLISH", "BEARISH") and s != i
    if conflict:
        text = f"Scalp is {str(s).lower()} inside a {str(i).lower()} intraday structure; classify the scalp as countertrend."
        scalp_type = "COUNTERTREND"
    elif s in ("BULLISH", "BEARISH") and s == i:
        text = f"Scalp and intraday horizons are aligned {str(s).lower()}."
        scalp_type = "WITH_TREND"
    else:
        text = "Horizon relationship is not fully resolved; preserve existing execution gates."
        scalp_type = "UNRESOLVED"
    return {
        "horizon_conflict": conflict or (i in ("BULLISH", "BEARISH") and w in ("BULLISH", "BEARISH") and i != w),
        "scalp_classification": scalp_type,
        "interpretation": text,
    }


def build_trade_horizon_intelligence(
    context: Optional[Mapping[str, Any]],
    *,
    daily_bars: Any = None,
    intraday_bars: Any = None,
) -> Dict[str, Any]:
    root = dict(context or {})
    pool = _evidence_pool(root, daily_bars, intraday_bars)
    authority = _authoritative_decision(root)
    quality = _runtime_quality(root)
    horizons = {
        name: _govern_horizon(_classify_horizon(name, pool), authority, quality)
        for name in HORIZONS
    }
    # Contract-level backstop. Keep this at composition scope so the public
    # payload cannot regress to CONFLICT/BULLISH for Intraday even if a legacy
    # governance helper is restored during a merge or deployment overlay.
    intraday = horizons["INTRADAY"]
    auth_dir = authority.get("direction")
    if (authority.get("available") and auth_dir in ("BULLISH", "BEARISH") and
            intraday.get("bias") in ("BULLISH", "BEARISH") and
            intraday.get("bias") != auth_dir):
        intraday["raw_context_trend"] = intraday.get("trend")
        intraday["raw_context_bias"] = intraday.get("bias")
        intraday["trend"] = auth_dir
        intraday["bias"] = auth_dir
        intraday["directional_context"] = "CALL" if auth_dir == "BULLISH" else "PUT"
        intraday["trade_focus"] = "NO_TRADE"
        intraday["status"] = "CANONICAL_SESSION_GOVERNED"
        intraday["relationship_to_authoritative"] = "GOVERNED_TO_AUTHORITY"
        intraday["confidence"] = min(_f(intraday.get("confidence")), 50.0)
        reasons = list(intraday.get("confidence_cap_reasons") or [])
        for reason in ("AUTHORITATIVE_DIRECTION_CONFLICT", "INTRADAY_USES_CANONICAL_SESSION_DIRECTION"):
            if reason not in reasons:
                reasons.append(reason)
        intraday["confidence_cap_reasons"] = reasons
    relation = _relationship(horizons["SCALP"], horizons["INTRADAY"], horizons["SWING"])
    conflicts = [name for name, item in horizons.items()
                 if item.get("relationship_to_authoritative") in ("CONFLICT", "GOVERNED_TO_AUTHORITY")]
    if conflicts:
        relation["horizon_conflict"] = True
        relation["authoritative_conflict"] = True
        relation["conflicting_horizons"] = conflicts
        relation["interpretation"] = (
            f"Authoritative decision is {str(authority.get('direction')).lower()}; "
            f"{', '.join(conflicts).lower()} context disagrees. Execution remains NO TRADE."
        )
    return {
        "ok": True,
        "version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "as_of": _now(),
        "ticker": str(root.get("ticker") or "SPX").upper(),
        "horizons": horizons,
        "relationship": relation,
        "authoritative_decision": authority,
        "runtime_quality": quality,
        "snapshot": {
            "canonical_as_of": authority.get("as_of"),
            "classification_as_of": _now(),
            "single_snapshot_contract": True,
        },
        "source_relevance": SOURCE_RELEVANCE,
        "execution_authority": "NONE",
        "guardrails": {
            "read_only": True,
            "advisory_only": True,
            "changes_trade_decisions": False,
            "changes_execution_authority": False,
            "subminute_direction_authority": False,
            "fail_closed_on_insufficient_evidence": True,
        },
    }
