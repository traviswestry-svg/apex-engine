from engine import institutional_governance as gov
from engine import decision_intelligence_core as core
from engine import confidence_attribution_engine as attr


def sample():
    return {'ticker':'SPX','decision_state':'ENTER','market_state':{'ticker':'SPX'},'recommendation':{'action':'ENTER','strategy':'CALL'},'evidence':{'auction':{'state':'ACCEPTED_HIGHER'}},'provider_health':{'polygon':True}}


def test_analysis_is_immutable_and_idempotent(monkeypatch,tmp_path):
    monkeypatch.setattr(gov,'DB_PATH',str(tmp_path/'a.db'))
    d=core.capture(sample(),recommendation_id='r1')
    a=attr.analyze(d['decision_id']); b=attr.analyze(d['decision_id'])
    assert a['created'] is True and b['status']=='IMMUTABLE_EXISTS'
    assert a['attribution_id']==b['attribution_id'] and len(a['integrity_hash'])==64


def test_contributions_reconcile_without_recalculation(monkeypatch,tmp_path):
    monkeypatch.setattr(gov,'DB_PATH',str(tmp_path/'a.db'))
    d=core.capture(sample(),recommendation_id='r2')
    a=attr.explain(d['decision_id'])
    assert a['reconciliation_status']=='RECONCILED'
    assert round(a['totals']['positive']+a['totals']['negative']+a['totals']['neutral']+a['totals']['unknown'],10)==a['deterministic_total']
    assert a['confidence_mutation_enabled'] is False


def test_ranked_classification_is_deterministic(monkeypatch,tmp_path):
    monkeypatch.setattr(gov,'DB_PATH',str(tmp_path/'a.db'))
    d=core.capture(sample(),recommendation_id='r3')
    a=attr.explain(d['decision_id'])
    vals=[x['absolute_contribution'] for x in a['contributors']]
    assert vals==sorted(vals,reverse=True)
    assert all(x['classification'] in {'POSITIVE','NEGATIVE','NEUTRAL','UNKNOWN'} for x in a['contributors'])


def test_status_is_observational(monkeypatch,tmp_path):
    monkeypatch.setattr(gov,'DB_PATH',str(tmp_path/'a.db'))
    s=attr.status()
    assert s['confidence_recalculation_enabled'] is False
    assert s['confidence_mutation_enabled'] is False
    assert s['production_effect']=='NONE'


def test_routes_and_dashboard_present():
    routes=open('engine/institutional_roadmap_routes.py').read()
    assert '/api/decision-intelligence/<identifier>/confidence' in routes
    assert '/api/decision-intelligence/confidence/status' in routes
    assert '/apex_os/confidence_attribution' in routes
    html=open('templates/confidence_attribution.html').read()
    assert 'Canonical confidence is never recalculated' in html
    assert 'No confidence recalculation' in html
