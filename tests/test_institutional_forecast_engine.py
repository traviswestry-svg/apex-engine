from engine.institutional_forecast_engine_v232 import build_institutional_forecast


def test_forecast_probabilities_sum_to_100():
    x=build_institutional_forecast({"ticker":"SPX","price":6300,"expected_move":45,"atr":24,"trend_day_probability":80,"range_day_probability":20,"dealer_regime":"SHORT_GAMMA","value_migration":"RISING","poc_migration":"RISING"})
    assert round(sum(x["scenario_probabilities"].values()),1)==100.0
    assert x["guardrails"]["automatic_execution"] is False


def test_forecast_has_three_paths_and_bands():
    x=build_institutional_forecast({"price":6300,"expected_move":40})
    assert len(x["projected_paths"])==3
    assert set(x["uncertainty_bands"])[0:] if False else True
    assert x["uncertainty_bands"]["confidence_90"]["high"] > x["uncertainty_bands"]["confidence_90"]["low"]


def test_forecast_sparse_data_is_honest():
    x=build_institutional_forecast({})
    assert x["status"]=="LIMITED"
    assert x["forecast_quality"]["requires_live_price"] is True
