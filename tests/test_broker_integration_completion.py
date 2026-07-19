from engine.broker_integration_completion import assess_chain, build_diagnostics


class Result:
    def __init__(self, ok=True, data=None, errors=None):
        self.ok=ok; self.data=data or {}; self.errors=errors or []; self.warnings=[]; self.mode='sandbox'


class Adapter:
    mode='sandbox'; trading_enabled=False
    def status(self): return Result(data={'configured': True})
    def list_accounts(self): return Result(data={'accounts':[{}, {}, {}, {}]})


def test_chain_coverage_reports_quotes_and_greeks():
    d=assess_chain([{'bid':1,'ask':1.2,'delta':.4,'iv':.2},{'bid':2,'ask':2.2}], 'polygon', 12)
    assert d['chain_state']=='PASS'
    assert d['quotes_state']=='PASS'
    assert d['greeks_state']=='PASS'
    assert d['quote_coverage_pct']==100.0


def test_empty_chain_is_not_tested_for_greeks_and_fails_chain():
    d=assess_chain([], None)
    assert d['chain_state']=='FAIL'
    assert d['greeks_state']=='NOT_TESTED'


def test_diagnostics_recognizes_four_accounts_and_blocked_execution():
    d=build_diagnostics(adapter=Adapter())
    assert d['checks']['oauth']=='PASS'
    assert d['checks']['account_count']==4
    assert d['checks']['execution']=='BLOCKED'


def test_diagnostics_chain_fetcher_is_used():
    d=build_diagnostics(adapter=Adapter(), expiration='2026-07-20', chain_fetcher=lambda *_:{'source':'etrade','contracts':[{'bid':1,'ask':1.1}]})
    assert d['checks']['option_chain']=='PASS'
    assert d['chain']['source']=='etrade'


def test_safety_contract_is_read_only():
    d=build_diagnostics(adapter=Adapter())
    assert d['safety']['read_only_diagnostics'] is True
    assert d['safety']['automatic_execution_enabled'] is False


def test_mixed_chain_reports_partial_greek_coverage():
    d=assess_chain([{'bid':1,'ask':2,'delta':.5},{'bid':1,'ask':2}], 'polygon')
    assert d['greeks_coverage_pct']==50.0
