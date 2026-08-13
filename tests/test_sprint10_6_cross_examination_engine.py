from engine import institutional_governance as gov
from engine import decision_intelligence_core as core
from engine import cross_examination_engine as ice


def sample(strategy='CALL'):
    return {'ticker':'SPX','decision_state':'ENTER','market_state':{'ticker':'SPX'},'recommendation':{'action':'ENTER','strategy':strategy},'evidence':{'auction':{'state':'ACCEPTED_HIGHER'}},'provider_health':{'polygon':True}}


def test_question_routing_is_deterministic():
    assert ice.route_question('Why is confidence only 74?') == 'CONFIDENCE'
    assert ice.route_question('What would invalidate this?') == 'INVALIDATION'
    assert ice.route_question('Which version produced this?') == 'GOVERNANCE'


def test_answers_are_immutable_and_idempotent(monkeypatch,tmp_path):
    monkeypatch.setattr(gov,'DB_PATH',str(tmp_path/'a.db')); d=core.capture(sample(),recommendation_id='r-106a')
    a=ice.ask(d['decision_id'],'Why did APEX recommend this?'); b=ice.ask(d['decision_id'],'Why did APEX recommend this?')
    assert a['created'] is True and b['status']=='IMMUTABLE_EXISTS' and a['integrity_hash']==b['integrity_hash']


def test_unsupported_question_returns_evidence_not_available(monkeypatch,tmp_path):
    monkeypatch.setattr(gov,'DB_PATH',str(tmp_path/'a.db')); d=core.capture(sample(),recommendation_id='r-106b')
    out=ice.ask(d['decision_id'],'Tell me the weather on Mars')
    assert out['answer']['headline']=='Evidence Not Available' and out['answer']['no_inference_generated'] is True


def test_comparison_uses_stored_decision_artifacts(monkeypatch,tmp_path):
    monkeypatch.setattr(gov,'DB_PATH',str(tmp_path/'a.db')); a=core.capture(sample('CALL'),recommendation_id='r-106c'); b=core.capture(sample('PUT'),recommendation_id='r-106d')
    out=ice.compare(a['decision_id'],b['decision_id'])
    assert out['ok'] and 'recommendation_changed' in out['comparison'] and out['comparison']['decision_a']['decision_id'] != out['comparison']['decision_b']['decision_id'] and out['production_effect']=='NONE'


def test_status_and_routes_are_safe():
    s=ice.status(); assert s['production_effect']=='NONE' and not s['free_form_inference_enabled'] and not s['future_information_allowed']
    routes=open('engine/institutional_roadmap_routes.py').read(); html=open('templates/cross_examination.html').read()
    assert '/api/cross-examination/ask' in routes and '/api/cross-examination/compare/<identifier_a>/<identifier_b>' in routes and '/apex_os/cross_examination' in routes
    assert 'Evidence Not Available' in html and 'No fabricated inference' in html
