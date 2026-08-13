from pathlib import Path
from engine import institutional_research_lab as irl

def setup_function(_):
    import tempfile
    from engine import institutional_governance as gov
    gov.DB_PATH=tempfile.mktemp(suffix='.db')

def candidate():
    return irl.register_candidate(name='Gamma Filter V2',candidate_type='FILTER',hypothesis='Reduces false breakouts',specification={'threshold':0.7})

def test_candidate_is_immutable():
    a=candidate(); b=candidate()
    assert a['created'] is True and b['status']=='IMMUTABLE_EXISTS'

def test_research_run_and_comparison():
    c=candidate(); rid=c['candidate_id']
    x=irl.record_run(candidate_id=rid,dataset_id='D1',started_at='2026-01-01T00:00:00+00:00',completed_at='2026-01-02T00:00:00+00:00',methodology={'walk_forward':True},metrics={'expectancy':0.4,'win_rate':62,'sharpe':1.5,'max_drawdown':8},diagnostics={'reproducible':True})
    assert x['created'] is True and irl.compare([rid])['winner_candidate_id']==rid

def test_alpha_attribution_is_deterministic_and_immutable():
    a=irl.alpha_attribution(scope_id='DAY1',total_result=100,contributions={'Auction':40,'Gamma':35,'Flow':25})
    b=irl.alpha_attribution(scope_id='DAY1',total_result=100,contributions={'Auction':40,'Gamma':35,'Flow':25})
    assert a['normalized']['Auction']==40 and b['status']=='IMMUTABLE_EXISTS'

def test_readiness_never_approves_production():
    c=candidate(); out=irl.assess_readiness(c['candidate_id'])
    assert out['summary']['approved_for_production'] is False and out['summary']['automatic_promotion'] is False

def test_status_safety_contract():
    s=irl.status(); assert s['offline_research_only'] and s['production_candidate_activation_enabled'] is False and s['production_effect']=='NONE'

def test_routes_and_dashboard_declared():
    root=Path(__file__).parents[1]; routes=(root/'engine/institutional_roadmap_routes.py').read_text(); html=(root/'templates/institutional_research_lab.html').read_text()
    assert '/api/research-lab/status' in routes and '/api/alpha-attribution/records' in routes and '/apex_os/research_lab' in routes and 'Institutional Research Lab' in html
