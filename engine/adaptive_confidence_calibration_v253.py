"""APEX 25.3 — Adaptive Confidence Calibration Engine.

Shadow-mode, deterministic calibration layer built on APEX 25.0 Decision
Integrity (for the confidence ceiling) and the APEX 23.4 outcome store (for
empirical history). It replaces unsupported headline confidence with an
empirically calibrated estimate: it answers "does a displayed confidence of 80
historically behave like ~80% under comparable conditions?".

Hard guarantees
---------------
* Shadow-only. It never mutates production confidence, never changes eligibility,
  never submits orders, never auto-promotes. ``production_effect`` is ``NONE``.
* No calibrated layer may exceed the APEX 25.0 integrity ceiling.
* Deterministic. Bucketing and Bayesian shrinkage are pure functions of the
  supplied history; no randomness.
* Hierarchical fallback: a narrowly defined group that lacks samples shrinks
  toward progressively broader groups and finally a global prior. The fallback
  level, effective sample size, and shrinkage amount are always reported.
* Data reuse: historical outcomes come from the existing 23.4 store
  (``apex_learning_outcomes_v234``) via ``continuous_learning_calibration_v234``;
  no parallel outcome pipeline is created. History may also be supplied inline
  for deterministic evaluation.
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Any, Mapping, Optional, Sequence

from . import institutional_decision_integrity_v250 as integrity

try:  # Reuse the existing 23.4 outcome store; degrade gracefully if absent.
    from . import continuous_learning_calibration_v234 as learning_store  # type: ignore
except Exception:  # pragma: no cover - defensive import guard
    learning_store = None  # type: ignore

VERSION = "25.3.0_ADAPTIVE_CONFIDENCE_CALIBRATION"
SCHEMA_VERSION = "apex.confidence_calibration.v253.v1"

# Sample-size governance thresholds.
MIN_PROVISIONAL = 5
MIN_ACTIVE = 20
MIN_VERIFIED = 50
PER_GROUP_MIN = 8          # minimum samples for a dimension group to be usable
PRIOR_STRENGTH = 15.0      # Bayesian pseudo-count toward the global prior

# Governed promotion thresholds (never auto-applied).
PROMOTION_MIN_SAMPLE = 50
PROMOTION_MAX_ECE = 0.08
PROMOTION_MAX_BRIER = 0.22

CONFIDENCE_BUCKETS = [(low, low + 10 if low < 90 else 101) for low in range(0, 100, 10)]


# --------------------------------------------------------------------------- #
# Helpers (shared conventions with 25.0/25.1/25.2).
# --------------------------------------------------------------------------- #
def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso_now() -> str:
    return _now().isoformat()


def _number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple)) else []


def _text(value: Any) -> str:
    return str(value or "").strip()


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _round(value: Any, places: int = 2) -> Optional[float]:
    if value is None:
        return None
    return round(float(value), places)


def shadow_mode() -> bool:
    """Calibration is shadow-only unless BOTH the production flag is enabled and
    an operator has recorded explicit approval. Even then this engine only
    reports readiness; it never writes production confidence itself."""
    import os
    enabled = _text(os.getenv("APEX_CALIBRATION_PRODUCTION_ENABLED", "false")).lower() == "true"
    approved = _text(os.getenv("APEX_CALIBRATION_PROMOTION_APPROVED", "false")).lower() == "true"
    return not (enabled and approved)


# --------------------------------------------------------------------------- #
# History acquisition (reuse 23.4 store; allow inline history for tests).
# --------------------------------------------------------------------------- #
def _normalize_row(raw: Mapping[str, Any]) -> Optional[dict[str, Any]]:
    conf = raw.get("stated_confidence", raw.get("confidence"))
    won = raw.get("won", raw.get("win"))
    if conf is None or won is None:
        return None
    confidence = _clamp(_number(conf))
    return {
        "stated_confidence": confidence,
        "won": 1 if (won in (1, True, "1", "true", "WIN", "win")) else 0,
        "realized_r": _number(raw.get("realized_r") or raw.get("r"), 0.0),
        "direction": _text(raw.get("direction")).upper() or "UNKNOWN",
        "regime": _text(raw.get("regime") or raw.get("market_regime")).upper() or "UNKNOWN",
        "setup_family": _text(raw.get("setup_family") or raw.get("playbook_id")) or "UNKNOWN",
        "observed_at": raw.get("observed_at"),
    }


def load_history(payload: Mapping[str, Any], *, before: Optional[str] = None) -> tuple[list[dict[str, Any]], str]:
    """Return (rows, source). Inline history wins for determinism; otherwise read
    the existing 23.4 store, look-ahead protected by ``before`` when supplied."""
    inline = payload.get("calibration_history") or payload.get("history")
    if isinstance(inline, (list, tuple)):
        rows = [r for r in (_normalize_row(_mapping(x)) for x in inline) if r]
        return rows, "inline"
    if learning_store is not None:
        try:
            ticker = _text(payload.get("symbol") or _mapping(payload.get("market_state")).get("symbol") or "SPX")
            raw_rows = learning_store._rows(ticker, before)  # noqa: SLF001 (documented reuse)
            rows = [r for r in (_normalize_row(_mapping(x)) for x in raw_rows) if r]
            return rows, "store_v234"
        except Exception:
            return [], "store_unavailable"
    return [], "none"


# --------------------------------------------------------------------------- #
# Empirical calibration with hierarchical fallback + Bayesian shrinkage.
# --------------------------------------------------------------------------- #
def _bucket_of(confidence: float) -> tuple[int, int]:
    for low, high in CONFIDENCE_BUCKETS:
        if low <= confidence < high:
            return (low, high)
    return (90, 101)


def _win_rate(rows: Sequence[Mapping[str, Any]]) -> Optional[float]:
    if not rows:
        return None
    return sum(int(r["won"]) for r in rows) / len(rows)


def _shrink(p_hat: float, n: int, prior: float) -> tuple[float, float]:
    """Bayesian shrinkage toward ``prior`` with pseudo-count PRIOR_STRENGTH.
    Returns (calibrated_probability, shrinkage_amount in [0,1])."""
    calibrated = (n * p_hat + PRIOR_STRENGTH * prior) / (n + PRIOR_STRENGTH)
    shrinkage = PRIOR_STRENGTH / (n + PRIOR_STRENGTH)
    return calibrated, shrinkage


def calibrate_confidence(rows: list[dict[str, Any]], raw_confidence: float,
                         direction: str, regime: str) -> dict[str, Any]:
    """Hierarchical empirical calibration for a raw confidence value.

    Fallback order: direction+regime+bucket -> regime+bucket -> bucket ->
    global prior. The first level with >= PER_GROUP_MIN samples is used, but
    every level is still shrunk toward the global base rate.
    """
    global_prior = _win_rate(rows)
    total = len(rows)
    if global_prior is None or total < MIN_PROVISIONAL:
        return {
            "historical_probability": None,
            "historical_confidence": None,
            "fallback_level": "INSUFFICIENT_DATA",
            "effective_sample_size": total,
            "shrinkage_amount": 1.0,
            "global_prior_pct": _round((global_prior or 0) * 100),
        }

    bucket = _bucket_of(raw_confidence)
    direction = direction.upper()
    regime = regime.upper()

    levels = [
        ("DIRECTION_REGIME_BUCKET",
         [r for r in rows if r["direction"] == direction and r["regime"] == regime and _bucket_of(r["stated_confidence"]) == bucket]),
        ("REGIME_BUCKET",
         [r for r in rows if r["regime"] == regime and _bucket_of(r["stated_confidence"]) == bucket]),
        ("BUCKET",
         [r for r in rows if _bucket_of(r["stated_confidence"]) == bucket]),
        ("GLOBAL", list(rows)),
    ]

    chosen_label, chosen_rows = levels[-1]
    for label, group in levels:
        if len(group) >= PER_GROUP_MIN:
            chosen_label, chosen_rows = label, group
            break

    p_hat = _win_rate(chosen_rows) or global_prior
    n = len(chosen_rows)
    calibrated_p, shrinkage = _shrink(p_hat, n, global_prior)
    return {
        "historical_probability": _round(calibrated_p, 4),
        "historical_confidence": _round(_clamp(calibrated_p * 100)),
        "fallback_level": chosen_label,
        "effective_sample_size": n,
        "group_win_rate_pct": _round(p_hat * 100),
        "shrinkage_amount": _round(shrinkage, 4),
        "global_prior_pct": _round(global_prior * 100),
    }


# --------------------------------------------------------------------------- #
# Reliability metrics.
# --------------------------------------------------------------------------- #
def reliability_curve(rows: list[dict[str, Any]]) -> dict[str, Any]:
    buckets = []
    total = len(rows)
    ece = 0.0
    max_ce = 0.0
    for low, high in CONFIDENCE_BUCKETS:
        items = [r for r in rows if low <= r["stated_confidence"] < high]
        if not items:
            buckets.append({"bucket": f"{low}-{high - 1 if high <= 100 else 100}",
                            "samples": 0, "predicted": None, "actual": None,
                            "error": None, "avg_return_r": None})
            continue
        n = len(items)
        predicted = sum(r["stated_confidence"] for r in items) / n
        actual = 100 * sum(int(r["won"]) for r in items) / n
        avg_r = sum(r["realized_r"] for r in items) / n
        error = actual - predicted
        ece += abs(error) / 100 * (n / total)
        max_ce = max(max_ce, abs(error) / 100)
        buckets.append({"bucket": f"{low}-{high - 1 if high <= 100 else 100}",
                        "samples": n, "predicted": _round(predicted), "actual": _round(actual),
                        "error": _round(error), "avg_return_r": _round(avg_r, 3)})

    brier = _round(sum((r["stated_confidence"] / 100 - r["won"]) ** 2 for r in rows) / total, 4) if total else None
    high_conf = [r for r in rows if r["stated_confidence"] >= 70]
    low_conf = [r for r in rows if r["stated_confidence"] < 50]
    false_conf = _round(100 * sum(1 for r in high_conf if not r["won"]) / len(high_conf), 2) if high_conf else None
    under_conf = _round(100 * sum(1 for r in low_conf if r["won"]) / len(low_conf), 2) if low_conf else None
    return {
        "buckets": buckets,
        "brier_score": brier,
        "expected_calibration_error": _round(ece, 4),
        "max_calibration_error": _round(max_ce, 4),
        "false_confidence_rate_pct": false_conf,
        "underconfidence_rate_pct": under_conf,
        "samples": total,
    }


def detect_drift(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    if total < 10:
        return {"state": "INSUFFICIENT_DATA", "detected": False, "samples": total, "reasons": []}
    ordered = sorted(rows, key=lambda r: _text(r.get("observed_at")))
    cut = max(5, total // 2)
    old, recent = ordered[:-cut], ordered[-cut:]
    old_wr = (_win_rate(old) or 0) * 100
    new_wr = (_win_rate(recent) or 0) * 100
    old_pred = sum(r["stated_confidence"] for r in old) / len(old) if old else 0
    new_pred = sum(r["stated_confidence"] for r in recent) / len(recent) if recent else 0
    divergence = new_wr - old_wr
    reasons = []
    if new_wr < new_pred - 12:
        reasons.append("Recent confidence is overstated relative to realized win rate.")
    if new_wr > new_pred + 12:
        reasons.append("Recent confidence is understated relative to realized win rate.")
    if abs(divergence) >= 15:
        reasons.append("Recent win rate diverges materially from the long-term baseline.")
    return {
        "state": "DRIFT_DETECTED" if reasons else "STABLE",
        "detected": bool(reasons),
        "recent_samples": len(recent),
        "recent_vs_longterm_divergence_pts": _round(divergence),
        "recent_win_rate_pct": _round(new_wr),
        "recent_predicted_pct": _round(new_pred),
        "reasons": reasons,
    }


def _calibration_quality(rows: list[dict[str, Any]], curve: Mapping[str, Any]) -> str:
    n = len(rows)
    if n < MIN_PROVISIONAL:
        return "INSUFFICIENT_DATA"
    ece = _number(curve.get("expected_calibration_error"), 1.0)
    if n < MIN_ACTIVE:
        return "WEAK"
    if n < MIN_VERIFIED or ece > PROMOTION_MAX_ECE:
        return "PROVISIONAL"
    return "VERIFIED"


# --------------------------------------------------------------------------- #
# Confidence layer stack (ceiling-enforced).
# --------------------------------------------------------------------------- #
def _execution_penalty(health: Mapping[str, Any], root: Mapping[str, Any]) -> tuple[float, list[str]]:
    penalty = 0.0
    reasons = []
    state = _text(health.get("state")).upper()
    if state == "DEGRADED":
        penalty += 5
        reasons.append("Evidence health degraded (-5).")
    elif state == "UNRELIABLE":
        penalty += 15
        reasons.append("Evidence health unreliable (-15).")
    critical_degraded = _list(health.get("critical_degraded"))
    if critical_degraded:
        penalty += 10
        reasons.append(f"Critical evidence degraded: {', '.join(map(str, critical_degraded))} (-10).")
    return penalty, reasons


def _confidence_caps(quality: str, rows: list[dict[str, Any]], drift: Mapping[str, Any],
                     health: Mapping[str, Any], curve: Mapping[str, Any]) -> tuple[float, list[str]]:
    """Return (absolute cap, reasons). Conservative ceilings under weak conditions."""
    cap = 100.0
    reasons = []
    if quality == "INSUFFICIENT_DATA":
        cap = min(cap, 55.0)
        reasons.append("Insufficient calibration data: confidence capped at 55.")
    elif quality == "WEAK":
        cap = min(cap, 65.0)
        reasons.append("Weak calibration sample: confidence capped at 65.")
    elif quality == "PROVISIONAL":
        cap = min(cap, 80.0)
        reasons.append("Provisional calibration: confidence capped at 80.")
    if drift.get("detected"):
        cap = min(cap, 70.0)
        reasons.append("Drift detected: confidence capped at 70.")
    if _text(health.get("state")).upper() == "UNRELIABLE":
        cap = min(cap, 50.0)
        reasons.append("Unreliable evidence: confidence capped at 50.")
    if _number(curve.get("expected_calibration_error"), 0) > 0.15:
        cap = min(cap, 68.0)
        reasons.append("High expected calibration error: confidence capped at 68.")
    return cap, reasons


def build_calibration(payload: Optional[Mapping[str, Any]], *,
                      before: Optional[str] = None,
                      decision: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    root = payload if isinstance(payload, Mapping) else {}
    evaluated = decision if isinstance(decision, Mapping) else integrity.evaluate_decision(root)
    decision_block = _mapping(evaluated.get("decision"))
    health = _mapping(evaluated.get("evidence_health"))

    raw_confidence = _number(decision_block.get("raw_confidence"))
    integrity_adjusted = _number(decision_block.get("integrity_adjusted_confidence"))
    ceiling = _number(decision_block.get("confidence_ceiling"), 100.0)
    direction = _text(decision_block.get("direction") or "NEUTRAL")
    regime = _text(root.get("market_regime") or _mapping(root.get("market_state")).get("regime") or "UNKNOWN")

    rows, source = load_history(root, before=before)
    curve = reliability_curve(rows)
    drift = detect_drift(rows)
    quality = _calibration_quality(rows, curve)
    hist = calibrate_confidence(rows, raw_confidence, direction, regime)

    # Layer 1-2: raw -> integrity-adjusted (already ceiling-capped by 25.0).
    historical_conf = hist.get("historical_confidence")
    historical_layer = min(integrity_adjusted, historical_conf) if historical_conf is not None else integrity_adjusted
    historical_layer = min(historical_layer, ceiling)

    # Layer 3: regime adjustment via regime-specific reliability (deterministic).
    regime_rows = [r for r in rows if r["regime"] == regime.upper()]
    regime_wr = _win_rate(regime_rows)
    if regime_wr is not None and len(regime_rows) >= PER_GROUP_MIN:
        regime_target = regime_wr * 100
        regime_layer = min((historical_layer + regime_target) / 2, ceiling)
        regime_note = f"Blended with regime win rate {regime_target:.1f}% (n={len(regime_rows)})."
    else:
        regime_layer = historical_layer
        regime_note = "Insufficient regime-specific samples; no regime adjustment."

    # Layer 4: execution conditions.
    exec_penalty, exec_reasons = _execution_penalty(health, root)
    execution_layer = min(_clamp(regime_layer - exec_penalty), ceiling)

    # Layer 5: final calibrated with conservative caps; never exceeds ceiling.
    cap, cap_reasons = _confidence_caps(quality, rows, drift, health, curve)
    final_calibrated = min(execution_layer, cap, ceiling)

    layers = {
        "raw_confidence": _round(raw_confidence),
        "integrity_adjusted_confidence": _round(integrity_adjusted),
        "historical_confidence": _round(historical_layer),
        "regime_adjusted_confidence": _round(regime_layer),
        "execution_confidence": _round(execution_layer),
        "final_calibrated_confidence": _round(final_calibrated),
        "integrity_ceiling": _round(ceiling),
    }

    # Invariant: no calibrated layer may exceed the integrity ceiling.
    for name in ("historical_confidence", "regime_adjusted_confidence",
                 "execution_confidence", "final_calibrated_confidence"):
        assert layers[name] is None or layers[name] <= ceiling + 1e-9, f"{name} exceeded integrity ceiling"

    promotion = evaluate_promotion(rows, curve, drift, health, quality)

    return {
        "ok": True,
        "status": "READY" if quality != "INSUFFICIENT_DATA" else "INSUFFICIENT_DATA",
        "version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "generated_at": _iso_now(),
        "calibration": {
            "confidence_layers": layers,
            "calibration_quality": quality,
            "history_source": source,
            "sample_size": len(rows),
            "effective_sample_size": hist.get("effective_sample_size"),
            "fallback_level": hist.get("fallback_level"),
            "shrinkage_amount": hist.get("shrinkage_amount"),
            "global_prior_pct": hist.get("global_prior_pct"),
            "regime_note": regime_note,
            "execution_adjustments": exec_reasons,
            "confidence_caps": cap_reasons,
            "reliability": curve,
            "drift": drift,
            "promotion": promotion,
        },
        "guardrails": {
            "shadow_mode": shadow_mode(),
            "read_only": True,
            "advisory_only": True,
            "mutates_production_confidence": False,
            "never_exceeds_integrity_ceiling": True,
            "auto_promotion": False,
        },
        "production_effect": "NONE",
    }


# --------------------------------------------------------------------------- #
# Governed promotion (never auto-applied).
# --------------------------------------------------------------------------- #
def evaluate_promotion(rows: list[dict[str, Any]], curve: Mapping[str, Any],
                       drift: Mapping[str, Any], health: Mapping[str, Any],
                       quality: str) -> dict[str, Any]:
    import os
    blockers = []
    n = len(rows)
    if n < PROMOTION_MIN_SAMPLE:
        blockers.append(f"Sample {n} below minimum {PROMOTION_MIN_SAMPLE}.")
    ece = _number(curve.get("expected_calibration_error"), 1.0)
    if ece > PROMOTION_MAX_ECE:
        blockers.append(f"Expected calibration error {ece:.4f} above max {PROMOTION_MAX_ECE}.")
    brier = curve.get("brier_score")
    if brier is None or _number(brier, 1.0) > PROMOTION_MAX_BRIER:
        blockers.append(f"Brier score {brier} above max {PROMOTION_MAX_BRIER}.")
    if drift.get("detected"):
        blockers.append("Calibration drift detected.")
    if _list(health.get("critical_degraded")):
        blockers.append("Critical evidence health failure.")
    if quality not in {"VERIFIED", "PROVISIONAL"}:
        blockers.append(f"Calibration quality {quality} is not promotable.")

    approved = _text(os.getenv("APEX_CALIBRATION_PROMOTION_APPROVED", "false")).lower() == "true"
    prod_enabled = _text(os.getenv("APEX_CALIBRATION_PRODUCTION_ENABLED", "false")).lower() == "true"

    if blockers:
        state = "BLOCKED"
    elif not (approved and prod_enabled):
        state = "NOT_READY"
        blockers.append("Operator approval + production flag required (never auto-promoted).")
    else:
        state = "READY"

    return {
        "state": state,
        "blockers": blockers,
        "operator_approved": approved,
        "production_flag_enabled": prod_enabled,
        "criteria": {
            "min_sample": PROMOTION_MIN_SAMPLE,
            "max_ece": PROMOTION_MAX_ECE,
            "max_brier": PROMOTION_MAX_BRIER,
        },
        "auto_promotion": False,
    }


# --------------------------------------------------------------------------- #
# Mission Control + status.
# --------------------------------------------------------------------------- #
def mission_control_group(result: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    calib = _mapping((result or {}).get("calibration"))
    layers = _mapping(calib.get("confidence_layers"))
    reliability = _mapping(calib.get("reliability"))
    panel_state = "EMPTY" if not calib else (
        "INSUFFICIENT_DATA" if calib.get("calibration_quality") == "INSUFFICIENT_DATA" else "READY")
    return {
        "group": "CONFIDENCE_CALIBRATION",
        "shadow_mode": shadow_mode(),
        "panel_state": panel_state,
        "raw_confidence": layers.get("raw_confidence"),
        "integrity_confidence": layers.get("integrity_adjusted_confidence"),
        "historical_confidence": layers.get("historical_confidence"),
        "regime_confidence": layers.get("regime_adjusted_confidence"),
        "execution_confidence": layers.get("execution_confidence"),
        "final_calibrated_confidence": layers.get("final_calibrated_confidence"),
        "calibration_quality": calib.get("calibration_quality"),
        "sample_size": calib.get("sample_size"),
        "effective_sample_size": calib.get("effective_sample_size"),
        "brier_score": reliability.get("brier_score"),
        "expected_calibration_error": reliability.get("expected_calibration_error"),
        "drift_status": _mapping(calib.get("drift")).get("state"),
        "promotion_status": _mapping(calib.get("promotion")).get("state"),
        "production_effect": "NONE",
    }


def status() -> dict[str, Any]:
    return {
        "status": "READY",
        "engine": "ADAPTIVE_CONFIDENCE_CALIBRATION",
        "version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "shadow_mode": shadow_mode(),
        "read_only": True,
        "advisory_only": True,
        "min_provisional": MIN_PROVISIONAL,
        "min_active": MIN_ACTIVE,
        "min_verified": MIN_VERIFIED,
        "prior_strength": PRIOR_STRENGTH,
        "mutates_production_confidence": False,
        "auto_promotion": False,
        "production_effect": "NONE",
    }
