"""Tests for APEX 25.2 Decision Outcome Forecasting Engine."""
import datetime as dt
import os
import tempfile

import pytest

from engine import decision_outcome_forecast_v252 as forecast


def _iso(offset_seconds: int = 0) -> str:
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=offset_seconds)).isoformat()


def _fresh_snapshot(**overrides):
    """A healthy, directional snapshot with sufficient analogs."""
    now = _iso()
    sessions = [
        {"session_date": "2025-01-1%d" % (d % 10), "similarity_score": 80 - d,
         "setup_family": "opening_drive", "market_regime": "trend",
         "maximum_favorable_excursion": 12 + d, "maximum_adverse_excursion": 5 + (d % 3),
         "outcome": "WIN" if d % 2 == 0 else "LOSS"}
        for d in range(14)
    ]
    snapshot = {
        "as_of": now,
        "symbol": "SPX",
        "decision_id": "dec_test_001",
        "market_state": {"spx": 5200.0, "as_of": now, "bias": "BULLISH"},
        "institutional_intelligence": {"as_of": now, "institutional_bias": "BULLISH", "ici_score": 78},
        "flow_intelligence": {"as_of": now, "direction": "BULLISH", "score": 72},
        "dealer_positioning": {"as_of": now, "bias": "BULLISH"},
        "multi_timeframe": {"as_of": now, "alignment_score": 70, "bias": "BULLISH"},
        "market_memory": {"as_of": now},
        "historical_similarity": {"as_of": now, "similarity": 0.8},
        "confidence_calibration": {"as_of": now},
        "direction": "BULLISH",
        "confidence": 82,
        "comparable_sessions": sessions,
    }
    snapshot.update(overrides)
    return snapshot


# --------------------------------------------------------------------------- #
# Unit tests
# --------------------------------------------------------------------------- #
def test_status_is_shadow_and_advisory():
    status = forecast.status()
    assert status["shadow_mode"] is True
    assert status["production_effect"] == "NONE"
    assert status["automatic_order_submission"] is False
    assert set(forecast.HORIZON_SECONDS).issuperset({"1m", "5m", "15m", "session"})


def test_build_forecast_shape_and_guardrails():
    result = forecast.build_forecast(_fresh_snapshot())
    assert result["ok"] is True
    assert result["production_effect"] == "NONE"
    guardrails = result["guardrails"]
    assert guardrails["shadow_mode"] is True
    assert guardrails["changes_execution_eligibility"] is False
    assert guardrails["mutates_production_confidence"] is False
    assert guardrails["overrides_integrity"] is False
    fc = result["forecast"]
    for key in ("forecast_id", "decision_id", "direction", "forecast_horizon",
                "expected_move_points", "expected_mfe", "expected_mae",
                "expected_grade", "forecast_quality", "scenarios"):
        assert key in fc


def test_directional_forecast_has_targets():
    fc = forecast.build_forecast(_fresh_snapshot())["forecast"]
    assert fc["direction"] == "BULLISH"
    assert fc["target_zone_1"] is not None
    assert fc["target_zone_1"] > fc["reference_price"]      # bullish target above price
    assert fc["invalidation_zone"] < fc["reference_price"]  # invalidation below price


def test_configurable_horizons_scale_magnitude():
    snap = _fresh_snapshot()
    m1 = forecast.build_forecast(snap, horizon="1m")["forecast"]["expected_move_points"]
    m30 = forecast.build_forecast(snap, horizon="30m")["forecast"]["expected_move_points"]
    assert m30 > m1  # longer horizon -> larger expected move (sqrt-of-time)


# --------------------------------------------------------------------------- #
# Determinism
# --------------------------------------------------------------------------- #
def test_forecast_is_deterministic():
    snap = _fresh_snapshot()
    a = forecast.build_forecast(snap)["forecast"]
    b = forecast.build_forecast(snap)["forecast"]
    # Ignore generated_at (wall clock); the forecast body must be identical.
    assert a == b


def test_scenarios_reconcile_to_100():
    for horizon in forecast.HORIZON_SECONDS:
        scenarios = forecast.build_forecast(_fresh_snapshot(), horizon=horizon)["forecast"]["scenarios"]
        assert sum(s["probability"] for s in scenarios) == 100


def test_neutral_direction_scenarios_reconcile():
    snap = _fresh_snapshot(direction="NEUTRAL")
    snap["market_state"]["bias"] = "NEUTRAL"
    snap["institutional_intelligence"]["institutional_bias"] = "NEUTRAL"
    scenarios = forecast.build_forecast(snap)["forecast"]["scenarios"]
    assert sum(s["probability"] for s in scenarios) == 100


# --------------------------------------------------------------------------- #
# Degraded-evidence handling: missing / stale / failed / not-configured
# --------------------------------------------------------------------------- #
def test_missing_critical_evidence_yields_insufficient_data():
    snap = _fresh_snapshot()
    snap.pop("market_state")            # critical source missing
    snap.pop("institutional_intelligence")
    result = forecast.build_forecast(snap)
    assert result["forecast"]["forecast_quality"] == "INSUFFICIENT_DATA"
    assert result["status"] == "INSUFFICIENT_DATA"


