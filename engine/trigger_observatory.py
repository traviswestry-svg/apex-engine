"""APEX 69.8.2 — Universal Trade Trigger Observatory, Linkage & Calibration Readiness Verification.

Captures every genuine trigger presented to APEX, including triggers that are
confirmed, blocked, abstained from, expired, or ignored by the operator. Each
trigger receives a durable identity, a manual Power E*TRADE handoff contract,
and a five-minute underlying-price excursion observation. This module has no
broker mutation or execution authority.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from .canonical_persistence import connect as canonical_connect
from .persistent_store import persistent_sqlite_path

VERSION = "69.8.2"
SCHEMA_VERSION = "apex.trade_trigger_observatory.v2"
PRODUCTION_EFFECT = "OBSERVATIONAL_ONLY"
MAX_HOLD_SECONDS = 300
MAX_CONTRACTS = int(os.getenv("APEX_MAX_CONTRACTS", "3"))
MAX_RISK_PER_TRADE = float(os.getenv("APEX_MAX_TRADE_RISK", "2000"))
MAX_DAILY_LOSS = float(os.getenv("APEX_MAX_DAILY_LOSS", "1000"))
MAX_DAILY_TRADES = int(os.getenv("APEX_MAX_DAILY_TRADES", "3"))


def _path() -> str:
    return persistent_sqlite_path("APEX_TRIGGER_OBSERVATORY_DB", "apex_trigger_observatory.db")


def _iso(value: Any = None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).isoformat()


def _epoch(value: Any) -> float:
    return datetime.fromisoformat(_iso(value)).timestamp()


def _f(value: Any) -> Optional[float]:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _u(value: Any, default: str = "UNKNOWN") -> str:
    text = str(value or "").strip().upper()
    return text or default


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS observed_trade_triggers (
    trigger_id TEXT PRIMARY KEY, source_event_key TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL, trigger_type TEXT NOT NULL, setup_family TEXT NOT NULL,
    symbol TEXT NOT NULL, direction TEXT NOT NULL, disposition TEXT NOT NULL,
    triggered_at TEXT NOT NULL, observed_at TEXT NOT NULL, underlying_price REAL,
    confidence REAL, entry_reference REAL, stop_reference REAL,
    target1_reference REAL, target2_reference REAL, target3_reference REAL,
    blocker_codes_json TEXT NOT NULL, evidence_json TEXT NOT NULL,
    etrade_handoff_json TEXT NOT NULL, status TEXT NOT NULL,
    mfe_points REAL, mae_points REAL, last_price REAL, observation_count INTEGER NOT NULL DEFAULT 0,
    observation_window_seconds INTEGER NOT NULL, terminal_at TEXT, outcome_label TEXT,
    execution_authority INTEGER NOT NULL DEFAULT 0, broker_mutation INTEGER NOT NULL DEFAULT 0,
    production_effect TEXT NOT NULL, decision_id TEXT, canonical_grade_status TEXT,
    canonical_grade_label TEXT, canonical_grade_json TEXT, canonical_graded_at TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_trigger_observatory_time
    ON observed_trade_triggers(triggered_at, source);
CREATE INDEX IF NOT EXISTS ix_trigger_observatory_open
    ON observed_trade_triggers(status, symbol);

CREATE TABLE IF NOT EXISTS trade_trigger_price_observations (
    observation_id TEXT PRIMARY KEY, trigger_id TEXT NOT NULL,
    observed_at TEXT NOT NULL, price REAL NOT NULL, favorable_points REAL NOT NULL,
    adverse_points REAL NOT NULL, created_at TEXT NOT NULL,
    UNIQUE(trigger_id, observed_at)
);
CREATE INDEX IF NOT EXISTS ix_trigger_prices ON trade_trigger_price_observations(trigger_id, observed_at);
"""


def initialize_store(path: Optional[str] = None) -> Dict[str, Any]:
    resolved = path or _path()
    with canonical_connect(resolved, timeout=10) as conn:
        conn.executescript(_SCHEMA)
        # Additive migration for 69.7.1 observatory databases already in production.
        existing = {row[1] for row in conn.execute("PRAGMA table_info(observed_trade_triggers)")}
        for name, decl in (
            ("decision_id", "TEXT"),
            ("canonical_grade_status", "TEXT"),
            ("canonical_grade_label", "TEXT"),
            ("canonical_grade_json", "TEXT"),
            ("canonical_graded_at", "TEXT"),
        ):
            if name not in existing:
                conn.execute(f"ALTER TABLE observed_trade_triggers ADD COLUMN {name} {decl}")
        conn.execute("CREATE INDEX IF NOT EXISTS ix_trigger_decision_id ON observed_trade_triggers(decision_id)")
        conn.commit()
    return {"ok": True, "status": "READY", "path": resolved, "version": VERSION,
            "schema_version": SCHEMA_VERSION, "canonical_outcome_linkage": True,
            "execution_authority": False, "broker_mutation": False,
            "production_effect": PRODUCTION_EFFECT}


