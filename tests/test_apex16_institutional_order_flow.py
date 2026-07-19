from pathlib import Path
from engine import institutional_order_flow_intelligence as iofi

def setup_function(_):
    import tempfile
    from engine import institutional_governance as gov
    gov.DB_PATH=tempfile.mktemp(suffix='.db')

def snap(**kw):
    x={'call_sweep_premium':900,'put_sweep_premium':100,'bullish_block_premium':500,'bearish_block_premium':100,'dealer_hedging_pressure':55,'gamma_pressure':35,'gamma_flip_distance_pct':.15,'delta_exposure_pressure':30,'auction_imbalance':45,'volume_profile_imbalance':35,'liquidity_pressure':20,'breadth_pressure':40,'es_return_pct':.25,'spx_return_pct':.2}; x.update(kw); return x

def test_pressure_is_deterministic_and_bullish():
    a=iofi.evaluate(snap()); b=iofi.evaluate(snap())
    assert a==b and a['institutional_pressure_score']>50 and 'BULLISH' in a['bias']

def test_bearish_pressure():
    s=snap(call_sweep_premium=50,put_sweep_premium=1000,bullish_block_premium=20,bearish_block_premium=800,dealer_hedging_pressure=-70,gamma_pressure=-50,delta_exposure_pressure=-40,auction_imbalance=-60,volume_profile_imbalance=-30,liquidity_pressure=-20,breadth_pressure=-50,es_return_pct=-.3,spx_return_pct=-.25)
    assert iofi.evaluate(s)['institutional_pressure_score']<50

def test_record_is_immutable_and_transitioned():
    t='2026-07-18T14:00:00+00:00'; a=iofi.record(snap(),observed_at=t); b=iofi.record(snap(),observed_at=t)
    assert a['created'] and b['status']=='IMMUTABLE_EXISTS'
    c=iofi.record(snap(call_sweep_premium=0,put_sweep_premium=2000,dealer_hedging_pressure=-90,gamma_pressure=-80,auction_imbalance=-90,breadth_pressure=-80,es_return_pct=-.5,spx_return_pct=-.5),observed_at='2026-07-18T14:01:00+00:00')
    assert c['transition'] is not None

def test_safety_contract():
    s=iofi.status(); assert s['deterministic'] and not s['broker_order_submission_enabled'] and s['production_effect']=='NONE'

def test_component_weights_reconcile():
    assert round(sum(iofi.COMPONENT_WEIGHTS.values()),6)==1.0 and len(iofi.COMPONENT_WEIGHTS)==10

def test_routes_and_dashboard_declared():
    root=Path(__file__).parents[1]; r=(root/'engine/institutional_roadmap_routes.py').read_text(); h=(root/'templates/institutional_trading_desk.html').read_text()
    assert '/api/order-flow-intelligence/status' in r and '/api/trading-desk/dashboard' in r and '/apex_os/institutional_trading_desk' in r and 'Institutional Trading Desk' in h
