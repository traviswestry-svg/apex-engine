"""APEX 50.6.0 — Level Transition Probability Engine tests."""
import tempfile

from engine import historical_level_calibration as hlce
from engine import level_transition_probability as ltpe


def _db():
    path = tempfile.mktemp(suffix=".db")
    hlce.initialize_store(path)
    ltpe.initialize_transition_store(path)
    return path


def _snapshot(price):
    return {
        "ticker": "SPX",
        "market_state": {"price": price, "pdh": 6050, "pdl": 5950},
        "previous_session": {"high": 6050, "low": 5950, "close": 6000, "open": 5985},
        "gamma_regime": {"regime": "long_gamma", "call_wall": 6100,
                         "put_wall": 5900, "zero_gamma": 6000},
        "volume_profile": {"levels": {"poc": 6000, "vah": 6030, "val": 5970}},
        "expected_move_high": 6080,
        "expected_move_low": 5920,
        "vix": 14,
        "generated_at": "2026-07-06T14:00:00+00:00",
    }


def _seed_bullish_pdh_transition(path):
    svc = hlce.CalibrationService(path)
    # Old timestamps ensure HLCE outcome maturity without waiting. Price approaches
    # PDH 6050 from below, accepts above it, and reaches EM high 6080.
    t = 1_784_000_000.0
    prices = [6025, 6040, 6048, 6050, 6053, 6060, 6070, 6078, 6081, 6085, 6090]
    for p in prices:
        svc.collector.observe(_snapshot(p), now=t)
        t += 20
    # Mature all first-touch outcomes after the 30m horizon.
    hlce.run_grader(path=path, horizon_seconds=120, now=t + 500)
    return ltpe.process_transition_outcomes(path=path, horizon_seconds=120)


def test_transition_store_is_additive_to_hlce_schema():
    path = _db()
    out = ltpe.status(path=path)
    assert out["ok"] is True
    assert out["observations"] == 0
    assert out["probability_policy"] == "EVIDENCE_ONLY_NO_FABRICATION"


def test_accepted_pdh_records_expected_move_as_next_target():
    path = _db()
    result = _seed_bullish_pdh_transition(path)
    assert result["recorded"] >= 1
    history = ltpe.transition_history(symbol="SPX", source_level_type="prev_day_high", path=path)
    rows = [r for r in history["rows"] if r["source_event"] == "ACCEPTED" and r["direction"] == "UP"]
    assert rows, history
    row = rows[0]
    assert row["target_level_type"] == "expected_move_high"
    assert row["target_reached"] == 1
    assert row["seconds_to_target"] is not None
    assert row["mfe"] >= row["target_distance"] - 3.0  # target touch band is allowed
    assert row["mae"] >= 0


def test_rebuild_statistics_produces_conditional_transition_probability():
    path = _db()
    _seed_bullish_pdh_transition(path)
    rebuilt = ltpe.rebuild_transition_statistics(path=path)
    assert rebuilt["statistics_written"] >= 1
    out = ltpe.next_level_probability(
        "SPX", "prev_day_high", "ACCEPTED", "UP",
        target_level_type="expected_move_high", path=path,
    )
    assert out["sample_count"] >= 1
    assert out["probability"] == 1.0
    assert out["source"] == "EARLY_HISTORY"  # sample exists, but not enough to call stable history
    assert out["ci_low"] is not None and out["ci_high"] is not None


def test_empty_history_never_fabricates_probability():
    path = _db()
    out = ltpe.next_level_probability(
        "SPX", "prev_day_high", "ACCEPTED", "UP",
        target_level_type="expected_move_high", path=path,
    )
    assert out["probability"] is None
    assert out["sample_count"] == 0
    assert out["source"] == "INSUFFICIENT_HISTORY"


def test_current_path_is_evidence_only_when_database_empty():
    path = _db()
    out = ltpe.current_transition_path(_snapshot(6000), path=path, direction="UP")
    assert out["ok"] is True
    assert out["probability_policy"] == "EVIDENCE_ONLY_NO_FABRICATION"
    assert out["steps"]
    # The first step is simply the next visible level. Later edges carry historical
    # evidence if available; with an empty DB they must not invent one.
    for step in out["steps"][1:]:
        assert step["transition"]["probability"] is None
        assert step["transition"]["source"] == "INSUFFICIENT_HISTORY"


def test_rejection_direction_moves_back_to_approach_side():
    assert ltpe._direction("REJECTED", "FROM_BELOW") == "DOWN"
    assert ltpe._direction("REJECTED", "FROM_ABOVE") == "UP"
    assert ltpe._direction("ACCEPTED", "FROM_BELOW") == "UP"
    assert ltpe._direction("ACCEPTED", "FROM_ABOVE") == "DOWN"