def _direction(value: Any) -> str:
    text = _u(value)
    if any(x in text for x in ("CALL", "BULL", "LONG", "BUY")): return "BULLISH"
    if any(x in text for x in ("PUT", "BEAR", "SHORT", "SELL")): return "BEARISH"
    if "EXIT" in text: return "EXIT"
    return "NEUTRAL"


def _hmac_key(source: str, event_key: str, trigger_type: str, symbol: str) -> str:
    return hashlib.sha256(f"{source}|{event_key}|{trigger_type}|{symbol}".encode()).hexdigest()[:32]


def _manual_etrade_handoff(*, symbol: str, direction: str, disposition: str,
                            entry: Optional[float], stop: Optional[float],
                            targets: list[Optional[float]]) -> Dict[str, Any]:
    side = "CALL" if direction == "BULLISH" else "PUT" if direction == "BEARISH" else None
    return {
        "mode": "MANUAL_POWER_ETRADE",
        "underlying": "SPX",
        "option_root": "SPXW",
        "expiration": "0DTE",
        "side": side,
        "suggested_contracts": 1 if disposition != "CONFIRMED" else min(3, MAX_CONTRACTS),
        "contract_selection_status": "LIVE_CHAIN_SELECTION_REQUIRED",
        "underlying_entry_reference": entry,
        "underlying_stop_reference": stop,
        "underlying_targets": [x for x in targets if x is not None],
        "max_hold_seconds": MAX_HOLD_SECONDS,
        "risk_limits": {"max_risk_per_trade": MAX_RISK_PER_TRADE,
                        "max_daily_loss": MAX_DAILY_LOSS,
                        "max_daily_trades": MAX_DAILY_TRADES,
                        "max_contracts": MAX_CONTRACTS},
        "order_submission_enabled": False,
        "order_preview_required": True,
        "human_confirmation_required": True,
    }


def record_trigger(*, source: str, trigger_type: str, symbol: str = "SPX",
                   direction: Any = None, disposition: str = "OBSERVED",
                   triggered_at: Any = None, source_event_key: Optional[str] = None,
                   setup_family: str = "UNCLASSIFIED", price: Any = None,
                   confidence: Any = None, entry: Any = None, stop: Any = None,
                   target1: Any = None, target2: Any = None, target3: Any = None,
                   blockers: Any = None, evidence: Optional[Mapping[str, Any]] = None,
                   decision_id: Optional[str] = None, path: Optional[str] = None) -> Dict[str, Any]:
    initialize_store(path)
    at = _iso(triggered_at)
    symbol = _u(symbol, "SPX"); source = _u(source); trigger_type = _u(trigger_type)
    direction = _direction(direction or trigger_type)
    event_key = str(source_event_key or f"{at}|{trigger_type}|{direction}")
    trigger_id = _hmac_key(source, event_key, trigger_type, symbol)
    entry_f = _f(entry) if _f(entry) is not None else _f(price)
    blocker_list = list(blockers or []) if isinstance(blockers, (list, tuple, set)) else ([str(blockers)] if blockers else [])
    disposition = _u(disposition, "OBSERVED")
    status = "OBSERVING" if direction in {"BULLISH", "BEARISH"} and entry_f is not None else "EVENT_ONLY"
    handoff = _manual_etrade_handoff(symbol=symbol, direction=direction, disposition=disposition,
                                     entry=entry_f, stop=_f(stop),
                                     targets=[_f(target1), _f(target2), _f(target3)])
    now = _iso()
    with canonical_connect(path or _path(), timeout=10) as conn:
        conn.execute(
            """INSERT OR IGNORE INTO observed_trade_triggers(
               trigger_id,source_event_key,source,trigger_type,setup_family,symbol,direction,
               disposition,triggered_at,observed_at,underlying_price,confidence,entry_reference,
               stop_reference,target1_reference,target2_reference,target3_reference,
               blocker_codes_json,evidence_json,etrade_handoff_json,status,observation_window_seconds,
               execution_authority,broker_mutation,production_effect,decision_id,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,0,?,?,?,?)""",
            (trigger_id, event_key, source, trigger_type, _u(setup_family), symbol, direction,
             disposition, at, now, _f(price), _f(confidence), entry_f, _f(stop), _f(target1),
             _f(target2), _f(target3), _json(blocker_list), _json(dict(evidence or {})),
             _json(handoff), status, MAX_HOLD_SECONDS, PRODUCTION_EFFECT,
             str(decision_id) if decision_id else None, now, now),
        )
        created = conn.execute("SELECT changes()").fetchone()[0] > 0
        conn.commit()
    return {"ok": True, "created": created, "trigger_id": trigger_id, "status": status,
            "disposition": disposition, "etrade_handoff": handoff,
            "execution_authority": False, "broker_mutation": False,
            "production_effect": PRODUCTION_EFFECT}


