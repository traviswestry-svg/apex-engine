from flask import Flask
from engine.institutional_expectancy_intelligence import ExpectancyStore, build_market_fingerprint, fingerprint_similarity, build_expectancy_intelligence
from engine.premium_discipline_routes import register_premium_discipline_routes
from tests.test_institutional_premium_intelligence_18_0_9 import bus, chain_fetcher


def test_identical_fingerprint_similarity_is_100():
    fp=build_market_fingerprint(bus(), observed_at='2026-07-19T14:00:00+00:00')
    assert fingerprint_similarity(fp, fp) == 100.0


def test_expectancy_builds_history_and_playbook(tmp_path):
    store=ExpectancyStore(str(tmp_path/'e.db'))
    out=build_expectancy_intelligence(bus(), store=store, ticker='SPX', chain_fetcher=chain_fetcher, expiration='2026-07-19')
    assert out['available'] is True
    assert out['recommendation'] in {'BULL_PUT_CREDIT_SPREAD','BEAR_CALL_CREDIT_SPREAD','IRON_CONDOR','NO_TRADE'}
    assert len(out['regime_playbook']) == 3
    assert out['execution_authority'] is False


def test_grade_contributes_to_similarity_expectancy(tmp_path):
    store=ExpectancyStore(str(tmp_path/'e.db'))
    build_expectancy_intelligence(bus(), store=store, ticker='SPX', chain_fetcher=chain_fetcher, expiration='2026-07-19')
    row=store.rows('SPX')[0]
    assert store.grade(row['id'], outcome='WIN', pnl=125.0)
    out=build_expectancy_intelligence(bus(), store=store, ticker='SPX', chain_fetcher=chain_fetcher, expiration='2026-07-19')
    assert out['similar_sessions']['graded_count'] >= 1


def test_expectancy_routes(tmp_path):
    app=Flask(__name__, template_folder='../templates')
    register_premium_discipline_routes(app,last_result_provider=bus,chain_fetcher=chain_fetcher,db_path=str(tmp_path/'x.db'))
    body=app.test_client().get('/api/premium_discipline/expectancy').get_json()
    assert body['ok'] is True
    assert body['expectancy_intelligence']['version'].startswith('18.1.0')
    rows=body['expectancy_intelligence']['similar_sessions']['matches']
    assert rows
    graded=app.test_client().post('/api/premium_discipline/expectancy/grade',json={'row_id':rows[0]['id'],'pnl':100}).get_json()
    assert graded['ok'] is True
