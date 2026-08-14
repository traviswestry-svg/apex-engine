from datetime import datetime, timedelta, timezone

from engine.flow_excitation import build_flow_excitation
from engine.residual_pressure_memory import evolve_residual_pressure
from engine.gamma import _build_gamma_path


def test_flow_excitation_collapses_same_burst_evidence():
    now = datetime(2026, 8, 14, 14, 0, tzinfo=timezone.utc)
    rows = [
        {"timestamp": (now-timedelta(seconds=s)).isoformat(), "symbol":"SPX", "side":"CALL", "option_type":"CALL", "strike":7400, "premium":100000}
        for s in (50, 35, 20, 5)
    ]
    out = build_flow_excitation(rows, now=now)
    assert out["burst_count"] == 1
    assert out["same_burst_probability"] == 1.0
    assert out["independent_evidence_factor"] < 0.5
    assert out["redundancy_factor"] > 0.5


def test_flow_excitation_separates_independent_bursts():
    now = datetime(2026, 8, 14, 14, 0, tzinfo=timezone.utc)
    rows = [
        {"timestamp": (now-timedelta(seconds=300)).isoformat(), "symbol":"SPX", "side":"CALL", "strike":7400},
        {"timestamp": (now-timedelta(seconds=5)).isoformat(), "symbol":"SPX", "side":"PUT", "strike":7350},
    ]
    out = build_flow_excitation(rows, now=now)
    assert out["burst_count"] == 2
    assert out["independent_evidence_factor"] == 1.0


def test_residual_pressure_survives_containment_then_decays():
    now = datetime(2026, 8, 14, 14, 0, tzinfo=timezone.utc)
    first = evolve_residual_pressure(None, direction="BULLISH", pressure_score=80,
        absorption_signal="HIGH_ABSORPTION", absorption_score=85,
        acceptance_state="REJECTING", level=7400, price_response=0.2, now=now)
    assert first["state"] == "RESIDUAL_PRESSURE"
    assert first["unresolved"] is True
    later = evolve_residual_pressure(first, direction="BULLISH", pressure_score=10,
        absorption_signal="NEUTRAL", absorption_score=30, acceptance_state="UNKNOWN",
        level=7400, price_response=0.1, now=now+timedelta(minutes=20))
    assert later["remaining_pressure"] < first["remaining_pressure"]


def test_gamma_path_is_spatial_not_scalar():
    curve = {
        7300.0: {"net": -10.0},
        7350.0: {"net": -5.0},
        7400.0: {"net": 20.0},
        7450.0: {"net": 30.0},
    }
    out = _build_gamma_path(curve, 7375.0, active_flip=7375.0, call_wall=7450.0,
                            put_wall=7300.0, high_gamma=7450.0, low_gamma=7300.0)
    assert out["available"] is True
    assert out["upside_destination"]["price"] == 7450.0
    assert out["downside_destination"]["price"] == 7300.0
    assert len(out["path_levels"]) >= 3
