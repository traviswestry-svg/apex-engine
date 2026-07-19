from flask import Flask
from engine.institutional_playbook_routes import register_institutional_playbook_routes

def test_playbook_routes_200():
    app=Flask(__name__); register_institutional_playbook_routes(app,last_result_provider=lambda:{'price':6300,'expected_move':40})
    c=app.test_client()
    for p in ('/api/institutional-playbooks/status','/api/institutional-playbooks/diagnostics','/api/institutional-playbooks/rankings','/api/institutional-playbooks/selected','/api/institutional-playbooks/guardrails'):
        assert c.get(p).status_code==200
