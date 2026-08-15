"""APEX 66.8.0 — Confidence Calibration Audit.

Read-only audit of stated APEX confidence versus governed terminal outcomes.
This module does not recalibrate production confidence and has no execution authority.
"""
from __future__ import annotations

import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

from .evidence_pipeline import DEFAULT_DB
from .historical_effectiveness_observatory import load_graded_records

VERSION = "66.8.0"
SCHEMA_VERSION = "apex.confidence_calibration_audit.v1"
DEFAULT_MINIMUM_SAMPLE = 20
VERIFIED_SAMPLE = 100
PRIOR_STRENGTH = 20.0


def _f(v: Any) -> float | None:
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _prob(v: Any) -> float | None:
    x = _f(v)
    if x is None:
        return None
    if x > 1.0:
        x /= 100.0
    return max(0.0, min(1.0, x))


def _mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def _wilson(wins: int, n: int, z: float = 1.96) -> tuple[float | None, float | None]:
    if n <= 0:
        return None, None
    p = wins / n
    den = 1 + z * z / n
    center = (p + z * z / (2 * n)) / den
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / den
    return max(0.0, center - margin), min(1.0, center + margin)


def _auc(rows: list[dict[str, Any]]) -> float | None:
    scored = [(float(r["confidence"]), 1 if r["won"] else 0) for r in rows if r.get("confidence") is not None]
    pos = [s for s, y in scored if y == 1]
    neg = [s for s, y in scored if y == 0]
    if not pos or not neg:
        return None
    wins = ties = 0.0
    for p in pos:
        for n in neg:
            if p > n:
                wins += 1
            elif p == n:
                ties += 1
    return (wins + 0.5 * ties) / (len(pos) * len(neg))


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    usable = [r for r in rows if r.get("confidence") is not None]
    n = len(usable)
    if not n:
        return {
            "sample_size": 0, "wins": 0, "losses": 0, "mean_stated_confidence": None,
            "observed_hit_rate": None, "calibration_gap_points": None, "brier_score": None,
            "log_loss": None, "auc": None, "overconfident": None, "underconfident": None,
        }
    probs = [max(1e-6, min(1 - 1e-6, float(r["confidence"]) / 100.0)) for r in usable]
    ys = [1.0 if r["won"] else 0.0 for r in usable]
    wins = int(sum(ys))
    mean_p = _mean(probs) or 0.0
    hit = wins / n
    gap = (mean_p - hit) * 100
    brier = sum((p - y) ** 2 for p, y in zip(probs, ys)) / n
    log_loss = -sum(y * math.log(p) + (1 - y) * math.log(1 - p) for p, y in zip(probs, ys)) / n
    return {
        "sample_size": n,
        "wins": wins,
        "losses": n - wins,
        "mean_stated_confidence": round(mean_p * 100, 2),
        "observed_hit_rate": round(hit * 100, 2),
        "calibration_gap_points": round(gap, 2),
        "brier_score": round(brier, 4),
        "log_loss": round(log_loss, 4),
        "auc": round(_auc(usable), 4) if _auc(usable) is not None else None,
        "overconfident": gap > 5,
        "underconfident": gap < -5,
    }


