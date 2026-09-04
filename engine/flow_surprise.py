"""APEX 69.10.0 Flow Surprise Intelligence.

Observational, learning-first context over the canonical flow-cluster identity.
No clustering, direction, conviction, consensus, sizing, or execution authority is
created here. Historical baselines are read from the existing immutable
``flow_features`` store.
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Any, Dict, Iterable, List, Mapping, Optional

VERSION = "69.10.0"
SCHEMA_VERSION = "apex.flow_surprise.v1"
MIN_BASELINE_SAMPLES = 20
BUCKET_MINUTES = 30


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _parse_time(value: Any) -> Optional[dt.datetime]:
    s = str(value or "").strip()
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def session_time_bucket(decision_time: Any, minutes: int = BUCKET_MINUTES) -> Optional[str]:
    d = _parse_time(decision_time)
    if d is None:
        return None
    start_minute = (d.minute // minutes) * minutes
    end_total = d.hour * 60 + start_minute + minutes
    eh, em = divmod(end_total, 60)
    return f"{d.hour:02d}:{start_minute:02d}-{eh:02d}:{em:02d}"


def expiration_class(expiration: Any, session_date: Any) -> Optional[str]:
    try:
        exp = dt.date.fromisoformat(str(expiration)[:10])
        ses = dt.date.fromisoformat(str(session_date)[:10])
    except (TypeError, ValueError):
        return None
    return "0DTE" if exp == ses else "LATER" if exp > ses else "EXPIRED"


def _percentile(values: List[float], current: float) -> Optional[float]:
    if not values:
        return None
    # empirical CDF, deterministic and bounded; ties receive <= percentile.
    return round(100.0 * sum(1 for v in values if v <= current) / len(values), 2)


def _confidence(n: int) -> str:
    return "HIGH" if n >= 100 else "MEDIUM" if n >= 50 else "LOW" if n >= MIN_BASELINE_SAMPLES else "INSUFFICIENT"


def evaluate_flow_surprise(cluster: Mapping[str, Any], *, session_date: str,
                           decision_time: str,
                           historical_rows: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    """Compare one canonical cluster to same-time/same-expiration history."""
    bucket = session_time_bucket(decision_time)
    exp_class = expiration_class(cluster.get("expiration"), session_date)
    context = {"session_time_bucket": bucket, "expiration_class": exp_class,
               "conditioning_dimensions": ["session_time_bucket", "expiration_class"]}
    base: List[Mapping[str, Any]] = []
    for row in historical_rows or []:
        features = row.get("features") if isinstance(row.get("features"), Mapping) else row
        rdt = row.get("decision_time") or features.get("decision_time")
        rsd = row.get("session_date") or str(rdt or "")[:10]
        rexp = features.get("cluster_expiration")
        if session_time_bucket(rdt) == bucket and expiration_class(rexp, rsd) == exp_class:
            base.append(features)

    current_contracts = _f(cluster.get("total_contracts"))
    current_premium = _f(cluster.get("total_premium"))
    duration = _f(cluster.get("duration_seconds"))
    current_rate = None if current_contracts is None or duration is None else current_contracts / max(duration, 1.0)

    premiums = [x for x in (_f(r.get("cluster_total_premium")) for r in base) if x is not None]
    contracts = [x for x in (_f(r.get("cluster_total_contracts")) for r in base) if x is not None]
    rates = []
    for r in base:
        c, d = _f(r.get("cluster_total_contracts")), _f(r.get("cluster_duration_seconds"))
        if c is not None and d is not None:
            rates.append(c / max(d, 1.0))
    n = min(len(premiums), len(contracts), len(rates))
    if bucket is None or exp_class not in {"0DTE", "LATER"} or n < MIN_BASELINE_SAMPLES:
        return {"available": False, "status": "INSUFFICIENT_HISTORY", "flow_surprise_state": "INSUFFICIENT_HISTORY",
                "baseline_sample_size": n, "baseline_confidence": _confidence(n), "baseline_context": context,
                "relative_contract_activity": None, "relative_premium_activity": None,
                "transaction_rate_ratio": None, "volume_percentile": None, "premium_percentile": None,
                "transaction_rate_percentile": None, "schema_version": SCHEMA_VERSION,
                "behavioral_authority": False, "execution_authority": False, "production_effect": "NONE"}

    def ratio(cur: Optional[float], vals: List[float]) -> Optional[float]:
        if cur is None or not vals:
            return None
        mean = sum(vals) / len(vals)
        return None if mean <= 0 else round(cur / mean, 4)

    pp = _percentile(premiums, current_premium) if current_premium is not None else None
    vp = _percentile(contracts, current_contracts) if current_contracts is not None else None
    rp = _percentile(rates, current_rate) if current_rate is not None else None
    top = max([x for x in (pp, vp, rp) if x is not None], default=None)
    state = "EXTREME" if top is not None and top >= 97 else "HIGH" if top is not None and top >= 90 else "ELEVATED" if top is not None and top >= 75 else "NORMAL"
    return {"available": True, "status": "AVAILABLE", "flow_surprise_state": state,
            "relative_contract_activity": ratio(current_contracts, contracts),
            "relative_premium_activity": ratio(current_premium, premiums),
            "transaction_rate_ratio": ratio(current_rate, rates),
            "volume_percentile": vp, "premium_percentile": pp, "transaction_rate_percentile": rp,
            "baseline_sample_size": n, "baseline_confidence": _confidence(n), "baseline_context": context,
            "schema_version": SCHEMA_VERSION, "behavioral_authority": False,
            "execution_authority": False, "production_effect": "NONE",
            "identity_source": "canonical_flow_cluster_id", "cluster_id": cluster.get("cluster_id")}
