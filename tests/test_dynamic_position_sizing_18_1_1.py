from flask import Flask
from engine.dynamic_position_sizing import build_position_sizing
from engine.institutional_expectancy_intelligence import ExpectancyStore, build_expectancy_intelligence
from engine.premium_discipline_routes import register_premium_discipline_routes
from tests.test_institutional_premium_intelligence_18_0_9 import bus, chain_fetcher


def _exp(tmp_path):
    return build_expectancy_intelligence(bus(), store=ExpectancyStore(str(tmp_path/'e.db')), ticker='SPX', chain_fetcher=chain_fetcher, expiration='2026-07-19')


def test_position_sizing_is_bounded_and_advisory(tmp_path):
    out=build_position_sizing(_exp(tmp_path), account_size=60000, max_risk_per_trade=2000, max_daily_loss=2500, max_contracts=3)
    assert out['execution_authority'] is False
    assert 0 <= out['recommended_contracts'] <= 3
    assert out['recommended_max_risk'] <= 1200  # 2% account cap


def test_position_sizing_blocks_when_daily_capacity_exhausted(tmp_path):
    out=build_position_sizing(_exp(tmp_path), daily_realized_pnl=-2500, max_daily_loss=2500)
    assert out['recommended_contracts'] == 0
    assert out['sizing_state'] == 'BLOCKED'


def test_position_sizing_route(tmp_path):
    app=Flask(__name__, template_folder='../templates')
    register_premium_discipline_routes(app,last_result_provider=bus,chain_fetcher=chain_fetcher,db_path=str(tmp_path/'x.db'))
    body=app.test_client().get('/api/premium_discipline/position-sizing?account_size=60000').get_json()
    assert body['ok'] is True
    assert body['position_sizing']['version'].startswith('18.1.1')
