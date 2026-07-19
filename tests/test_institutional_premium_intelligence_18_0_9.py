from flask import Flask

from engine.institutional_premium_intelligence import classify_premium_regime, rank_premium_strategies
from engine.premium_discipline_routes import register_premium_discipline_routes


def bus():
    return {
        "market_state": {"price": 6000, "session_state": "REGULAR", "gamma_regime": "POSITIVE", "vix": 18},
        "volatility": {"vix": 18, "iv_rank_estimate": 50},
        "range_intelligence": {"range_intelligence": {"expected_move": 40, "mean_reversion_probability": 72, "expansion_probability": 25, "pin_probability": 75}},
        "institutional_intelligence": {"auction_state": "BALANCED_ROTATION", "gamma_regime": "POSITIVE", "pin_probability": 75, "flow_bias": "NEUTRAL", "flow_conviction": 20, "momentum_probability": 20, "overall_score": 80, "direction": "NEUTRAL"},
    }


def chain_fetcher(symbol, expiration, side):
    rows=[]
    for strike in range(5900, 6110, 5):
        intrinsic=max(0, 6000-strike) if side == "put" else max(0, strike-6000)
        mid=max(.25, 5.0-abs(strike-6000)*.045)+intrinsic
        rows.append({"strike": strike, "bid": max(.05, mid-.10), "ask": mid+.10, "side": side})
    return rows


def test_regime_classifies_gamma_pin():
    assert classify_premium_regime(bus())["name"] == "GAMMA_PIN"


def test_ranker_scores_all_supported_structures():
    out=rank_premium_strategies(bus(), chain_fetcher=chain_fetcher, symbol="SPX", expiration="2026-07-19")
    assert out["available"] is True
    assert len(out["rankings"]) == 3
    assert {r["strategy"] for r in out["rankings"]} == {"BULL_PUT_CREDIT_SPREAD", "BEAR_CALL_CREDIT_SPREAD", "IRON_CONDOR"}
    assert out["execution_authority"] is False
    assert out["rankings"][0]["rank"] == 1


def test_intelligence_route(tmp_path):
    app=Flask(__name__, template_folder="../templates")
    register_premium_discipline_routes(app, last_result_provider=bus, chain_fetcher=chain_fetcher, db_path=str(tmp_path/"x.db"))
    body=app.test_client().get('/api/premium_discipline/intelligence').get_json()
    assert body['ok'] is True
    assert body['premium_intelligence']['version'].startswith('18.0.9')
