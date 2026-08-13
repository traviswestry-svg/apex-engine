import os
from engine import institutional_market_state_engine as imse
from engine import institutional_governance as gov


def setup_function():
    if os.path.exists(gov.DB_PATH): os.remove(gov.DB_PATH)
    imse.init_db()


def snap(**kw):
    x={"atr_pct":1.2,"trend_strength":80,"balance_score":25,"gamma_score":-300,"gamma_flip_distance_pct":1.0,"breadth":70,"flow_bias":80,"liquidity_score":75,"value_break":True}
    x.update(kw); return x


def test_deterministic_classification_and_taxonomy():
    a=imse.classify(snap()); b=imse.classify(snap())
    assert a==b and a['active_state'] in imse.TAXONOMY and a['future_information_used'] is False


def test_immutable_record_and_integrity():
    a=imse.record(snap(),symbol='SPX',session_id='2026-07-18',observed_at='2026-07-18T14:00:00+00:00')
    b=imse.record({"trend_strength":0},symbol='SPX',session_id='2026-07-18',observed_at='2026-07-18T14:00:00+00:00')
    assert a['created'] is True and b['status']=='IMMUTABLE_EXISTS' and b['integrity_hash']==a['integrity_hash']


def test_transition_is_recorded_only_on_state_change():
    imse.record(snap(balance_score=95,trend_strength=5,value_break=False),session_id='s',observed_at='2026-07-18T13:30:00+00:00')
    imse.record(snap(),session_id='s',observed_at='2026-07-18T14:00:00+00:00')
    t=imse.transitions(); assert len(t)>=2 and t[0]['from_state'] != t[0]['to_state']


def test_status_safety_contract():
    s=imse.status(); assert s['production_effect']=='NONE' and not s['future_information_allowed'] and not s['recommendation_mutation_enabled']


def test_routes_and_dashboard_present():
    routes=open('engine/institutional_roadmap_routes.py').read(); html=open('templates/institutional_market_state.html').read()
    assert '/api/imse/record' in routes and '/api/imse/transitions' in routes and '/apex_os/institutional_market_state' in routes and 'Institutional Market State Engine' in html

def test_decision_intelligence_replay_and_cross_exam_integration_present():
    center=open('engine/decision_intelligence_center.py').read(); replay=open('engine/institutional_replay_2.py').read(); cross=open('engine/cross_examination_engine.py').read()
    assert 'market_state' in center and 'imse.at_or_before' in replay and 'MARKET_STATE' in cross
