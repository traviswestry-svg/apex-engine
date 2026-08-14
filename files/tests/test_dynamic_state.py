"""Tests for the dynamic-state dashboard aggregator (engine.dynamic_state)."""
from engine.dynamic_state import build_dynamic_state


def _bus():
    return {
        "institutional_options_flow": {
            "flow_excitation": {"available": True, "state": "HIGH_EXCITATION",
                                "excitation_ratio": 2.4, "burst_count": 1, "event_count": 4,
                                "independent_evidence_factor": 0.25, "redundancy_factor": 0.75,
                                "same_burst_probability": 1.0},
            "independent_evidence_factor": 0.25,
        },
        "execution_intelligence": {
            "residual_pressure_memory": {"state": "RESIDUAL_PRESSURE", "direction": "BULLISH",
                                         "remaining_pressure": 42.0, "initial_pressure": 80.0,
                                         "origin_level": 7400, "unresolved": True,
                                         "absorption_signal": "HIGH_ABSORPTION"},
        },
        "dealer_positioning": {
            "gamma_path": {"available": True, "current_regime": "POSITIVE_GAMMA",
                           "active_flip": 7375.0,
                           "upside_destination": {"price": 7450.0, "label": "Call wall"},
                           "downside_destination": {"price": 7300.0, "label": "Put wall"},
                           "path_levels": [{"price": 7400, "net": 20}, {"price": 7450, "net": 30}]},
        },
    }


def test_all_three_signals_surfaced():
    d = build_dynamic_state(_bus())
    assert d["available"] is True
    assert d["flow_excitation"]["state"] == "HIGH_EXCITATION"
    assert d["residual_pressure"]["state"] == "RESIDUAL_PRESSURE"
    assert d["gamma_path"]["current_regime"] == "POSITIVE_GAMMA"


def test_flow_independence_surfaced():
    d = build_dynamic_state(_bus())
    assert d["flow_excitation"]["independent_evidence_factor"] == 0.25
    assert d["flow_excitation"]["redundancy_factor"] == 0.75
    assert "one repeated burst" in (d["summary"] or "")


def test_gamma_path_destinations():
    d = build_dynamic_state(_bus())
    gp = d["gamma_path"]
    assert gp["upside_destination"]["price"] == 7450.0
    assert gp["downside_destination"]["price"] == 7300.0
    assert len(gp["path_levels"]) == 2


def test_residual_from_scanner_state_fallback():
    lr = {"institutional_options_flow": {"flow_excitation": {"available": True, "state": "NORMAL",
          "excitation_ratio": 1.0, "burst_count": 2, "independent_evidence_factor": 1.0}}}
    ss = {"residual_pressure_memory": {"state": "ACTIVE", "direction": "BEARISH",
                                       "remaining_pressure": 60.0, "unresolved": True}}
    d = build_dynamic_state(lr, ss)
    assert d["residual_pressure"]["state"] == "ACTIVE"
    assert d["residual_pressure"]["direction"] == "BEARISH"


def test_empty_bus_is_unavailable_not_error():
    d = build_dynamic_state(None)
    assert d["available"] is False
    assert d["flow_excitation"]["available"] is False
    assert d["residual_pressure"]["available"] is False
    assert d["gamma_path"]["available"] is False


def test_never_raises_on_garbage():
    for bad in [42, "x", {"institutional_options_flow": "nope"}, {"gamma": {"gamma_path": 5}}]:
        d = build_dynamic_state(bad)
        assert "available" in d
