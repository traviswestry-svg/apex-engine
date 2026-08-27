from __future__ import annotations
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

from engine.tick_momentum import capability, initial_state, process_transactions, validate_transactions
from engine.tick_momentum_store import TickMomentumStore

ROOT=Path(__file__).resolve().parents[1]

def _tx(n:int, *, up:bool=True):
    base=6500.0
    t0=datetime(2026,8,27,13,30,tzinfo=timezone.utc)  # 09:30 ET during DST
    return [{"observed_at":(t0+timedelta(milliseconds=10*i)).isoformat(),
             "price":base + (i*0.25 if up else -i*0.25),"size":1.0} for i in range(n)]

def test_release_truth_and_registry_preserve_69_5_0_observational():
    m=json.loads((ROOT/'config/apex_release_manifest.json').read_text())
    parts=tuple(int(x) for x in m['apex_version'].split('.'))
    assert parts >= (69,5,0)
    assert m['semantic_version']==m['application_version']==m['apex_version']
    g=m['guardrails']
    assert g['tick_momentum_observational_only'] is True
    assert g['tick_momentum_changes_trade_decisions'] is False
    assert g['tick_momentum_changes_execution_authority'] is False
    assert g['tick_momentum_production_effect']=='NONE'
    assert g['tick_momentum_aggregate_bars_allowed_as_ticks'] is False
    assert g['tick_momentum_l2_mbo_depth_equivalent'] is False
    assert g['tick_momentum_synthetic_depth_allowed'] is False
    assert g['tick_momentum_automatic_promotion'] is False
    r=(ROOT/'config/apex_capability_registry.yaml').read_text()
    assert 'multi_horizon_tick_momentum_intelligence:' in r
    import re
    match = re.search(r'multi_horizon_tick_momentum_intelligence:.*?version: "(\d+)\.(\d+)\.(\d+)"', r, re.S)
    assert match is not None
    assert tuple(int(x) for x in match.groups()) >= (69, 5, 0)
    assert 'multi_horizon_tick_momentum_intelligence:' in r
    for route in ['/api/tick-momentum/capability','/api/tick-momentum/health','/api/tick-momentum/state','/api/tick-momentum/history','/api/tick-momentum/ingest']:
        assert route in r

def test_capability_matches_pine_vocabulary_without_claiming_depth():
    c=capability()
    assert c['horizons']==[233,512,1000,2000]
    assert c['weights']=={233:1,512:2,1000:2,2000:3}
    assert c['aggregate_bars_allowed_as_ticks'] is False
    assert c['l2_mbo_depth_equivalent'] is False
    assert c['governance']['production_effect']=='NONE'
    assert c['governance']['decision_authority']=='NONE'
    assert c['governance']['execution_authority']=='NONE'

def test_aggregate_bars_are_rejected_as_tick_transactions():
    with pytest.raises(ValueError,match='aggregate OHLC'):
        validate_transactions([{"timestamp":"2026-08-27T14:30:00+00:00","open":1,"high":2,"low":1,"close":2,"price":2}],instrument='ES')

def test_2000_true_transactions_close_all_horizons_and_align_bullish():
    rows=validate_transactions(_tx(2000),instrument='ES')
    state,closed=process_transactions(initial_state('ES'),rows,instrument='ES')
    assert state['transactions_seen']==2000
    assert state['horizons']['233']['buckets_closed']==8
    assert state['horizons']['512']['buckets_closed']==3
    assert state['horizons']['1000']['buckets_closed']==2
    assert state['horizons']['2000']['buckets_closed']==1
    assert state['alignment']['score']==8
    assert state['alignment']['state']=='STRONG_BULL'
    assert len(closed)==14

def test_store_uses_bounded_bucket_snapshots_not_raw_transaction_history(tmp_path):
    store=TickMomentumStore(tmp_path/'tick.db')
    rows=validate_transactions(_tx(512),instrument='ES')
    state,closed=process_transactions(store.load_state('ES'),rows,instrument='ES')
    store.save(state,closed)
    loaded=store.load_state('ES')
    hist=store.history('ES',100)
    assert loaded['transactions_seen']==512
    assert len(hist)==3  # 233 closes twice + 512 once
    assert all('price' not in row for row in hist)

def test_runtime_wiring_and_microstructure_bridge_are_present():
    app=(ROOT/'app.py').read_text()
    bridge=(ROOT/'engine/market_microstructure_ingest.py').read_text()
    assert 'register_tick_momentum_routes' in app
    assert 'register_tick_momentum_routes(app)' in app
    assert 'validate_transactions(trades' in bridge
    assert 'SKIPPED_INVALID_TRANSACTION_BATCH' in bridge

def test_versioned_pine_companion_matches_contract_and_avoids_tick_time_call():
    pine=(ROOT/'docs/APEX_ES_Tick_Momentum_v1_3.pine').read_text()
    for h in ('233','512','1000','2000'):
        assert h in pine
    assert 'time(timeframe.period' not in pine
    assert 'shorttitle="APEXESTICK"' in pine
