"""APEX — Flow Excitation / Burst Identity.

Classifies whether apparently separate options-flow observations are likely one
continuing burst.  This is deliberately separate from institutional-order
``persistence_score``: persistence asks whether an old order still matters;
excitation asks whether new observations are independent evidence.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import exp
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple
import hashlib

from .event_calendar import event_phase_at

VERSION = "66.4.0_FLOW_EXCITATION"


def _f(v: Any, d: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def _ts(v: Any) -> Optional[datetime]:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _identity(e: Mapping[str, Any]) -> Tuple[str, str, str, str]:
    return (
        str(e.get("symbol") or e.get("ticker") or "SPX").upper(),
        str(e.get("side") or e.get("sentiment") or e.get("direction") or "UNKNOWN").upper(),
        str(e.get("option_type") or e.get("right") or e.get("contract_type") or "UNKNOWN").upper(),
        str(e.get("strike") or e.get("strike_price") or "UNKNOWN"),
    )


def build_flow_excitation(events: Iterable[Mapping[str, Any]], *, now: Optional[datetime] = None,
                          half_life_seconds: float = 90.0, burst_gap_seconds: float = 120.0) -> Dict[str, Any]:
    rows = [dict(x) for x in events if isinstance(x, Mapping)]
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    if not rows:
        return {"available": False, "version": VERSION, "state": "NO_FLOW", "burst_count": 0,
                "current_intensity": 0.0, "baseline_intensity": 0.0, "excitation_ratio": 0.0,
                "same_burst_probability": 0.0, "independent_evidence_factor": 1.0,
                "redundancy_factor": 0.0, "bursts": []}

    enriched: List[Tuple[datetime, Dict[str, Any]]] = []
    for idx, e in enumerate(rows):
        t = _ts(e.get("timestamp") or e.get("executed_at") or e.get("time") or e.get("created_at"))
        # Missing timestamps remain usable but cannot create false temporal precision.
        t = t or current
        ee = dict(e); ee["_idx"] = idx
        enriched.append((t, ee))
    enriched.sort(key=lambda x: x[0])

    bursts: List[Dict[str, Any]] = []
    active: Optional[Dict[str, Any]] = None
    for t, e in enriched:
        ident = _identity(e)
        phase = event_phase_at(t)
        segment_id = phase.get("segment_id")
        if (active is None or ident != active["identity"] or segment_id != active["segment_id"]
                or (t - active["last_at"]).total_seconds() > burst_gap_seconds):
            if active is not None:
                bursts.append(active)
            seed = "|".join(ident) + "|" + t.isoformat()
            active = {"burst_id": hashlib.sha1(seed.encode()).hexdigest()[:12], "identity": ident,
                      "first_at": t, "last_at": t, "event_count": 0, "premium": 0.0, "contracts": 0.0,
                      "segment_id": segment_id}
        active["last_at"] = t
        active["event_count"] += 1
        active["premium"] += _f(e.get("premium") or e.get("notional") or e.get("value"))
        active["contracts"] += _f(e.get("size") or e.get("contracts"))
    if active is not None:
        bursts.append(active)

    weighted = 0.0
    total_events = max(1, len(rows))
    for b in bursts:
        age = max(0.0, (current - b["last_at"]).total_seconds())
        weight = exp(-0.69314718056 * age / max(1.0, half_life_seconds))
        weighted += b["event_count"] * weight

    baseline = total_events / max(1.0, len(bursts))
    ratio = weighted / max(1.0, baseline)
    largest = max((b["event_count"] for b in bursts), default=1)
    same_prob = min(1.0, max(0.0, (largest - 1) / max(1.0, total_events - 1))) if total_events > 1 else 0.0
    independent = max(0.2, min(1.0, len(bursts) / total_events))
    redundancy = 1.0 - independent

    public_bursts = []
    for b in bursts[-10:]:
        public_bursts.append({
            "burst_id": b["burst_id"], "symbol": b["identity"][0], "side": b["identity"][1],
            "option_type": b["identity"][2], "strike": b["identity"][3],
            "event_count": b["event_count"], "premium": round(b["premium"], 2),
            "contracts": round(b["contracts"], 2), "first_at": b["first_at"].isoformat(),
            "last_at": b["last_at"].isoformat(),
        })
    state = "HIGH_EXCITATION" if ratio >= 2.0 else "ELEVATED_EXCITATION" if ratio >= 1.25 else "NORMAL"
    return {"available": True, "version": VERSION, "state": state, "burst_count": len(bursts),
            "event_count": total_events, "current_intensity": round(weighted, 3),
            "baseline_intensity": round(baseline, 3), "excitation_ratio": round(ratio, 3),
            "same_burst_probability": round(same_prob, 3),
            "independent_evidence_factor": round(independent, 3),
            "redundancy_factor": round(redundancy, 3), "bursts": public_bursts}
