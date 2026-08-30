"""APEX 69.7.1 — Universal Trade Trigger Observatory.

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

VERSION = "69.7.1"
SCHEMA_VERSION = "apex.trade_trigger_observatory.v1"
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
    production_effect TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
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
        conn.executescript(_SCHEMA); conn.commit()
    return {"ok": True, "status": "READY", "path": resolved, "version": VERSION,
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
                   path: Optional[str] = None) -> Dict[str, Any]:
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
               execution_authority,broker_mutation,production_effect,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,0,?,?,?)""",
            (trigger_id, event_key, source, trigger_type, _u(setup_family), symbol, direction,
             disposition, at, now, _f(price), _f(confidence), entry_f, _f(stop), _f(target1),
             _f(target2), _f(target3), _json(blocker_list), _json(dict(evidence or {})),
             _json(handoff), status, MAX_HOLD_SECONDS, PRODUCTION_EFFECT, now, now),
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


def record_canonical_snapshot(snapshot: Optional[Mapping[str, Any]], *,
                              fbd_capture: Optional[Mapping[str, Any]] = None,
                              path: Optional[str] = None) -> Dict[str, Any]:
    s = dict(snapshot or {}); market = s.get("market_state") or {}
    symbol = str(s.get("ticker") or "SPX"); price = _f(market.get("price") or s.get("spot"))
    observed = observe_price(symbol=symbol, price=price, observed_at=s.get("timestamp") or _iso(), path=path)
    created = []
    decision = s.get("institutional_decision_object") or s.get("canonical_decision") or {}
    action = _u(decision.get("action") or s.get("decision_state"))
    direction = decision.get("direction") or s.get("direction")
    if any(x in action for x in ("ENTER", "TRADE", "EXECUTE")):
        created.append(record_trigger(
            source="CANONICAL_DECISION", trigger_type=action, symbol=symbol, direction=direction,
            disposition="CONFIRMED" if decision.get("actionable", True) else "BLOCKED",
            triggered_at=s.get("timestamp") or _iso(), source_event_key=decision.get("decision_id"),
            setup_family=decision.get("setup_family") or s.get("setup_family") or "CANONICAL",
            price=price, confidence=decision.get("confidence") or s.get("confidence"),
            entry=decision.get("entry_reference") or price, stop=decision.get("invalidation"),
            target1=decision.get("target") or (s.get("risk") or {}).get("target1"),
            target2=(s.get("risk") or {}).get("target2"), blockers=decision.get("blocking_conditions"),
            evidence={"decision": decision}, path=path))
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
        out.append(row)
    return {"ok": True, "status": "READY", "triggers": out, "count": len(out),
            "version": VERSION, "execution_authority": False, "broker_mutation": False,
            "production_effect": PRODUCTION_EFFECT}


def capability() -> Dict[str, Any]:
    return {"ok": True, "version": VERSION, "schema_version": SCHEMA_VERSION,
            "status": "OBSERVATIONAL", "captures": ["PINE_CALL", "PINE_PUT", "PINE_EXIT",
            "CANONICAL_ENTRY", "FAILED_BREAKDOWN_ENTRY_ELIGIBLE", "BLOCKED_TRIGGERS"],
            "observation_window_seconds": MAX_HOLD_SECONDS,
            "manual_etrade_handoff": True, "automatic_order_submission": False,
            "execution_authority": False, "broker_mutation": False,
            "production_effect": PRODUCTION_EFFECT}
