from datetime import datetime, timedelta, timezone

from flask import Flask

from engine.trigger_observatory import (
    capability, history, observe_price, record_pine_signal, record_trigger,
)
from engine.trigger_observatory_routes import register_trigger_observatory_routes, verify_registered


def test_every_pine_trigger_is_retained_even_when_blocked(tmp_path):
    db = str(tmp_path / "triggers.db")
    t = datetime(2026, 8, 31, 14, 35, tzinfo=timezone.utc)
    out = record_pine_signal({"received_at": t.isoformat(), "ticker": "SPX",
                              "signal": "CALL_ENTRY", "price": 7700, "score": 88,
                              "system": "APEX_SCALPER"},
                             {"alert": False, "blockers": ["FLOW_NOT_ALIGNED"]}, path=db)
    assert out["created"] is True and out["disposition"] == "BLOCKED"
    rows = history(path=db)["triggers"]
    assert len(rows) == 1 and rows[0]["disposition"] == "BLOCKED"
    assert rows[0]["etrade_handoff"]["order_submission_enabled"] is False


def test_duplicate_trigger_is_idempotent_and_observed_for_five_minutes(tmp_path):
    db = str(tmp_path / "triggers.db")
    t = datetime(2026, 8, 31, 14, 35, tzinfo=timezone.utc)
    args = dict(source="PINE", trigger_type="CALL_ENTRY", symbol="SPX",
                direction="BULLISH", disposition="CONFIRMED", triggered_at=t,
                source_event_key="pine-1", price=7700, path=db)
    assert record_trigger(**args)["created"] is True
    assert record_trigger(**args)["created"] is False
    observe_price(symbol="SPX", price=7705, observed_at=t + timedelta(seconds=60), path=db)
    observe_price(symbol="SPX", price=7698, observed_at=t + timedelta(seconds=301), path=db)
    row = history(path=db)["triggers"][0]
    assert row["status"] == "OBSERVED"
    assert row["mfe_points"] == 5.0 and row["mae_points"] == 0.0
    assert row["observation_count"] == 2
    assert row["late_observation_count"] == 1


def test_capability_and_routes_preserve_manual_boundary():
    cap = capability()
    assert cap["manual_etrade_handoff"] is True
    assert cap["automatic_order_submission"] is False
    assert cap["execution_authority"] is False and cap["broker_mutation"] is False
    app = Flask(__name__); register_trigger_observatory_routes(app)
    assert verify_registered(app)
