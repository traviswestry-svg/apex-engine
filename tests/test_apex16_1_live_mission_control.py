from engine import live_mission_control as lmc

def test_confluence_is_deterministic_and_high_when_aligned():
    kw=dict(pressure={'institutional_pressure_score':88,'conviction':84,'bias':'STRONG_BULLISH'},market_state={'active_state':'TREND_AUCTION','confidence':90,'stability':88},playbook={'active_playbook':'OPENING_DRIVE_CONTINUATION','direction':'BULLISH','playbook_quality_score':92,'state_compatibility':94},engine_snapshot={'decision_confidence':91,'recommendation':'CALLS','structure_alignment':90})
    a=lmc.confluence(**kw); b=lmc.confluence(**kw)
    assert a==b and a['institutional_confluence_score']>=85 and a['grade'] in {'A','A+'}

def test_conflicting_direction_penalizes_confluence():
    aligned=lmc.confluence(pressure={'institutional_pressure_score':85,'conviction':80,'bias':'BULLISH'},market_state={'confidence':85,'stability':85},playbook={'direction':'BULLISH','playbook_quality_score':85,'state_compatibility':85},engine_snapshot={'decision_confidence':85,'recommendation':'CALLS','structure_alignment':85})
    conflict=lmc.confluence(pressure={'institutional_pressure_score':85,'conviction':80,'bias':'BULLISH'},market_state={'confidence':85,'stability':85},playbook={'direction':'BEARISH','playbook_quality_score':85,'state_compatibility':85},engine_snapshot={'decision_confidence':85,'recommendation':'CALLS','structure_alignment':85})
    assert conflict['institutional_confluence_score'] < aligned['institutional_confluence_score']

def test_position_monitor_is_advisory_only():
    p=lmc.position_monitor({'position':{'symbol':'SPX','side':'LONG','quantity':1,'entry_price':10,'mark_price':11}})
    assert p['position_open'] and p['unrealized_pnl']==100 and p['broker_effect']=='NONE'

def test_safety_contract():
    s=lmc.status(); assert s['production_effect']=='NONE' and not s['broker_order_submission_enabled'] and not s['recommendation_mutation_enabled']

def test_routes_and_dashboard_present():
    from pathlib import Path
    root=Path(__file__).parents[1]; r=(root/'engine/institutional_roadmap_routes.py').read_text(); h=(root/'templates/institutional_trading_desk.html').read_text()
    assert '/api/mission-control/dashboard' in r and '/api/mission-control/confluence' in r and '/apex_os/mission_control' in r
    assert 'Institutional Confluence' in h and 'Live Position Monitor' in h
