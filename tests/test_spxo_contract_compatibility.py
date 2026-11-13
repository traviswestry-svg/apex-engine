from datetime import datetime, timezone
from engine.options.spxo_contract_lifecycle import classify_contract, execution_blockers
from engine.options.options_data_bus import normalize_contract
from engine.options.polygon_chain import _map_snapshot
from scripts.spxo_compatibility_audit import audit
from engine.execution.paper_order_preflight import inspect
from engine.execution.traderspost_paper import make_signal
from engine.execution.trade_risk_guard import validate_entry, RiskLimits
import pytest

SPXO = {"ticker": "SPX", "osi_key": "O:SPXO261118C06000000", "expiry": "2026-11-18", "side": "CALL", "strike": 6000}
SPXW = {"ticker": "SPX", "osi_key": "O:SPXW261118C06000000", "expiry": "2026-11-18", "side": "CALL", "strike": 6000}


def test_spxo_has_exchange_correct_cutoff_and_settlement():
    d = classify_contract(SPXO)
    assert d['contract_class'] == 'SPXO' and d['settlement_type'] == 'AM'
    assert d['settlement_reference'] == 'SET'
    assert d['last_trading_timestamp'] == '2026-11-17T17:00:00-05:00'
    assert d['execution_eligible'] is False


def test_spxw_same_expiry_stays_pm_and_distinct():
    d = classify_contract(SPXW)
    assert d['contract_class'] == 'SPXW' and d['settlement_type'] == 'PM'
    assert d['settlement_reference'] == 'CLOSING_INDEX'
    assert d['last_trading_timestamp'] is None
    assert not execution_blockers(SPXW)
    assert execution_blockers(SPXO) == ['SPXO_AM_SETTLEMENT_UNSUPPORTED_FOR_0DTE_EXECUTION']


def test_underlying_only_cannot_infer_contract_class():
    d = classify_contract({'ticker': 'SPX', 'symbol': 'SPX', 'expiration':'2026-11-18'})
    assert d['contract_class'] == 'UNKNOWN'
    assert 'CONTRACT_CLASS_UNVERIFIED' in execution_blockers({'ticker':'SPX'})


def test_conflicting_identity_rejected():
    d = classify_contract({**SPXO, 'contract_class':'SPXW', 'settlement_type':'PM'})
    assert d['identity_conflict']
    assert 'CONTRACT_SETTLEMENT_IDENTITY_CONFLICT' in execution_blockers({**SPXO, 'settlement_type':'PM'})


def test_future_expiration_does_not_infer_trading_cutoff():
    d = classify_contract({**SPXO,'expiry':'2027-01-20'})
    assert d['last_trading_timestamp'] is None and not d['execution_eligible']


def test_normalized_chain_preserves_root():
    a = normalize_contract({'symbol':SPXO['osi_key'],'expiration':'2026-11-18','strike':6000,'type':'call','bid':1,'ask':2})
    b = normalize_contract({'symbol':SPXW['osi_key'],'expiration':'2026-11-18','strike':6000,'type':'call','bid':1,'ask':2})
    assert a.contract_class == 'SPXO' and a.settlement_type == 'AM'
    assert b.contract_class == 'SPXW' and b.settlement_type == 'PM'
    assert a.to_dict()['settlement_reference'] == 'SET'


def test_polygon_preserves_option_symbol():
    raw = _map_snapshot({'details':{'ticker':SPXO['osi_key'],'strike_price':6000,'expiration_date':'2026-11-18','contract_type':'call'}})
    assert raw['contract_ticker'] == SPXO['osi_key']
    assert normalize_contract(raw).contract_class == 'SPXO'


def test_preflight_explicitly_blocks_spxo_despite_existing_authority_blockers():
    c = {'ticker':'SPX','contract':SPXO,'decision_id':'d1','quantity':1,'bid':2,'ask':3}
    out = inspect(c, clock=datetime(2026,11,17,15,0,tzinfo=timezone.utc), decision_reader=lambda _: None)
    assert 'SPXO_AM_SETTLEMENT_UNSUPPORTED_FOR_0DTE_EXECUTION' in out['blockers']
    assert out['may_send_order'] is False
    assert out['contract_lifecycle']['contract_class'] == 'SPXO'


def test_paper_signal_cannot_recast_spxo_as_spx():
    with pytest.raises(ValueError, match='SPXO_AM_SETTLEMENT'):
        make_signal({'ticker':'SPX','osi_key':SPXO['osi_key']})


def test_trading_guard_explicit_spxo_denied():
    c = {'symbol':'SPX','osi_key':SPXO['osi_key'],'expiration':'2026-11-18','side':'CALL','bid':1,'ask':1.1}
    outcome = validate_entry(contract=c,quantity=1,entry_premium=1.1,stop_premium=.5,limits=RiskLimits(),now=datetime(2026,11,17,tzinfo=timezone.utc))
    assert not outcome.allow and any('SPXO_AM_SETTLEMENT' in r for r in outcome.reasons)


def test_offline_audit_remains_read_only():
    out = audit([SPXO,SPXW,{'ticker':'SPX'}])
    assert out['by_class']['SPXO'] == 1 and out['by_class']['UNKNOWN'] == 1
    assert out['execution_authority'] is False