def record_pine_signal(signal: Mapping[str, Any], assistant: Optional[Mapping[str, Any]] = None,
                       *, path: Optional[str] = None) -> Dict[str, Any]:
    sig = dict(signal or {}); decision = dict(assistant or {})
    alert = bool(decision.get("alert"))
    blockers = decision.get("blockers") or decision.get("reason") or []
    return record_trigger(
        source="TRADINGVIEW_PINE", trigger_type=sig.get("signal") or "UNKNOWN",
        symbol=sig.get("ticker") or "SPX", direction=sig.get("direction") or sig.get("signal"),
        disposition="CONFIRMED" if alert else "BLOCKED", triggered_at=sig.get("received_at"),
        source_event_key=sig.get("signal_id") or sig.get("received_at"),
        setup_family=sig.get("system") or "PINE", price=sig.get("price") or sig.get("close"),
        confidence=sig.get("score") or sig.get("apex_ici"), stop=sig.get("stop"),
        target1=sig.get("target1") or sig.get("tp1"), target2=sig.get("target2") or sig.get("tp2"),
        target3=sig.get("target3") or sig.get("tp3"), blockers=blockers,
        evidence={"pine": sig, "assistant_disposition": decision}, path=path,
    )


def observe_price(*, symbol: str, price: Any, observed_at: Any = None,
                  path: Optional[str] = None) -> Dict[str, Any]:
    resolved = path or _path(); px = _f(price)
    if px is None or not Path(resolved).exists():
        return {"ok": False, "status": "PRICE_OR_STORE_UNAVAILABLE", "updated": 0}
    at = _iso(observed_at); at_epoch = _epoch(at); updated = terminal = 0
    with canonical_connect(resolved, timeout=10) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM observed_trade_triggers WHERE symbol=? AND status='OBSERVING'",
                            (_u(symbol, "SPX"),)).fetchall()
        for raw in rows:
            row = dict(raw); entry = _f(row.get("entry_reference"))
            if entry is None: continue
            sign = 1.0 if row["direction"] == "BULLISH" else -1.0
            move = (px-entry)*sign; favorable = max(0.0, move); adverse = min(0.0, move)
            elapsed = max(0.0, at_epoch - _epoch(row["triggered_at"]))
            conn.execute("INSERT OR IGNORE INTO trade_trigger_price_observations VALUES(?,?,?,?,?,?,?)",
                         (str(uuid.uuid4()), row["trigger_id"], at, px, favorable, adverse, _iso()))
            mfe = max(_f(row.get("mfe_points")) or 0.0, favorable)
            mae = min(_f(row.get("mae_points")) or 0.0, adverse)
            status = "OBSERVED" if elapsed >= row["observation_window_seconds"] else "OBSERVING"
            outcome = None
            terminal_at = None
            if status == "OBSERVED":
                terminal += 1; terminal_at = at
                outcome = "FAVORABLE" if mfe > abs(mae) and mfe > 0 else "ADVERSE" if abs(mae) > mfe else "MIXED"
            conn.execute(
                """UPDATE observed_trade_triggers SET mfe_points=?,mae_points=?,last_price=?,
                   observation_count=observation_count+1,status=?,terminal_at=COALESCE(?,terminal_at),
                   outcome_label=COALESCE(?,outcome_label),updated_at=? WHERE trigger_id=?""",
                (mfe, mae, px, status, terminal_at, outcome, at, row["trigger_id"]),
            ); updated += 1
        conn.commit()
    return {"ok": True, "status": "UPDATED", "updated": updated, "terminal": terminal,
            "execution_authority": False, "broker_mutation": False}


def _canonical_blockers(decision: Mapping[str, Any]) -> list[str]:
    """Expose only reasons derivable from the finalized canonical decision."""
    out: list[str] = []
    explicit = decision.get("blocking_conditions")
    if not explicit:
        explicit = (decision.get("conviction") or {}).get("blocking_conditions") if isinstance(decision.get("conviction"), Mapping) else None
    if isinstance(explicit, (list, tuple, set)):
        out.extend(str(x) for x in explicit if x not in (None, ""))
    elif explicit:
        out.append(str(explicit))

    if not bool(decision.get("actionable")):
        conviction = decision.get("conviction") if isinstance(decision.get("conviction"), Mapping) else {}
        score = _f(conviction.get("score") if conviction else decision.get("confidence"))
        if score is not None and score < 55.0:
            out.append("CONVICTION_BELOW_ACTIONABLE_THRESHOLD")
        direction = _u(decision.get("direction"))
        if direction not in {"BULLISH", "BEARISH"}:
            out.append("DIRECTION_NOT_ACTIONABLE")
        status = _u(decision.get("status"), "")
        if status and status not in {"ACTIONABLE", "UNKNOWN"}:
            out.append(status)
    return list(dict.fromkeys(out))


