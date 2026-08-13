"""Tests for engine/settlement_health.py."""
from __future__ import annotations

import datetime as dt

from engine.settlement_health import build_settlement_health

NOW = dt.datetime(2026, 7, 28, 16, 10, tzinfo=dt.timezone.utc)  # ~12:10 ET


def _fs(ready=True, features=0, labels=0, unlabelled=0, sessions=0):
    return {"ready": ready, "feature_rows": features, "label_rows": labels,
            "unlabelled": unlabelled, "feature_sessions": sessions}


def test_no_signal_ever_is_broken():
    r = build_settlement_health(
        last_signal=None, feature_store_health=_fs(), calibration={},
        is_rth=True, now=NOW)
    assert r["state"] == "BROKEN"
    assert r["chain"]["signal_receipt"]["health"] == "NONE_RECEIVED"
    assert "test alert" in r["recommended_action"].lower()


def test_signal_received_but_nothing_graded_warns():
    sig = {"received_at": (NOW - dt.timedelta(minutes=5)).isoformat(),
           "signal": "CALL", "ticker": "SPX"}
    r = build_settlement_health(
        last_signal=sig, feature_store_health=_fs(features=3, labels=0),
        calibration={}, is_rth=True, now=NOW)
    assert r["state"] == "WARNING"
    assert r["chain"]["outcome_grading"]["health"] == "NO_OUTCOMES_GRADED"


def test_stale_signal_mid_session_flagged():
    sig = {"received_at": (NOW - dt.timedelta(hours=2)).isoformat(),
           "signal": "PUT", "ticker": "SPX"}
    r = build_settlement_health(
        last_signal=sig, feature_store_health=_fs(features=0, labels=0),
        calibration={}, is_rth=True, now=NOW)
    assert r["chain"]["signal_receipt"]["health"] == "STALE"
    assert r["state"] == "WARNING"


def test_backlog_of_unlabelled_warns():
    sig = {"received_at": (NOW - dt.timedelta(minutes=2)).isoformat(), "signal": "CALL"}
    r = build_settlement_health(
        last_signal=sig, feature_store_health=_fs(features=20, labels=3, unlabelled=8),
        calibration={}, is_rth=True, now=NOW)
    assert r["chain"]["outcome_grading"]["health"] == "SETTLEMENT_BACKLOG"
    assert r["state"] == "WARNING"


def test_healthy_early_when_chain_works_but_calibration_young():
    sig = {"received_at": (NOW - dt.timedelta(minutes=2)).isoformat(), "signal": "CALL"}
    r = build_settlement_health(
        last_signal=sig,
        feature_store_health=_fs(features=12, labels=12, sessions=2),
        calibration={"train": {"sample_count": 0}, "active_policy": None},
        is_rth=True, now=NOW)
    assert r["state"] == "HEALTHY_EARLY"
    assert r["chain"]["calibration"]["health"] == "ACCUMULATING"


def test_fully_healthy_with_active_policy():
    sig = {"received_at": (NOW - dt.timedelta(minutes=2)).isoformat(), "signal": "CALL"}
    r = build_settlement_health(
        last_signal=sig,
        feature_store_health=_fs(features=60, labels=55, sessions=6),
        calibration={"train": {"sample_count": 55}, "active_policy": "policy_v3"},
        is_rth=True, now=NOW)
    assert r["state"] == "HEALTHY"
    assert r["chain"]["calibration"]["policy_active"] is True


def test_store_down_takes_precedence():
    sig = {"received_at": (NOW - dt.timedelta(minutes=2)).isoformat(), "signal": "CALL"}
    r = build_settlement_health(
        last_signal=sig, feature_store_health=_fs(ready=False),
        calibration={}, is_rth=True, now=NOW)
    assert r["state"] == "DEGRADED"


def test_never_raises_on_garbage():
    r = build_settlement_health(
        last_signal={"received_at": "not-a-date"},
        feature_store_health={"feature_rows": "x"},  # type: ignore
        calibration={"train": None}, is_rth=True, now=NOW)
    assert r["ok"] is True


def test_reflects_the_2026_07_27_incident():
    # The exact production condition: webhook 403 all day, calibration empty.
    r = build_settlement_health(
        last_signal=None,
        feature_store_health=_fs(ready=True, features=0, labels=0),
        calibration={"train": {"sample_count": 0}, "active_policy": None},
        is_rth=False, now=NOW)
    assert r["state"] == "BROKEN"
    assert r["chain"]["signal_receipt"]["ever_received"] is False
    assert r["chain"]["signal_receipt"]["last_received_human"] == "never"
