"""APEX 24.2 - Institutional Replay & Simulator.

Reconstructs the exact historical decision environment across every institutional
engine, rather than recalculating from current market data. A captured session is
an immutable, integrity-hashed snapshot of the outputs of the Trading Brain,
Regime Intelligence, Forecast Engine, Playbook Engine, Trading Coach, Execution
Intelligence, and Portfolio Intelligence, plus Market Memory references and a
read-only Continuous Learning view, assembled at capture time.

Design principles:
  * Reuse, don't duplicate: every engine output comes from that engine's existing
    ``build_*`` function. This module performs no market recalculation of its own.
  * Immutable history: a captured session (keyed by ``session_key``) is written
    once. Re-capture with the same key returns the existing record.
  * Read-only / advisory: nothing here places, modifies, or cancels orders,
    resizes positions, or mutates any other engine's records.
  * Simulator isolation: what-if analysis operates on the frozen captured inputs
    and returns an advisory comparison. It never writes to the session tables and
    never modifies historical records.

Trade-level decision replay reuses the existing APEX 14 ``institutional_replay_2``
engine (immutable, decision-time-only, look-ahead blocked) where a ``decision_id``
is available.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import sqlite3
import uuid
from typing import Any, Mapping, Optional

from . import institutional_governance as gov
from . import institutional_replay_2 as decision_replay
from .institutional_trading_brain_v230 import build_institutional_trading_brain
from .institutional_regime_intelligence_v231 import build_regime_intelligence
from .institutional_forecast_engine_v232 import build_institutional_forecast
from .institutional_playbook_engine_v233 import build_institutional_playbooks
from .continuous_learning_calibration_v234 import build_continuous_learning
from .institutional_ai_trading_coach_v235 import build_trading_coach
from .institutional_execution_intelligence_v240 import build_execution_intelligence
from .institutional_portfolio_risk_v241 import build_portfolio_intelligence

VERSION = "24.2.0_INSTITUTIONAL_REPLAY_SIMULATOR"
SCHEMA_VERSION = "apex.institutional_replay_v242.v1"

# Canonical timeline ordering. Events are emitted in this order and stamped with
# monotonically increasing timestamps so step/jump navigation is deterministic.
EVENT_ORDER = (
    "MARKET_STATE",
    "SIGNAL_GENERATION",
    "REGIME_TRANSITION",
    "FORECAST_UPDATE",
    "PLAYBOOK_UPDATE",
    "COACH_RECOMMENDATION",
    "ENTRY_APPROVAL",
    "TRADE_MANAGEMENT",
    "EXIT",
    "OUTCOME",
)


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _json(v: Any) -> str:
    return json.dumps(v, sort_keys=True, separators=(",", ":"), default=str)


def _load(v: Any, default: Any = None) -> Any:
    if v in (None, ""):
        return default
    try:
        return json.loads(v)
    except Exception:
        return default


def _conn():
    c = sqlite3.connect(gov.DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db() -> dict[str, Any]:
    gov.init_db()
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS apex_replay_sessions_v242(
          session_id TEXT PRIMARY KEY,
          session_key TEXT NOT NULL UNIQUE,
          ticker TEXT NOT NULL,
          captured_at TEXT NOT NULL,
          decision_id TEXT,
          frame_count INTEGER NOT NULL,
          environment_json TEXT NOT NULL,
          integrity_hash TEXT NOT NULL,
          schema_version TEXT NOT NULL,
          engine_version TEXT NOT NULL,
          created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS apex_replay_events_v242(
          event_id TEXT PRIMARY KEY,
          session_id TEXT NOT NULL,
          frame_index INTEGER NOT NULL,
          event_at TEXT NOT NULL,
          event_type TEXT NOT NULL,
          source_engine TEXT NOT NULL,
          rationale TEXT,
          event_json TEXT NOT NULL,
          FOREIGN KEY(session_id) REFERENCES apex_replay_sessions_v242(session_id));
        CREATE INDEX IF NOT EXISTS idx_replay_v242_events ON apex_replay_events_v242(session_id, frame_index);
        CREATE INDEX IF NOT EXISTS idx_replay_v242_created ON apex_replay_sessions_v242(created_at);
        """)
    return {"ok": True, "schema_version": SCHEMA_VERSION, "build_version": VERSION}


# ---------------------------------------------------------------------------
# Environment + timeline assembly (reuses existing engine builders)
# ---------------------------------------------------------------------------

