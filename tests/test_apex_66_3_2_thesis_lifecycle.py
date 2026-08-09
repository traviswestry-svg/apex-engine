import os

from engine.thesis_lifecycle import (
    get_state, get_events, persist_thesis, evaluate_trigger, expire_prior_sessions,
)
from engine.institutional_narrative import build_institutional_narrative
from engine.institutional_decision_object import build_canonical_institutional_decision


def _candidate(direction='BULLISH', state='ACTIVE', raw=70.0, consensus=75.0, *, hard=None, soft=None):
    return {
        'schema_version': 'apex.institutional_thesis.v2',
        'state': state,
        'current_thesis': f'{direction} thesis',
        'alternative_thesis': 'alternative',
        'dominant_direction': direction,
        'market_regime': 'TREND',
        'supporting_engines': ['flow','dealer','breadth'],
        'contradicting_engines': [],
        'abstaining_engines': [],
        'known_unknowns': [],
        'expected_next_event': 'test',
        'consensus': consensus,
        'raw_conviction': raw,
        'calibrated_conviction': None,
        'hard_invalidation': hard or [],
        'soft_invalidation': soft or [],
        'provenance': {'source':'test'},
    }


def _use_tmp_db(monkeypatch, tmp_path):
    db = tmp_path / 'tracking.db'
    monkeypatch.setenv('RECOMMENDATION_LEDGER_DB_PATH', str(db))
    monkeypatch.delenv('DB_PATH', raising=False)
    return db


