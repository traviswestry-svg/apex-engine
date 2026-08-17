from datetime import datetime, timezone
from flask import Flask

from engine.breadth_regime import build_breadth_regime
from engine.breadth_regime_routes import register_breadth_regime_routes


NOW = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)


def test_missing_bpspx_fails_closed_without_direction():
    result = build_breadth_regime({"ticker": "SPX"}, now=NOW)
    assert result["state"] == "DATA_LIMITED"
    assert result["bpspx"] is None
    assert result["execution_authority"] == "NONE"


def test_sub_15_falling_is_capitulation_not_buy_signal():
    result = build_breadth_regime({"bpspx": 14.0, "bpspx_previous": 18.0, "bpspx_observed_at": "2026-08-17T11:30:00+00:00"}, now=NOW)
    assert result["state"] == "CAPITULATION"
    assert result["horizon_influence"]["SCALP"]["authority"] == "CONTEXT_ONLY"
    assert result["guardrails"]["automatic_entry"] is False


def test_rising_from_extreme_is_early_not_confirmed_recovery():
    result = build_breadth_regime({"bpspx": 19.0, "bpspx_previous": 14.0, "bpspx_observed_at": "2026-08-17T11:30:00+00:00"}, now=NOW)
    assert result["state"] == "EARLY_RECOVERY"
    assert result["recovery_confirmed"] is False
    assert result["horizon_influence"]["SWING"]["effect"] == "BULLISH_WATCH"


def test_cross_above_30_confirms_recovery():
    result = build_breadth_regime({"bpspx": 32.0, "bpspx_previous": 27.0, "bpspx_observed_at": "2026-08-17T11:30:00+00:00"}, now=NOW)
    assert result["state"] == "CONFIRMED_RECOVERY"
    assert result["recovery_confirmed"] is True


def test_routes_expose_dashboard_payload():
    app = Flask(__name__)
    register_breadth_regime_routes(app, last_result_provider=lambda: {"bpspx": 14, "bpspx_previous": 18, "bpspx_observed_at": "2026-08-17T11:30:00+00:00"})
    response = app.test_client().get("/api/breadth-regime/status")
    assert response.status_code == 200
    assert response.get_json()["state"] == "CAPITULATION"
