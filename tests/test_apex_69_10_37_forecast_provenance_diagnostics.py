from types import SimpleNamespace
from engine.forecast_provenance_diagnostics import capture
from engine.morning_brief import _deterministic_forecast_regime


def test_frozen_diagnostics_show_votes_and_straddle_path():
    dkl = SimpleNamespace(
        spot=7818.93,
        trade_map=[SimpleNamespace(condition='inside range', implication='balance', regime_hint='balance'),
                   SimpleNamespace(condition='momentum', implication='trend', regime_hint='trend'),
                   SimpleNamespace(condition='another balance', implication='balance', regime_hint='balance')],
        expected_move=SimpleNamespace(em_1sigma=27.11, straddle_implied=27.11,
                                      iv_implied=33.0, atr=45.0, avg_daily_range=75.0,
                                      upper=7846.04, lower=7791.82, confidence=.8))
    regime = _deterministic_forecast_regime(dkl)
    out = capture(dkl, regime)
    assert out['regime']['selected'] == 'Balanced Auction'
    assert out['regime']['votes'] == {'Balanced Auction': 2, 'Trend': 1}
    assert len(out['regime']['evidence_rows']) == 3
    assert out['expected_move']['selected_path'] == 'STRADDLE_FIRST'
    assert abs(out['expected_move']['implied_atm_straddle_premium'] - 27.11/.85) < 1e-8
    assert out['expected_move']['quote_timestamp'] is None
    assert out['authority'] == 'DIAGNOSTIC_ONLY_NO_FORECAST_OR_EXECUTION_CHANGE'


def test_fallback_and_missing_metadata_are_explicit():
    dkl = SimpleNamespace(spot=None, trade_map=[], expected_move=SimpleNamespace(
        em_1sigma=19, straddle_implied='[FEED REQUIRED]', iv_implied=19,
        upper=None, lower=None, atr=None, avg_daily_range=None, confidence=None))
    out = capture(dkl, _deterministic_forecast_regime(dkl))
    assert out['expected_move']['selected_path'] == 'IV_FALLBACK'
    assert out['regime']['selected'] is None
    assert out['expected_move']['atr_to_selected_ratio'] is None
    assert out['expected_move']['source_atm_iv'] is None
