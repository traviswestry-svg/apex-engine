import datetime as dt
from engine.portfolio_outcome_attribution import PortfolioOutcomeStore, replay_due_portfolios
from engine.adaptive_portfolio_calibration import PortfolioCalibrationStore
from engine.multi_strategy_portfolio_optimizer import build_portfolio_optimizer


def _expectancy():
    return {"premium_intelligence":{"rankings":[
      {"strategy":"BULL_PUT","eligible":True,"institutional_score":90,"execution_confidence":90,"candidate":{"strategy":"BULL_PUT_CREDIT_SPREAD","legs":{"sell_leg":5000,"width":10,"entry_credit":2}},"expected_value":{"max_loss":800,"value_per_contract":100,"probability_of_profit":.7}},
      {"strategy":"BEAR_CALL","eligible":True,"institutional_score":85,"execution_confidence":90,"candidate":{"strategy":"BEAR_CALL_CREDIT_SPREAD","legs":{"sell_leg":5100,"width":10,"entry_credit":2}},"expected_value":{"max_loss":800,"value_per_contract":90,"probability_of_profit":.7}}
    ]},"regime_playbook":{}}

def test_optimizer_applies_governed_policy():
    r=build_portfolio_optimizer(_expectancy(),max_portfolio_risk=1600,max_daily_loss=3000,allocation_policy={"source":"PROMOTED","run_id":3,"institutional_score_weight":.4,"expected_value_weight":.6,"bull_bear_pair_penalty":.5})
    assert r["allocation_policy"]["source"]=="PROMOTED"
    assert r["allocation_policy"]["bull_bear_pair_penalty"]==.5

def test_portfolio_replay_and_calibration_governance(tmp_path):
    db=str(tmp_path/'x.db'); store=PortfolioOutcomeStore(db)
    p=build_portfolio_optimizer(_expectancy(),max_portfolio_risk=800,max_daily_loss=3000)
    when=dt.datetime(2026,7,17,14,0,tzinfo=dt.timezone.utc)
    row=store.record('SPX',p,when)
    bars=[{"t":when.timestamp()*1000+60000,"h":5060,"l":5040,"c":5050}]
    out=replay_due_portfolios(store,lambda *a:bars,now_et=dt.datetime(2026,7,18,12,0,tzinfo=dt.timezone.utc))
    assert out['graded']==1
    assert store.scorecard()['graded']==1
    cal=PortfolioCalibrationStore(db)
    run=cal.run(min_sample=5)
    assert run['status']=='INSUFFICIENT_SAMPLE'
    try: cal.promote(run['run_id'])
    except ValueError: pass
    else: raise AssertionError('immature run promoted')
