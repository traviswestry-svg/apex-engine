import datetime as dt

from engine.portfolio_outcome_attribution import PortfolioOutcomeStore, replay_due_portfolios
from engine.premium_discipline_routes import register_premium_discipline_routes


def _portfolio():
    return {
        "state": "PORTFOLIO_READY",
        "selected_positions": [{
            "strategy": "BULL_PUT", "contracts": 2, "allocated_risk": 1600,
            "portfolio_expected_value": 180,
            "candidate": {"strategy": "BULL_PUT_CREDIT_SPREAD", "legs": {"sell_leg": 5000, "buy_leg": 4990, "width": 10, "entry_credit": 2}},
        }],
        "portfolio_summary": {"expected_value": 180, "maximum_defined_risk": 1600},
    }


def test_store_is_idempotent_and_scorecard(tmp_path):
    store = PortfolioOutcomeStore(str(tmp_path / "p.db"))
    ts = "2026-07-17T14:00:00+00:00"
    a = store.record("SPX", _portfolio(), observed_at=ts)
    b = store.record("SPX", _portfolio(), observed_at=ts)
    assert a["id"] == b["id"]
    assert store.scorecard()["pending_portfolios"] == 1


def test_replay_attributes_contract_weighted_pnl(tmp_path):
    store = PortfolioOutcomeStore(str(tmp_path / "p.db"))
    store.record("SPX", _portfolio(), observed_at="2026-07-17T14:00:00+00:00")
    bars = [
        {"t": 1784298600000, "h": 5025, "l": 5010, "c": 5015},
        {"t": 1784318400000, "h": 5030, "l": 5010, "c": 5020},
    ]
    run = replay_due_portfolios(store, lambda *args: bars, now_et=dt.datetime(2026,7,18,10,tzinfo=dt.timezone.utc))
    assert run["graded"] == 1
    row = store.recent(1)[0]
    assert row["outcome"] == "PORTFOLIO_WIN"
    assert row["modeled_pnl"] == 400
    assert row["attribution"]["positions"][0]["modeled_pnl"] == 400


def test_routes_expose_outcome_api(tmp_path):
    from flask import Flask
    app = Flask(__name__)
    register_premium_discipline_routes(app, last_result_provider=lambda: {}, db_path=str(tmp_path / "r.db"))
    client = app.test_client()
    body = client.get('/api/premium_discipline/portfolio/outcomes').get_json()
    assert body['ok'] is True
    assert body['scorecard']['version'].startswith('18.1.3')
    unavailable = client.post('/api/premium_discipline/portfolio/replay/run')
    assert unavailable.status_code == 503
