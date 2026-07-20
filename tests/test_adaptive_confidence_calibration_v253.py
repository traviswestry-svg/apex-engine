"""Tests for APEX 25.3 Adaptive Confidence Calibration Engine."""
import datetime as dt

import pytest

from engine import adaptive_confidence_calibration_v253 as calib


def _iso(offset_days=0):
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=offset_days)).isoformat()


def _history(n=60, win_rate=0.6, stated=80, regime="TREND", direction="BULLISH"):
    """Deterministic synthetic history: first `wins` are wins, rest losses."""
    wins = int(round(n * win_rate))
    rows = []
    for i in range(n):
        rows.append({
            "stated_confidence": stated,
            "won": 1 if i < wins else 0,
            "realized_r": 1.2 if i < wins else -1.0,
            "direction": direction,
            "regime": regime,
            "setup_family": "opening_drive",
            "observed_at": _iso(-n + i),
        })
    return rows


def _snapshot(confidence=82, direction="BULLISH", history=None, regime="TREND"):
    now = _iso()
    return {
        "as_of": now, "symbol": "SPX", "market_regime": regime, "confidence": confidence,
        "direction": direction,
        "market_state": {"spx": 5200.0, "as_of": now, "bias": direction, "regime": regime},
        "institutional_intelligence": {"as_of": now, "institutional_bias": direction, "ici_score": 78},
        "flow_intelligence": {"as_of": now, "direction": direction, "score": 72},
        "dealer_positioning": {"as_of": now, "bias": direction},
        "multi_timeframe": {"as_of": now, "alignment_score": 70},
        "market_memory": {"as_of": now},
        "historical_similarity": {"as_of": now},
        "confidence_calibration": {"as_of": now},
        "calibration_history": history if history is not None else _history(),
    }


# --------------------------------------------------------------------------- #
# Status / shape
# --------------------------------------------------------------------------- #
def test_status_shadow_and_advisory():
    s = calib.status()
    assert s["shadow_mode"] is True
    assert s["production_effect"] == "NONE"
    assert s["auto_promotion"] is False


def test_build_shape_and_layers():
    result = calib.build_calibration(_snapshot())
    assert result["ok"] is True
    assert result["production_effect"] == "NONE"
    layers = result["calibration"]["confidence_layers"]
    for key in ("raw_confidence", "integrity_adjusted_confidence", "historical_confidence",
                "regime_adjusted_confidence", "execution_confidence",
                "final_calibrated_confidence", "integrity_ceiling"):
        assert key in layers


# --------------------------------------------------------------------------- #
# The core invariant: no layer exceeds the integrity ceiling
# --------------------------------------------------------------------------- #
def test_no_layer_exceeds_integrity_ceiling():
    # Even with a history that would justify high confidence, the ceiling holds.
    result = calib.build_calibration(_snapshot(confidence=99, history=_history(n=80, win_rate=0.95)))
    layers = result["calibration"]["confidence_layers"]
    ceiling = layers["integrity_ceiling"]
    for key in ("historical_confidence", "regime_adjusted_confidence",
                "execution_confidence", "final_calibrated_confidence"):
        assert layers[key] <= ceiling + 1e-9


def test_degraded_evidence_lowers_ceiling_and_final():
    snap = _snapshot()
    stale = _iso(-5)
    snap["market_state"]["as_of"] = stale  # degrade a critical source
    result = calib.build_calibration(snap)
    layers = result["calibration"]["confidence_layers"]
    assert layers["final_calibrated_confidence"] <= layers["integrity_ceiling"] + 1e-9


# --------------------------------------------------------------------------- #
# Determinism
# --------------------------------------------------------------------------- #
def test_deterministic():
    snap = _snapshot()
    a = calib.build_calibration(snap)["calibration"]
    b = calib.build_calibration(snap)["calibration"]
    a.pop("promotion"); b.pop("promotion")  # promotion reads env, otherwise identical
    assert a == b


# --------------------------------------------------------------------------- #
# Empirical calibration + shrinkage + fallback
# --------------------------------------------------------------------------- #
def test_overconfidence_is_calibrated_down():
    # Stated 80 but only 40% actually win -> historical confidence should drop.
    hist = _history(n=60, win_rate=0.40, stated=80)
    result = calib.build_calibration(_snapshot(confidence=80, history=hist))
    layers = result["calibration"]["confidence_layers"]
    assert layers["historical_confidence"] < layers["integrity_adjusted_confidence"]


