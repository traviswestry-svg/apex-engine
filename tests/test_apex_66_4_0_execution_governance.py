"""APEX 66.4.0 — Canonical Decision Execution Governance tests.

Two layers:
  1. The pure `evaluate_open_risk` rule and each explicit blocker code.
  2. The boundary asymmetry: OPENING risk is blocked when the canonical decision
     is not actionable; REDUCING/protecting risk is NEVER blocked by thesis state.
"""
import time
import pytest

from engine.execution import canonical_governance as cg
from engine.execution import canonical_execution as ce
from engine.execution.broker_interface import OrderIntent, BrokerResult


NOW = 1_800_000_000.0


def _snap(**kw):
    base = {"available": True, "authoritative": True, "actionable": True,
            "action": "ENTER", "direction": "BULLISH", "thesis_state": "ACTIVE",
            "generated_at": NOW - 10}
    base.update(kw)
    return base


# ── 1. pure rule ─────────────────────────────────────────────────────────────

def test_actionable_active_matching_fresh_allows():
    r = cg.evaluate_open_risk(_snap(), proposed_side="CALL", now_epoch=NOW, max_age_seconds=180)
    assert r.allow and r.blockers == []


def test_unavailable_blocks_open():
    r = cg.evaluate_open_risk(None, proposed_side="CALL", now_epoch=NOW, max_age_seconds=180)
    assert not r.allow and cg.CANONICAL_DECISION_UNAVAILABLE in r.codes


def test_not_actionable_blocks_open():
    r = cg.evaluate_open_risk(_snap(actionable=False), proposed_side="CALL", now_epoch=NOW, max_age_seconds=180)
    assert not r.allow and cg.CANONICAL_DECISION_NOT_ACTIONABLE in r.codes


@pytest.mark.parametrize("state", ["FORMING", "WEAKENING", "CONFLICTED", "INVALIDATED", "UNKNOWN"])
def test_non_active_thesis_blocks_open(state):
    r = cg.evaluate_open_risk(_snap(thesis_state=state), proposed_side="CALL", now_epoch=NOW, max_age_seconds=180)
    assert not r.allow and cg.THESIS_NOT_ACTIVE in r.codes


def test_direction_mismatch_blocks_open():
    r = cg.evaluate_open_risk(_snap(direction="BEARISH"), proposed_side="CALL", now_epoch=NOW, max_age_seconds=180)
    assert not r.allow and cg.DECISION_DIRECTION_MISMATCH in r.codes


def test_direction_agreement_put_bearish_allows():
    r = cg.evaluate_open_risk(_snap(direction="BEARISH"), proposed_side="PUT", now_epoch=NOW, max_age_seconds=180)
    assert r.allow


def test_stale_blocks_open():
    r = cg.evaluate_open_risk(_snap(generated_at=NOW - 4000), proposed_side="CALL", now_epoch=NOW, max_age_seconds=180)
    assert not r.allow and cg.CANONICAL_DECISION_STALE in r.codes


def test_missing_timestamp_is_stale():
    r = cg.evaluate_open_risk(_snap(generated_at=None), proposed_side="CALL", now_epoch=NOW, max_age_seconds=180)
    assert not r.allow and cg.CANONICAL_DECISION_STALE in r.codes


def test_no_trade_action_surfaces_distinctly_when_actionable_true():
    # Inconsistent-but-defensive input: actionable True yet action NO_TRADE.
    r = cg.evaluate_open_risk(_snap(action="NO_TRADE"), proposed_side="CALL", now_epoch=NOW, max_age_seconds=180)
    assert not r.allow and cg.CANONICAL_DECISION_NO_TRADE in r.codes


def test_snapshot_from_decision_extracts_fields():
    dec = {"authoritative_contract": True, "actionable": True, "action": "ENTER",
           "direction": "BULLISH", "thesis": {"state": "ACTIVE"}, "timestamp": "2026-08-07T14:00:00+00:00"}
    s = cg.governance_snapshot_from_decision(dec)
    assert s["available"] and s["actionable"] and s["thesis_state"] == "ACTIVE" and s["direction"] == "BULLISH"


def test_snapshot_from_empty_is_unavailable():
    assert cg.governance_snapshot_from_decision(None)["available"] is False
    assert cg.governance_snapshot_from_decision({})["available"] is False


# ── 2. boundary asymmetry ────────────────────────────────────────────────────

class _FakeAdapter:
    mode = "sandbox"
    trading_enabled = False

    def __init__(self):
        self.placed = []

    def place_order(self, preview_id, intent):
        self.placed.append(("place_order", preview_id, getattr(intent, "action", None)))
        return BrokerResult(ok=True, mode="sandbox", data={"order_id": "OID1"})


class _AllowDecision:
    allow = True
    reasons = []
    warnings = []

    def to_dict(self):
        return {"allow": True}


