"""APEX 48.2.1 — session-aware Morning Readiness tests.

Covers every scenario named in the build spec: weekend, holiday, premarket,
open market, live recommendation, broker disconnected, quotes stale/healthy,
risk configured/missing, and recommendation waiting.
"""
from engine.session_readiness import (
    build_session_readiness,
    normalize_session,
    ReadinessState,
    OverallStatus,
)
from engine.institutional_execution_os import build_morning_readiness


def _states(block):
    return {row["key"]: row["state"] for row in block["checklist"]}


def _closed_checks():
    # Everything the execution snapshot reports False while the market is closed.
    return {
        "recommendation_present": False,
        "chain_gate_passed": True,   # nothing suppressing when no rec
        "quotes_present": False,
        "quotes_fresh": False,
        "liquidity_acceptable": False,
        "risk_defined": False,
        "market_open": False,
        "broker_ready": False,
    }


def _live_healthy_checks():
    return {
        "recommendation_present": True,
        "chain_gate_passed": True,
        "quotes_present": True,
        "quotes_fresh": True,
        "liquidity_acceptable": True,
        "risk_defined": True,
        "market_open": True,
        "broker_ready": True,
    }


# ── session normalization ──────────────────────────────────────────────────
def test_normalize_maps_canonical_states():
    assert normalize_session("MARKET_OPEN")["phase"] == "REGULAR_SESSION"
    assert normalize_session("PREMARKET")["phase"] == "PREMARKET"
    assert normalize_session("AFTER_HOURS")["phase"] == "AFTER_HOURS"
    assert normalize_session("OVERNIGHT")["phase"] == "OVERNIGHT"
    assert normalize_session("CLOSED")["phase"] == "WEEKEND"
    assert normalize_session({"session": "CLOSED", "is_holiday": True})["phase"] == "HOLIDAY"
    assert normalize_session("MARKET_OPEN")["is_live"] is True
    assert normalize_session("PREMARKET")["is_live"] is False


# ── the core promise: no false FAIL when closed ────────────────────────────
def test_weekend_has_no_fail_states():
    block = build_session_readiness(session="CLOSED", execution_checks=_closed_checks(),
                                    risk_config_ready=True)
    assert all(r["state"] != ReadinessState.FAIL.value for r in block["checklist"])
    s = _states(block)
    assert s["market"] == ReadinessState.CLOSED.value
    assert s["quotes_present"] == ReadinessState.NOT_EXPECTED.value
    assert s["quotes_fresh"] == ReadinessState.NOT_EXPECTED.value
    assert s["liquidity"] == ReadinessState.NOT_EXPECTED.value
    assert s["recommendation"] == ReadinessState.WAITING.value
    assert s["risk"] == ReadinessState.READY.value
    assert s["broker"] == ReadinessState.NOT_REQUIRED.value
    assert block["overall"]["status"] == OverallStatus.STANDBY.value


def test_holiday_reports_standby_holiday():
    block = build_session_readiness(session={"session": "CLOSED", "is_holiday": True},
                                    execution_checks=_closed_checks(), risk_config_ready=True)
    assert block["session"]["phase"] == "HOLIDAY"
    assert block["overall"]["status"] == OverallStatus.STANDBY.value
    assert block["overall"]["headline"] == "Market Holiday"
    assert all(r["state"] != ReadinessState.FAIL.value for r in block["checklist"])


def test_premarket_has_no_fail_states():
    block = build_session_readiness(session="PREMARKET", execution_checks=_closed_checks(),
                                    risk_config_ready=True)
    s = _states(block)
    assert s["market"] == ReadinessState.CLOSED.value
    assert s["quotes_present"] == ReadinessState.NOT_EXPECTED.value
    assert all(r["state"] != ReadinessState.FAIL.value for r in block["checklist"])
    assert block["overall"]["status"] == OverallStatus.STANDBY.value


# ── open market ────────────────────────────────────────────────────────────
def test_open_market_all_healthy_is_ready():
    block = build_session_readiness(session="MARKET_OPEN", execution_checks=_live_healthy_checks(),
                                    risk_config_ready=True)
    s = _states(block)
    assert s["market"] == ReadinessState.OPEN.value
    assert s["quotes_present"] == ReadinessState.READY.value
    assert s["quotes_fresh"] == ReadinessState.READY.value
    assert s["liquidity"] == ReadinessState.READY.value
    assert s["recommendation"] == ReadinessState.READY.value
    assert s["broker"] == ReadinessState.READY.value
    assert block["overall"]["status"] == OverallStatus.READY.value