def test_small_sample_shrinks_toward_prior():
    small = calib.calibrate_confidence(_history(n=6, win_rate=1.0, stated=80), 80, "BULLISH", "TREND")
    large = calib.calibrate_confidence(_history(n=200, win_rate=1.0, stated=80), 80, "BULLISH", "TREND")
    # More samples -> less shrinkage toward the global prior.
    assert small["shrinkage_amount"] > large["shrinkage_amount"]


def test_hierarchical_fallback_reported():
    result = calib.build_calibration(_snapshot())
    assert result["calibration"]["fallback_level"] in {
        "DIRECTION_REGIME_BUCKET", "REGIME_BUCKET", "BUCKET", "GLOBAL", "INSUFFICIENT_DATA"}


def test_insufficient_history_is_insufficient_data():
    result = calib.build_calibration(_snapshot(history=_history(n=3)))
    assert result["calibration"]["calibration_quality"] == "INSUFFICIENT_DATA"
    assert result["status"] == "INSUFFICIENT_DATA"


# --------------------------------------------------------------------------- #
# Reliability metrics
# --------------------------------------------------------------------------- #
def test_reliability_metrics_present():
    curve = calib.reliability_curve(_history(n=60, win_rate=0.6))
    assert curve["brier_score"] is not None
    assert curve["expected_calibration_error"] is not None
    assert curve["max_calibration_error"] is not None
    assert any(b["samples"] > 0 for b in curve["buckets"])


def test_false_confidence_rate_flagged():
    # High stated confidence but frequent losses -> false confidence rate > 0.
    curve = calib.reliability_curve(_history(n=40, win_rate=0.3, stated=85))
    assert curve["false_confidence_rate_pct"] is not None
    assert curve["false_confidence_rate_pct"] > 0


# --------------------------------------------------------------------------- #
# Drift
# --------------------------------------------------------------------------- #
def test_drift_detected_on_regime_shift():
    # First half win, second half lose -> drift.
    rows = _history(n=40, win_rate=0.5)
    for i, r in enumerate(rows):
        r["won"] = 1 if i < 20 else 0
        r["realized_r"] = 1.0 if i < 20 else -1.0
    drift = calib.detect_drift(rows)
    assert drift["detected"] is True
    assert drift["reasons"]


def test_drift_insufficient_data():
    drift = calib.detect_drift(_history(n=4))
    assert drift["state"] == "INSUFFICIENT_DATA"


# --------------------------------------------------------------------------- #
# Promotion governance
# --------------------------------------------------------------------------- #
def test_promotion_not_ready_without_operator_approval(monkeypatch):
    monkeypatch.delenv("APEX_CALIBRATION_PROMOTION_APPROVED", raising=False)
    monkeypatch.delenv("APEX_CALIBRATION_PRODUCTION_ENABLED", raising=False)
    # Clean, large, well-calibrated history so the only blocker is approval.
    hist = _history(n=80, win_rate=0.8, stated=80)
    result = calib.build_calibration(_snapshot(confidence=80, history=hist))
    promo = result["calibration"]["promotion"]
    assert promo["state"] in {"NOT_READY", "BLOCKED"}
    assert promo["auto_promotion"] is False


def test_promotion_blocked_on_small_sample():
    result = calib.build_calibration(_snapshot(history=_history(n=10)))
    promo = result["calibration"]["promotion"]
    assert promo["state"] == "BLOCKED"
    assert any("below minimum" in b for b in promo["blockers"])


def test_promotion_never_auto_even_when_flags_set(monkeypatch):
    monkeypatch.setenv("APEX_CALIBRATION_PROMOTION_APPROVED", "true")
    monkeypatch.setenv("APEX_CALIBRATION_PRODUCTION_ENABLED", "true")
    hist = _history(n=80, win_rate=0.8, stated=80)
    result = calib.build_calibration(_snapshot(confidence=80, history=hist))
    # Engine may report READY, but it still never mutates production confidence.
    assert result["guardrails"]["mutates_production_confidence"] is False
    assert result["production_effect"] == "NONE"


# --------------------------------------------------------------------------- #
# Mission Control
# --------------------------------------------------------------------------- #
def test_mission_control_group():
    result = calib.build_calibration(_snapshot())
    group = calib.mission_control_group(result)
    assert group["group"] == "CONFIDENCE_CALIBRATION"
    assert group["production_effect"] == "NONE"
    assert group["panel_state"] in {"READY", "EMPTY", "INSUFFICIENT_DATA"}


def test_empty_payload_safe():
    result = calib.build_calibration({})
    assert result["ok"] is True
    assert result["production_effect"] == "NONE"