def _build_environment(last: Mapping[str, Any]) -> dict[str, Any]:
    """Assemble the full multi-engine environment from existing builders."""
    last = dict(last or {})
    ticker = str(last.get("ticker") or "SPX")
    brain = build_institutional_trading_brain(last)
    regime = build_regime_intelligence(last)
    forecast = build_institutional_forecast(last)
    playbooks = build_institutional_playbooks(last)
    coach = build_trading_coach(last)
    execution = build_execution_intelligence(last)
    portfolio = build_portfolio_intelligence(last)
    learning = build_continuous_learning(last)  # read-only view
    return {
        "ticker": ticker,
        "trading_brain": brain,
        "regime_intelligence": regime,
        "forecast_engine": forecast,
        "playbook_engine": playbooks,
        "trading_coach": coach,
        "execution_intelligence": execution,
        "portfolio_intelligence": portfolio,
        "continuous_learning": {"read_only": True, "status": learning.get("status"),
                                "calibration": learning.get("calibration"),
                                "drift": learning.get("drift")},
        "market_memory_reference": last.get("market_memory") or {"referenced": False},
    }


def _evidence(support: Any, contra: Any) -> dict[str, list]:
    def _norm(v):
        if isinstance(v, list):
            return v
        if v in (None, ""):
            return []
        return [v]
    return {"supporting_evidence": _norm(support), "contradicting_evidence": _norm(contra)}