def record_canonical_snapshot(snapshot: Optional[Mapping[str, Any]], *,
                              fbd_capture: Optional[Mapping[str, Any]] = None,
                              canonical_decision_id: Optional[str] = None,
                              path: Optional[str] = None) -> Dict[str, Any]:
    s = dict(snapshot or {}); market = s.get("market_state") or {}
    symbol = str(s.get("ticker") or "SPX"); price = _f(market.get("price") or s.get("spot"))
    observed = observe_price(symbol=symbol, price=price, observed_at=s.get("timestamp") or _iso(), path=path)
    created = []
    decision = s.get("institutional_decision_object") or s.get("canonical_decision") or {}
    historical_capture = s.get("historical_evidence_capture") if isinstance(s.get("historical_evidence_capture"), Mapping) else {}
    decision_id = str(canonical_decision_id or historical_capture.get("decision_id") or decision.get("decision_id") or "").strip() or None
    action = _u(decision.get("action") or s.get("decision_state"))
    direction = decision.get("direction") or s.get("direction")
    blockers = _canonical_blockers(decision)
    if any(x in action for x in ("ENTER", "TRADE", "EXECUTE")):
        created.append(record_trigger(
            source="CANONICAL_DECISION", trigger_type=action, symbol=symbol, direction=direction,
            disposition="CONFIRMED" if decision.get("actionable", True) else "BLOCKED",
            triggered_at=s.get("timestamp") or _iso(), source_event_key=decision_id,
            decision_id=decision_id,
            setup_family=decision.get("setup_family") or s.get("setup_family") or "CANONICAL",
            price=price, confidence=decision.get("confidence") or decision.get("raw_conviction") or s.get("confidence"),
            entry=decision.get("entry_reference") or price, stop=decision.get("invalidation"),
            target1=decision.get("target") or (s.get("risk") or {}).get("target1"),
            target2=(s.get("risk") or {}).get("target2"), blockers=blockers,
            evidence={"decision": decision, "canonical_decision_id": decision_id}, path=path))
    for transition in (fbd_capture or {}).get("transitions") or []:
        if transition.get("state") != "ENTRY_ELIGIBLE": continue
        lifecycle_id = transition.get("lifecycle_id")
        current = next((x for x in ((fbd_capture or {}).get("current") or {}).get("active", [])
                        if x.get("lifecycle_id") == lifecycle_id), {})
        created.append(record_trigger(
            source="FAILED_BREAKDOWN_LIFECYCLE", trigger_type="ENTRY_ELIGIBLE",
            symbol=symbol, direction="BULLISH", disposition="OBSERVED",
            triggered_at=current.get("confirmed_at") or s.get("timestamp") or _iso(),
            source_event_key=lifecycle_id, setup_family="FAILED_BREAKDOWN",
            price=price, entry=price, stop=current.get("invalidation_price"),
            target1=current.get("target1_price"), target2=current.get("target2_price"),
            evidence={"lifecycle": current}, path=path))
    return {"ok": True, "created": created, "price_observation": observed, "version": VERSION,
            "execution_authority": False, "broker_mutation": False,
            "production_effect": PRODUCTION_EFFECT}



def sync_canonical_outcomes(*, path: Optional[str] = None, evidence_path: Optional[str] = None) -> Dict[str, Any]:
    """Persist canonical grading linkage for triggers that originated from decisions.

    This is observational synchronization only. It never changes the canonical grade,
    decision, eligibility, confidence, or execution state.
    """
    resolved = path or _path()
    if not Path(resolved).exists():
        return {"ok": True, "status": "WAITING_FOR_TRIGGERS", "linked": 0,
                "execution_authority": False, "production_effect": PRODUCTION_EFFECT}
    initialize_store(resolved)
    if evidence_path is None:
        from .evidence_pipeline import DEFAULT_DB
        evidence_path = str(DEFAULT_DB)
    if not Path(str(evidence_path)).exists():
        return {"ok": True, "status": "WAITING_FOR_CANONICAL_OUTCOMES", "linked": 0,
                "execution_authority": False, "production_effect": PRODUCTION_EFFECT}
    linked = 0
    with canonical_connect(str(evidence_path), read_only=True, timeout=4) as evidence_conn:
        evidence_conn.row_factory = sqlite3.Row
        grades = evidence_conn.execute(
            "SELECT decision_id,graded_at,status,exclusion_reason,horizon_seconds,outcome_json FROM grading_results"
        ).fetchall()
    by_decision = {str(row["decision_id"]): dict(row) for row in grades}
    if not by_decision:
        return {"ok": True, "status": "WAITING_FOR_CANONICAL_OUTCOMES", "linked": 0,
                "execution_authority": False, "production_effect": PRODUCTION_EFFECT}
    with canonical_connect(resolved, timeout=10) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT trigger_id,decision_id,source_event_key FROM observed_trade_triggers "
            "WHERE decision_id IS NOT NULL OR source='CANONICAL_DECISION'"
        ).fetchall()
        for row in rows:
            did = str(row["decision_id"] or row["source_event_key"] or "")
            grade = by_decision.get(did)
            if not grade:
                continue
            try:
                outcome = json.loads(grade.get("outcome_json") or "{}")
            except Exception:
                outcome = {}
            label = (
                "WIN" if outcome.get("won") is True else
                "LOSS" if outcome.get("won") is False and grade.get("status") == "GRADED" else
                str(grade.get("exclusion_reason") or grade.get("status") or "UNKNOWN").upper()
            )
            conn.execute(
                """UPDATE observed_trade_triggers SET decision_id=?,canonical_grade_status=?,
                   canonical_grade_label=?,canonical_grade_json=?,canonical_graded_at=?,updated_at=?
                   WHERE trigger_id=?""",
                (did, grade.get("status"), label, _json({
                    "status": grade.get("status"), "exclusion_reason": grade.get("exclusion_reason"),
                    "horizon_seconds": grade.get("horizon_seconds"), "outcome": outcome,
                }), grade.get("graded_at"), _iso(), row["trigger_id"]),
            )
            linked += 1
        conn.commit()
    return {"ok": True, "status": "LINKED" if linked else "NO_MATCHING_TRIGGER_GRADES",
            "linked": linked, "version": VERSION, "execution_authority": False,
            "broker_mutation": False, "production_effect": PRODUCTION_EFFECT}


