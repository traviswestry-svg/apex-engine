"""engine/settlement_health.py — Settlement-Path Health.

WHY THIS EXISTS
---------------
The learning/calibration stack can only accumulate samples if the full chain
works end to end:

    Pine webhook received  ->  trade decided  ->  outcome graded (labeled)
                            ->  calibration accumulates samples

On 2026-07-27 the webhook 403'd all session, so no signal ever reached the
execution engine, so nothing was graded, so calibration sat at sample_count=0
— and NOTHING on the dashboard said so. The calm "waiting for data" message
looked identical to a silent outage. This engine makes the difference visible:
it distinguishes "healthy but quiet" from "the feed is broken."

WHAT IT REPORTS
---------------
  * last Pine signal received (age) — never-received is flagged loudly
  * graded outcomes in the feature store (features written vs labels written)
  * unlabelled samples waiting on settlement (a backlog is its own warning)
  * calibration sample_count and whether a policy is active
  * an overall STATE with a plain-language reason and the single most useful
    next action

Read-only. Never raises into the compose loop — any error returns
available=False with the error string. Advisory only; it reports, it does not
gate execution.
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Dict, Optional

VERSION = "1.0.0_SETTLEMENT_HEALTH"

# A received signal older than this (and no newer one) during RTH is stale
# enough to warn about — the feed may have stopped.
_SIGNAL_STALE_SECONDS = 90 * 60
# Backlog of unlabelled samples above this suggests settlement isn't running.
_BACKLOG_WARN = 5


def _sf(v: Any, d: float = 0.0) -> float:
    try:
        x = float(v)
        return x if x == x else d
    except (TypeError, ValueError):
        return d


def _age_seconds(iso_ts: Optional[str], now: dt.datetime) -> Optional[int]:
    if not iso_ts:
        return None
    try:
        ts = dt.datetime.fromisoformat(str(iso_ts).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=dt.timezone.utc)
        return max(0, int((now - ts).total_seconds()))
    except (ValueError, TypeError):
        return None


def _humanize(seconds: Optional[int]) -> str:
    if seconds is None:
        return "never"
    if seconds < 90:
        return f"{seconds}s ago"
    if seconds < 90 * 60:
        return f"{seconds // 60}m ago"
    if seconds < 48 * 3600:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def build_settlement_health(
    *,
    last_signal: Optional[Dict[str, Any]],
    feature_store_health: Optional[Dict[str, Any]],
    calibration: Optional[Dict[str, Any]],
    is_rth: bool,
    now: Optional[dt.datetime] = None,
) -> Dict[str, Any]:
    """Assemble the settlement-path health payload from the three sources.

    All inputs are already-fetched dicts — this function never does I/O, so it
    can't time out or raise the compose loop.
    """
    try:
        return _build(last_signal, feature_store_health, calibration, is_rth,
                      now or dt.datetime.now(dt.timezone.utc))
    except Exception as err:
        return {"ok": True, "available": False, "version": VERSION,
                "state": "ERROR", "error": f"{type(err).__name__}: {err!r}"}


def _build(last_signal, fs, calib, is_rth, now) -> Dict[str, Any]:
    fs = fs or {}
    calib = calib or {}
    last_signal = last_signal or {}

    # ── Stage 1: signal receipt ──
    sig_age = _age_seconds(last_signal.get("received_at"), now)
    ever_received = sig_age is not None
    signal_stage = {
        "ever_received": ever_received,
        "last_received_age_seconds": sig_age,
        "last_received_human": _humanize(sig_age),
        "last_signal_side": last_signal.get("signal") if ever_received else None,
        "last_signal_ticker": last_signal.get("ticker") if ever_received else None,
    }
    if not ever_received:
        signal_health = "NONE_RECEIVED"
    elif is_rth and sig_age is not None and sig_age > _SIGNAL_STALE_SECONDS:
        signal_health = "STALE"
    else:
        signal_health = "OK"

    # ── Stage 2: grading / labeling (feature store) ──
    feature_rows = int(_sf(fs.get("feature_rows")))
    label_rows = int(_sf(fs.get("label_rows")))
    unlabelled = int(_sf(fs.get("unlabelled")))
    sessions = int(_sf(fs.get("feature_sessions")))
    grading_stage = {
        "features_written": feature_rows,
        "outcomes_graded": label_rows,
        "unlabelled_backlog": unlabelled,
        "distinct_sessions": sessions,
        "store_ready": bool(fs.get("ready")),
    }
    if not fs.get("ready"):
        grading_health = "STORE_DOWN"
    elif feature_rows == 0:
        grading_health = "NO_FEATURES"       # nothing ever captured
    elif label_rows == 0:
        grading_health = "NO_OUTCOMES_GRADED"  # captured but never settled
    elif unlabelled >= _BACKLOG_WARN:
        grading_health = "SETTLEMENT_BACKLOG"
    else:
        grading_health = "OK"

    # ── Stage 3: calibration accumulation ──
    train = calib.get("train") or {}
    calib_samples = int(_sf(train.get("sample_count") if "sample_count" in train
                            else calib.get("sample_count")))
    active_policy = calib.get("active_policy")
    calibration_stage = {
        "sample_count": calib_samples,
        "active_policy": active_policy,
        "policy_active": active_policy is not None,
        "expected_calibration_error": (train.get("expected_calibration_error")
                                       if train else calib.get("expected_calibration_error")),
    }
    calibration_health = "ACCUMULATING" if calib_samples == 0 else (
        "POLICY_ACTIVE" if active_policy is not None else "TRAINING")

    # ── Overall state + the single most useful next action ──
    # Order matters: report the FIRST broken link in the chain, because fixing
    # a downstream stage is pointless while an upstream one is dead.
    if not fs.get("ready"):
        state, reason, action = ("DEGRADED",
            "Feature store is not ready — outcomes cannot be recorded.",
            "Check the feature-store DB path and permissions on the data disk.")
    elif signal_health == "NONE_RECEIVED":
        state, reason, action = ("BROKEN",
            "No Pine signal has EVER been received. The execution feed is not reaching APEX, "
            "so no trade can be taken, graded, or learned from.",
            "Fire a manual TradingView test alert and confirm a 200 on /tv_signal. "
            "If it 403s, check the WEBHOOK REJECTED log line for the secret-length fingerprint.")
    elif signal_health == "STALE" and grading_health in ("NO_OUTCOMES_GRADED", "NO_FEATURES"):
        state, reason, action = ("WARNING",
            f"Last Pine signal was {signal_stage['last_received_human']} and nothing has graded. "
            "The feed may have stopped mid-session.",
            "Confirm TradingView alerts are still firing; check the latest /tv_signal log entry.")
    elif grading_health == "NO_FEATURES":
        state, reason, action = ("WARNING",
            "Signals are arriving but no decision features have been captured — the evidence "
            "pipeline may not be writing.",
            "Check decision_evidence_pipeline write_features logs for non-fatal errors.")
    elif grading_health == "NO_OUTCOMES_GRADED":
        state, reason, action = ("WARNING",
            f"{feature_rows} decision(s) captured but 0 graded. Outcomes are not being settled, "
            "so calibration can never accumulate.",
            "Verify the settlement/grading job runs after each session and writes flow_labels.")
    elif grading_health == "SETTLEMENT_BACKLOG":
        state, reason, action = ("WARNING",
            f"{unlabelled} captured decisions are unlabelled — settlement is falling behind.",
            "Run or unblock the outcome-grading job to clear the backlog.")
    elif calibration_health == "ACCUMULATING":
        state, reason, action = ("HEALTHY_EARLY",
            f"Chain is working: {label_rows} outcome(s) graded across {sessions} session(s). "
            "Calibration is accumulating toward its training threshold.",
            "No action needed — let graded outcomes accumulate.")
    else:
        state, reason, action = ("HEALTHY",
            f"Full settlement path is live: {label_rows} graded outcomes, calibration "
            f"{'policy active' if active_policy else 'in training'}.",
            "No action needed.")

    return {
        "ok": True,
        "available": True,
        "version": VERSION,
        "state": state,
        "reason": reason,
        "recommended_action": action,
        "is_rth": is_rth,
        "chain": {
            "signal_receipt": {"health": signal_health, **signal_stage},
            "outcome_grading": {"health": grading_health, **grading_stage},
            "calibration": {"health": calibration_health, **calibration_stage},
        },
        "advisory_only": True,
        "read_only": True,
    }
