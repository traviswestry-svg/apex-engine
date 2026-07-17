"""Live post-cluster confirmation for the Flow Authenticity Layer.

The initial cluster decision remains immutable.  This module stores later market
observations separately and derives confirmation only after the configured 30s
and 120s horizons have elapsed.
"""
from __future__ import annotations

import datetime as dt
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional
from zoneinfo import ZoneInfo

from .flow_authenticity import assess_cluster_authenticity

EASTERN = ZoneInfo("America/New_York")
CONFIRMATION_VERSION = "9.4.1_LIVE_FLOW_CONFIRMATION"


def _f(v: Any) -> Optional[float]:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _secs(v: Any) -> Optional[int]:
    p = str(v or "").split(":")
    if len(p) < 2:
        return None
    try:
        return int(p[0]) * 3600 + int(p[1]) * 60 + (int(p[2]) if len(p) > 2 else 0)
    except (TypeError, ValueError):
        return None


def market_snapshot(last_result: Dict[str, Any], *, observed_at: Optional[dt.datetime] = None) -> Dict[str, Any]:
    """Extract SPX/ES marks and observable liquidity from the canonical bus."""
    lr = last_result or {}
    ms = lr.get("market_state") or {}
    instruments = ms.get("instruments") or {}
    spx = _f((instruments.get("SPX") or {}).get("price"))
    if spx is None:
        spx = _f(ms.get("price") or lr.get("price"))
    es = _f((instruments.get("ES") or {}).get("price"))
    if es is None:
        es = _f(ms.get("es_price") or lr.get("es_price"))

    # Liquidity is intentionally optional.  Prefer explicit market/chain metrics;
    # never manufacture a value from price movement.
    liq = None
    for obj in (ms, lr, ms.get("flow") or {}, ms.get("gamma") or {}):
        for key in ("liquidity_score", "market_liquidity_score", "chain_liquidity_score"):
            liq = _f(obj.get(key)) if isinstance(obj, dict) else None
            if liq is not None:
                break
        if liq is not None:
            break

    now = observed_at or dt.datetime.now(EASTERN)
    return {
        "observed_at": now.isoformat(),
        "observed_at_et_seconds": now.hour * 3600 + now.minute * 60 + now.second,
        "spx_price": spx,
        "es_price": es,
        "liquidity_score": liq,
    }


def signed_delta_total(events: Iterable[Dict[str, Any]]) -> Optional[float]:
    """Aggregate signed contract delta when the feed actually supplies delta.

    Sign comes only from observable execution aggression.  Missing delta remains
    unmeasurable; signed premium is not relabelled as delta.
    """
    total = 0.0
    measured = 0
    for ev in events:
        f = ev.get("observable_facts") or {}
        delta = _f(f.get("delta"))
        contracts = _f(f.get("contracts"))
        if delta is None or contracts is None:
            continue
        agg = str(ev.get("execution_aggression") or "")
        sign = 1.0 if agg in ("AGGRESSIVE_BUY", "BUY") else -1.0 if agg in ("AGGRESSIVE_SELL", "SELL") else 0.0
        if sign == 0:
            continue
        total += sign * delta * contracts * 100.0
        measured += 1
    return round(total, 4) if measured else None


def _same_direction(change: Optional[float], direction: str, *, threshold: float = 0.0) -> Optional[bool]:
    if change is None:
        return None
    d = str(direction or "").upper()
    if d == "BULLISH":
        return change > threshold
    if d == "BEARISH":
        return change < -threshold
    return None


@dataclass
class _Record:
    cluster: Dict[str, Any]
    baseline: Dict[str, Any]
    baseline_signed_delta: Optional[float]
    observations: List[Dict[str, Any]] = field(default_factory=list)


