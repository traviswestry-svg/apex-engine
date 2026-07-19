from flask import Flask
from engine.multi_strategy_portfolio_optimizer import build_portfolio_optimizer
from engine.institutional_expectancy_intelligence import ExpectancyStore, build_expectancy_intelligence
from engine.premium_discipline_routes import register_premium_discipline_routes
from tests.test_institutional_premium_intelligence_18_0_9 import bus, chain_fetcher


def _exp(tmp_path):
    return build_expectancy_intelligence(bus(), store=ExpectancyStore(str(tmp_path/'e.db')), ticker='SPX', chain_fetcher=chain_fetcher, expiration='2026-07-19')


def test_optimizer_is_bounded_and_advisory(tmp_path):
    out = build_portfolio_optimizer(_exp(tmp_path), account_size=60000, max_portfolio_risk=2000, max_daily_loss=2500)
    assert out['execution_authority'] is False
    assert out['portfolio_summary']['maximum_defined_risk'] <= 1800  # 3% account cap
    assert len(out['selected_positions']) <= 2


def test_optimizer_blocks_when_daily_capacity_exhausted(tmp_path):
    out = build_portfolio_optimizer(_exp(tmp_path), daily_realized_pnl=-2500, max_daily_loss=2500)
    assert out['state'] == 'BLOCKED'
    assert not out['selected_positions']


def test_optimizer_excludes_overlapping_condor(tmp_path):
    out = build_portfolio_optimizer(_exp(tmp_path), account_size=100000, max_portfolio_risk=5000)
    names = {x['strategy'] for x in out['selected_positions']}
    assert not ('IRON_CONDOR' in names and len(names) > 1)


def test_portfolio_routes(tmp_path):
    app = Flask(__name__, template_folder='../templates')
    register_premium_discipline_routes(app, last_result_provider=bus, chain_fetcher=chain_fetcher, db_path=str(tmp_path/'x.db'))
    client = app.test_client()
    for path in ('/api/premium_discipline/portfolio', '/api/premium_discipline/portfolio/allocation', '/api/premium_discipline/portfolio/risk'):
        body = client.get(path + '?account_size=60000').get_json()
        assert body['ok'] is True
        assert body['portfolio_optimizer']['version'].startswith('18.1.2')