def test_live_recommendation_available():
    checks = _live_healthy_checks()
    block = build_session_readiness(session="MARKET_OPEN", execution_checks=checks,
                                    risk_config_ready=True)
    assert _states(block)["recommendation"] == ReadinessState.READY.value


def test_recommendation_waiting_when_open_without_rec():
    checks = _live_healthy_checks()
    checks["recommendation_present"] = False
    block = build_session_readiness(session="MARKET_OPEN", execution_checks=checks,
                                    risk_config_ready=True)
    assert _states(block)["recommendation"] == ReadinessState.WAITING.value
    assert block["overall"]["status"] == OverallStatus.WAITING.value


# ── broker ─────────────────────────────────────────────────────────────────
def test_broker_disconnected_requires_action():
    checks = _live_healthy_checks()
    checks["broker_ready"] = False  # live + rec present but broker down
    block = build_session_readiness(session="MARKET_OPEN", execution_checks=checks,
                                    risk_config_ready=True)
    assert _states(block)["broker"] == ReadinessState.DISCONNECTED.value
    assert block["overall"]["status"] == OverallStatus.ACTION_REQUIRED.value


def test_broker_not_required_when_closed():
    block = build_session_readiness(session="CLOSED", execution_checks=_closed_checks(),
                                    risk_config_ready=True)
    assert _states(block)["broker"] == ReadinessState.NOT_REQUIRED.value


# ── quotes ─────────────────────────────────────────────────────────────────
def test_quotes_stale_when_open_is_fail():
    checks = _live_healthy_checks()
    checks["quotes_fresh"] = False
    block = build_session_readiness(session="MARKET_OPEN", execution_checks=checks,
                                    risk_config_ready=True)
    assert _states(block)["quotes_fresh"] == ReadinessState.FAIL.value
    assert block["overall"]["status"] == OverallStatus.FAILURE.value


def test_quotes_healthy_when_open_is_ready():
    block = build_session_readiness(session="MARKET_OPEN", execution_checks=_live_healthy_checks(),
                                    risk_config_ready=True)
    assert _states(block)["quotes_fresh"] == ReadinessState.READY.value


# ── risk ───────────────────────────────────────────────────────────────────
def test_risk_configured_is_ready():
    block = build_session_readiness(session="CLOSED", execution_checks=_closed_checks(),
                                    risk_config_ready=True)
    assert _states(block)["risk"] == ReadinessState.READY.value


def test_risk_missing_when_closed_is_waiting_not_fail():
    block = build_session_readiness(session="CLOSED", execution_checks=_closed_checks(),
                                    risk_config_ready=False)
    assert _states(block)["risk"] == ReadinessState.WAITING.value
    assert all(r["state"] != ReadinessState.FAIL.value for r in block["checklist"])


def test_risk_missing_when_open_is_fail():
    checks = _live_healthy_checks()
    block = build_session_readiness(session="MARKET_OPEN", execution_checks=checks,
                                    risk_config_ready=False)
    assert _states(block)["risk"] == ReadinessState.FAIL.value


# ── integration through build_morning_readiness ────────────────────────────
def _sys_checks_all_pass():
    return {k: {"status": "PASS", "summary": "ok"} for k in [
        "application", "database", "data_freshness", "providers", "recommendation_ledger",
        "execution", "clock", "version_consistency", "alerts", "scheduler"]}


def test_morning_readiness_closed_matches_expected_ui():
    out = build_morning_readiness(
        system_checks=_sys_checks_all_pass(),
        execution={"execution_score": 90, "execution_decision": "DO_NOT_EXECUTE",
                   "checks": _closed_checks()},
        market_open=False,
        session="CLOSED",
        risk_config_ready=True,
    )
    # Legacy contract preserved.
    assert out["trading_mode"] == "ANALYSIS_ONLY"
    # New session-aware surface present.
    assert out["overall_status"] == "STANDBY"
    s = {r["key"]: r["state"] for r in out["checklist"]}
    assert s["market"] == "CLOSED"
    assert s["quotes_present"] == "NOT_EXPECTED"
    assert s["recommendation"] == "WAITING"
    assert s["risk"] == "READY"
    assert all(r["state"] != "FAIL" for r in out["checklist"])


def test_morning_readiness_backward_compatible_without_session():
    # Existing callers that pass no session must still work.
    out = build_morning_readiness(
        system_checks=_sys_checks_all_pass(),
        execution={"execution_score": 95},
        market_open=False,
    )
    assert out["trading_mode"] == "ANALYSIS_ONLY"
    assert out["overall_status"] == "STANDBY"
    assert "checklist" in out
