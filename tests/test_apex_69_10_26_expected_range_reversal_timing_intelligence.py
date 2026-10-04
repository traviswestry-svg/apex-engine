import datetime as dt
import json
from pathlib import Path

from engine.range_intelligence import build_range_intelligence
from engine.range_reversal_intelligence import (
    VERSION,
    build_extension_bands,
    build_range_reversal_intelligence,
    timing_from_samples,
)

ROOT = Path(__file__).resolve().parents[1]


def _ri(low=7613.03, high=7690.05, price=7651.54, session_high=7680.0, session_low=7640.0):
    return {
        "expected_session_range": {"low": low, "high": high, "mid": round((low + high) / 2, 2)},
        "canonical": {"spot": price},
        "session_high": session_high,
        "session_low": session_low,
    }


def test_release_truth_and_capability_registration():
    manifest = json.loads((ROOT / "config" / "apex_release_manifest.json").read_text())
    assert manifest["apex_version"] == manifest["semantic_version"] == manifest["application_version"] == "69.10.33"
    g = manifest["guardrails"]
    assert g["expected_range_reversal_timing_intelligence"] is True
    assert g["range_boundary_is_not_entry_signal"] is True
    assert g["reversal_timing_changes_execution_authority"] is False
    registry = (ROOT / "config" / "apex_capability_registry.yaml").read_text()
    assert "apex_version: 69.10.33" in registry
    assert "expected_range_reversal_timing_intelligence" in registry


def test_extension_bands_use_full_expected_range_width():
    out = build_extension_bands(7613.03, 7690.05)
    assert out["available"] is True
    assert out["range_points"] == 77.02
    assert out["upper"][0] == {"percent": 10, "price": 7697.75}
    assert out["upper"][1] == {"percent": 20, "price": 7705.45}
    assert out["upper"][2] == {"percent": 30, "price": 7713.16}
    assert out["lower"][0] == {"percent": 10, "price": 7605.33}
    assert out["lower"][2] == {"percent": 30, "price": 7589.92}


def test_upper_extension_is_watch_state_not_reversal_confirmation():
    last = {"market_state": {"flow_bias": "BULLISH"}}
    out = build_range_reversal_intelligence(last, _ri(price=7700.0, session_high=7700.0))
    assert out["side"] == "UPPER"
    assert out["state"] == "EXTENSION_ACTIVE"
    assert out["location"]["extension_percent"] > 10
    assert out["governance"]["reversal_state_is_not_trade_authorization"] is True
    assert out["governance"]["execution_authority"] is False


def test_return_through_upper_envelope_plus_bearish_evidence_confirms_advisory_reversal():
    last = {
        "market_state": {"flow_bias": "BEARISH"},
        "institutional_market_structure": {
            "direction": "BEARISH",
            "acceptance_rejection": {"direction": "BEARISH"},
        },
        "market_microstructure": {
            "interaction": {"absorption_candidate": {"eligible": True, "detected": True, "side": "ASK_SELLER"}}
        },
    }
    out = build_range_reversal_intelligence(last, _ri(price=7680.0, session_high=7722.0, session_low=7670.0))
    assert out["side"] == "UPPER"
    assert out["reversal_evidence"]["rejection_proxy"]["rejected_back_inside"] is True
    assert out["reversal_evidence"]["flow"]["confirmed"] is True
    assert out["reversal_evidence"]["structure"]["confirmed"] is True
    assert out["reversal_evidence"]["absorption"]["confirmed"] is True
    assert out["reversal_evidence"]["displacement"]["confirmed"] is True
    assert out["state"] == "REVERSAL_CONFIRMED_ADVISORY"
    assert out["contract_horizon_advisory"]["preferred_dte"] == 1
    assert out["contract_horizon_advisory"]["delta_range"] == [0.45, 0.60]


def test_early_or_unconfirmed_edge_uses_more_time_not_low_delta_0dte():
    out = build_range_reversal_intelligence({}, _ri(price=7695.0, session_high=7695.0))
    assert out["state"] in {"EXTENSION_ACTIVE", "EXHAUSTION_WATCH"}
    advice = out["contract_horizon_advisory"]
    assert advice["preferred_dte"] == 2
    assert advice["delta_range"] == [0.50, 0.65]
    assert "0DTE" in advice["rationale"]


def test_lower_reversal_is_symmetric():
    last = {
        "market_state": {"flow_bias": "BULLISH"},
        "institutional_market_structure": {"direction": "BULLISH"},
    }
    out = build_range_reversal_intelligence(last, _ri(price=7620.0, session_high=7640.0, session_low=7590.0))
    assert out["side"] == "LOWER"
    assert out["reversal_evidence"]["rejection_proxy"]["rejected_back_inside"] is True
    assert out["reversal_evidence"]["flow"]["confirmed"] is True
    assert out["reversal_evidence"]["structure"]["confirmed"] is True


def test_timing_uses_genuine_samples_and_caps_gaps():
    samples = [
        {"observed_at": "2026-10-01T14:00:00+00:00", "price": 7688.0},
        {"observed_at": "2026-10-01T14:05:00+00:00", "price": 7692.0},
        {"observed_at": "2026-10-01T14:10:00+00:00", "price": 7696.0},
        {"observed_at": "2026-10-01T14:30:00+00:00", "price": 7694.0},
        {"observed_at": "2026-10-01T14:35:00+00:00", "price": 7680.0},
    ]
    now = dt.datetime(2026, 10, 1, 15, 0, tzinfo=dt.timezone.utc)
    out = timing_from_samples(samples, low=7613.03, high=7690.05, now=now)
    assert out["edge_touched"] is True
    assert out["first_touch_at"] == "2026-10-01T14:05:00+00:00"
    assert out["minutes_since_first_touch"] == 55.0
    # 14:05->14:10 = 5m, 14:10->14:30 capped at 5m, 14:30->14:35 = 5m
    assert out["observed_extreme_minutes"] == 10.0
    assert out["gap_cap_seconds"] == 300


def test_range_engine_embeds_reversal_layer_without_changing_authority():
    bus = {
        "market_state": {"price": 7680.0, "flow_bias": "BEARISH", "session_state": "REGULAR"},
        "structure": {"current_price": 7680.0, "session_high": 7722.0, "session_low": 7670.0,
                      "prev_day_high": 7710.0, "prev_day_low": 7600.0},
        "volatility": {"vix": 20.0},
        "strike_magnets": {"magnets": []},
        "institutional_market_structure": {"direction": "BEARISH"},
    }
    canon = {"spot": 7680.0, "em_low": 7613.03, "em_high": 7690.05}
    env = build_range_intelligence(bus, market_open=True, canonical=canon)
    rr = env["range_intelligence"]["reversal_timing_intelligence"]
    assert rr["available"] is True
    assert rr["version"] == VERSION
    assert rr["governance"]["changes_trade_decisions"] is False
    assert rr["governance"]["automatic_order_submission"] is False