def effectiveness(*, symbol: str = "SPX", path: Optional[str] = None) -> Dict[str, Any]:
    """Aggregate trigger effectiveness without granting behavioral authority."""
    resolved = path or _path()
    if not Path(resolved).exists():
        return {"ok": True, "status": "WAITING_FOR_TRIGGERS", "sample_size": 0,
                "groups": [], "version": VERSION, "execution_authority": False,
                "production_effect": PRODUCTION_EFFECT}
    initialize_store(resolved)
    with canonical_connect(resolved, read_only=True, timeout=4) as conn:
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute(
            """SELECT source,trigger_type,setup_family,direction,disposition,outcome_label,
                      mfe_points,mae_points,canonical_grade_status,canonical_grade_label,canonical_grade_json
               FROM observed_trade_triggers WHERE symbol=? ORDER BY triggered_at""",
            (_u(symbol, "SPX"),),
        ).fetchall()]
    groups: Dict[tuple[str, str, str, str], Dict[str, Any]] = {}
    linked = 0
    for row in rows:
        key = (row["source"], row["trigger_type"], row["setup_family"], row["direction"])
        g = groups.setdefault(key, {"source": key[0], "trigger_type": key[1],
                                    "setup_family": key[2], "direction": key[3],
                                    "sample_size": 0, "five_minute_observed": 0,
                                    "five_minute_favorable": 0, "canonical_graded": 0,
                                    "canonical_wins": 0, "canonical_losses": 0,
                                    "mfe_sum": 0.0, "mae_abs_sum": 0.0})
        g["sample_size"] += 1
        if row.get("outcome_label"):
            g["five_minute_observed"] += 1
            g["five_minute_favorable"] += int(row.get("outcome_label") == "FAVORABLE")
        if row.get("mfe_points") is not None:
            g["mfe_sum"] += float(row["mfe_points"])
        if row.get("mae_points") is not None:
            g["mae_abs_sum"] += abs(float(row["mae_points"]))
        if row.get("canonical_grade_status") == "GRADED":
            linked += 1; g["canonical_graded"] += 1
            g["canonical_wins"] += int(row.get("canonical_grade_label") == "WIN")
            g["canonical_losses"] += int(row.get("canonical_grade_label") == "LOSS")
    output = []
    for g in groups.values():
        n5 = g["five_minute_observed"]; ng = g["canonical_graded"]; n = g["sample_size"]
        g["five_minute_favorable_rate_pct"] = round(100.0 * g["five_minute_favorable"] / n5, 2) if n5 else None
        g["canonical_win_rate_pct"] = round(100.0 * g["canonical_wins"] / ng, 2) if ng else None
        g["avg_mfe_points"] = round(g.pop("mfe_sum") / n, 4) if n else None
        g["avg_mae_abs_points"] = round(g.pop("mae_abs_sum") / n, 4) if n else None
        g["behavioral_authority"] = False
        output.append(g)
    output.sort(key=lambda x: (-x["canonical_graded"], -x["five_minute_observed"], -x["sample_size"]))
    return {"ok": True, "status": "READY" if rows else "WAITING_FOR_TRIGGERS",
            "sample_size": len(rows), "canonical_graded_links": linked, "groups": output,
            "limitations": ["Five-minute excursion is observational and is not a canonical trade grade.",
                            "Canonical trigger effectiveness is reported only where a persisted graded decision is linked.",
                            "No trigger statistic automatically changes production behavior."],
            "version": VERSION, "schema_version": SCHEMA_VERSION,
            "execution_authority": False, "broker_mutation": False,
            "production_effect": PRODUCTION_EFFECT}


