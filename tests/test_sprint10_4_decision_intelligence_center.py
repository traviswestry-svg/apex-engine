from engine import institutional_governance as gov
from engine import decision_intelligence_core as core
from engine import decision_intelligence_center as dic


def sample():
    return {'ticker':'SPX','decision_state':'ENTER','market_state':{'ticker':'SPX'},'recommendation':{'action':'ENTER','strategy':'CALL'},'evidence':{'auction':{'state':'ACCEPTED_HIGHER'}},'provider_health':{'polygon':True}}


def test_dic_unifies_immutable_artifacts(monkeypatch,tmp_path):
    monkeypatch.setattr(gov,'DB_PATH',str(tmp_path/'a.db')); d=core.capture(sample(),recommendation_id='d1'); out=dic.dashboard(d['decision_id'])
    assert out['ok'] and out['summary']['decision_id']==d['decision_id'] and out['evidence_graph']['ok']


def test_decision_quality_is_deterministic_and_outcome_independent(monkeypatch,tmp_path):
    monkeypatch.setattr(gov,'DB_PATH',str(tmp_path/'a.db')); d=core.capture(sample(),recommendation_id='d2'); a=dic.dashboard(d['decision_id']); b=dic.dashboard(d['decision_id'])
    assert a['summary']['decision_quality']==b['summary']['decision_quality']
    assert 'outcome' not in a['summary']['decision_quality']['components']


def test_dic_exposes_support_conflict_risk_timeline_and_governance(monkeypatch,tmp_path):
    monkeypatch.setattr(gov,'DB_PATH',str(tmp_path/'a.db')); d=core.capture(sample(),recommendation_id='d3'); out=dic.dashboard(d['decision_id'])
    for key in ('supporting_evidence','conflicting_evidence','risk','timeline','governance','invalidation'): assert key in out


def test_dic_is_read_only():
    s=dic.status(); assert s['decision_mutation_enabled'] is False and s['confidence_mutation_enabled'] is False and s['future_information_allowed'] is False and s['production_effect']=='NONE'


def test_routes_and_dashboard_present():
    routes=open('engine/institutional_roadmap_routes.py').read(); html=open('templates/decision_intelligence_center.html').read()
    assert '/api/dic/dashboard/<identifier>' in routes and '/api/dic/status' in routes and '/apex_os/decision_intelligence_center' in routes
    assert 'Decision Intelligence Center' in html and 'Decision Quality' in html and 'No future information' in html
