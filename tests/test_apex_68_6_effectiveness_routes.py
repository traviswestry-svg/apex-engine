from flask import Flask
from engine.decision_outcome_attribution_routes import register_decision_outcome_attribution_routes


def test_effectiveness_routes_register_without_execution_authority(monkeypatch, tmp_path):
    import engine.decision_outcome_attribution as doa
    monkeypatch.setattr(doa, 'DEFAULT_DB', tmp_path / 'evidence.db')
    app = Flask(__name__)
    register_decision_outcome_attribution_routes(app)
    rules = {(r.rule, tuple(sorted(r.methods - {'HEAD','OPTIONS'}))) for r in app.url_map.iter_rules()}
    assert ('/api/effectiveness', ('GET',)) in rules
    assert ('/api/effectiveness/attribution', ('GET',)) in rules
    assert ('/api/effectiveness/abstentions', ('GET',)) in rules
    assert ('/api/effectiveness/exits', ('GET',)) in rules
