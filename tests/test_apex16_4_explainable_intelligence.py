from engine import explainable_intelligence_assistant as eia

def snap():
    return {'institutional_confluence':{'institutional_confluence_score':91,'grade':'A+','components':[{'name':'playbook_quality','score':94,'weighted':16.92,'available':True}]},'institutional_pressure':{'institutional_pressure_score':84,'bias':'STRONG_BULLISH','conviction':82},'market_state':{'active_state':'TREND_AUCTION','confidence':90,'stability':88},'playbook':{'active_playbook':'OPENING_DRIVE_CONTINUATION','direction':'BULLISH','playbook_quality_score':94},'trade_director':{'action':'CALLS','confidence':92},'portfolio_risk':{'risk_state':'NORMAL','breaches':[]}}

def test_intent_and_grounded_answer():
    x=eia.explain('Why is confidence high?',snap())
    assert x['intent']=='WHY_CONFIDENCE' and x['evidence_only'] and x['citations']
    assert x['recommendation_changed'] is False

def test_change_detection():
    old=snap(); new=snap(); new['market_state']={'active_state':'GAMMA_PIN','confidence':70,'stability':65}
    x=eia.explain('What changed in the last 15 minutes?',new,old)
    assert x['intent']=='WHAT_CHANGED' and any('active_state' in r for r in x['reasons'])

def test_similar_sessions_are_descriptive():
    x=eia.explain('Show similar sessions',snap(),similar_sessions=[{'session_id':'S1','score':91}])
    assert x['intent']=='SIMILAR_SESSIONS' and len(x['similar_sessions'])==1

def test_immutable_record(tmp_path,monkeypatch):
    monkeypatch.setattr(eia.gov,'DB_PATH',str(tmp_path/'a.db'))
    a=eia.record('Why is confidence high?',snap(),observed_at='2026-07-18T14:00:00+00:00')
    b=eia.record('Why is confidence high?',snap(),observed_at='2026-07-18T14:00:00+00:00')
    assert a['created'] and not b['created'] and b['status']=='IMMUTABLE_EXISTS'

def test_safety_contract():
    s=eia.status(); assert not s['free_form_generation_enabled'] and not s['broker_order_submission_enabled'] and s['production_effect']=='NONE'
