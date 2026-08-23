"""APEX 69.0 — Unified Historical Evidence Lifecycle Closure.

Runtime-only bridge connecting the canonical Institutional OS decision to the
existing durable evidence ledger.  This module is observational: it never
changes trade decisions, confidence, thresholds, or execution authority.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import threading
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from .evidence_pipeline import DEFAULT_DB, readiness, record_price, record_snapshot
from .outcome_grader import run_grader

VERSION = "69.0.0"
SCHEMA_VERSION = "apex.historical_evidence_lifecycle.v1"

_LOCK = threading.RLock()
_RUNTIME: Dict[str, Any] = {
    "decision_attempts": 0,
    "decisions_inserted": 0,
    "decision_duplicates": 0,
    "decision_errors": 0,
    "price_attempts": 0,
    "prices_written": 0,
    "price_errors": 0,
    "grader_runs": 0,
    "grader_errors": 0,
    "last_decision_at": None,
    "last_price_at": None,
    "last_grade_at": None,
    "last_grade_result": None,
    "market_memory_captures": 0,
    "market_memory_duplicates": 0,
    "market_memory_errors": 0,
}
_MEMORY_KEYS: set[str] = set()


def _m(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _f(value: Any) -> Optional[float]:
    try:
        x = float(value)
        return x if x == x else None
    except (TypeError, ValueError):
        return None


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _path(source: Mapping[str, Any], *paths: str) -> Any:
    for path in paths:
        cur: Any = source
        ok = True
        for key in path.split("."):
            if not isinstance(cur, Mapping) or key not in cur:
                ok = False
                break
            cur = cur[key]
        if ok and cur not in (None, ""):
            return cur
    return None


def _decision_id(ticker: str, timestamp: str, action: str, direction: str) -> str:
    raw = f"69.0|{ticker}|{timestamp}|{action}|{direction}"
    return "apex69_" + hashlib.sha256(raw.encode()).hexdigest()[:24]


def _extract_price(result: Mapping[str, Any], ido: Mapping[str, Any]) -> Optional[float]:
    for value in (
        _path(ido, "market_state.price", "market_state.spot", "entry_price"),
        _path(result, "market_state.price", "market_state.spot", "spot", "price", "underlying_price", "flow.stock_price"),
    ):
        price = _f(value)
        if price is not None and price > 0:
            return price
    return None


def _extract_confidence(result: Mapping[str, Any], ido: Mapping[str, Any]) -> Optional[float]:
    value = _path(
        ido,
        "conviction.score",
        "conviction.calibrated_conviction",
        "calibrated_conviction",
        "raw_conviction",
    )
    if value is None:
        value = _path(result, "confidence", "institutional_confidence", "ici")
    return _f(value)


def build_snapshot(result: Mapping[str, Any], *, session_state: Optional[str] = None) -> Dict[str, Any]:
    """Build one bounded, decision-time-only snapshot from a composed IOS result."""
    root = dict(result or {})
    ido = _m(root.get("institutional_decision_object"))
    ticker = str(ido.get("ticker") or root.get("ticker") or "SPX").upper()
    timestamp = str(ido.get("timestamp") or ido.get("generated_at") or root.get("generated_at") or _now())
    action = str(ido.get("action") or ido.get("decision_state") or "NO_TRADE").upper()
    direction = str(ido.get("direction") or "NEUTRAL").upper()
    actionable = bool(ido.get("actionable")) and action not in {"NO_TRADE", "STAND_DOWN", "ABSTAIN", "WATCH", "WATCH_ONLY"}
    price = _extract_price(root, ido)
    confidence = _extract_confidence(root, ido)

    # Preserve exactly the decision-time fields consumed by effectiveness,
    # dynamic-state calibration and attribution. Avoid persisting raw providers.
    snapshot: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "version": VERSION,
        "decision_id": _decision_id(ticker, timestamp, action, direction),
        "timestamp": timestamp,
        "ticker": ticker,
        "session": str(session_state or root.get("session") or "UNKNOWN").upper(),
        "action": action,
        "decision_state": action,
        "direction": direction,
        "entry_reference": price,
        "confidence": confidence,
        "learning_eligible": actionable,
        "actionable": actionable,
        "setup": ido.get("strategy") or root.get("setup") or root.get("playbook"),
        "institutional_decision_object": ido,
        "trade_horizon_intelligence": _m(root.get("trade_horizon_intelligence")),
        "market_regime": _path(root, "market_regime.regime", "market_regime.state", "market_state.regime", "regime"),
        "gamma_regime": _path(root, "gamma_regime.regime", "gamma_regime.state", "dealer_positioning.gamma_regime", "gamma.regime"),
        "volatility_regime": _path(root, "volatility_regime.regime", "volatility_regime.state", "volatility.regime"),
        "auction_regime": _path(root, "auction_regime.regime", "auction_regime.state", "auction.regime", "auction_intelligence.regime"),
        "dynamic_state": _m(root.get("dynamic_state")),
        "dynamic_state_policy": _m(root.get("dynamic_state_policy")),
        "decision_quality": _m(root.get("decision_quality")),
        "flow_excitation": _m(root.get("flow_excitation")),
        "gamma_path": _m(root.get("gamma_path")),
        "gamma_term_structure": _m(root.get("gamma_term_structure")),
        "residual_pressure": _m(root.get("residual_pressure")),
        "event_phase": _m(root.get("event_phase")),
        "execution_authority": False,
        "production_effect": "OBSERVATIONAL_ONLY",
    }
    return snapshot


def capture_decision(result: Mapping[str, Any], *, session_state: Optional[str] = None,
                     path: str | Path = DEFAULT_DB) -> Dict[str, Any]:
    """Persist one canonical composed decision. Idempotent by decision_id."""
    snap = build_snapshot(result, session_state=session_state)
    with _LOCK:
        _RUNTIME["decision_attempts"] += 1
    try:
        inserted = bool(record_snapshot(snap, path=path))
        with _LOCK:
            if inserted:
                _RUNTIME["decisions_inserted"] += 1
            else:
                _RUNTIME["decision_duplicates"] += 1
            _RUNTIME["last_decision_at"] = snap["timestamp"]
        _capture_market_memory(result, snap)
        return {"ok": True, "inserted": inserted, "decision_id": snap["decision_id"], "snapshot": snap}
    except Exception as exc:
        with _LOCK:
            _RUNTIME["decision_errors"] += 1
        return {"ok": False, "inserted": False, "decision_id": snap.get("decision_id"), "error": f"{type(exc).__name__}: {exc}"}


def _capture_market_memory(result: Mapping[str, Any], snap: Mapping[str, Any]) -> None:
    """Capture at most one Market Memory observation per session-state/day.

    APEX 69 makes canonical scanner-owned historical capture active by default,
    but it remains observational and can be disabled independently.
    """
    if str(os.getenv("APEX_MARKET_MEMORY_CAPTURE_ENABLED", "true")).lower() not in {"1", "true", "yes", "on"}:
        return
    timestamp = str(snap.get("timestamp") or _now())
    key = f"{timestamp[:10]}|{snap.get('ticker')}|{snap.get('session')}"
    with _LOCK:
        if key in _MEMORY_KEYS:
            _RUNTIME["market_memory_duplicates"] += 1
            return
    try:
        from .market_memory_engine_v220 import capture_snapshot
        payload = dict(result or {})
        payload.update({
            "ticker": snap.get("ticker"),
            "session": snap.get("session"),
            "direction": snap.get("direction"),
            "confidence": snap.get("confidence"),
            "price": snap.get("entry_reference"),
            "institutional_decision": {
                "decision": snap.get("action"),
                "bias": snap.get("direction"),
                "confidence": snap.get("confidence"),
                "regime": snap.get("market_regime"),
            },
        })
        out = capture_snapshot(payload, observed_at=timestamp, force=True)
        with _LOCK:
            _MEMORY_KEYS.add(key)
            if out.get("captured"):
                _RUNTIME["market_memory_captures"] += 1
            else:
                _RUNTIME["market_memory_duplicates"] += 1
    except Exception:
        with _LOCK:
            _RUNTIME["market_memory_errors"] += 1


def sample_price(ticker: str, price: Any, *, observed_at: Optional[str] = None,
                 path: str | Path = DEFAULT_DB) -> Dict[str, Any]:
    with _LOCK:
        _RUNTIME["price_attempts"] += 1
    try:
        written = bool(record_price(ticker, price, observed_at=observed_at, path=path))
        with _LOCK:
            if written:
                _RUNTIME["prices_written"] += 1
                _RUNTIME["last_price_at"] = observed_at or _now()
        return {"ok": written, "written": written}
    except Exception as exc:
        with _LOCK:
            _RUNTIME["price_errors"] += 1
        return {"ok": False, "written": False, "error": f"{type(exc).__name__}: {exc}"}


def grade(*, path: str | Path = DEFAULT_DB) -> Dict[str, Any]:
    with _LOCK:
        _RUNTIME["grader_runs"] += 1
    try:
        out = run_grader(path=path)
        with _LOCK:
            _RUNTIME["last_grade_at"] = _now()
            _RUNTIME["last_grade_result"] = out
        return out
    except Exception as exc:
        with _LOCK:
            _RUNTIME["grader_errors"] += 1
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def runtime_status(*, path: str | Path = DEFAULT_DB) -> Dict[str, Any]:
    try:
        ready = readiness(path)
    except Exception as exc:
        ready = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    with _LOCK:
        runtime = dict(_RUNTIME)
    return {
        "ok": bool(ready.get("ok", False)),
        "version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "readiness": ready,
        "runtime": runtime,
        "guardrails": {
            "backfills_history": False,
            "creates_synthetic_evidence": False,
            "changes_trade_decisions": False,
            "changes_execution_authority": False,
            "execution_authority": False,
        },
    }
