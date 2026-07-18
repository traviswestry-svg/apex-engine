from engine import institutional_governance as gov
from engine import decision_intelligence_core as core
from engine import institutional_evidence_graph as graph


def sample():
    return {'ticker':'SPX','decision_state':'ENTER','market_state':{'ticker':'SPX'},'recommendation':{'action':'ENTER','strategy':'CALL'},'evidence':{'auction':{'state':'ACCEPTED_HIGHER'}},'provider_health':{'polygon':True}}


def test_graph_is_immutable_and_idempotent(monkeypatch,tmp_path):
    monkeypatch.setattr(gov,'DB_PATH',str(tmp_path/'a.db'))
    d=core.capture(sample(),recommendation_id='g1'); a=graph.create(d['decision_id']); b=graph.create(d['decision_id'])
    assert a['created'] is True and b['status']=='IMMUTABLE_EXISTS' and a['graph_id']==b['graph_id'] and len(a['integrity_hash'])==64


def test_graph_contains_root_nodes_edges_and_provenance(monkeypatch,tmp_path):
    monkeypatch.setattr(gov,'DB_PATH',str(tmp_path/'a.db'))
    d=core.capture(sample(),recommendation_id='g2'); a=graph.explain(d['decision_id']); g=a['graph']
    assert g['root_node_id'].startswith('decision:') and len(g['nodes']) >= 2 and len(g['edges']) >= 1
    assert any(n['kind']=='PROVENANCE' for n in g['nodes'])


def test_graph_references_only_frozen_records(monkeypatch,tmp_path):
    monkeypatch.setattr(gov,'DB_PATH',str(tmp_path/'a.db'))
    d=core.capture(sample(),recommendation_id='g3'); a=graph.explain(d['decision_id'])
    assert all(n.get('source_ref') for n in a['graph']['nodes'])
    assert graph.status()['future_information_allowed'] is False


def test_graph_is_observational(monkeypatch,tmp_path):
    monkeypatch.setattr(gov,'DB_PATH',str(tmp_path/'a.db'))
    s=graph.status(); assert s['recommendation_mutation_enabled'] is False and s['confidence_mutation_enabled'] is False and s['production_effect']=='NONE'


def test_routes_and_dashboard_present():
    routes=open('engine/institutional_roadmap_routes.py').read(); html=open('templates/institutional_evidence_graph.html').read()
    assert '/api/decision-intelligence/<identifier>/graph' in routes and '/api/decision-intelligence/graph/status' in routes and '/apex_os/evidence_graph' in routes
    assert 'No causal links are invented' in html and 'No post-hoc inference' in html