@pytest.fixture
def boundary(monkeypatch):
    # Isolate governance from risk-guard specifics: force the risk guard to pass
    # so the governance gate is the sole deciding factor.
    monkeypatch.setattr(ce.guard, "validate_entry", lambda **kw: _AllowDecision())
    monkeypatch.setattr(ce.guard, "validate_exit_quantity", lambda *a, **k: _AllowDecision())
    monkeypatch.setenv("APEX_EXECUTION_GOVERNANCE_ENABLED", "true")

    class _Limits:
        require_confirmation = False
    monkeypatch.setattr(ce.guard, "RiskLimits", type("RL", (), {"from_env": staticmethod(lambda: _Limits())}))
    return ce.CanonicalExecutionBoundary()


def _entry_intent(side="CALL"):
    return OrderIntent(symbol="SPX", osi_key="SPX...C", side=side, action="BUY_OPEN",
                       quantity=1, order_type="LIMIT", limit_price=1.0, tag="ENTRY")


def _contract(side="CALL"):
    return {"osi_key": "SPX...C", "side": side}


def test_open_risk_blocked_when_thesis_not_active(boundary):
    a = _FakeAdapter()
    boundary.register_preview("P1", contract=_contract(), quantity=1, entry_premium=1.0,
                              stop_premium=0.5, session_state="MARKET_OPEN", intent=_entry_intent(),
                              governance=_snap(thesis_state="INVALIDATED"))
    r = boundary.execute_single_leg(adapter=a, preview_id="P1", intent=_entry_intent(),
                                    contract=_contract(), quantity=1, entry_premium=1.0,
                                    stop_premium=0.5, session_state="MARKET_OPEN", last_order_epoch=None)
    assert not r.ok
    assert a.placed == []  # broker NEVER called
    assert cg.THESIS_NOT_ACTIVE in (r.data.get("governance", {}).get("codes") or [])


def test_open_risk_allowed_when_actionable_active(boundary):
    a = _FakeAdapter()
    boundary.register_preview("P2", contract=_contract(), quantity=1, entry_premium=1.0,
                              stop_premium=0.5, session_state="MARKET_OPEN", intent=_entry_intent(),
                              governance=_snap(generated_at=time.time()))
    r = boundary.execute_single_leg(adapter=a, preview_id="P2", intent=_entry_intent(),
                                    contract=_contract(), quantity=1, entry_premium=1.0,
                                    stop_premium=0.5, session_state="MARKET_OPEN", last_order_epoch=None)
    assert r.ok and a.placed and a.placed[0][0] == "place_order"


def test_open_risk_blocked_when_no_governance_snapshot(boundary):
    # Fail closed: previewed without a decision -> cannot open new risk.
    a = _FakeAdapter()
    boundary.register_preview("P3", contract=_contract(), quantity=1, entry_premium=1.0,
                              stop_premium=0.5, session_state="MARKET_OPEN", intent=_entry_intent(),
                              governance=None)
    r = boundary.execute_single_leg(adapter=a, preview_id="P3", intent=_entry_intent(),
                                    contract=_contract(), quantity=1, entry_premium=1.0,
                                    stop_premium=0.5, session_state="MARKET_OPEN", last_order_epoch=None)
    assert not r.ok and a.placed == []
    assert cg.CANONICAL_DECISION_UNAVAILABLE in (r.data.get("governance", {}).get("codes") or [])


def test_governance_disabled_allows_open(boundary, monkeypatch):
    monkeypatch.setenv("APEX_EXECUTION_GOVERNANCE_ENABLED", "false")
    a = _FakeAdapter()
    boundary.register_preview("P4", contract=_contract(), quantity=1, entry_premium=1.0,
                              stop_premium=0.5, session_state="MARKET_OPEN", intent=_entry_intent(),
                              governance=_snap(thesis_state="INVALIDATED"))
    r = boundary.execute_single_leg(adapter=a, preview_id="P4", intent=_entry_intent(),
                                    contract=_contract(), quantity=1, entry_premium=1.0,
                                    stop_premium=0.5, session_state="MARKET_OPEN", last_order_epoch=None)
    assert r.ok and a.placed  # flag off -> governance does not gate


def test_EXIT_never_blocked_even_with_invalidated_thesis(boundary):
    # THE safety property: a risk-reducing SELL_CLOSE must execute regardless of
    # thesis state. There is no way to even pass a governance snapshot to the
    # management executor — it is ungovernable by construction.
    a = _FakeAdapter()
    exit_intent = OrderIntent(symbol="SPX", osi_key="SPX...C", side="CALL", action="SELL_CLOSE",
                              quantity=1, order_type="LIMIT", limit_price=1.0, tag="EXIT")
    boundary.register_management_preview("X1", intent=exit_intent, held_quantity=1)
    r = boundary.execute_management_exit(adapter=a, preview_id="X1", intent=exit_intent,
                                         held_quantity=1, confirmed=True)
    assert r.ok and a.placed and a.placed[0][2] == "SELL_CLOSE"
