import tempfile
from pathlib import Path
from engine import institutional_governance as gov
from engine import institutional_market_state_engine as imse
from engine import institutional_playbook_engine as ipe


def setup_db(monkeypatch):
    p=Path(tempfile.mkdtemp())/'ipe.db'; monkeypatch.setattr(gov,'DB_PATH',str(p)); return p


def snap(**kw):
    d={'trend_strength':82,'balance_score':25,'atr_pct':1.8,'flow_bias':70,'breadth':65,'liquidity_score':80,'opening_drive':True,'vwap_hold':True,'direction':'CALLS'}; d.update(kw); return d


def test_deterministic_recognition(monkeypatch):
    setup_db(monkeypatch); ms=imse.classify(snap())
    a=ipe.evaluate(snap(),market_state=ms); b=ipe.evaluate(snap(),market_state=ms)
    assert a==b and a['active_playbook']=='OPENING_DRIVE_CONTINUATION'
    assert a['future_information_used'] is False and a['historical_outcomes_used_in_live_selection'] is False


def test_immutable_record_and_transition(monkeypatch):
    setup_db(monkeypatch)
    imse.record(snap(),observed_at='2026-07-18T13:31:00+00:00')
    a=ipe.record(snap(),observed_at='2026-07-18T13:31:00+00:00')
    b=ipe.record(snap(),observed_at='2026-07-18T13:31:00+00:00')
    assert a['created'] and b['status']=='IMMUTABLE_EXISTS'
    assert len(ipe.transitions())==1


def test_state_compatibility_changes_ranking(monkeypatch):
    setup_db(monkeypatch)
    ms={'active_state':'GAMMA_PIN','active_confidence':94,'stability_index':90,'secondary_states':[{'state':'BALANCED_AUCTION','confidence':88}]}
    out=ipe.evaluate({'balance_score':90,'atr_pct':.3},market_state=ms)
    assert out['active_playbook']=='GAMMA_PIN_ROTATION'


def test_statistics_are_separate(monkeypatch):
    setup_db(monkeypatch); ipe.record(snap(),observed_at='2026-07-18T13:31:00+00:00')
    out=ipe.statistics(); assert out['historical_outcomes_used_in_live_selection'] is False
    assert out['statistics'][0]['selection_feedback_enabled'] is False


def test_routes_dashboard_and_integrations_exist():
    root=Path(__file__).parents[1]
    routes=(root/'engine/institutional_roadmap_routes.py').read_text(); html=(root/'templates/institutional_playbook_engine.html').read_text()
    center=(root/'engine/decision_intelligence_center.py').read_text(); replay=(root/'engine/institutional_replay_2.py').read_text(); cross=(root/'engine/cross_examination_engine.py').read_text()
    assert '/api/playbooks/record' in routes and '/apex_os/playbook_engine' in routes
    assert 'Institutional Playbook Engine' in html and '"playbook"' in center and '"playbook"' in replay and 'PLAYBOOK' in cross


def test_safety_status(monkeypatch):
    setup_db(monkeypatch); s=ipe.status()
    assert s['deterministic'] is True and s['future_information_allowed'] is False
    assert s['recommendation_mutation_enabled'] is False and s['production_effect']=='NONE'
