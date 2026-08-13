import json
from flask import Flask
from engine.institutional_volume_profile_v211 import build_volume_profile_intelligence
from engine.institutional_workspace_v212 import build_workspace
from engine.institutional_mission_control_v213 import build_mission_control
from engine.institutional_workspace_routes import register_institutional_workspace_routes

SAMPLE={
 'ticker':'SPX','price':6000,'session':'MARKET_OPEN','atr':20,
 'volume_profile':{'poc':5998,'vah':6005,'val':5990,'hvn':[5998,6010],'lvn':[6003],
  'levels':[{'price':6004,'volume':1200,'previous_volume':900,'delta':250},
            {'price':5999,'volume':800,'previous_volume':800,'delta':50},
            {'price':5994,'volume':1000,'previous_volume':1100,'delta':-200}]},
 'market_structure':{'direction':'BULLISH'},
}

def test_volume_profile_colors_and_redaction_contract():
    out=build_volume_profile_intelligence(SAMPLE)
    assert out['ok'] is True
    assert out['summary']['active_green'] >= 1
    assert out['summary']['stalled_red'] >= 1
    assert {x['color'] for x in out['levels']} <= {'GREEN','RED','GRAY'}
    assert out['guardrails']['broker_mutation'] is False

def test_workspace_is_advisory_and_has_banner():
    out=build_workspace(SAMPLE)
    assert out['ok'] is True
    assert 'decision_banner' in out
    assert out['guardrails']['automatic_execution'] is False
    assert out['workspace']['execution_plan']['sizing']['max_contracts'] == 0

def test_mission_control_groups_and_lock():
    out=build_mission_control(SAMPLE, {'state':'PASS','configured':10}, {'state':'PASS','configured':5,'total':5})
    assert 'CONFIGURATION' in out['groups']
    assert out['groups']['BROKER']['state']=='BLOCKED'
    assert out['guardrails']['kill_switch_authoritative'] is True

def test_routes_return_200():
    app=Flask(__name__)
    register_institutional_workspace_routes(app,lambda:SAMPLE,lambda:{'state':'PASS','configured':10},lambda:{'state':'PASS','configured':5,'total':5})
    client=app.test_client()
    for path in ['/api/institutional-volume-profile/status','/api/institutional-volume-profile/diagnostics','/api/institutional-volume-profile/levels','/api/institutional-workspace/status','/api/institutional-workspace/layout','/api/mission-control-v2/status','/api/mission-control-v2/diagnostics']:
        response=client.get(path)
        assert response.status_code==200, path
        assert response.get_json()['ok'] is True

def test_no_order_mutation_language_in_api_payload():
    payload=json.dumps(build_workspace(SAMPLE)).lower()
    assert 'submit_order' not in payload
    assert 'place_order' not in payload
    assert 'broker_mutation": true' not in payload
