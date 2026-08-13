from engine.trade_director_cross_asset import build_cross_asset_snapshot, build_cross_asset_intelligence


def test_cached_only_bullish_confirmation():
    cached={"cross_asset":{"ES":{"change_pct":0.4},"NQ":{"change_pct":0.7},"VIX":{"change_pct":-1.0},"HYG":{"change_pct":0.1},"BREADTH":{"bias":"bullish"}}}
    result=build_cross_asset_intelligence(build_cross_asset_snapshot(cached,{"expected_path":"UP"}),{"expected_path":"UP"})
    assert result["data_policy"] == "CACHED_ONLY"
    assert result["spx_confirmation_score"] > 50
    assert result["cross_asset_bias"] == "BULLISH"


def test_vix_divergence_is_high_severity():
    cached={"cross_asset":{"ES":{"change_pct":0.4},"VIX":{"change_pct":1.2}}}
    result=build_cross_asset_intelligence(build_cross_asset_snapshot(cached,{"expected_path":"UP"}),{"expected_path":"UP"})
    assert any(x["asset"] == "VIX" and x["severity"] == "HIGH" for x in result["divergences"])
    assert result["trade_director_effect"]["sizing_posture"] == "REDUCED"


def test_missing_assets_fail_to_data_limited_not_bullish():
    result=build_cross_asset_intelligence(build_cross_asset_snapshot({},{}),{})
    assert result["coverage_pct"] == 0
    assert result["cross_asset_bias"] == "NEUTRAL"
    assert result["lead_lag"]["status"] == "DATA_LIMITED"


def test_historical_comparable_sessions_are_returned():
    cached={"cross_asset":{"NQ":{"change_pct":0.8},"ES":{"change_pct":0.5}}}
    snapshot=build_cross_asset_snapshot(cached,{"expected_path":"UP"})
    base=build_cross_asset_intelligence(snapshot,{"expected_path":"UP"})
    history=[{"session_date":"2026-07-01","snapshot":{"cross_asset_regime":base["regime"],"spx_confirmation_score":base["spx_confirmation_score"]},"outcome":{"realized_pnl":500}}]
    result=build_cross_asset_intelligence(snapshot,{"expected_path":"UP"},history)
    assert result["historical_cross_asset_memory"]["sample_count"] == 1


def test_execution_authority_remains_outside_phase13():
    result=build_cross_asset_intelligence(build_cross_asset_snapshot({},{}),{})
    assert "Phase 9 and Phase 10 remain authoritative" in result["trade_director_effect"]["execution_note"]
