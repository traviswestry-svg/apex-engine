from engine.premium_execution_orchestrator import PremiumExecutionOrchestrator

def test_confirmation_required_and_execution_disabled(tmp_path):
    o=PremiumExecutionOrchestrator(str(tmp_path/'x.db'))
    portfolio={"selected_positions":[{"strategy":"BULL_PUT","contracts":1}],"portfolio_summary":{"maximum_defined_risk":500}}
    risk={"approved":True}; er={"state":"EXECUTABLE","recommendation":{"shadow_fill_credit":1.2}}
    c=o.create_intent('SPX',portfolio,risk,er); assert c['ok']
    p=o.preview(c['intent_id']); assert p['status']=='PREVIEWED'
    bad=o.confirm(c['intent_id'],'operator',False); assert not bad['ok']
    good=o.confirm(c['intent_id'],'operator',True); assert good['status']=='CONFIRMED'
    s=o.submit(c['intent_id'],good['confirmation']['confirmation_id'],{"risk_governor":risk,"execution_reality":er})
    assert s['status']=='EXECUTION_DISABLED'