def test_stale_critical_evidence_degrades_quality():
    snap = _fresh_snapshot()
    stale = _iso(-100000)               # far older than freshness limit
    snap["market_state"]["as_of"] = stale
    snap["institutional_intelligence"]["as_of"] = stale
    result = forecast.build_forecast(snap)
    assert result["forecast"]["forecast_quality"] in {"INSUFFICIENT_DATA", "LOW"}


def test_failed_provider_not_treated_as_neutral():
    snap = _fresh_snapshot()
    snap["market_state"] = {"status": "FAILED", "error": "provider timeout"}
    snap["institutional_intelligence"] = {"status": "FAILED", "error": "auth"}
    result = forecast.build_forecast(snap)
    # A failed critical provider must not silently produce a HIGH-quality forecast.
    assert result["forecast"]["forecast_quality"] in {"INSUFFICIENT_DATA", "LOW"}


def test_insufficient_analogs_lowers_quality():
    snap = _fresh_snapshot(comparable_sessions=[])
    result = forecast.build_forecast(snap)
    assert result["forecast"]["forecast_quality"] in {"LOW", "INSUFFICIENT_DATA"}
    assert result["forecast"]["forecast_basis"] == "volatility_scaled_baseline"


# --------------------------------------------------------------------------- #
# Look-ahead protection (explicitly required for 25.2)
# --------------------------------------------------------------------------- #
def test_future_analog_sessions_are_excluded():
    now = dt.datetime.now(dt.timezone.utc)
    snap = _fresh_snapshot(as_of=now.isoformat())
    # Inject a session dated AFTER as_of; it must be dropped.
    future = (now + dt.timedelta(days=1)).isoformat()
    snap["comparable_sessions"] = snap["comparable_sessions"] + [
        {"session_date": future, "similarity_score": 99,
         "maximum_favorable_excursion": 999, "maximum_adverse_excursion": 0, "outcome": "WIN"}]
    fc = forecast.build_forecast(snap)["forecast"]
    for session in fc["comparable_sessions"]:
        assert session["session_date"] != future


def test_evaluator_refuses_immature_forecast():
    fc = forecast.build_forecast(_fresh_snapshot())["forecast"]
    result = forecast.evaluate_forecast(fc, {"realized_direction": "BULLISH"})
    assert result["ok"] is False
    assert result["status"] == "NOT_MATURED"
    assert result["seconds_remaining"] > 0


def test_evaluator_scores_matured_forecast():
    snap = _fresh_snapshot(as_of=_iso(-2000))   # issued > 30m ago
    fc = forecast.build_forecast(snap, horizon="15m")["forecast"]
    realized = {"realized_direction": "BULLISH", "realized_mfe": 10, "realized_mae": 4,
                "target_hit": True, "invalidated": False, "realized_scenario": "base",
                "realized_hold_seconds": 900}
    result = forecast.evaluate_forecast(fc, realized)
    assert result["ok"] is True
    assert result["status"] == "MATURED"
    assert result["metrics"]["direction_accuracy"] == 1.0
    assert result["metrics"]["target_hit"] is True
    assert result["metrics"]["scenario_brier"] is not None


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #
def test_persistence_round_trip(tmp_path, monkeypatch):
    db = tmp_path / "forecast.db"
    monkeypatch.setenv("APEX_DECISION_FORECAST_DB", str(db))
    result = forecast.build_forecast(_fresh_snapshot())
    persisted = forecast.persist_forecast(result, input_snapshot={"decision_id": "dec_test_001"})
    assert persisted["ok"] is True
    hist = forecast.history(limit=10)
    assert hist["count"] >= 1
    assert hist["forecasts"][0]["decision_id"] == "dec_test_001"
    assert db.exists()


def test_persist_evaluation_only_when_matured(tmp_path, monkeypatch):
    monkeypatch.setenv("APEX_DECISION_FORECAST_DB", str(tmp_path / "f.db"))
    snap = _fresh_snapshot(as_of=_iso(-2000))
    result = forecast.build_forecast(snap, horizon="15m")
    forecast.persist_forecast(result)
    fc = result["forecast"]
    realized = {"realized_direction": "BULLISH", "realized_mfe": 9, "realized_mae": 4,
                "realized_scenario": "base"}
    evaluation = forecast.evaluate_forecast(fc, realized)
    saved = forecast.persist_evaluation(fc["forecast_id"], evaluation, realized)
    assert saved["ok"] is True


# --------------------------------------------------------------------------- #
# Mission Control
# --------------------------------------------------------------------------- #
def test_mission_control_group():
    result = forecast.build_forecast(_fresh_snapshot())
    group = forecast.mission_control_group(result)
    assert group["group"] == "DECISION_OUTCOME_FORECAST"
    assert group["shadow_mode"] is True
    assert group["panel_state"] in {"READY", "EMPTY", "INSUFFICIENT_DATA"}
    assert group["production_effect"] == "NONE"


def test_empty_payload_is_safe():
    result = forecast.build_forecast({})
    assert result["ok"] is True
    assert result["production_effect"] == "NONE"
    assert forecast.mission_control_group(result)["panel_state"] in {"READY", "INSUFFICIENT_DATA"}
