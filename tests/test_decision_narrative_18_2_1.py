from engine.decision_narrative import build_decision_narrative

def test_narrative_approves_explainably():
    r=build_decision_narrative(eligibility={'decision':'APPROVE','score':82,'threshold':65},intelligence={'recommendation':{'strategy':'BULL_PUT','institutional_score':90,'expected_value':120}},portfolio={'selected_positions':[{'strategy':'BULL_PUT'}]},execution={'recommendation':{'status':'EXECUTABLE','execution_adjusted_expected_value':95}},risk={'decision':'APPROVED','blockers':[]},learning={'best_pattern':{'strategy':'BULL_PUT','regime':'GAMMA_PIN','samples':30,'win_rate':.8,'average_pnl':110}})
    assert r['decision']=='APPROVE_PREVIEW'
    assert 'BULL_PUT' in r['headline']
    assert r['execution_authority'] is False