class FlowConfirmationTracker:
    """Thread-safe in-memory tracker; safe for repeated dashboard polling."""

    def __init__(self) -> None:
        self._records: Dict[str, _Record] = {}
        self._lock = threading.RLock()

    def observe(self, clusters: List[Dict[str, Any]], events_by_id: Dict[str, Dict[str, Any]],
                snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        with self._lock:
            for original in clusters:
                cl = dict(original)
                cid = str(cl.get("cluster_id") or "")
                if not cid:
                    out.append(cl)
                    continue
                members = [events_by_id[e] for e in cl.get("member_event_ids", []) if e in events_by_id]
                current_delta = signed_delta_total(members)
                rec = self._records.get(cid)
                if rec is None:
                    rec = _Record(dict(cl), dict(snapshot), current_delta)
                    self._records[cid] = rec
                rec.observations.append(dict(snapshot, signed_delta=current_delta))
                rec.observations = rec.observations[-20:]
                confirmation, metrics = self._evaluate(rec, cl)
                cl["post_cluster_confirmation"] = metrics
                cl["flow_authenticity"] = assess_cluster_authenticity(cl, confirmation=confirmation)
                cl["directional_confidence_adjusted"] = round(
                    float(cl.get("confidence") or 0.0) * cl["flow_authenticity"]["directional_confidence_multiplier"], 3)
                out.append(cl)
        return out

    def _evaluate(self, rec: _Record, cl: Dict[str, Any]) -> tuple[Dict[str, Optional[bool]], Dict[str, Any]]:
        end = _secs(cl.get("end_time"))
        direction = cl.get("directional_interpretation")
        base = rec.baseline
        observations = rec.observations

        def at_horizon(seconds: int) -> Optional[Dict[str, Any]]:
            if end is None:
                return None
            eligible = [o for o in observations if (o.get("observed_at_et_seconds") or 0) - end >= seconds]
            return eligible[0] if eligible else None

        o30, o120 = at_horizon(30), at_horizon(120)
        spx30 = None if not o30 or base.get("spx_price") is None or o30.get("spx_price") is None else o30["spx_price"] - base["spx_price"]
        spx120 = None if not o120 or base.get("spx_price") is None or o120.get("spx_price") is None else o120["spx_price"] - base["spx_price"]
        es120 = None if not o120 or base.get("es_price") is None or o120.get("es_price") is None else o120["es_price"] - base["es_price"]

        d30 = None if not o30 else o30.get("signed_delta")
        d120 = None if not o120 else o120.get("signed_delta")
        base_d = rec.baseline_signed_delta
        flow30 = None if base_d is None or d30 is None else _same_direction(d30 - base_d, direction)
        flow120 = None if base_d is None or d120 is None else _same_direction(d120 - base_d, direction)

        liq_resp = None
        if o120 and base.get("liquidity_score") is not None and o120.get("liquidity_score") is not None:
            # Confirmation means liquidity did not deteriorate by more than 15 points.
            liq_resp = (o120["liquidity_score"] - base["liquidity_score"]) >= -15.0

        confirmation = {
            "flow_persistence_30s": flow30,
            "flow_persistence_2m": flow120,
            "price_response_after_cluster": _same_direction(spx120 if spx120 is not None else spx30, direction),
            "es_confirmation": _same_direction(es120, direction),
            "liquidity_response": liq_resp,
        }
        return confirmation, {
            "version": CONFIRMATION_VERSION,
            "baseline": base,
            "horizon_30s_observed": o30 is not None,
            "horizon_2m_observed": o120 is not None,
            "spx_change_30s": None if spx30 is None else round(spx30, 4),
            "spx_change_2m": None if spx120 is None else round(spx120, 4),
            "es_change_2m": None if es120 is None else round(es120, 4),
            "signed_delta_baseline": base_d,
            "signed_delta_30s": d30,
            "signed_delta_2m": d120,
            "liquidity_baseline": base.get("liquidity_score"),
            "liquidity_2m": None if not o120 else o120.get("liquidity_score"),
            "confirmation": confirmation,
            "note": "Future observations are attached separately; the original decision-time feature vector is not rewritten.",
        }


TRACKER = FlowConfirmationTracker()
