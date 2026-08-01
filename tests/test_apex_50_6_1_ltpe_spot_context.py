"""APEX 50.6.1 — LTPE spot context and next-session path tests."""
import tempfile

from engine import historical_level_calibration as hlce
from engine import level_transition_probability as ltpe


def _db():
    path = tempfile.mktemp(suffix=".db")
    hlce.initialize_store(path)
    ltpe.initialize_transition_store(path)
    return path


def _snapshot(price=None):
    snap = {
        "ticker": "SPX",
        "market_state": {"pdh": 6050, "pdl": 5950},
        "previous_session": {"high": 6050, "low": 5950, "close": 6000, "open": 5985},
        "gamma_regime": {"regime": "long_gamma", "call_wall": 6100,
                         "put_wall": 5900, "zero_gamma": 6000},
        "volume_profile": {"levels": {"poc": 6000, "vah": 6030, "val": 5970}},
        "expected_move_high": 6080,
        "expected_move_low": 5920,
        "vix": 14,
        "source_session_date": "2026-07-31",
        "generated_at": "2026-08-01T16:00:00+00:00",
    }
    if price is not None:
        snap["market_state"]["price"] = price
    return snap


def test_next_session_path_uses_latest_persisted_hlce_spot_when_live_spot_missing():
    path = _db()
    hlce.register_daily_levels(_snapshot(6001.25), path=path, session_date="2026-07-31")

    out = ltpe.current_transition_path(_snapshot(None), path=path, direction="UP")

    assert out["ok"] is True
    assert out["spot"] == 6001.25
    assert out["spot_mode"] == "LAST_SESSION_SPOT"
    assert out["spot_session"] == "2026-07-31"
    assert out["spot_is_observation_input"] is False
    assert out["steps"]
    for step in out["steps"][1:]:
        assert step["transition"]["probability"] is None
        assert step["transition"]["source"] == "INSUFFICIENT_HISTORY"


def test_explicit_spot_overrides_live_and_persisted_context_without_recording_observation():
    path = _db()
    hlce.register_daily_levels(_snapshot(6001.25), path=path, session_date="2026-07-31")

    out = ltpe.current_transition_path(_snapshot(6005), path=path, direction="UP", spot=6012.5)

    assert out["ok"] is True
    assert out["spot"] == 6012.5
    assert out["spot_mode"] == "EXPLICIT_SPOT"
    assert out["spot_is_observation_input"] is False
    assert ltpe.status(path=path)["observations"] == 0


def test_path_falls_back_to_prior_close_when_no_live_or_persisted_spot_exists():
    path = _db()
    out = ltpe.current_transition_path(_snapshot(None), path=path, direction="UP")
    assert out["ok"] is True
    assert out["spot"] == 6000.0
    assert out["spot_mode"] == "LAST_SESSION_CLOSE"
    assert out["spot_is_observation_input"] is False