def test_thesis_persists_across_reads_and_idempotent_updates(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    c = _candidate()
    first = persist_thesis(c, ticker='SPX', session_date='2026-08-10', price=6000, market_closed=False)
    second = persist_thesis(c, ticker='SPX', session_date='2026-08-10', price=6001, market_closed=False)
    reloaded = get_state('SPX', '2026-08-10')
    assert first['state'] == 'ACTIVE'
    assert reloaded['state'] == 'ACTIVE'
    assert first['thesis_id'] == reloaded['thesis_id']
    assert second['revision'] == first['revision']
    assert second['lifecycle']['transition_reason'] == 'NO_MATERIAL_CHANGE'
    assert len(get_events(first['thesis_id'])) == 1


def test_strengthening_and_weakening_transitions_are_persisted(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    first = persist_thesis(_candidate(raw=60, consensus=65), ticker='SPX', session_date='2026-08-10', price=6000, market_closed=False)
    stronger = persist_thesis(_candidate(raw=72, consensus=75), ticker='SPX', session_date='2026-08-10', price=6002, market_closed=False)
    weaker = persist_thesis(_candidate(state='FORMING', raw=50, consensus=55), ticker='SPX', session_date='2026-08-10', price=6001, market_closed=False)
    assert first['state'] == 'ACTIVE'
    assert stronger['state'] == 'ACTIVE'
    assert stronger['lifecycle']['transition_reason'] == 'THESIS_STRENGTHENED'
    assert weaker['state'] == 'WEAKENING'
    assert weaker['lifecycle']['transition_reason'] == 'THESIS_EVIDENCE_WEAKENED'
    events = get_events(first['thesis_id'])
    assert [e['event_type'] for e in events] == ['THESIS_CREATED','THESIS_STRENGTHENED','THESIS_WEAKENED']


def test_soft_invalidation_weakens_and_hard_invalidation_invalidates(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    soft = [{'level': 5995, 'operator':'AT_OR_BELOW', 'machine_evaluable':True, 'severity':'SOFT'}]
    hard = [{'level': 5990, 'operator':'AT_OR_BELOW', 'machine_evaluable':True, 'severity':'HARD'}]
    base = _candidate(hard=hard, soft=soft)
    persist_thesis(base, ticker='SPX', session_date='2026-08-10', price=6000, market_closed=False)
    weak = persist_thesis(base, ticker='SPX', session_date='2026-08-10', price=5994, market_closed=False)
    invalid = persist_thesis(base, ticker='SPX', session_date='2026-08-10', price=5989, market_closed=False)
    assert weak['state'] == 'WEAKENING'
    assert weak['lifecycle']['invalidation_evaluation']['soft_triggered'] is True
    assert invalid['state'] == 'INVALIDATED'
    assert invalid['lifecycle']['transition_reason'] == 'HARD_INVALIDATION_TRIGGERED'
    assert invalid['invalidated_at'] is not None


def test_replacement_after_hard_invalidation_requires_opposite_direction(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    bull = _candidate(hard=[{'level': 5990, 'operator':'AT_OR_BELOW', 'machine_evaluable':True}])
    persist_thesis(bull, ticker='SPX', session_date='2026-08-10', price=6000, market_closed=False)
    persist_thesis(bull, ticker='SPX', session_date='2026-08-10', price=5985, market_closed=False)
    bear = _candidate(direction='BEARISH', state='ACTIVE', hard=[{'level': 6010, 'operator':'AT_OR_ABOVE', 'machine_evaluable':True}])
    replacement = persist_thesis(bear, ticker='SPX', session_date='2026-08-10', price=5995, market_closed=False)
    assert replacement['state'] == 'FORMING'
    assert replacement['lifecycle']['transition_reason'] == 'REPLACEMENT_AFTER_INVALIDATION'
    assert replacement['dominant_direction'] == 'BEARISH'


def test_previous_session_nonterminal_thesis_expires_on_new_session(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    old = persist_thesis(_candidate(), ticker='SPX', session_date='2026-08-10', price=6000, market_closed=False)
    new = persist_thesis(_candidate(direction='BEARISH'), ticker='SPX', session_date='2026-08-11', price=5980, market_closed=False)
    expired = get_state('SPX','2026-08-10')
    assert expired['state'] == 'EXPIRED'
    assert new['state'] == 'ACTIVE'
    assert any(e['event_type']=='THESIS_EXPIRED' for e in get_events(old['thesis_id']))


def test_market_close_closes_existing_thesis_but_does_not_create_weekend_junk(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    created = persist_thesis(_candidate(), ticker='SPX', session_date='2026-08-10', price=6000, market_closed=False)
    closed = persist_thesis(_candidate(state='FORMING', raw=0, consensus=0), ticker='SPX', session_date='2026-08-10', price=6001, market_closed=True)
    assert created['state'] == 'ACTIVE'
    assert closed['state'] == 'CLOSED'
    assert closed['closed_at'] is not None
    weekend = persist_thesis(_candidate(direction='UNKNOWN', state='FORMING', raw=0, consensus=0), ticker='SPX', session_date='2026-08-15', price=None, market_closed=True)
    assert weekend['lifecycle']['persisted'] is False
    assert get_state('SPX','2026-08-15') is None


def test_trigger_evaluator_fails_closed_for_ambiguous_reference_operator():
    hit, reason = evaluate_trigger({'level':6000,'operator':'THROUGH_REFERENCE_LEVEL','machine_evaluable':False}, price=5990)
    assert hit is False
    assert reason == 'NOT_MACHINE_EVALUABLE'


def test_narrative_only_creates_hard_invalidation_from_explicit_stop():
    state = {
        'market_state': {'price': 6000, 'regime': 'TREND', 'session_state': 'RTH', 'vah': 6010, 'val': 5990},
        'institutional_intelligence': {'available': True, 'institutional_bias':'BULLISH', 'confidence':85},
        'flow_intelligence_2': {'available': True, 'flow_bias':'BULLISH', 'flow_conviction':80},
        'dealer_positioning': {'available': True, 'bias':'BULLISH', 'pressure_score':75},
        'market_drivers': {'available': True, 'market_bias':'BULLISH', 'driver_score':72},
        'execution_intelligence': {'available': True, 'approved_side':'CALL', 'execution_score':80},
        'recommendation': {'hard_invalidation_level': 5988},
    }
    n = build_institutional_narrative(state, session_state='RTH')
    assert all(x['machine_evaluable'] is False for x in n['thesis']['soft_invalidation'])
    assert n['thesis']['hard_invalidation']
    hard=n['thesis']['hard_invalidation'][0]
    assert hard['operator'] == 'AT_OR_BELOW'
    assert hard['level'] == 5988
    assert hard['machine_evaluable'] is True


def test_canonical_decision_exposes_persisted_thesis_lifecycle(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    state = {
        'session_date':'2026-08-10',
        'market_state': {'price': 6000, 'regime': 'TREND', 'session_state': 'RTH'},
        'institutional_intelligence': {'available': True, 'institutional_bias':'BULLISH', 'confidence':85},
        'auction_intelligence': {'available': True, 'auction_state': {'state':'TREND_UP','confidence':75}},
        'institutional_market_structure': {'available': True, 'direction':'BULLISH', 'confidence':75},
        'flow_intelligence_2': {'available': True, 'flow_bias':'BULLISH', 'flow_conviction':80},
        'liquidity_intelligence': {'ok':True,'status':'READY','institutional_intent':{'direction':'BULLISH','confidence':75}},
        'dealer_positioning': {'available': True, 'bias':'BULLISH', 'pressure_score':75},
        'market_drivers': {'available': True, 'market_bias':'BULLISH', 'driver_score':72},
        'execution_intelligence': {'available': True, 'approved_side':'CALL', 'execution_score':80},
        'recommendation': {'hard_invalidation_level': 5988},
    }
    d=build_canonical_institutional_decision(state, session_state='RTH')
    assert d['thesis']['schema_version']=='apex.institutional_thesis.v2'
    assert d['thesis_lifecycle']['persisted'] is True
    assert d['thesis']['thesis_id']
    assert d['thesis']['revision'] >= 1
    assert d['thesis_evolution_timeline']
    assert d['market_state']['session_state'] == 'RTH'


def test_recommendation_replay_accepts_thesis_snapshot(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    from engine import recommendation_ledger as ledger
    capture = ledger.build_capture(ticker='SPX', panel={'strategy':'NO_TRADE','tradeable':False,'legs':{}}, last_result={}, session_date='2026-08-10', application_version='66.3.2')
    created = ledger.record_recommendation(capture)
    rid = created['recommendation_id']
    result = ledger.append_event(rid, 'THESIS_SNAPSHOT', {'state':'ACTIVE','dominant_direction':'BULLISH'})
    assert result['ok'] is True
    row = ledger.get_recommendation(rid)
    thesis_events = [e for e in row['events'] if e['event_type']=='THESIS_SNAPSHOT']
    assert len(thesis_events) == 1
    assert thesis_events[0]['payload']['state'] == 'ACTIVE'


def test_only_active_thesis_can_be_actionable(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    # Persist a hard-invalidated thesis first.
    bull=_candidate(hard=[{'level':5990,'operator':'AT_OR_BELOW','machine_evaluable':True}])
    persist_thesis(bull,ticker='SPX',session_date='2026-08-10',price=6000,market_closed=False)
    persist_thesis(bull,ticker='SPX',session_date='2026-08-10',price=5985,market_closed=False)
    # Lifecycle state itself is sufficient to fail closed even if raw inputs later remain directional.
    state=get_state('SPX','2026-08-10')
    assert state['state']=='INVALIDATED'


def test_hard_invalidated_thesis_suppresses_otherwise_actionable_decision(monkeypatch, tmp_path):
    _use_tmp_db(monkeypatch, tmp_path)
    state={
        'session_date':'2026-08-10','market_state':{'price':6000,'regime':'TREND','session_state':'RTH'},
        'institutional_intelligence':{'available':True,'institutional_bias':'BULLISH','confidence':90},
        'auction_intelligence':{'available':True,'auction_state':{'state':'TREND_UP','confidence':85}},
        'institutional_market_structure':{'available':True,'direction':'BULLISH','confidence':85},
        'flow_intelligence_2':{'available':True,'flow_bias':'BULLISH','flow_conviction':90},
        'liquidity_intelligence':{'ok':True,'status':'READY','institutional_intent':{'direction':'BULLISH','confidence':85}},
        'dealer_positioning':{'available':True,'bias':'BULLISH','pressure_score':85},
        'market_drivers':{'available':True,'market_bias':'BULLISH','driver_score':85},
        'execution_intelligence':{'available':True,'approved_side':'CALL','execution_score':90},
        'recommendation':{'action':'CALL','strategy':'TEST','hard_invalidation_level':5990},
    }
    live=build_canonical_institutional_decision(state,session_state='RTH')
    assert live['thesis']['state']=='ACTIVE'
    assert live['actionable'] is True
    state['market_state']['price']=5985
    invalid=build_canonical_institutional_decision(state,session_state='RTH')
    assert invalid['thesis']['state']=='INVALIDATED'
    assert invalid['actionable'] is False
    assert invalid['action']=='NO_TRADE'
    assert invalid['status']=='THESIS_INVALIDATED'