def history(*, symbol: str = "SPX", limit: int = 100, status: Optional[str] = None,
            path: Optional[str] = None) -> Dict[str, Any]:
    resolved = path or _path()
    if not Path(resolved).exists():
        return {"ok": True, "status": "WAITING_FOR_TRIGGERS", "triggers": [], "version": VERSION}
    limit = max(1, min(int(limit), 1000)); args: list[Any] = [_u(symbol, "SPX")]
    query = "SELECT * FROM observed_trade_triggers WHERE symbol=?"
    if status: query += " AND status=?"; args.append(_u(status))
    query += " ORDER BY triggered_at DESC LIMIT ?"; args.append(limit)
    with canonical_connect(resolved, read_only=True, timeout=4) as conn:
        conn.row_factory = sqlite3.Row; rows = conn.execute(query, args).fetchall()
    out = []
    for raw in rows:
        row = dict(raw)
        for key in ("blocker_codes_json", "evidence_json", "etrade_handoff_json"):
            row[key[:-5]] = json.loads(row.pop(key) or "{}")
        if row.get("canonical_grade_json"):
            try:
                row["canonical_grade"] = json.loads(row["canonical_grade_json"])
            except Exception:
                row["canonical_grade"] = None
        out.append(row)
    return {"ok": True, "status": "READY", "triggers": out, "count": len(out),
            "version": VERSION, "execution_authority": False, "broker_mutation": False,
            "production_effect": PRODUCTION_EFFECT}



