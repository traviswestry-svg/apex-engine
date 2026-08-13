from engine.premium_portfolio_risk_governor import evaluate_portfolio_risk, RiskGovernorStore

def test_governor_approves_and_blocks(tmp_path):
    portfolio={"state":"PORTFOLIO_READY","selected_positions":[{"strategy":"BULL_PUT"}],"portfolio_summary":{"maximum_defined_risk":800,"expected_value":120}}
    er={"state":"EXECUTABLE"}
    a=evaluate_portfolio_risk(portfolio,er,open_risk=0,daily_realized_pnl=0,max_total_open_risk=2000,max_daily_loss=1000)
    assert a["approved"]
    b=evaluate_portfolio_risk(portfolio,er,open_risk=1500,max_total_open_risk=2000,max_daily_loss=1000)
    assert b["state"]=="BLOCKED"
    st=RiskGovernorStore(str(tmp_path/'x.db')); assert st.record('SPX',a)["state"] in ('APPROVED','REDUCE')