def _bucket_label(confidence: float) -> str:
    lo = min(90, int(confidence // 10) * 10)
    return f"{lo:02d}-{100 if lo == 90 else lo + 9:02d}"


def _reliability(rows: list[dict[str, Any]], minimum_sample: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if r.get("confidence") is not None:
            groups[_bucket_label(float(r["confidence"]))].append(r)

    total = sum(len(v) for v in groups.values())
    overall_wins = sum(1 for r in rows if r.get("confidence") is not None and r["won"])
    global_rate = overall_wins / total if total else 0.5
    ece = 0.0
    mce = 0.0
    buckets = []
    for lo in range(0, 100, 10):
        label = f"{lo:02d}-{100 if lo == 90 else lo + 9:02d}"
        g = groups.get(label, [])
        n = len(g)
        wins = sum(1 for r in g if r["won"])
        stated = _mean([float(r["confidence"]) for r in g]) if g else None
        actual = wins / n if n else None
        err = ((stated / 100.0) - actual) if stated is not None and actual is not None else None
        if err is not None and total:
            ece += abs(err) * n / total
            mce = max(mce, abs(err))
        lo_ci, hi_ci = _wilson(wins, n)
        ref = ((n * (actual or 0.0)) + PRIOR_STRENGTH * global_rate) / (n + PRIOR_STRENGTH) if n else None
        buckets.append({
            "bucket": label,
            "sample_size": n,
            "wins": wins,
            "mean_stated_confidence": round(stated, 2) if stated is not None else None,
            "observed_hit_rate": round(actual * 100, 2) if actual is not None else None,
            "calibration_error_points": round(err * 100, 2) if err is not None else None,
            "hit_rate_ci95_low": round(lo_ci * 100, 2) if lo_ci is not None else None,
            "hit_rate_ci95_high": round(hi_ci * 100, 2) if hi_ci is not None else None,
            "audit_reference_probability": round(ref * 100, 2) if ref is not None else None,
            "qualified": n >= minimum_sample,
        })
    return buckets, {"expected_calibration_error": round(ece, 4) if total else None, "max_calibration_error": round(mce, 4) if total else None}


def _dimension(rows: list[dict[str, Any]], getter, minimum_sample: int) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        groups[str(getter(r) or "UNKNOWN")].append(r)
    out = []
    for value, group in groups.items():
        m = _metrics(group)
        out.append({"value": value, **m, "qualified": m["sample_size"] >= minimum_sample})
    return sorted(out, key=lambda x: (x["qualified"], x["sample_size"]), reverse=True)


def _window_drift(rows: list[dict[str, Any]], minimum_sample: int) -> dict[str, Any]:
    ordered = sorted([r for r in rows if r.get("confidence") is not None], key=lambda r: str(r.get("observed_at") or ""))
    if len(ordered) < max(10, minimum_sample):
        return {"state": "INSUFFICIENT_DATA", "detected": False, "sample_size": len(ordered)}
    split = max(5, len(ordered) // 2)
    prior, recent = ordered[:-split], ordered[-split:]
    pm, rm = _metrics(prior), _metrics(recent)
    reasons = []
    if pm["observed_hit_rate"] is not None and rm["observed_hit_rate"] is not None and abs(rm["observed_hit_rate"] - pm["observed_hit_rate"]) >= 15:
        reasons.append("Recent hit rate differs from prior history by at least 15 points.")
    if rm["calibration_gap_points"] is not None and abs(rm["calibration_gap_points"]) >= 12:
        reasons.append("Recent stated confidence differs from realized hit rate by at least 12 points.")
    if pm["brier_score"] is not None and rm["brier_score"] is not None and rm["brier_score"] - pm["brier_score"] >= 0.05:
        reasons.append("Recent Brier score deteriorated by at least 0.05.")
    return {"state": "DRIFT_DETECTED" if reasons else "STABLE", "detected": bool(reasons), "prior": pm, "recent": rm, "reasons": reasons}


def _assessment(metrics: Mapping[str, Any], reliability: Mapping[str, Any], minimum_sample: int) -> dict[str, Any]:
    n = int(metrics.get("sample_size") or 0)
    if n < minimum_sample:
        return {"state": "COLLECTING", "quality": "INSUFFICIENT_DATA", "message": f"Need at least {minimum_sample} graded observations before judging calibration."}
    gap = float(metrics.get("calibration_gap_points") or 0.0)
    ece = reliability.get("expected_calibration_error")
    brier = metrics.get("brier_score")
    if gap >= 8:
        state = "OVERCONFIDENT"
    elif gap <= -8:
        state = "UNDERCONFIDENT"
    else:
        state = "ALIGNED"
    if n >= VERIFIED_SAMPLE and ece is not None and ece <= 0.08 and brier is not None and brier <= 0.22:
        quality = "VERIFIED"
    elif n >= 50:
        quality = "PROVISIONAL"
    else:
        quality = "EARLY"
    return {"state": state, "quality": quality, "message": "Diagnostic only; no production confidence is changed."}


def build_confidence_calibration_audit(*, path: str | Path = DEFAULT_DB, symbol: str = "SPX", minimum_sample: int = DEFAULT_MINIMUM_SAMPLE, limit: int = 10000) -> dict[str, Any]:
    minimum_sample = max(1, int(minimum_sample))
    rows, exclusions = load_graded_records(path=path, symbol=symbol, limit=limit)
    rows = [r for r in rows if r.get("direction") in {"BULLISH", "BEARISH"} and r.get("confidence") is not None]
    overall = _metrics(rows)
    buckets, reliability = _reliability(rows, minimum_sample)
    assessment = _assessment(overall, reliability, minimum_sample)
    return {
        "ok": True,
        "status": "READY" if overall["sample_size"] >= minimum_sample else ("COLLECTING" if overall["sample_size"] else "WAITING_FOR_GRADED_OUTCOMES"),
        "version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "symbol": symbol.upper(),
        "minimum_sample": minimum_sample,
        "overall": {**overall, **reliability},
        "assessment": assessment,
        "reliability_buckets": buckets,
        "breakdowns": {
            "horizon": _dimension([h for r in rows for h in _horizon_rows(r)], lambda x: x["horizon"], minimum_sample),
            "setup": _dimension(rows, lambda r: r.get("setup"), minimum_sample),
            "session_period": _dimension(rows, lambda r: r.get("session_period"), minimum_sample),
            "market_regime": _dimension(rows, lambda r: r.get("regimes", {}).get("market_regime"), minimum_sample),
            "gamma_regime": _dimension(rows, lambda r: r.get("regimes", {}).get("gamma_regime"), minimum_sample),
            "volatility_regime": _dimension(rows, lambda r: r.get("regimes", {}).get("volatility_regime"), minimum_sample),
            "auction_regime": _dimension(rows, lambda r: r.get("regimes", {}).get("auction_regime"), minimum_sample),
        },
        "drift": _window_drift(rows, minimum_sample),
        "exclusions": exclusions,
        "interpretation": {
            "stated_confidence": "Captured APEX evidence/conviction score. It is audited as a probability claim only for diagnostic comparison; the audit does not assume it was historically calibrated.",
            "brier_score": "Mean squared probability error; lower is better. 0 is perfect.",
            "expected_calibration_error": "Weighted average absolute gap between stated confidence and observed hit rate across confidence buckets.",
            "auc": "Discrimination metric: whether higher-confidence observations tend to win more often than lower-confidence observations.",
            "audit_reference_probability": "Bayesian-shrunk observed rate shown as an audit reference only. It is not written back into APEX confidence.",
        },
        "guardrails": {
            "read_only": True,
            "automatic_recalibration": False,
            "writes_calibrated_confidence": False,
            "changes_trade_decisions": False,
            "changes_execution_authority": False,
            "requires_governed_graded_outcomes": True,
            "codespaces_safe_paths": True,
        },
    }


def _horizon_rows(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    out = []
    canonical = record.get("direction")
    for name, h in (record.get("horizons") or {}).items():
        if not isinstance(h, Mapping) or h.get("direction") not in {"BULLISH", "BEARISH"} or h.get("confidence") is None:
            continue
        row = dict(record)
        row["horizon"] = name
        row["confidence"] = h.get("confidence")
        row["won"] = record.get("won") if h.get("direction") == canonical else not bool(record.get("won"))
        out.append(row)
    return out


def health(*, path: str | Path = DEFAULT_DB, symbol: str = "SPX") -> dict[str, Any]:
    x = build_confidence_calibration_audit(path=path, symbol=symbol, minimum_sample=DEFAULT_MINIMUM_SAMPLE, limit=2000)
    return {"ok": x["ok"], "status": x["status"], "version": VERSION, "sample_size": x["overall"]["sample_size"], "assessment": x["assessment"], "read_only": True}