def _timeline(environment: Mapping[str, Any], base_at: str,
              trade: Optional[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Deterministic ordered timeline. Each event carries timestamp, source
    engine, rationale, supporting evidence, and contradicting evidence."""
    base = dt.datetime.fromisoformat(base_at)
    brain = environment.get("trading_brain", {})
    regime = environment.get("regime_intelligence", {})
    forecast = environment.get("forecast_engine", {})
    playbooks = environment.get("playbook_engine", {})
    coach = environment.get("trading_coach", {})
    execution = environment.get("execution_intelligence", {})
    portfolio = environment.get("portfolio_intelligence", {})
    trade = dict(trade or {})

    candidates = {
        "MARKET_STATE": ("REGIME_INTELLIGENCE", f"Primary regime {regime.get('primary_regime')}",
                         {"primary_regime": regime.get("primary_regime"),
                          "confidence": regime.get("confidence"),
                          "risk_posture": regime.get("risk_posture")},
                         regime.get("aligned_signals"), regime.get("transition")),
        "SIGNAL_GENERATION": ("TRADING_BRAIN", brain.get("headline"),
                              {"primary_thesis": brain.get("primary_thesis"),
                               "confidence": brain.get("calibrated_confidence")},
                              brain.get("primary_thesis"), brain.get("conflicting_evidence")),
        "REGIME_TRANSITION": ("REGIME_INTELLIGENCE", "Regime transition state",
                              regime.get("transition"),
                              regime.get("transition"), None),
        "FORECAST_UPDATE": ("FORECAST_ENGINE", f"Primary scenario {forecast.get('primary_scenario')}",
                            {"primary_scenario": forecast.get("primary_scenario"),
                             "forecast_confidence": forecast.get("forecast_confidence"),
                             "scenario_probabilities": forecast.get("scenario_probabilities")},
                            forecast.get("primary_scenario"), forecast.get("alternate_scenario")),
        "PLAYBOOK_UPDATE": ("PLAYBOOK_ENGINE", "Selected playbook",
                            playbooks.get("selected_playbook"),
                            playbooks.get("selected_playbook"), None),
        "COACH_RECOMMENDATION": ("TRADING_COACH", (coach.get("coaching") or {}).get("recommendation"),
                                 coach.get("coaching"),
                                 (coach.get("coaching") or {}).get("supporting"),
                                 (coach.get("coaching") or {}).get("cautions")),
        "ENTRY_APPROVAL": ("EXECUTION_INTELLIGENCE", "Entry approval gate",
                           {"execution_score": execution.get("execution_score"),
                            "eligible": (execution.get("execution_score") or {}).get("eligible")},
                           (execution.get("execution_score") or {}).get("grade"),
                           None),
        "TRADE_MANAGEMENT": ("EXECUTION_INTELLIGENCE", "Management plan",
                             execution.get("management_plan"),
                             execution.get("levels"), None),
        "EXIT": ("EXECUTION_INTELLIGENCE", "Exit guidance",
                 trade.get("exit") or (execution.get("management_plan") or {}),
                 trade.get("exit"), None),
        "OUTCOME": ("MARKET_MEMORY", "Recorded outcome",
                    trade.get("outcome"),
                    trade.get("outcome"), None),
    }

    events: list[dict[str, Any]] = []
    frame = 0
    for offset, event_type in enumerate(EVENT_ORDER):
        spec = candidates.get(event_type)
        if not spec:
            continue
        source, rationale, payload, support, contra = spec
        # Skip empty OUTCOME/EXIT events when no trade context is supplied so a
        # live decision-time replay contains no look-ahead outcome.
        if event_type in ("EXIT", "OUTCOME") and not payload:
            continue
        at = (base + dt.timedelta(seconds=offset)).isoformat()
        ev = {
            "frame_index": frame,
            "event_at": at,
            "event_type": event_type,
            "source_engine": source,
            "rationale": rationale if isinstance(rationale, str) else _json(rationale)[:280],
            "payload": payload,
            **_evidence(support, contra),
        }
        events.append(ev)
        frame += 1
    return events


# ---------------------------------------------------------------------------
# Capture (immutable) + retrieval
# ---------------------------------------------------------------------------

def capture(last: Mapping[str, Any], *, session_key: Optional[str] = None,
            trade: Optional[Mapping[str, Any]] = None, actor: str = "SYSTEM") -> dict[str, Any]:
    """Capture an immutable replay session from the current environment.

    Re-capturing with the same ``session_key`` returns the existing immutable
    record (no mutation).
    """
    init_db()
    last = dict(last or {})
    ticker = str(last.get("ticker") or "SPX")
    captured_at = _now()
    key = str(session_key or f"{ticker}:{captured_at}")
    decision_id = str(last.get("decision_id") or (trade or {}).get("decision_id") or "") or None

    with _conn() as c:
        row = c.execute("SELECT session_id, integrity_hash FROM apex_replay_sessions_v242 WHERE session_key=?",
                        (key,)).fetchone()
        if row:
            return {"ok": True, "status": "IMMUTABLE_EXISTS", "session_id": row["session_id"],
                    "integrity_hash": row["integrity_hash"], "created": False, "production_effect": "NONE"}

    environment = _build_environment(last)
    events = _timeline(environment, captured_at, trade)
    package = {"schema_version": SCHEMA_VERSION, "ticker": ticker, "captured_at": captured_at,
               "decision_id": decision_id, "environment": environment, "trade": dict(trade or {}),
               "events": events}
    ih = hashlib.sha256(_json(package).encode()).hexdigest()
    session_id = str(uuid.uuid4())
    created = _now()
    with _conn() as c:
        c.execute("INSERT INTO apex_replay_sessions_v242 VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                  (session_id, key, ticker, captured_at, decision_id, len(events),
                   _json(package), ih, SCHEMA_VERSION, VERSION, created))
        for ev in events:
            c.execute("INSERT INTO apex_replay_events_v242 VALUES(?,?,?,?,?,?,?,?)",
                      (str(uuid.uuid4()), session_id, ev["frame_index"], ev["event_at"],
                       ev["event_type"], ev["source_engine"], ev.get("rationale"), _json(ev)))
    gov.audit("CREATE_REPLAY_SESSION", "institutional_replay_v242", session_id,
              new={"session_key": key, "integrity_hash": ih, "frame_count": len(events)},
              actor=actor, explanation="Immutable multi-engine replay session captured")
    return {"ok": True, "status": "CREATED", "created": True, "session_id": session_id,
            "session_key": key, "ticker": ticker, "captured_at": captured_at,
            "decision_id": decision_id, "frame_count": len(events),
            "integrity_hash": ih, "production_effect": "NONE"}


def _fetch(session_id: str) -> Optional[dict[str, Any]]:
    with _conn() as c:
        row = c.execute("SELECT * FROM apex_replay_sessions_v242 WHERE session_id=? OR session_key=?",
                        (session_id, session_id)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["package"] = _load(d.pop("environment_json"), {})
    return d


def session(session_id: str) -> dict[str, Any]:
    """Return the immutable reconstructed environment for a session."""
    init_db()
    rec = _fetch(session_id)
    if not rec:
        return {"ok": False, "status": "NOT_FOUND", "error": "replay_session_not_found"}
    package = rec["package"]
    events = package.get("events", [])
    return {
        "ok": True, "status": "READY", "version": VERSION,
        "session_id": rec["session_id"], "session_key": rec["session_key"],
        "ticker": rec["ticker"], "captured_at": rec["captured_at"],
        "decision_id": rec["decision_id"], "integrity_hash": rec["integrity_hash"],
        "environment": package.get("environment", {}),
        "frame_count": len(events),
        "navigation": {"cursor": 0, "frame_count": len(events),
                       "actions": ["PLAY", "PAUSE", "STEP_FORWARD", "STEP_BACKWARD",
                                   "JUMP_TIMESTAMP", "JUMP_TRADE", "JUMP_REGIME_TRANSITION"]},
        "immutable": True, "future_information_allowed": False, "production_effect": "NONE",
    }


def timeline(session_id: str) -> dict[str, Any]:
    """Return the ordered, immutable timeline for a session."""
    init_db()
    rec = _fetch(session_id)
    if not rec:
        return {"ok": False, "status": "NOT_FOUND", "error": "replay_session_not_found"}
    events = rec["package"].get("events", [])
    ordered = sorted(events, key=lambda e: (e.get("frame_index", 0), e.get("event_at", "")))
    return {"ok": True, "status": "READY", "version": VERSION, "session_id": rec["session_id"],
            "event_count": len(ordered), "events": ordered,
            "immutable": True, "production_effect": "NONE"}


def trade(session_id: Optional[str] = None, decision_id: Optional[str] = None) -> dict[str, Any]:
    """Trade replay view. Reuses institutional_replay_2 decision replay when a
    decision_id is available; otherwise returns the captured trade context."""
    init_db()
    rec = _fetch(session_id) if session_id else None
    resolved_decision = decision_id or (rec["decision_id"] if rec else None)
    decision_view = None
    if resolved_decision:
        built = decision_replay.get(resolved_decision)
        if not built.get("ok"):
            decision_replay.create(resolved_decision)
            built = decision_replay.get(resolved_decision)
        if built.get("ok"):
            decision_view = built
    env = (rec["package"].get("environment") if rec else {}) or {}
    execution = env.get("execution_intelligence", {})
    brain = env.get("trading_brain", {})
    portfolio = env.get("portfolio_intelligence", {})
    trade_ctx = (rec["package"].get("trade") if rec else {}) or {}
    return {
        "ok": True, "status": "READY", "version": VERSION,
        "session_id": rec["session_id"] if rec else None,
        "decision_id": resolved_decision,
        "trade_replay": {
            "entry_thesis": brain.get("primary_thesis"),
            "market_structure": env.get("regime_intelligence", {}).get("primary_regime"),
            "supporting_evidence": brain.get("primary_thesis"),
            "conflicting_evidence": brain.get("conflicting_evidence"),
            "risk_parameters": portfolio.get("risk_budget"),
            "execution_score": execution.get("execution_score"),
            "coach_guidance": env.get("trading_coach", {}).get("coaching"),
            "final_outcome": trade_ctx.get("outcome"),
        },
        "decision_time_replay": decision_view,
        "immutable": True, "production_effect": "NONE",
    }


# ---------------------------------------------------------------------------
# Session navigation (pure functions over immutable frames)
# ---------------------------------------------------------------------------

def navigate(session_id: str, *, action: str = "PLAY", cursor: int = 0,
             timestamp: Optional[str] = None) -> dict[str, Any]:
    """Advisory navigation over immutable frames. Never mutates history."""
    init_db()
    rec = _fetch(session_id)
    if not rec:
        return {"ok": False, "status": "NOT_FOUND", "error": "replay_session_not_found"}
    events = sorted(rec["package"].get("events", []),
                    key=lambda e: (e.get("frame_index", 0), e.get("event_at", "")))
    n = len(events)
    action = str(action or "PLAY").upper()
    cursor = max(0, min(int(cursor), max(0, n - 1)))
    playing = False
    if action == "PLAY":
        playing = True
    elif action == "PAUSE":
        playing = False
    elif action == "STEP_FORWARD":
        cursor = min(n - 1, cursor + 1) if n else 0
    elif action == "STEP_BACKWARD":
        cursor = max(0, cursor - 1)
    elif action == "JUMP_TIMESTAMP" and timestamp:
        for i, e in enumerate(events):
            if e.get("event_at", "") >= timestamp:
                cursor = i
                break
        else:
            cursor = max(0, n - 1)
    elif action == "JUMP_TRADE":
        for i, e in enumerate(events):
            if e.get("event_type") in ("ENTRY_APPROVAL", "TRADE_MANAGEMENT"):
                cursor = i
                break
    elif action == "JUMP_REGIME_TRANSITION":
        for i, e in enumerate(events):
            if e.get("event_type") == "REGIME_TRANSITION":
                cursor = i
                break
    current = events[cursor] if n else None
    frames = events[cursor:] if (action == "PLAY" and n) else ([current] if current else [])
    return {"ok": True, "status": "READY", "version": VERSION, "session_id": rec["session_id"],
            "action": action, "playing": playing, "cursor": cursor, "frame_count": n,
            "current_frame": current, "frames": frames,
            "immutable": True, "production_effect": "NONE"}


# ---------------------------------------------------------------------------
# What-if Simulator (isolated; never mutates history)
# ---------------------------------------------------------------------------

def simulate(session_id: str, scenario: Mapping[str, Any]) -> dict[str, Any]:
    """Advisory what-if comparison on frozen captured inputs.

    Supported scenario types: ALTERNATIVE_PLAYBOOK, ALTERNATIVE_SIZING,
    ALTERNATIVE_EXITS. This function is pure with respect to persistence: it reads
    the immutable session and returns a comparison. It NEVER writes to the session
    tables and NEVER modifies historical records.
    """
    init_db()
    rec = _fetch(session_id)
    if not rec:
        return {"ok": False, "status": "NOT_FOUND", "error": "replay_session_not_found"}
    scenario = dict(scenario or {})
    stype = str(scenario.get("type") or "ALTERNATIVE_SIZING").upper()
    env = rec["package"].get("environment", {})
    portfolio = env.get("portfolio_intelligence", {})
    baseline_alloc = portfolio.get("capital_allocation", {})
    exposure = portfolio.get("exposure", {})

    comparison: dict[str, Any] = {"type": stype}
    if stype == "ALTERNATIVE_SIZING":
        factor = float(scenario.get("size_multiplier", 0.5) or 0.5)
        base_risk = float(baseline_alloc.get("advised_max_risk", 0.0) or 0.0)
        comparison["baseline"] = {"advised_max_risk": base_risk,
                                  "grade": baseline_alloc.get("grade")}
        comparison["alternative"] = {"size_multiplier": factor,
                                     "advised_max_risk": round(base_risk * factor, 2)}
        comparison["delta"] = {"advised_max_risk": round(base_risk * factor - base_risk, 2)}
    elif stype == "ALTERNATIVE_PLAYBOOK":
        comparison["baseline"] = {"playbook": env.get("playbook_engine", {}).get("selected_playbook"),
                                  "grade": baseline_alloc.get("grade")}
        comparison["alternative"] = {"playbook": scenario.get("playbook"),
                                     "note": "Advisory comparison only; production playbook unchanged."}
        comparison["delta"] = {"changed": scenario.get("playbook") is not None}
    elif stype == "ALTERNATIVE_EXITS":
        entry = float(scenario.get("entry", 0.0) or 0.0)
        base_exit = float(scenario.get("baseline_exit", 0.0) or 0.0)
        alt_exit = float(scenario.get("alternative_exit", 0.0) or 0.0)
        risk = max(1e-9, float(scenario.get("risk_per_unit", 1.0) or 1.0))
        comparison["baseline"] = {"exit": base_exit, "r_multiple": round((base_exit - entry) / risk, 3)}
        comparison["alternative"] = {"exit": alt_exit, "r_multiple": round((alt_exit - entry) / risk, 3)}
        comparison["delta"] = {"r_multiple": round(((alt_exit - entry) - (base_exit - entry)) / risk, 3)}
    else:
        return {"ok": False, "status": "UNSUPPORTED_SCENARIO", "type": stype}

    return {
        "ok": True, "status": "READY", "version": VERSION, "session_id": rec["session_id"],
        "scenario": scenario, "comparison": comparison,
        "advisory_only": True, "history_modified": False, "records_written": 0,
        "exposure_reference": exposure, "production_effect": "NONE",
    }


def list_sessions(limit: int = 100) -> dict[str, Any]:
    init_db()
    with _conn() as c:
        rows = c.execute("SELECT session_id, session_key, ticker, captured_at, decision_id, "
                         "frame_count, integrity_hash, created_at FROM apex_replay_sessions_v242 "
                         "ORDER BY created_at DESC LIMIT ?", (max(1, min(int(limit), 1000)),)).fetchall()
    return {"ok": True, "sessions": [dict(r) for r in rows], "count": len(rows)}


def status() -> dict[str, Any]:
    init_db()
    with _conn() as c:
        sessions = c.execute("SELECT COUNT(*) n FROM apex_replay_sessions_v242").fetchone()["n"]
        events = c.execute("SELECT COUNT(*) n FROM apex_replay_events_v242").fetchone()["n"]
    return {
        "status": "READY", "engine": "INSTITUTIONAL_REPLAY_SIMULATOR",
        "version": VERSION, "schema_version": SCHEMA_VERSION,
        "session_count": sessions, "event_count": events,
        "read_only": True, "advisory_only": True, "immutable_history": True,
        "simulator_writes_history": False, "future_information_allowed": False,
        "broker_order_submission_enabled": False, "production_effect": "NONE",
    }