def learning_readiness(*, evidence_path: Optional[str] = None, trigger_path: Optional[str] = None) -> Dict[str, Any]:
    """Return operator-facing evidence accumulation state without changing policy.

    This is deliberately read-only and does not create an evidence database merely
    because the Premium Discipline dashboard was opened.
    """
    if evidence_path is None:
        from .evidence_pipeline import DEFAULT_DB
        evidence_path = str(DEFAULT_DB)
    resolved = str(evidence_path)
    try:
        from .institutional_governance import MIN_GRADED
        required = int(MIN_GRADED)
    except Exception:
        required = 50
    if not Path(resolved).exists():
        return {
            "ok": True, "status": "WAITING_FOR_LIVE_DATA", "stage": "COLLECTING",
            "decisions_recorded": 0, "graded_outcomes": 0, "pending_decisions": 0,
            "excluded_outcomes": 0, "price_samples": 0, "minimum_graded": required,
            "progress_pct": 0.0, "calibration_eligible": False,
            "behavioral_authority": False, "execution_authority": False,
            "production_effect": PRODUCTION_EFFECT, "version": VERSION,
        }
    try:
        with canonical_connect(resolved, read_only=True, timeout=4) as conn:
            conn.row_factory = sqlite3.Row
            total = int(conn.execute("SELECT COUNT(*) n FROM decisions").fetchone()["n"])
            graded = int(conn.execute("SELECT COUNT(*) n FROM grading_results WHERE status='GRADED'").fetchone()["n"])
            excluded = int(conn.execute("SELECT COUNT(*) n FROM grading_results WHERE status='EXCLUDED'").fetchone()["n"])
            pending = int(conn.execute("SELECT COUNT(*) n FROM decisions WHERE status='PENDING'").fetchone()["n"])
            samples = int(conn.execute("SELECT COUNT(*) n FROM price_samples").fetchone()["n"])
    except Exception as exc:
        return {
            "ok": False, "status": "UNAVAILABLE", "stage": "UNKNOWN",
            "error": f"{type(exc).__name__}: {exc}", "minimum_graded": required,
            "calibration_eligible": False, "behavioral_authority": False,
            "execution_authority": False, "production_effect": PRODUCTION_EFFECT,
            "version": VERSION,
        }
    eligible = graded >= required
    progress = min(100.0, round(100.0 * graded / required, 1)) if required > 0 else 100.0
    stage = "CALIBRATION_ELIGIBLE" if eligible else ("SAMPLE_BUILDING" if graded > 0 else "COLLECTING")

    calibration = {"status": "UNAVAILABLE", "eligibility_mode": "HEURISTIC",
                   "graded_contexts": 0, "decision_contexts": 0,
                   "candidate_counts": {}, "active_calibrations": 0,
                   "automatic_activation": False, "human_activation_required": True}
    activation = {"active_count": 0, "policy": {"automatic_activation": False, "human_activation_required": True}}
    try:
        from .calibration_activation import activation_status, eligibility_readout
        calibration = eligibility_readout(resolved)
        activation = activation_status(resolved)
    except Exception as exc:
        calibration = dict(calibration, status="UNAVAILABLE", error=f"{type(exc).__name__}: {exc}")

    eligibility_mode = str(calibration.get("eligibility_mode") or calibration.get("status") or "HEURISTIC").upper()
    activation_eligible = eligibility_mode in {"ELIGIBLE", "APPROVED", "ACTIVE"}
    active_count = int(activation.get("active_count") or calibration.get("active_calibrations") or 0)
    if active_count > 0:
        activation_state = "ACTIVE"
        readiness_reason = "At least one human-approved bounded calibration is active."
    elif eligibility_mode == "APPROVED":
        activation_state = "APPROVED_AWAITING_ACTIVATION"
        readiness_reason = "A calibration candidate is approved but still requires explicit human activation."
    elif eligibility_mode == "ELIGIBLE":
        activation_state = "ELIGIBLE_FOR_HUMAN_REVIEW"
        readiness_reason = "Per-bucket calibration evidence is eligible for governed human review; automatic activation remains disabled."
    elif eligible:
        activation_state = "AGGREGATE_READY_BUCKETS_NOT_YET_ELIGIBLE"
        readiness_reason = "Aggregate graded history exceeds the global minimum, but governed per-context calibration readiness has not reached ELIGIBLE."
    else:
        activation_state = "ACCUMULATING"
        readiness_reason = "Aggregate graded history has not reached the governed minimum."

    maturation = {"observing": 0, "matured": 0, "overdue_observing": 0, "with_price_observations": 0}
    trigger_path = trigger_path or _path()
    if Path(trigger_path).exists():
        try:
            now_epoch = datetime.now(timezone.utc).timestamp()
            with canonical_connect(trigger_path, read_only=True, timeout=4) as tconn:
                tconn.row_factory = sqlite3.Row
                rows = tconn.execute("SELECT status,triggered_at,observation_count,observation_window_seconds FROM observed_trade_triggers").fetchall()
            for row in rows:
                status_value = str(row["status"] or "").upper()
                if status_value == "OBSERVING":
                    maturation["observing"] += 1
                    try:
                        if now_epoch - _epoch(row["triggered_at"]) >= int(row["observation_window_seconds"] or MAX_HOLD_SECONDS):
                            maturation["overdue_observing"] += 1
                    except Exception:
                        pass
                elif status_value == "OBSERVED":
                    maturation["matured"] += 1
                if int(row["observation_count"] or 0) > 0:
                    maturation["with_price_observations"] += 1
        except Exception:
            pass

    return {
        "ok": True, "status": "READY", "stage": stage,
        "decisions_recorded": total, "graded_outcomes": graded,
        "pending_decisions": pending, "excluded_outcomes": excluded,
        "price_samples": samples, "minimum_graded": required,
        "progress_pct": progress, "calibration_eligible": eligible,
        "calibration_activation_state": activation_state,
        "activation_eligible": activation_eligible,
        "readiness_reason": readiness_reason,
        "calibration_governance": calibration,
        "calibration_activation": activation,
        "observation_maturation": maturation,
        "automatic_activation": False, "human_activation_required": True,
        "behavioral_authority": False, "execution_authority": False,
        "production_effect": PRODUCTION_EFFECT, "version": VERSION,
    }


def _premium_projection(evidence: Mapping[str, Any]) -> Dict[str, Any]:
    """Extract only explicitly observed option-premium fields from trigger evidence."""
    pine = evidence.get("pine") if isinstance(evidence, Mapping) else None
    sources = [evidence, pine if isinstance(pine, Mapping) else {}]
    aliases = {
        "contract": ("contract", "option_contract", "contract_symbol"),
        "entry_premium": ("entry_premium", "premium", "option_premium"),
        "current_premium": ("current_premium",),
        "peak_premium": ("peak_premium", "max_premium"),
        "target1_premium": ("target1_premium", "tp1_premium"),
        "target2_premium": ("target2_premium", "tp2_premium"),
        "target3_premium": ("target3_premium", "tp3_premium"),
        "stop_premium": ("stop_premium",),
    }
    out: Dict[str, Any] = {}
    for dest, keys in aliases.items():
        value = None
        for source in sources:
            for key in keys:
                if source.get(key) not in (None, ""):
                    value = source.get(key); break
            if value not in (None, ""):
                break
        out[dest] = value
    out["available"] = any(v not in (None, "") for k, v in out.items() if k != "available")
    out["source"] = "RECORDED_TRIGGER_EVIDENCE" if out["available"] else "UNAVAILABLE"
    return out


