from engine import level_transition_probability as ltpe
from engine.historical_level_calibration import ExtractedLevel


def _level(kind, price, source="test"):
    return ExtractedLevel(kind, price, source, 1.0)


def test_zone_path_prunes_microstructure_and_far_tail():
    levels = [
        _level("vah", 7495.0, "volume_profile_engine"),
        _level("equal_lows", 7496.70, "liquidity_engine"),
        _level("swing_low", 7502.16, "liquidity_engine"),
        _level("hvn", 7508.0, "volume_profile_engine"),
        _level("prev_day_high", 7512.04, "polygon"),
        _level("hvn", 7517.0, "volume_profile_engine"),
        _level("developing_poc", 7521.0, "volume_profile_engine"),
        _level("expected_move_high", 7529.0, "computed"),
        _level("low_gamma_strike", 8000.0, "gamma_provider"),
    ]
    brief = {"structured": {"expected_move": {"one_sigma": 39.48}}}
    zones = ltpe._build_level_zones(levels, 7489.52, "UP", brief)
    assert [(z["representative_type"], z["representative_price"]) for z in zones] == [
        ("vah", 7495.0),
        ("swing_low", 7502.16),
        ("prev_day_high", 7512.04),
        ("expected_move_high", 7529.0),
    ]
    pdh = zones[2]
    assert any(z["representative_type"] == "hvn" for z in pdh.get("supporting_zones", []))
    emh = zones[3]
    assert any(z["representative_type"] == "developing_poc" for z in emh.get("supporting_zones", []))


def test_zone_probability_never_fabricates(tmp_path):
    db = str(tmp_path / "hlce.db")
    src = {"members": [{"level_type": "prev_day_high"}]}
    tgt = {"members": [{"level_type": "expected_move_high"}]}
    out = ltpe._zone_probability("SPX", src, tgt, "UP", {}, path=db)
    assert out["probability"] is None
    assert out["sample_count"] == 0
    assert out["source"] == "INSUFFICIENT_HISTORY"
    assert out["path_intelligence_version"] == "50.6.5_INSTITUTIONAL_LEVEL_PATH_INTELLIGENCE"
