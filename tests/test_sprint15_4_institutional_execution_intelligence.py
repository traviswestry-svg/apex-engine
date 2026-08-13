from pathlib import Path
from engine import institutional_execution_intelligence as iei

def setup_function(_):
    import tempfile
    from engine import institutional_governance as gov
    gov.DB_PATH=tempfile.mktemp(suffix='.db')

def sample():
    return dict(trade_id='T1',symbol='SPX',side='LONG',quantity=1,planned_entry=10,actual_entry=10.2,actual_exit=12,opened_at='2026-07-18T10:00:00+00:00',closed_at='2026-07-18T10:05:00+00:00',stop_price=9.2,best_price=13,worst_price=9.8,fees=2)

def test_metrics_are_deterministic():
    a=iei.evaluate_trade(**{k:v for k,v in sample().items() if k!='trade_id' and k!='symbol'})
    b=iei.evaluate_trade(**{k:v for k,v in sample().items() if k!='trade_id' and k!='symbol'})
    assert a==b and a['metrics']['entry_slippage_points']==0.2

def test_immutable_record():
    a=iei.record(**sample()); b=iei.record(**sample())
    assert a['created'] is True and b['status']=='IMMUTABLE_EXISTS'

def test_analysis_and_safety():
    iei.record(**sample()); x=iei.analyze(persist=True)
    assert x['metrics']['sample_size']==1 and x['diagnostics']['broker_execution_changed'] is False
    assert iei.status()['live_order_mutation_enabled'] is False

def test_routes_and_dashboard_declared():
    root=Path(__file__).parents[1]; routes=(root/'engine/institutional_roadmap_routes.py').read_text(); html=(root/'templates/institutional_execution_intelligence.html').read_text()
    assert '/api/execution-intelligence/status' in routes and '/apex_os/execution_intelligence' in routes and 'Institutional Execution Intelligence' in html
