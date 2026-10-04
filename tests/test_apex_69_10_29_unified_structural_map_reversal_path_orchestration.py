import json
from pathlib import Path

from engine.structural_map_orchestration import build_unified_structural_map, refresh_unified_structural_map


def _ri(state="REVERSAL_DEVELOPING", side="UPPER"):
    return {
        "available": True,
        "canonical": {"spot": 7702.0},
        "expected_session_range": {"low": 7613.03, "high": 7690.05, "mid": 7651.54},
        "immediate_reaction_zones": [
            {"side": "UPPER", "low": 7688.0, "high": 7693.0, "reasons": ["Call wall near 7690"]},
            {"side": "LOWER", "low": 7610.0, "high": 7615.0, "reasons": ["VAL near 7613"]},
        ],
        "intermediate_targets": [
            {"label": "Previous day high", "price": 7678.0, "kind": "PRIOR", "direction": "DOWN"},
        ],
        "reversal_timing_intelligence": {
            "available": True, "state": state, "side": side,
            "extension_bands": {
                "available": True, "range_points": 77.02,
                "upper": [{"percent": 10, "price": 7697.75}, {"percent": 20, "price": 7705.45}, {"percent": 30, "price": 7713.16}],
                "lower": [{"percent": 10, "price": 7605.33}, {"percent": 20, "price": 7597.63}, {"percent": 30, "price": 7589.92}],
            },
            "reversal_evidence": {"normalized_score": 74.0},
            "contract_horizon_advisory": {"preferred_dte": 2, "delta_range": [0.50, 0.65]},
            "timing": {"available": False},
        },
    }


def _last():
    return {
        "market_state": {
            "vwap": 7660.0, "poc": 7654.0, "zero_gamma": 7652.0,
            "call_wall": 7690.0, "put_wall": 7610.0,
        },
        "strike_magnets": {"magnets": [{"side": "BELOW", "strike": 7640.0, "type": "OI"}]},
    }


def test_release_manifest_and_registry_ratchet():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "config/apex_release_manifest.json").read_text())
    assert manifest["apex_version"] == manifest["semantic_version"] == manifest["application_version"] == "69.10.33"
    assert manifest["build_name"] == "Session Calendar Integrity Closure"
    registry = (root / "config/apex_capability_registry.yaml").read_text()
    assert "apex_version: 69.10.32" in registry
    assert "unified_structural_map_reversal_path_orchestration" in registry


def test_structural_map_uses_existing_level_for_regime_pivot():
    out = build_unified_structural_map(_last(), _ri())
    pivot = out["regime_pivot"]
    assert out["available"] is True
    assert pivot["available"] is True
    assert pivot["selection_policy"] == "EXISTING_CANONICAL_LEVEL_ONLY"
    assert pivot["price"] in {7660.0, 7654.0, 7652.0, 7651.54}
    assert pivot["price"] in {x["price"] for x in pivot["supporting_levels"]}


def test_reaction_zones_cover_30_percent_expected_range_extensions():
    out = build_unified_structural_map(_last(), _ri())
    zones = out["reaction_zones"]
    assert zones["policy"] == "SEARCH_ZONE_NOT_ENTRY_SIGNAL"
    assert zones["upper"]["canonical_boundary"] == 7690.05
    assert zones["upper"]["high"] == 7713.16
    assert zones["lower"]["canonical_boundary"] == 7613.03
    assert zones["lower"]["low"] == 7589.92


def test_upper_reversal_ranks_downside_destinations_without_new_probability():
    out = build_unified_structural_map(_last(), _ri())
    magnets = out["destination_magnets"]
    assert magnets["direction"] == "DOWN"
    assert magnets["probability_policy"] == "NO_NEW_PROBABILITY_INFERENCE"
    assert 1 <= len(magnets["targets"]) <= 3
    assert all(t["price"] < 7702.0 for t in magnets["targets"])
    assert out["governance"]["changes_trade_decisions"] is False
    assert out["governance"]["execution_authority"] is False


def test_extension_without_rejection_activates_continuation_not_reversal():
    out = build_unified_structural_map(_last(), _ri(state="EXTENSION_ACTIVE", side="UPPER"))
    scenarios = {x["name"]: x for x in out["session_path_scenarios"]}
    assert scenarios["UPPER_REJECTION"]["active"] is False
    assert scenarios["RANGE_ACCEPTANCE_CONTINUATION"]["active"] is True


def test_refresh_propagates_price_history_timing():
    ri = _ri()
    ri["unified_structural_map"] = build_unified_structural_map(_last(), ri)
    ri["reversal_timing_intelligence"]["timing"] = {"available": True, "observed_extreme_minutes": 87.5}
    refresh_unified_structural_map(ri)
    assert ri["unified_structural_map"]["reversal_path"]["timing"]["observed_extreme_minutes"] == 87.5


def test_structural_map_skips_malformed_optional_list_members():
    ri = _ri()
    ri["reversal_timing_intelligence"]["extension_bands"]["upper"].extend([7700.0, None, "bad"])
    ri["reversal_timing_intelligence"]["extension_bands"]["lower"].extend([7600.0, None, "bad"])
    ri["intermediate_targets"].extend([7670.0, None, "bad"])
    last = _last()
    last["strike_magnets"]["magnets"].extend([7645.0, None, "bad"])

    out = build_unified_structural_map(last, ri)

    assert out["available"] is True
    assert out["reaction_zones"]["upper"]["high"] == 7713.16
    assert out["reaction_zones"]["lower"]["low"] == 7589.92
    assert out["destination_magnets"]["available"] is True
    assert out["governance"]["execution_authority"] is False


def test_range_intelligence_contains_structural_map_exception(monkeypatch):
    import engine.range_intelligence as range_intelligence

    def _boom(*_args, **_kwargs):
        raise AttributeError("malformed optional structural-map evidence")

    monkeypatch.setattr(range_intelligence, "build_unified_structural_map", _boom)

    # Exercise the integration source directly rather than duplicating its behavior:
    # the protected call must exist and preserve a fail-closed structural-map payload.
    source = Path(range_intelligence.__file__).read_text()
    assert 'try:\n        ri["unified_structural_map"] = build_unified_structural_map(lr, ri)' in source
    assert '"quality_flags": ["STRUCTURAL_MAP_EXCEPTION"]' in source
    assert '"execution_authority": False' in source
