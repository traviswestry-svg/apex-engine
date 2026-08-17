from datetime import datetime, timezone

from engine.breadth_regime import build_breadth_regime


NOW = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)


def test_missing_timestamp_fails_closed_even_with_value():
    result = build_breadth_regime({"bpspx": 42.0}, now=NOW)
    assert result["state"] == "DATA_LIMITED"
    assert result["freshness"]["state"] == "DATA_LIMITED"
    assert result["freshness"]["usable"] is False


def test_current_session_observation_is_usable():
    result = build_breadth_regime(
        {"bpspx": 42.0, "bpspx_previous": 40.0, "bpspx_observed_at": "2026-08-17T11:30:00+00:00", "market_open": True},
        now=NOW,
    )
    assert result["status"] == "READY"
    assert result["freshness"]["state"] == "CURRENT_SESSION"
    assert result["freshness"]["usable"] is True


def test_stale_open_session_observation_suppresses_influence():
    result = build_breadth_regime(
        {"bpspx": 42.0, "bpspx_previous": 40.0, "bpspx_observed_at": "2026-08-15T11:30:00+00:00", "market_open": True},
        now=NOW,
    )
    assert result["state"] == "DATA_LIMITED"
    assert result["freshness"]["state"] == "STALE"
    assert result["horizon_influence"]["INTRADAY"]["weight"] == 0.0


def test_prior_settled_session_allowed_when_market_closed():
    result = build_breadth_regime(
        {"bpspx": 42.0, "bpspx_previous": 40.0, "bpspx_observed_at": "2026-08-14T20:00:00+00:00", "market_open": False},
        now=NOW,
    )
    assert result["status"] == "READY"
    assert result["freshness"]["state"] == "PRIOR_SETTLED_SESSION"


def test_old_weekend_carry_forward_becomes_stale():
    result = build_breadth_regime(
        {"bpspx": 42.0, "bpspx_observed_at": "2026-08-10T20:00:00+00:00", "market_open": False},
        now=NOW,
    )
    assert result["state"] == "DATA_LIMITED"
    assert result["freshness"]["state"] == "STALE"


def test_invalid_timestamp_is_data_limited():
    result = build_breadth_regime({"bpspx": 42.0, "bpspx_observed_at": "not-a-time", "market_open": True}, now=NOW)
    assert result["state"] == "DATA_LIMITED"
    assert result["freshness"]["reason"] == "bpspx_observed_at_missing_or_invalid"
