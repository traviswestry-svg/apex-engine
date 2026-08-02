import time
from unittest.mock import Mock

from engine.execution.broker_interface import BrokerResult, OrderIntent
from engine.execution.canonical_execution import CanonicalExecutionBoundary
from engine.learning_maturity import maturity_contract


def _contract(**overrides):
    c = {
        "symbol": "SPX", "side": "CALL", "expiration": "2099-01-01",
        "bid": 9.9, "ask": 10.1, "spread_pct": 2.0, "quote_age_seconds": 1.0,
        "osi_key": "SPXW TEST",
    }
    c.update(overrides)
    return c


def _intent():
    return OrderIntent(symbol="SPX", osi_key="SPXW TEST", side="CALL",
                       action="BUY_OPEN", quantity=1, limit_price=10.0, tag="ENTRY")


def test_learning_maturity_blocks_thin_sample_confidence():
    early = maturity_contract(1, 5, source="EARLY_ZONE_HISTORY")
    assert early["maturity"] == "EARLY_SAMPLE"
    assert early["statistically_usable"] is False
    assert early["display_policy"] == "DO_NOT_RENDER_AS_CALIBRATED_CONFIDENCE"
    ready = maturity_contract(5, 5, source="HISTORICAL_ZONE")
    assert ready["statistically_usable"] is True


def test_canonical_boundary_revalidates_risk_at_placement(monkeypatch):
    boundary = CanonicalExecutionBoundary()
    adapter = Mock(mode="sandbox", trading_enabled=False)
    adapter.place_order.return_value = BrokerResult(ok=True, mode="sandbox", data={"order_id": "1"})
    boundary.register_preview("p1", contract=_contract(), quantity=1, entry_premium=10.0,
                              stop_premium=8.0, session_state="MARKET_OPEN", intent=_intent())
    # Changed placement state is unsafe: stale quote. Must fail before adapter I/O.
    result = boundary.execute_single_leg(adapter=adapter, preview_id="p1", intent=_intent(),
        contract=_contract(quote_age_seconds=999), quantity=1, entry_premium=10.0,
        stop_premium=8.0, session_state="MARKET_OPEN", last_order_epoch=None)
    assert result.ok is False
    adapter.place_order.assert_not_called()


def test_canonical_boundary_blocks_duplicate_submit(monkeypatch):
    import engine.execution.canonical_execution as ce
    monkeypatch.setattr(ce.guard, "validate_entry", lambda **kwargs: Mock(allow=True, reasons=[], warnings=[], to_dict=lambda: {"allow": True}))
    boundary = CanonicalExecutionBoundary()
    adapter = Mock(mode="sandbox", trading_enabled=False)
    adapter.place_order.return_value = BrokerResult(ok=True, mode="sandbox", data={"order_id": "1"})
    boundary.register_preview("p2", contract=_contract(), quantity=1, entry_premium=10.0,
                              stop_premium=8.0, session_state="MARKET_OPEN", intent=_intent())
    kwargs=dict(adapter=adapter, preview_id="p2", intent=_intent(), contract=_contract(), quantity=1,
                entry_premium=10.0, stop_premium=8.0, session_state="MARKET_OPEN", last_order_epoch=None)
    assert boundary.execute_single_leg(**kwargs).ok is True
    assert boundary.execute_single_leg(**kwargs).ok is False
    assert adapter.place_order.call_count == 1


def test_hlce_route_registration_has_no_collector_start_side_effect():
    from pathlib import Path
    src = Path("engine/historical_level_calibration_routes.py").read_text()
    assert "service.start(" not in src
    scanner = Path("scanner_worker.py").read_text()
    assert "get_hlce_service().start(" in scanner


def test_runtime_db_files_are_ignored():
    from pathlib import Path
    ignore = Path(".gitignore").read_text()
    assert "*.db" in ignore