def trade_visualization(*, trigger_id: Optional[str] = None, symbol: str = "SPX",
                        path: Optional[str] = None) -> Dict[str, Any]:
    """Build a read-only visualization contract from persisted trigger observations."""
    resolved = path or _path()
    if not Path(resolved).exists():
        return {"ok": True, "status": "WAITING_FOR_TRIGGERS", "trade": None,
                "execution_authority": False, "broker_mutation": False,
                "production_effect": PRODUCTION_EFFECT, "version": VERSION}
    initialize_store(resolved)
    with canonical_connect(resolved, read_only=True, timeout=4) as conn:
        conn.row_factory = sqlite3.Row
        if trigger_id:
            row = conn.execute("SELECT * FROM observed_trade_triggers WHERE trigger_id=?", (str(trigger_id),)).fetchone()
        else:
            row = conn.execute("SELECT * FROM observed_trade_triggers WHERE symbol=? ORDER BY triggered_at DESC LIMIT 1", (_u(symbol, "SPX"),)).fetchone()
        if row is None:
            return {"ok": True, "status": "NOT_FOUND", "trade": None,
                    "execution_authority": False, "broker_mutation": False,
                    "production_effect": PRODUCTION_EFFECT, "version": VERSION}
        raw = dict(row)
        observations = [dict(x) for x in conn.execute(
            "SELECT observed_at,price,favorable_points,adverse_points FROM trade_trigger_price_observations WHERE trigger_id=? ORDER BY observed_at",
            (raw["trigger_id"],),
        ).fetchall()]
    evidence = {}
    blockers = []
    try: evidence = json.loads(raw.get("evidence_json") or "{}")
    except Exception: evidence = {}
    try: blockers = json.loads(raw.get("blocker_codes_json") or "[]")
    except Exception: blockers = []
    direction = raw.get("direction")
    prices = [float(x["price"]) for x in observations if x.get("price") is not None]
    entry = _f(raw.get("entry_reference"))
    if entry is not None and not prices:
        prices = [entry]
    target_hits: Dict[str, bool] = {}
    for name, field in (("tp1", "target1_reference"), ("tp2", "target2_reference"), ("tp3", "target3_reference")):
        target = _f(raw.get(field))
        if target is None or not prices:
            target_hits[name] = False
        elif direction == "BULLISH":
            target_hits[name] = max(prices) >= target
        elif direction == "BEARISH":
            target_hits[name] = min(prices) <= target
        else:
            target_hits[name] = False
    stop = _f(raw.get("stop_reference"))
    stop_hit = False
    if stop is not None and prices:
        stop_hit = min(prices) <= stop if direction == "BULLISH" else max(prices) >= stop if direction == "BEARISH" else False
    trade = {
        "trigger_id": raw.get("trigger_id"), "decision_id": raw.get("decision_id"),
        "source": raw.get("source"), "trigger_type": raw.get("trigger_type"),
        "setup_family": raw.get("setup_family"), "symbol": raw.get("symbol"),
        "direction": direction, "disposition": raw.get("disposition"),
        "triggered_at": raw.get("triggered_at"), "status": raw.get("status"),
        "confidence": raw.get("confidence"), "entry": entry, "stop": stop,
        "tp1": _f(raw.get("target1_reference")), "tp2": _f(raw.get("target2_reference")),
        "tp3": _f(raw.get("target3_reference")), "last_price": _f(raw.get("last_price")),
        "mfe_points": _f(raw.get("mfe_points")), "mae_points": _f(raw.get("mae_points")),
        "outcome_label": raw.get("outcome_label"), "canonical_grade_status": raw.get("canonical_grade_status"),
        "canonical_grade_label": raw.get("canonical_grade_label"), "canonical_graded_at": raw.get("canonical_graded_at"),
        "blockers": blockers, "target_hits": target_hits, "stop_hit": stop_hit,
        "observations": observations, "premium": _premium_projection(evidence),
        "is_actionable_trade": raw.get("source") == "CANONICAL_DECISION" and raw.get("disposition") == "CONFIRMED" and raw.get("trigger_type") != "NO_TRADE",
        "observational_only": True,
    }
    return {"ok": True, "status": "READY", "trade": trade,
            "execution_authority": False, "broker_mutation": False,
            "production_effect": PRODUCTION_EFFECT, "version": VERSION}

def capability() -> Dict[str, Any]:
    return {"ok": True, "version": VERSION, "schema_version": SCHEMA_VERSION,
            "status": "OBSERVATIONAL", "captures": ["PINE_CALL", "PINE_PUT", "PINE_EXIT",
            "CANONICAL_ENTRY", "FAILED_BREAKDOWN_ENTRY_ELIGIBLE", "BLOCKED_TRIGGERS"],
            "observation_window_seconds": MAX_HOLD_SECONDS,
            "manual_etrade_handoff": True, "automatic_order_submission": False,
            "canonical_outcome_linkage": True, "canonical_decision_id_propagation": True, "blocked_reason_visibility": True, "trade_visualization": True, "learning_readiness_surface": True, "calibration_readiness_verification": True, "trigger_effectiveness_observational_only": True,
            "execution_authority": False, "broker_mutation": False,
            "production_effect": PRODUCTION_EFFECT}
