from engine import institutional_governance as gov
from engine import decision_intelligence_core as di


def sample():
    return {
      'ticker':'SPX','decision_state':'ENTER','market_state':{'ticker':'SPX'},
      'recommendation':{'action':'ENTER','strategy':'CALL'},
      'execution_intelligence':{'execution_score':82},
      'evidence':{'auction':{'state':'ACCEPTED_HIGHER'},'gamma':{'regime':'POSITIVE'}},
      'provider_health':{'polygon':True},
    }


def test_capture_is_immutable_and_idempotent(monkeypatch,tmp_path):
    monkeypatch.setattr(gov,'DB_PATH',str(tmp_path/'di.db'))
    first=di.capture(sample(),recommendation_id='rec-10-1')
    second=di.capture({'ticker':'QQQ'},recommendation_id='rec-10-1')
    assert first['ok'] and first['created']
    assert second['status']=='IMMUTABLE_EXISTS' and second['decision_id']==first['decision_id']
    assert len(first['integrity_hash'])==64


def test_capture_normalizes_real_decision_evidence(monkeypatch,tmp_path):
    monkeypatch.setattr(gov,'DB_PATH',str(tmp_path/'di.db'))
    x=di.capture(sample(),recommendation_id='rec-evidence')
    record=di.get(x['decision_id'])
    cats={r['category'] for r in record['evidence']}
    assert {'AUCTION','GAMMA'} <= cats
    assert all(r['provenance']['post_hoc'] is False for r in record['evidence'])


def test_contributions_are_mathematically_preserved(monkeypatch,tmp_path):
    monkeypatch.setattr(gov,'DB_PATH',str(tmp_path/'di.db'))
    x=di.capture(sample(),recommendation_id='rec-contrib')
    record=di.get(x['decision_id'])
    expected=record['decision']['confidence_attribution']['deterministic_total']
    actual=round(sum(r['contribution'] for r in record['contributions']),4)
    assert actual==expected


def test_status_is_observational_and_fail_safe(monkeypatch,tmp_path):
    monkeypatch.setattr(gov,'DB_PATH',str(tmp_path/'di.db'))
    s=di.status()
    assert s['recommendation_mutation_enabled'] is False
    assert s['confidence_mutation_enabled'] is False
    assert s['future_information_allowed'] is False
    assert s['production_effect']=='NONE'


def test_routes_and_dashboard_present():
    routes=open('engine/institutional_roadmap_routes.py').read()
    assert '/api/decision-intelligence/status' in routes
    assert '/api/decision-intelligence/<identifier>/evidence' in routes
    assert '/apex_os/decision_intelligence' in routes
    html=open('templates/decision_intelligence_core.html').read()
    assert 'No recommendation mutation' in html
    assert 'Immutable Decisions' in html
