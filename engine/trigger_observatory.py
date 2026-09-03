"""APEX 69.9.10 — Live Actionability Capture Probe & Lifecycle Attribution Closure.

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
from zoneinfo import ZoneInfo

from .canonical_persistence import connect as canonical_connect
from .persistent_store import persistent_sqlite_path

VERSION = "69.9.10"
SCHEMA_VERSION = "apex.trade_trigger_observatory.v3"
PRODUCTION_EFFECT = "OBSERVATIONAL_ONLY"
MAX_HOLD_SECONDS = 300
MAX_CONTRACTS = int(os.getenv("APEX_MAX_CONTRACTS", "3"))
MAX_RISK_PER_TRADE = float(os.getenv("APEX_MAX_TRADE_RISK", "2000"))
MAX_DAILY_LOSS = float(os.getenv("APEX_MAX_DAILY_LOSS", "1000"))
MAX_DAILY_TRADES = int(os.getenv("APEX_MAX_DAILY_TRADES", "3"))
_RECOMMENDATION_NO_TRADE_STATES = {"NO_TRADE", "STAND_DOWN", "ABSTAIN", "WATCH", "WATCH_ONLY"}


def _recommendation_layer_blocks(actionability: Dict[str, Any]) -> bool:
    """Return True when captured recommendation intent itself abstains.

    Historical blocker attribution originally collapsed rows with an explicit
    recommendation-layer ``NO_TRADE`` into ``NO_EXPLICIT_BLOCKER`` whenever the
    raw trigger blocker list was empty. That made the blocker taxonomy less
    honest and inflated the diagnostic "no explicit blocker" cohort with
    recommendation-driven abstentions.
    """
    recommendation_action = str(actionability.get("recommendation_action") or "UNKNOWN").upper()
    recommendation_state = str(actionability.get("recommendation_state") or "UNKNOWN").upper()
    return (
        recommendation_action in _RECOMMENDATION_NO_TRADE_STATES
        or recommendation_state in _RECOMMENDATION_NO_TRADE_STATES
    )


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


def _window_metrics(trigger: Mapping[str, Any], observations: list[Mapping[str, Any]], *, now: Any = None) -> Dict[str, Any]:
    """Recompute the five-minute observation contract from persisted samples only.

    The legacy trigger row may contain MFE/MAE produced by a late first sample.
    69.9.5 never trusts those aggregates; it recomputes from raw observations whose
    elapsed time is within [0, observation_window_seconds].
    """
    window_seconds = int(trigger.get("observation_window_seconds") or MAX_HOLD_SECONDS)
    if _u(trigger.get("direction")) not in {"BULLISH", "BEARISH"} or _f(trigger.get("entry_reference")) is None:
        return {
            "window_integrity_status": "NOT_APPLICABLE", "window_matured": False,
            "observation_window_seconds": window_seconds, "in_window_observation_count": 0,
            "late_observation_count": 0, "pre_trigger_observation_count": 0,
            "window_mfe_points": None, "window_mae_points": None, "window_outcome_label": None,
            "first_in_window_observed_at": None, "last_in_window_observed_at": None,
            "first_late_observed_at": None, "first_in_window_elapsed_seconds": None,
            "last_in_window_elapsed_seconds": None, "first_late_elapsed_seconds": None,
            "in_window_observations": [], "late_observations": [], "pre_trigger_observations": [],
        }
    triggered_epoch = _epoch(trigger.get("triggered_at"))
    now_epoch = _epoch(now) if now is not None else datetime.now(timezone.utc).timestamp()
    in_window: list[Dict[str, Any]] = []
    late: list[Dict[str, Any]] = []
    pre_trigger: list[Dict[str, Any]] = []
    for raw in observations or []:
        row = dict(raw)
        try:
            elapsed = _epoch(row.get("observed_at")) - triggered_epoch
        except Exception:
            continue
        row["elapsed_seconds"] = round(float(elapsed), 3)
        if 0.0 <= elapsed <= float(window_seconds):
            row["window_class"] = "IN_WINDOW"
            in_window.append(row)
        elif elapsed > float(window_seconds):
            row["window_class"] = "LATE"
            late.append(row)
        else:
            row["window_class"] = "PRE_TRIGGER"
            pre_trigger.append(row)

    matured = (now_epoch - triggered_epoch) >= float(window_seconds)
    if in_window:
        window_status = "IN_WINDOW"
    elif late:
        window_status = "LATE"
    elif matured:
        window_status = "WINDOW_MISSED"
    else:
        window_status = "OBSERVING"

    mfes = [_f(x.get("favorable_points")) for x in in_window]
    maes = [_f(x.get("adverse_points")) for x in in_window]
    mfes = [x for x in mfes if x is not None]
    maes = [x for x in maes if x is not None]
    mfe = max(mfes) if mfes else None
    mae = min(maes) if maes else None
    if in_window and mfe is not None and mae is not None:
        outcome = "FAVORABLE" if mfe > abs(mae) and mfe > 0 else "ADVERSE" if abs(mae) > mfe else "MIXED"
    elif in_window:
        outcome = "MIXED"
    elif matured or late:
        outcome = "OBSERVATION_WINDOW_INCOMPLETE"
    else:
        outcome = None

    return {
        "window_integrity_status": window_status,
        "window_matured": bool(matured),
        "observation_window_seconds": window_seconds,
        "in_window_observation_count": len(in_window),
        "late_observation_count": len(late),
        "pre_trigger_observation_count": len(pre_trigger),
        "window_mfe_points": mfe,
        "window_mae_points": mae,
        "window_outcome_label": outcome,
        "first_in_window_observed_at": in_window[0].get("observed_at") if in_window else None,
        "last_in_window_observed_at": in_window[-1].get("observed_at") if in_window else None,
        "first_late_observed_at": late[0].get("observed_at") if late else None,
        "first_in_window_elapsed_seconds": in_window[0].get("elapsed_seconds") if in_window else None,
        "last_in_window_elapsed_seconds": in_window[-1].get("elapsed_seconds") if in_window else None,
        "first_late_elapsed_seconds": late[0].get("elapsed_seconds") if late else None,
        "in_window_observations": in_window,
        "late_observations": late,
        "pre_trigger_observations": pre_trigger,
    }


def _reconcile_window_integrity_conn(conn, *, now: Any = None) -> Dict[str, int]:
    """Repair derived observatory fields from persisted raw observations only."""
    conn.row_factory = sqlite3.Row
    triggers = conn.execute("SELECT * FROM observed_trade_triggers").fetchall()
    counts = {"in_window": 0, "late": 0, "window_missed": 0, "observing": 0, "not_applicable": 0, "reconciled": 0}
    checked_at = _iso(now)
    for raw in triggers:
        row = dict(raw)
        obs = [dict(x) for x in conn.execute(
            "SELECT * FROM trade_trigger_price_observations WHERE trigger_id=? ORDER BY observed_at",
            (row["trigger_id"],),
        ).fetchall()]
        metrics = _window_metrics(row, obs, now=now)
        status = metrics["window_integrity_status"]
        if status == "IN_WINDOW": counts["in_window"] += 1
        elif status == "LATE": counts["late"] += 1
        elif status == "WINDOW_MISSED": counts["window_missed"] += 1
        elif status == "NOT_APPLICABLE": counts["not_applicable"] += 1
        else: counts["observing"] += 1
        if status == "NOT_APPLICABLE":
            conn.execute("UPDATE observed_trade_triggers SET window_integrity_status=?,window_integrity_checked_at=?,updated_at=? WHERE trigger_id=?",
                         (status, checked_at, checked_at, row["trigger_id"]))
            counts["reconciled"] += 1
            continue
        effective_status = (
            "OBSERVED" if status == "IN_WINDOW" and metrics["window_matured"] else
            "OBSERVATION_WINDOW_INCOMPLETE" if status in {"LATE", "WINDOW_MISSED"} else
            "OBSERVING" if status == "OBSERVING" else
            str(row.get("status") or "OBSERVING")
        )
        terminal_at = None
        if metrics["window_matured"]:
            terminal_at = datetime.fromtimestamp(
                _epoch(row.get("triggered_at")) + metrics["observation_window_seconds"], timezone.utc
            ).isoformat()
        conn.execute(
            """UPDATE observed_trade_triggers SET
               status=?,mfe_points=?,mae_points=?,outcome_label=?,terminal_at=?,
               window_integrity_status=?,in_window_observation_count=?,late_observation_count=?,
               pre_trigger_observation_count=?,window_mfe_points=?,window_mae_points=?,window_outcome_label=?,
               first_in_window_observed_at=?,last_in_window_observed_at=?,first_late_observed_at=?,
               window_integrity_checked_at=?,updated_at=? WHERE trigger_id=?""",
            (
                effective_status, metrics["window_mfe_points"], metrics["window_mae_points"],
                metrics["window_outcome_label"], terminal_at,
                status, metrics["in_window_observation_count"], metrics["late_observation_count"],
                metrics["pre_trigger_observation_count"], metrics["window_mfe_points"],
                metrics["window_mae_points"], metrics["window_outcome_label"],
                metrics["first_in_window_observed_at"], metrics["last_in_window_observed_at"],
                metrics["first_late_observed_at"], checked_at, checked_at, row["trigger_id"],
            ),
        )
        for sample in metrics["in_window_observations"] + metrics["late_observations"] + metrics["pre_trigger_observations"]:
            conn.execute(
                """UPDATE trade_trigger_price_observations SET elapsed_seconds=?,window_class=?
                   WHERE trigger_id=? AND observed_at=?""",
                (sample.get("elapsed_seconds"), sample.get("window_class"), row["trigger_id"], sample.get("observed_at")),
            )
        counts["reconciled"] += 1
    return counts


def _attach_window_metrics(rows: list[Dict[str, Any]], resolved: str, *, now: Any = None) -> Dict[str, int]:
    """Attach horizon-safe observation metrics to trigger rows in memory."""
    by_trigger: Dict[str, list[Dict[str, Any]]] = {}
    try:
        with canonical_connect(resolved, read_only=True, timeout=4) as conn:
            conn.row_factory = sqlite3.Row
            for obs in conn.execute(
                "SELECT * FROM trade_trigger_price_observations ORDER BY trigger_id,observed_at"
            ).fetchall():
                by_trigger.setdefault(str(obs["trigger_id"]), []).append(dict(obs))
    except Exception:
        by_trigger = {}
    counts = {"IN_WINDOW": 0, "LATE": 0, "WINDOW_MISSED": 0, "OBSERVING": 0, "NOT_APPLICABLE": 0}
    for row in rows:
        metrics = _window_metrics(row, by_trigger.get(str(row.get("trigger_id") or ""), []), now=now)
        row["_window_metrics"] = metrics
        row["_window_integrity_status"] = metrics["window_integrity_status"]
        row["_in_window_observation_count"] = metrics["in_window_observation_count"]
        row["_late_observation_count"] = metrics["late_observation_count"]
        row["_pre_trigger_observation_count"] = metrics["pre_trigger_observation_count"]
        row["_window_mfe_points"] = metrics["window_mfe_points"]
        row["_window_mae_points"] = metrics["window_mae_points"]
        row["_window_outcome_label"] = metrics["window_outcome_label"]
        # All five-minute analytics below use only the reconstructed in-window values.
        row["mfe_points"] = metrics["window_mfe_points"]
        row["mae_points"] = metrics["window_mae_points"]
        row["outcome_label"] = (
            metrics["window_outcome_label"] if metrics["window_integrity_status"] == "IN_WINDOW" else None
        )
        counts[metrics["window_integrity_status"]] = counts.get(metrics["window_integrity_status"], 0) + 1
    return counts


def _explicit_target_candidates(snapshot: Mapping[str, Any]) -> list[Dict[str, Any]]:
    """Return explicit persisted target values with provenance; never infer from generic levels."""
    snap = dict(snapshot or {})
    ido = snap.get("institutional_decision_object")
    ido = dict(ido) if isinstance(ido, Mapping) else {}
    candidates: list[Dict[str, Any]] = []

    def add(value: Any, source: str) -> None:
        if isinstance(value, Mapping):
            value = value.get("price") if value.get("price") is not None else value.get("level") if value.get("level") is not None else value.get("value")
        number = _f(value)
        if number is not None and number > 0:
            candidates.append({"price": number, "source": source})

    def walk_explicit(container: Any, prefix: str) -> None:
        if not isinstance(container, Mapping):
            return
        mapping = dict(container)
        for key in ("target1", "target_1", "tp1", "first_target", "primary_target"):
            if key in mapping:
                add(mapping.get(key), f"{prefix}.{key}")
        targets = mapping.get("targets")
        if isinstance(targets, Mapping):
            for key in ("tp1", "target1", "target_1", "first_target", "primary_target"):
                if key in targets:
                    add(targets.get(key), f"{prefix}.targets.{key}")

    walk_explicit(ido.get("targets_and_decision_levels"), "institutional_decision_object.targets_and_decision_levels")
    walk_explicit(ido.get("execution_snapshot"), "institutional_decision_object.execution_snapshot")
    execution = ido.get("execution_snapshot")
    if isinstance(execution, Mapping):
        walk_explicit(execution.get("reference_plan"), "institutional_decision_object.execution_snapshot.reference_plan")
    # Preserve only explicit target-named values. Supports/resistances or generic decision
    # levels are deliberately excluded because choosing one would be an inferred threshold.
    dedup: list[Dict[str, Any]] = []
    seen = set()
    for row in candidates:
        key = (round(float(row["price"]), 8), row["source"])
        if key not in seen:
            seen.add(key); dedup.append(row)
    return dedup


def _directional_target_threshold(candidates: list[Mapping[str, Any]], *, entry: Optional[float], direction: str) -> tuple[Optional[float], str]:
    if entry is None or direction not in {"BULLISH", "BEARISH"}:
        return None, "UNAVAILABLE"
    eligible = []
    for row in candidates or []:
        price = _f(row.get("price"))
        if price is None:
            continue
        move = (price - entry) if direction == "BULLISH" else (entry - price)
        if move > 0:
            eligible.append((float(move), str(row.get("source") or "UNKNOWN")))
    if not eligible:
        return None, "UNAVAILABLE"
    # Multiple explicit target-named values may exist. The smallest favorable explicit
    # target is selected because it is the least demanding persisted regret threshold,
    # not because a generic level was inferred.
    move, source = sorted(eligible, key=lambda x: x[0])[0]
    return move, f"PERSISTED_CANONICAL_EXPLICIT_TARGET:{source}"


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
    window_integrity_status TEXT, in_window_observation_count INTEGER NOT NULL DEFAULT 0,
    late_observation_count INTEGER NOT NULL DEFAULT 0, pre_trigger_observation_count INTEGER NOT NULL DEFAULT 0,
    window_mfe_points REAL, window_mae_points REAL, window_outcome_label TEXT,
    first_in_window_observed_at TEXT, last_in_window_observed_at TEXT, first_late_observed_at TEXT,
    window_integrity_checked_at TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_trigger_observatory_time
    ON observed_trade_triggers(triggered_at, source);
CREATE INDEX IF NOT EXISTS ix_trigger_observatory_open
    ON observed_trade_triggers(status, symbol);

CREATE TABLE IF NOT EXISTS trade_trigger_price_observations (
    observation_id TEXT PRIMARY KEY, trigger_id TEXT NOT NULL,
    observed_at TEXT NOT NULL, price REAL NOT NULL, favorable_points REAL NOT NULL,
    adverse_points REAL NOT NULL, elapsed_seconds REAL, window_class TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(trigger_id, observed_at)
);
CREATE INDEX IF NOT EXISTS ix_trigger_prices ON trade_trigger_price_observations(trigger_id, observed_at);
"""


def initialize_store(path: Optional[str] = None, *, reconcile: bool = True) -> Dict[str, Any]:
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
            ("window_integrity_status", "TEXT"),
            ("in_window_observation_count", "INTEGER NOT NULL DEFAULT 0"),
            ("late_observation_count", "INTEGER NOT NULL DEFAULT 0"),
            ("pre_trigger_observation_count", "INTEGER NOT NULL DEFAULT 0"),
            ("window_mfe_points", "REAL"),
            ("window_mae_points", "REAL"),
            ("window_outcome_label", "TEXT"),
            ("first_in_window_observed_at", "TEXT"),
            ("last_in_window_observed_at", "TEXT"),
            ("first_late_observed_at", "TEXT"),
            ("window_integrity_checked_at", "TEXT"),
        ):
            if name not in existing:
                conn.execute(f"ALTER TABLE observed_trade_triggers ADD COLUMN {name} {decl}")
        obs_existing = {row[1] for row in conn.execute("PRAGMA table_info(trade_trigger_price_observations)")}
        for name, decl in (("elapsed_seconds", "REAL"), ("window_class", "TEXT")):
            if name not in obs_existing:
                conn.execute(f"ALTER TABLE trade_trigger_price_observations ADD COLUMN {name} {decl}")
        conn.execute("CREATE INDEX IF NOT EXISTS ix_trigger_decision_id ON observed_trade_triggers(decision_id)")
        reconciliation = _reconcile_window_integrity_conn(conn) if reconcile else {"reconciled": 0, "skipped": True}
        conn.commit()
    return {"ok": True, "status": "READY", "path": resolved, "version": VERSION,
            "schema_version": SCHEMA_VERSION, "canonical_outcome_linkage": True,
            "observation_window_integrity": reconciliation,
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
    initialize_store(path, reconcile=False)
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
    """Persist price evidence without allowing late samples into the five-minute window."""
    resolved = path or _path(); px = _f(price)
    if px is None or not Path(resolved).exists():
        return {"ok": False, "status": "PRICE_OR_STORE_UNAVAILABLE", "updated": 0}
    # Ensure 69.9.5 integrity columns and reconcile any legacy contamination first.
    initialize_store(resolved, reconcile=False)
    at = _iso(observed_at); at_epoch = _epoch(at); updated = terminal = 0
    in_window_samples = late_samples = pre_trigger_samples = incomplete = 0
    with canonical_connect(resolved, timeout=10) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM observed_trade_triggers WHERE symbol=? AND status='OBSERVING'",
            (_u(symbol, "SPX"),),
        ).fetchall()
        for raw in rows:
            row = dict(raw); entry = _f(row.get("entry_reference"))
            if entry is None:
                continue
            sign = 1.0 if row["direction"] == "BULLISH" else -1.0
            move = (px-entry)*sign; favorable = max(0.0, move); adverse = min(0.0, move)
            elapsed = at_epoch - _epoch(row["triggered_at"])
            window_seconds = int(row.get("observation_window_seconds") or MAX_HOLD_SECONDS)
            if elapsed < 0:
                window_class = "PRE_TRIGGER"; pre_trigger_samples += 1
            elif elapsed <= window_seconds:
                window_class = "IN_WINDOW"; in_window_samples += 1
            else:
                window_class = "LATE"; late_samples += 1
            conn.execute(
                """INSERT OR IGNORE INTO trade_trigger_price_observations(
                   observation_id,trigger_id,observed_at,price,favorable_points,adverse_points,
                   elapsed_seconds,window_class,created_at) VALUES(?,?,?,?,?,?,?,?,?)""",
                (str(uuid.uuid4()), row["trigger_id"], at, px, favorable, adverse,
                 round(float(elapsed), 3), window_class, _iso()),
            )
            obs = [dict(x) for x in conn.execute(
                "SELECT * FROM trade_trigger_price_observations WHERE trigger_id=? ORDER BY observed_at",
                (row["trigger_id"],),
            ).fetchall()]
            metrics = _window_metrics(row, obs, now=at)
            window_status = metrics["window_integrity_status"]
            matured = metrics["window_matured"]
            if matured and window_status == "IN_WINDOW":
                status = "OBSERVED"; terminal += 1
            elif matured and window_status in {"LATE", "WINDOW_MISSED"}:
                status = "OBSERVATION_WINDOW_INCOMPLETE"; terminal += 1; incomplete += 1
            else:
                status = "OBSERVING"
            terminal_at = (
                datetime.fromtimestamp(_epoch(row["triggered_at"]) + window_seconds, timezone.utc).isoformat()
                if matured else None
            )
            conn.execute(
                """UPDATE observed_trade_triggers SET
                   mfe_points=?,mae_points=?,last_price=?,observation_count=observation_count+1,
                   status=?,terminal_at=?,outcome_label=?,window_integrity_status=?,
                   in_window_observation_count=?,late_observation_count=?,pre_trigger_observation_count=?,
                   window_mfe_points=?,window_mae_points=?,window_outcome_label=?,
                   first_in_window_observed_at=?,last_in_window_observed_at=?,first_late_observed_at=?,
                   window_integrity_checked_at=?,updated_at=? WHERE trigger_id=?""",
                (
                    metrics["window_mfe_points"], metrics["window_mae_points"], px, status, terminal_at,
                    metrics["window_outcome_label"], window_status,
                    metrics["in_window_observation_count"], metrics["late_observation_count"],
                    metrics["pre_trigger_observation_count"], metrics["window_mfe_points"],
                    metrics["window_mae_points"], metrics["window_outcome_label"],
                    metrics["first_in_window_observed_at"], metrics["last_in_window_observed_at"],
                    metrics["first_late_observed_at"], at, at, row["trigger_id"],
                ),
            )
            updated += 1
        conn.commit()
    return {
        "ok": True, "status": "UPDATED", "updated": updated, "terminal": terminal,
        "in_window_samples": in_window_samples, "late_samples": late_samples,
        "pre_trigger_samples": pre_trigger_samples, "observation_window_incomplete": incomplete,
        "observation_window_seconds": MAX_HOLD_SECONDS,
        "execution_authority": False, "broker_mutation": False,
    }

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
    """Aggregate trigger effectiveness from horizon-safe observations only."""
    resolved = path or _path()
    if not Path(resolved).exists():
        return {"ok": True, "status": "WAITING_FOR_TRIGGERS", "sample_size": 0,
                "groups": [], "version": VERSION, "execution_authority": False,
                "production_effect": PRODUCTION_EFFECT}
    initialize_store(resolved)
    with canonical_connect(resolved, read_only=True, timeout=4) as conn:
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute(
            """SELECT trigger_id,triggered_at,observation_window_seconds,entry_reference,
                      source,trigger_type,setup_family,direction,disposition,outcome_label,
                      mfe_points,mae_points,canonical_grade_status,canonical_grade_label,canonical_grade_json
               FROM observed_trade_triggers WHERE symbol=? ORDER BY triggered_at""",
            (_u(symbol, "SPX"),),
        ).fetchall()]
    window_counts = _attach_window_metrics(rows, resolved)
    groups: Dict[tuple[str, str, str, str], Dict[str, Any]] = {}
    linked = 0
    for row in rows:
        key = (row["source"], row["trigger_type"], row["setup_family"], row["direction"])
        g = groups.setdefault(key, {"source": key[0], "trigger_type": key[1],
                                    "setup_family": key[2], "direction": key[3],
                                    "sample_size": 0, "five_minute_observed": 0,
                                    "five_minute_favorable": 0, "canonical_graded": 0,
                                    "canonical_wins": 0, "canonical_losses": 0,
                                    "in_window": 0, "late": 0, "window_missed": 0,
                                    "window_incomplete": 0,
                                    "mfe_sum": 0.0, "mae_abs_sum": 0.0, "excursion_n": 0})
        g["sample_size"] += 1
        window_status = row.get("_window_integrity_status")
        if window_status == "IN_WINDOW":
            g["in_window"] += 1
            if row.get("outcome_label"):
                g["five_minute_observed"] += 1
                g["five_minute_favorable"] += int(row.get("outcome_label") == "FAVORABLE")
            if row.get("mfe_points") is not None and row.get("mae_points") is not None:
                g["mfe_sum"] += float(row["mfe_points"])
                g["mae_abs_sum"] += abs(float(row["mae_points"]))
                g["excursion_n"] += 1
        elif window_status == "LATE":
            g["late"] += 1; g["window_incomplete"] += 1
        elif window_status == "WINDOW_MISSED":
            g["window_missed"] += 1; g["window_incomplete"] += 1
        if row.get("canonical_grade_status") == "GRADED":
            linked += 1; g["canonical_graded"] += 1
            g["canonical_wins"] += int(row.get("canonical_grade_label") == "WIN")
            g["canonical_losses"] += int(row.get("canonical_grade_label") == "LOSS")
    output = []
    for g in groups.values():
        n5 = g["five_minute_observed"]; ng = g["canonical_graded"]; nx = g.pop("excursion_n")
        g["five_minute_favorable_rate_pct"] = round(100.0 * g["five_minute_favorable"] / n5, 2) if n5 else None
        g["canonical_win_rate_pct"] = round(100.0 * g["canonical_wins"] / ng, 2) if ng else None
        g["avg_mfe_points"] = round(g.pop("mfe_sum") / nx, 4) if nx else None
        g["avg_mae_abs_points"] = round(g.pop("mae_abs_sum") / nx, 4) if nx else None
        g["behavioral_authority"] = False
        output.append(g)
    output.sort(key=lambda x: (-x["canonical_graded"], -x["five_minute_observed"], -x["sample_size"]))
    return {"ok": True, "status": "READY" if rows else "WAITING_FOR_TRIGGERS",
            "sample_size": len(rows), "canonical_graded_links": linked, "groups": output,
            "observation_window_integrity": {
                "window_seconds": MAX_HOLD_SECONDS,
                "in_window": window_counts.get("IN_WINDOW", 0),
                "late": window_counts.get("LATE", 0),
                "window_missed": window_counts.get("WINDOW_MISSED", 0),
                "observing": window_counts.get("OBSERVING", 0),
                "not_applicable": window_counts.get("NOT_APPLICABLE", 0),
                "late_samples_excluded_from_five_minute_metrics": True,
            },
            "limitations": ["Five-minute excursion is observational and is not a canonical trade grade.",
                            "Only observations with elapsed_seconds between 0 and the configured window are included in MFE/MAE and favorable-rate statistics.",
                            "Late-only or missed-window triggers are excluded from five-minute excursion denominators.",
                            "Canonical trigger effectiveness is reported only where a persisted graded decision is linked.",
                            "No trigger statistic automatically changes production behavior."],
            "version": VERSION, "schema_version": SCHEMA_VERSION,
            "execution_authority": False, "broker_mutation": False,
            "production_effect": PRODUCTION_EFFECT}

def predictive_validation(*, symbol: str = "SPX", path: Optional[str] = None,
                          evidence_path: Optional[str] = None) -> Dict[str, Any]:
    """Read-only decision-quality and confidence-reliability validation.

    Confidence is treated as an ordinal decision score, not an empirical
    probability. Diagnostics therefore measure outcome ordering, uncertainty,
    cohort composition, and context quality without probability-calibration
    claims or behavioral mutation.
    """
    resolved = path or _path()
    from .evidence_pipeline import DEFAULT_DB as evidence_default_db
    evidence_resolved = evidence_path or str(evidence_default_db)
    base = {
        "ok": True, "status": "READY", "version": VERSION,
        "schema_version": "apex.predictive_validation.v9",
        "behavioral_authority": False, "execution_authority": False,
        "broker_mutation": False, "production_effect": PRODUCTION_EFFECT,
        "automatic_calibration_activation": False,
    }
    if not Path(resolved).exists():
        return {**base, "status": "WAITING_FOR_TRIGGERS", "sample_size": 0,
                "confidence_bands": [], "confidence_reliability": {},
                "blocker_effectiveness": [], "directional_cohorts": [],
                "cross_cohorts": {}, "calibration_fragmentation": {},
                "calibration_context_quality": {}}

    initialize_store(resolved)
    with canonical_connect(resolved, read_only=True, timeout=4) as conn:
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute(
            """SELECT trigger_id,decision_id,source,trigger_type,setup_family,direction,disposition,
                      triggered_at,observation_window_seconds,confidence,entry_reference,stop_reference,target1_reference,blocker_codes_json,
                      outcome_label,mfe_points,mae_points,canonical_grade_status,canonical_grade_label
               FROM observed_trade_triggers WHERE symbol=? ORDER BY triggered_at""",
            (_u(symbol, "SPX"),),
        ).fetchall()]
    observation_window_counts = _attach_window_metrics(rows, resolved)

    # Canonical session, decision class, release cohort, and grade horizon are
    # joined from the evidence ledger by decision_id. Metadata parsing is isolated
    # per row so one malformed or legacy snapshot cannot erase all valid joins.
    decision_meta: Dict[str, Dict[str, Any]] = {}
    horizon_by_decision: Dict[str, str] = {}
    metadata_join_errors: list[Dict[str, str]] = []
    evidence_metadata_status = "MISSING_EVIDENCE_DB"
    if Path(evidence_resolved).exists():
        evidence_metadata_status = "READY"
        try:
            with canonical_connect(evidence_resolved, read_only=True, timeout=4) as conn:
                conn.row_factory = sqlite3.Row
                has_decisions = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='decisions'"
                ).fetchone()
                if has_decisions:
                    for meta_row in conn.execute(
                        "SELECT decision_id,session,action,snapshot_json FROM decisions"
                    ).fetchall():
                        decision_id = str(meta_row["decision_id"] or "").strip()
                        if not decision_id:
                            continue
                        try:
                            snap_raw = json.loads(meta_row["snapshot_json"] or "{}")
                            snap = dict(snap_raw) if isinstance(snap_raw, Mapping) else {}
                            action = _u(meta_row["action"] or snap.get("action"))
                            execution_actionable = bool(snap.get("execution_actionable", snap.get("actionable")))
                            observational = bool(snap.get("observational_learning_eligible"))
                            if execution_actionable:
                                decision_class = "ACTIONABLE_TRADE"
                            elif observational and action in {"NO_TRADE", "STAND_DOWN", "ABSTAIN", "WATCH", "WATCH_ONLY"}:
                                decision_class = "OBSERVATIONAL_NO_TRADE"
                            else:
                                decision_class = "NON_ACTIONABLE_OTHER"
                            deployment = snap.get("deployment")
                            deployment = dict(deployment) if isinstance(deployment, Mapping) else {}
                            release_version = str(
                                snap.get("apex_release_version")
                                or deployment.get("apex_version")
                                or "UNKNOWN"
                            ).strip() or "UNKNOWN"
                            ido = snap.get("institutional_decision_object")
                            ido = dict(ido) if isinstance(ido, Mapping) else {}
                            direct_policy = snap.get("dynamic_state_policy")
                            direct_policy = dict(direct_policy) if isinstance(direct_policy, Mapping) else {}
                            ido_conviction = ido.get("conviction")
                            ido_conviction = dict(ido_conviction) if isinstance(ido_conviction, Mapping) else {}
                            ido_consensus = ido.get("institutional_consensus") or ido.get("consensus")
                            ido_consensus = dict(ido_consensus) if isinstance(ido_consensus, Mapping) else {}
                            conviction_policy = ido_conviction.get("dynamic_state_policy")
                            conviction_policy = dict(conviction_policy) if isinstance(conviction_policy, Mapping) else {}
                            consensus_policy = ido_consensus.get("dynamic_state_policy")
                            consensus_policy = dict(consensus_policy) if isinstance(consensus_policy, Mapping) else {}
                            dynamic_policy = direct_policy or conviction_policy or consensus_policy
                            governed_move_threshold = _f(dynamic_policy.get("required_boundary_margin_points"))
                            actionability = snap.get("counterfactual_actionability")
                            actionability = dict(actionability) if isinstance(actionability, Mapping) else {}
                            if not actionability:
                                narrative = ido.get("market_narrative") or ido.get("narrative")
                                narrative = dict(narrative) if isinstance(narrative, Mapping) else {}
                                thesis = ido.get("institutional_thesis") or ido.get("thesis")
                                thesis = dict(thesis) if isinstance(thesis, Mapping) else {}
                                actionability = {
                                    "schema_version": "apex.counterfactual_actionability_capture.legacy_partial",
                                    "capture_version": release_version,
                                    "session_intelligence_present": False,
                                    "session_mode": None,
                                    "entry_window_source": "UNAVAILABLE",
                                    "entry_window_source_present": False,
                                    "entry_cutoff_et": None,
                                    "cutoff_passed": None,
                                    "entry_window_authorized": None,
                                    "market_session": _u(meta_row["session"]),
                                    "trade_guidance_enabled": (
                                        bool(narrative.get("trade_guidance_enabled"))
                                        if "trade_guidance_enabled" in narrative else None
                                    ),
                                    "thesis_state": thesis.get("state"),
                                    "direction": _u(snap.get("direction") or ido.get("direction")),
                                    "conviction_score": ido_conviction.get("score"),
                                    "blocking_conditions": list(ido_conviction.get("blocking_conditions") or []),
                                    "ido_actionable": (bool(ido.get("actionable")) if "actionable" in ido else None),
                                    "ido_status": ido.get("status"),
                                    "recommendation_action": None,
                                    "recommendation_state": None,
                                    "final_action": _u(meta_row["action"] or snap.get("action")),
                                    "entry_reference_available": snap.get("entry_reference") is not None,
                                    "targets_and_decision_levels": (
                                        dict(ido.get("targets_and_decision_levels"))
                                        if isinstance(ido.get("targets_and_decision_levels"), Mapping) else {}
                                    ),
                                    "dynamic_policy_state": dynamic_policy.get("state"),
                                    "dynamic_policy_blocking_conditions": list(dynamic_policy.get("blocking_conditions") or []),
                                    "capture_provenance": {},
                                    "source_truth": "LEGACY_PARTIAL_CANONICAL_SNAPSHOT",
                                    "historical_policy_inference": False,
                                }
                            decision_meta[decision_id] = {
                                "session": _u(meta_row["session"]),
                                "decision_class": decision_class,
                                "release_version": release_version,
                                "governed_move_threshold_points": governed_move_threshold,
                                "governed_move_threshold_source": (
                                    "DYNAMIC_STATE_POLICY_REQUIRED_BOUNDARY_MARGIN"
                                    if governed_move_threshold is not None and governed_move_threshold > 0
                                    else "UNAVAILABLE"
                                ),
                                "explicit_target_candidates": _explicit_target_candidates(snap),
                                "counterfactual_actionability": actionability,
                            }
                        except Exception as exc:
                            if len(metadata_join_errors) < 25:
                                metadata_join_errors.append({
                                    "decision_id": decision_id,
                                    "stage": "DECISION_METADATA_PARSE",
                                    "error": f"{type(exc).__name__}: {exc}",
                                })
                else:
                    evidence_metadata_status = "DECISIONS_TABLE_MISSING"

                has_grades = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='grading_results'"
                ).fetchone()
                if has_grades:
                    for grade_row in conn.execute(
                        "SELECT decision_id,horizon_seconds FROM grading_results"
                    ).fetchall():
                        decision_id = str(grade_row["decision_id"] or "").strip()
                        if not decision_id:
                            continue
                        horizon_by_decision[decision_id] = str(
                            grade_row["horizon_seconds"]
                            if grade_row["horizon_seconds"] is not None else "UNKNOWN"
                        )
                elif evidence_metadata_status == "READY":
                    evidence_metadata_status = "GRADING_RESULTS_TABLE_MISSING"
        except Exception as exc:
            evidence_metadata_status = "DEGRADED"
            metadata_join_errors.append({
                "decision_id": "",
                "stage": "EVIDENCE_METADATA_READ",
                "error": f"{type(exc).__name__}: {exc}",
            })

    def confidence_band(value: Any) -> str:
        c = _f(value)
        if c is None: return "UNKNOWN"
        if c < 40: return "<40"
        if c < 50: return "40-49.9"
        if c < 60: return "50-59.9"
        if c < 70: return "60-69.9"
        if c < 80: return "70-79.9"
        return "80+"

    for r in rows:
        r["_confidence_band"] = confidence_band(r.get("confidence"))
        decision_id = str(r.get("decision_id") or "")
        meta = decision_meta.get(decision_id, {})
        r["_session"] = meta.get("session", "UNKNOWN")
        r["_decision_class"] = meta.get("decision_class", "UNLINKED_OBSERVATION")
        r["_release_version"] = meta.get("release_version", "UNKNOWN")
        r["_grade_horizon_seconds"] = horizon_by_decision.get(decision_id, "UNKNOWN")
        r["_counterfactual_actionability"] = dict(meta.get("counterfactual_actionability") or {})
        entry_ref = _f(r.get("entry_reference"))
        target1_ref = _f(r.get("target1_reference"))
        target_move = None
        if entry_ref is not None and target1_ref is not None:
            signed_target_move = ((target1_ref - entry_ref) if _u(r.get("direction")) == "BULLISH"
                                  else (entry_ref - target1_ref) if _u(r.get("direction")) == "BEARISH"
                                  else None)
            if signed_target_move is not None and signed_target_move > 0:
                target_move = float(signed_target_move)
        if target_move is not None:
            r["_move_threshold_points"] = target_move
            r["_move_threshold_source"] = "PERSISTED_TARGET1_REFERENCE"
        else:
            explicit_move, explicit_source = _directional_target_threshold(
                meta.get("explicit_target_candidates") or [], entry=entry_ref, direction=_u(r.get("direction"))
            )
            if explicit_move is not None:
                r["_move_threshold_points"] = explicit_move
                r["_move_threshold_source"] = explicit_source
            else:
                governed_move_threshold = _f(meta.get("governed_move_threshold_points"))
                r["_move_threshold_points"] = governed_move_threshold if governed_move_threshold and governed_move_threshold > 0 else None
                r["_move_threshold_source"] = (
                    meta.get("governed_move_threshold_source")
                    if r["_move_threshold_points"] is not None else "UNAVAILABLE"
                )
        if r.get("_move_threshold_points") is not None:
            r["_move_threshold_absence_reason"] = None
        elif entry_ref is None:
            r["_move_threshold_absence_reason"] = "ENTRY_REFERENCE_MISSING"
        elif meta.get("explicit_target_candidates"):
            r["_move_threshold_absence_reason"] = "EXPLICIT_TARGET_PRESENT_BUT_NOT_DIRECTIONALLY_FAVORABLE"
        else:
            r["_move_threshold_absence_reason"] = "NO_EXPLICIT_PERSISTED_TARGET_OR_GOVERNED_MARGIN"
        try:
            blockers = json.loads(r.get("blocker_codes_json") or "[]")
        except Exception:
            blockers = []
        normalized_blockers = {str(x).upper() for x in blockers if str(x).strip()} if isinstance(blockers, list) else set()
        if not normalized_blockers and _recommendation_layer_blocks(r.get("_counterfactual_actionability") or {}):
            normalized_blockers.add("RECOMMENDATION_LAYER_NO_TRADE")
        r["_blockers"] = sorted(normalized_blockers)
        blocker_count = len(r["_blockers"])
        r["_blocker_multiplicity"] = (
            "NO_EXPLICIT_BLOCKER" if blocker_count == 0 else
            "ISOLATED_BLOCKER" if blocker_count == 1 else
            "SIMULTANEOUS_BLOCKERS"
        )
        r["_first_favorable_seconds"] = None
        r["_first_adverse_seconds"] = None
        r["_first_threshold_favorable_seconds"] = None
        threshold = _f(r.get("_move_threshold_points"))
        metrics = r.get("_window_metrics") or {}
        for obs in metrics.get("in_window_observations") or []:
            elapsed = _f(obs.get("elapsed_seconds"))
            favorable = _f(obs.get("favorable_points")) or 0.0
            adverse = _f(obs.get("adverse_points")) or 0.0
            if elapsed is None:
                continue
            if favorable > 0 and r["_first_favorable_seconds"] is None:
                r["_first_favorable_seconds"] = round(elapsed, 3)
            if adverse < 0 and r["_first_adverse_seconds"] is None:
                r["_first_adverse_seconds"] = round(elapsed, 3)
            if threshold is not None and favorable >= threshold and r["_first_threshold_favorable_seconds"] is None:
                r["_first_threshold_favorable_seconds"] = round(elapsed, 3)

    graded_rows_for_join = [r for r in rows if str(r.get("canonical_grade_status") or "").upper() == "GRADED"]
    graded_with_decision_id = [r for r in graded_rows_for_join if str(r.get("decision_id") or "").strip()]
    metadata_joined = sum(1 for r in graded_with_decision_id if str(r.get("decision_id")) in decision_meta)
    horizon_joined = sum(1 for r in graded_with_decision_id if str(r.get("decision_id")) in horizon_by_decision)
    session_known = sum(1 for r in graded_with_decision_id if r.get("_session") not in {None, "", "UNKNOWN"})
    decision_class_joined = sum(1 for r in graded_with_decision_id if r.get("_decision_class") != "UNLINKED_OBSERVATION")
    release_known = sum(1 for r in graded_with_decision_id if r.get("_release_version") not in {None, "", "UNKNOWN"})
    join_denominator = len(graded_with_decision_id)
    metadata_join_rate = round(100.0 * metadata_joined / join_denominator, 2) if join_denominator else None
    if not join_denominator:
        metadata_join_status = "NO_GRADED_LINKS"
    elif metadata_joined == join_denominator:
        metadata_join_status = "COMPLETE"
    elif metadata_joined > 0:
        metadata_join_status = "PARTIAL"
    else:
        metadata_join_status = "DEGRADED"
    metadata_join = {
        "status": metadata_join_status,
        "evidence_metadata_status": evidence_metadata_status,
        "canonical_graded_links": len(graded_rows_for_join),
        "graded_links_with_decision_id": join_denominator,
        "metadata_joined": metadata_joined,
        "metadata_missing": max(0, join_denominator - metadata_joined),
        "metadata_join_rate_pct": metadata_join_rate,
        "session_known": session_known,
        "session_unknown": max(0, join_denominator - session_known),
        "decision_class_joined": decision_class_joined,
        "grade_horizon_joined": horizon_joined,
        "release_version_known": release_known,
        "release_version_unknown": max(0, join_denominator - release_known),
        "decision_metadata_rows_loaded": len(decision_meta),
        "grade_horizon_rows_loaded": len(horizon_by_decision),
        "parse_error_count": len(metadata_join_errors),
        "parse_errors": metadata_join_errors,
        "single_row_parse_failure_cannot_clear_valid_joins": True,
    }

    def grade_win(row: Mapping[str, Any]) -> Optional[bool]:
        if row.get("canonical_grade_status") != "GRADED":
            return None
        label = _u(row.get("canonical_grade_label"))
        if label == "WIN": return True
        if label == "LOSS": return False
        return None

    def summarize(group_rows: list[Dict[str, Any]]) -> Dict[str, Any]:
        graded = [r for r in group_rows if grade_win(r) is not None]
        wins = sum(1 for r in graded if grade_win(r))
        observed = [r for r in group_rows if r.get("outcome_label")]
        favorable = sum(1 for r in observed if r.get("outcome_label") == "FAVORABLE")
        mfes = [float(r["mfe_points"]) for r in group_rows if r.get("mfe_points") is not None]
        maes = [abs(float(r["mae_points"])) for r in group_rows if r.get("mae_points") is not None]
        window_counts: Dict[str, int] = {}
        for r in group_rows:
            state = str(r.get("_window_integrity_status") or "UNKNOWN")
            window_counts[state] = window_counts.get(state, 0) + 1
        try:
            from .dynamic_state_calibration_governance import wilson_interval
            ci = wilson_interval(float(wins), float(len(graded))) if graded else {"lower_pct": None, "upper_pct": None}
        except Exception:
            ci = {"lower_pct": None, "upper_pct": None}
        return {
            "sample_size": len(group_rows), "canonical_graded": len(graded),
            "canonical_wins": wins, "canonical_losses": len(graded) - wins,
            "canonical_win_rate_pct": round(100.0 * wins / len(graded), 2) if graded else None,
            "canonical_win_rate_confidence_interval_95": ci,
            "five_minute_observed": len(observed),
            "five_minute_favorable_rate_pct": round(100.0 * favorable / len(observed), 2) if observed else None,
            "avg_mfe_points": round(sum(mfes) / len(mfes), 4) if mfes else None,
            "avg_mae_abs_points": round(sum(maes) / len(maes), 4) if maes else None,
            "observation_window_integrity": window_counts,
        }

    def market_open_elapsed_bucket(row: Mapping[str, Any]) -> str:
        if str(row.get("_session") or "").upper() != "MARKET_OPEN":
            return "NOT_MARKET_OPEN"
        try:
            raw = str(row.get("triggered_at") or "")
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            local = parsed.astimezone(ZoneInfo("America/New_York"))
            minutes = (local.hour * 60 + local.minute + local.second / 60.0) - (9 * 60 + 30)
            if minutes < 0:
                return "PRE_OPEN_CLOCK_MISMATCH"
            if minutes < 15:
                return "OPENING_0_15"
            if minutes < 30:
                return "OPENING_15_30"
            if minutes < 60:
                return "OPENING_30_60"
            if minutes < 90:
                return "MARKET_OPEN_60_90"
            if minutes < 120:
                return "MARKET_OPEN_90_120"
            if minutes < 180:
                return "MARKET_OPEN_120_180"
            return "MARKET_OPEN_180_PLUS"
        except Exception:
            return "UNKNOWN"

    for r in rows:
        r["_market_open_elapsed_bucket"] = market_open_elapsed_bucket(r)

    def abstention_classification(row: Mapping[str, Any]) -> tuple[str, str]:
        outcome = grade_win(row)
        if outcome is None:
            return "NOT_CANONICALLY_GRADED", "Canonical grade is unavailable."
        if outcome is False:
            return "ABSTENTION_SUCCESS", "Blocked directional thesis was canonically graded incorrect."
        threshold = _f(row.get("_move_threshold_points"))
        mfe = _f(row.get("mfe_points"))
        window_status = str(row.get("_window_integrity_status") or "UNKNOWN")
        if window_status != "IN_WINDOW":
            return (
                "DIRECTIONALLY_CORRECT_BUT_NOT_PROVEN_TRADEABLE",
                f"Directional thesis graded correct, but five-minute observation integrity is {window_status}; late or missed-window samples are not regret-eligible."
            )
        if threshold is None:
            return (
                "DIRECTIONALLY_CORRECT_BUT_NOT_PROVEN_TRADEABLE",
                "Directional thesis graded correct, but no persisted governed movement threshold is available."
            )
        if mfe is None:
            return (
                "DIRECTIONALLY_CORRECT_BUT_NOT_PROVEN_TRADEABLE",
                "Directional thesis graded correct, but valid in-window favorable excursion is unavailable."
            )
        if mfe >= threshold:
            return (
                "POTENTIAL_BLOCKER_REGRET",
                "Directional thesis graded correct and observed favorable excursion met a persisted movement threshold; execution quality remains unproven."
            )
        return (
            "DIRECTIONALLY_CORRECT_BUT_NOT_PROVEN_TRADEABLE",
            "Directional thesis graded correct, but observed favorable excursion did not meet the persisted movement threshold."
        )

    abstention_rows = [
        r for r in rows
        if _u(r.get("source")) == "CANONICAL_DECISION"
        and r.get("_decision_class") == "OBSERVATIONAL_NO_TRADE"
    ]
    for r in abstention_rows:
        classification, classification_reason = abstention_classification(r)
        r["_abstention_classification"] = classification
        r["_abstention_classification_reason"] = classification_reason

    def summarize_abstention(group_rows: list[Dict[str, Any]]) -> Dict[str, Any]:
        graded = [r for r in group_rows if grade_win(r) is not None]
        directional_correct = sum(1 for r in graded if grade_win(r) is True)
        directional_incorrect = sum(1 for r in graded if grade_win(r) is False)
        regret = sum(1 for r in graded if r.get("_abstention_classification") == "POTENTIAL_BLOCKER_REGRET")
        correct_not_tradeable = sum(
            1 for r in graded if r.get("_abstention_classification") == "DIRECTIONALLY_CORRECT_BUT_NOT_PROVEN_TRADEABLE"
        )
        threshold_evaluable = [
            r for r in graded
            if r.get("_window_integrity_status") == "IN_WINDOW"
            and _f(r.get("_move_threshold_points")) is not None
            and _f(r.get("mfe_points")) is not None
        ]
        threshold_met = [
            r for r in threshold_evaluable
            if (_f(r.get("mfe_points")) or 0.0) >= (_f(r.get("_move_threshold_points")) or math.inf)
        ]
        threshold_sources: Dict[str, int] = {}
        window_integrity_counts: Dict[str, int] = {}
        for r in group_rows:
            source = str(r.get("_move_threshold_source") or "UNAVAILABLE")
            threshold_sources[source] = threshold_sources.get(source, 0) + 1
            window_state = str(r.get("_window_integrity_status") or "UNKNOWN")
            window_integrity_counts[window_state] = window_integrity_counts.get(window_state, 0) + 1
        first_fav = [float(r["_first_favorable_seconds"]) for r in group_rows if r.get("_first_favorable_seconds") is not None]
        first_adv = [float(r["_first_adverse_seconds"]) for r in group_rows if r.get("_first_adverse_seconds") is not None]
        first_threshold = [
            float(r["_first_threshold_favorable_seconds"])
            for r in group_rows if r.get("_first_threshold_favorable_seconds") is not None
        ]
        mfes = [float(r["mfe_points"]) for r in group_rows if r.get("mfe_points") is not None]
        maes = [abs(float(r["mae_points"])) for r in group_rows if r.get("mae_points") is not None]
        try:
            from .dynamic_state_calibration_governance import wilson_interval
            abstention_ci = wilson_interval(float(directional_incorrect), float(len(graded))) if graded else {"lower_pct": None, "upper_pct": None}
        except Exception:
            abstention_ci = {"lower_pct": None, "upper_pct": None}
        return {
            "sample_size": len(group_rows),
            "canonical_graded": len(graded),
            "blocked_thesis_directionally_correct": directional_correct,
            "blocked_thesis_directionally_incorrect": directional_incorrect,
            "abstention_success_rate_pct": (
                round(100.0 * directional_incorrect / len(graded), 2) if graded else None
            ),
            "abstention_success_confidence_interval_95": abstention_ci,
            "potential_blocker_regret": regret,
            "potential_blocker_regret_rate_pct_of_graded": (
                round(100.0 * regret / len(graded), 2) if graded else None
            ),
            "movement_threshold_evaluable": len(threshold_evaluable),
            "movement_threshold_met": len(threshold_met),
            "movement_threshold_sources": threshold_sources,
            "observation_window_integrity": window_integrity_counts,
            "regret_requires_in_window_excursion": True,
            "potential_blocker_regret_rate_pct_when_threshold_evaluable": (
                round(100.0 * regret / len(threshold_evaluable), 2) if threshold_evaluable else None
            ),
            "directionally_correct_but_not_proven_tradeable": correct_not_tradeable,
            "avg_mfe_points": round(sum(mfes) / len(mfes), 4) if mfes else None,
            "avg_mae_abs_points": round(sum(maes) / len(maes), 4) if maes else None,
            "time_to_favorable_observed": len(first_fav),
            "avg_time_to_first_favorable_seconds": round(sum(first_fav) / len(first_fav), 2) if first_fav else None,
            "time_to_adverse_observed": len(first_adv),
            "avg_time_to_first_adverse_seconds": round(sum(first_adv) / len(first_adv), 2) if first_adv else None,
            "time_to_threshold_favorable_observed": len(first_threshold),
            "avg_time_to_threshold_favorable_seconds": (
                round(sum(first_threshold) / len(first_threshold), 2) if first_threshold else None
            ),
        }

    def abstention_groups(dimensions: tuple[str, ...], *, expand_blocker: bool = False) -> list[Dict[str, Any]]:
        groups: Dict[tuple[str, ...], list[Dict[str, Any]]] = {}
        for row in abstention_rows:
            blockers = (row.get("_blockers") or ["NO_EXPLICIT_BLOCKER"]) if expand_blocker else [None]
            for blocker in blockers:
                key_parts = []
                for dimension in dimensions:
                    if dimension == "blocker":
                        key_parts.append(str(blocker))
                    else:
                        value = row.get(dimension)
                        if value is None:
                            value = row.get("_" + dimension, "UNKNOWN")
                        key_parts.append(str(value if value not in (None, "") else "UNKNOWN"))
                groups.setdefault(tuple(key_parts), []).append(row)
        out = []
        for key, vals in groups.items():
            item = {dimension: key[i] for i, dimension in enumerate(dimensions)}
            item.update(summarize_abstention(vals))
            out.append(item)
        out.sort(key=lambda x: (-x["canonical_graded"], -x["sample_size"], tuple(str(x.get(d)) for d in dimensions)))
        return out

    abstention_classification_counts: Dict[str, int] = {}
    for row in abstention_rows:
        key = str(row.get("_abstention_classification") or "NOT_CANONICALLY_GRADED")
        abstention_classification_counts[key] = abstention_classification_counts.get(key, 0) + 1

    abstention_regret = {
        "schema_version": "apex.abstention_regret.v2",
        "status": "READY" if abstention_rows else "WAITING_FOR_OBSERVATIONAL_NO_TRADE",
        "production_effect": PRODUCTION_EFFECT,
        "behavioral_authority": False,
        "execution_authority": False,
        "broker_mutation": False,
        "population_contract": "CANONICAL_OBSERVATIONAL_NO_TRADE_ONLY",
        "sample_size": len(abstention_rows),
        "overall": summarize_abstention(abstention_rows),
        "classification_counts": abstention_classification_counts,
        "by_blocker_session": abstention_groups(("blocker", "session"), expand_blocker=True),
        "by_blocker_direction_session": abstention_groups(("blocker", "direction", "session"), expand_blocker=True),
        "by_blocker_confidence_session": abstention_groups(("blocker", "confidence_band", "session"), expand_blocker=True),
        "by_blocker_multiplicity_session": abstention_groups(("blocker_multiplicity", "session")),
        "market_open_elapsed": abstention_groups(("market_open_elapsed_bucket", "blocker"), expand_blocker=True),
        "movement_threshold_contract": {
            "priority": [
                "PERSISTED_TARGET1_REFERENCE",
                "PERSISTED_CANONICAL_EXPLICIT_TARGET:*",
                "DYNAMIC_STATE_POLICY_REQUIRED_BOUNDARY_MARGIN",
                "UNAVAILABLE",
            ],
            "missing_threshold_behavior": "NOT_EVALUABLE_NO_INFERENCE",
            "threshold_is_execution_proof": False,
            "valid_in_window_excursion_required": True,
            "generic_support_resistance_levels_inferred": False,
            "interpretation": (
                "Meeting a persisted movement threshold is necessary-not-sufficient evidence for potential blocker regret; "
                "it does not prove option premium, fill quality, stop viability, or executable tradeability."
            ),
        },
        "classification_contract": {
            "ABSTENTION_SUCCESS": "Blocked directional thesis was canonically graded incorrect.",
            "DIRECTIONALLY_CORRECT_BUT_NOT_PROVEN_TRADEABLE": (
                "Blocked thesis was directionally correct but lacked sufficient persisted movement evidence to support a regret hypothesis."
            ),
            "POTENTIAL_BLOCKER_REGRET": (
                "Blocked thesis was directionally correct and met a persisted movement threshold; execution viability remains unproven."
            ),
        },
        "observation_timing_contract": "PERSISTED_IN_WINDOW_TRIGGER_PRICE_OBSERVATIONS_ONLY_NO_INTERPOLATION",
        "observation_window_integrity": {
            "window_seconds": MAX_HOLD_SECONDS,
            "in_window": observation_window_counts.get("IN_WINDOW", 0),
            "late": observation_window_counts.get("LATE", 0),
            "window_missed": observation_window_counts.get("WINDOW_MISSED", 0),
            "observing": observation_window_counts.get("OBSERVING", 0),
            "not_applicable": observation_window_counts.get("NOT_APPLICABLE", 0),
            "late_samples_regret_eligible": False,
            "window_missed_regret_eligible": False,
        },
    }

    # APEX 69.9.6 — actionability qualification.  Historical policy gates are
    # considered authoritative only when they were persisted in the canonical
    # decision snapshot. The current configured cutoff is exposed as a comparison
    # reference only and never backfilled into historical eligibility.
    current_cutoff_et = str(os.getenv("TRADE_NO_NEW_AFTER_ET", "11:30") or "11:30")

    def current_policy_cutoff_passed(row: Mapping[str, Any]) -> Optional[bool]:
        try:
            hh, mm = [int(x) for x in current_cutoff_et.split(":", 1)]
            dt = datetime.fromisoformat(str(row.get("triggered_at") or "").replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            local = dt.astimezone(ZoneInfo("America/New_York"))
            return (local.hour, local.minute) >= (hh, mm)
        except Exception:
            return None

    def _condition_code(value: Any) -> str:
        text = str(value or "").upper().replace(" ", "_").replace("-", "_")
        return "_".join(part for part in text.split("_") if part)

    def _target_matches_condition(target_blocker: str, condition: Any) -> bool:
        target = _condition_code(target_blocker)
        condition_code = _condition_code(condition)
        if not target or not condition_code:
            return False
        aliases = {
            "THESIS_INVALIDATED": ("THESIS_INVALIDATED", "INVALIDATED"),
            "THESIS_CONFLICTED": ("THESIS_CONFLICTED", "CONFLICTED"),
            "CONVICTION_BELOW_ACTIONABLE_THRESHOLD": (
                "CONVICTION_BELOW_ACTIONABLE_THRESHOLD", "CONVICTION_BELOW_THRESHOLD", "LOW_CONVICTION"
            ),
            "MARKET_CLOSED": ("MARKET_CLOSED", "SESSION_CLOSED", "CLOSED"),
        }
        return any(alias in condition_code or condition_code in alias for alias in aliases.get(target, (target,)))

    def qualify_counterfactual(row: Mapping[str, Any], target_blocker: str) -> Dict[str, Any]:
        win = grade_win(row)
        actionability = dict(row.get("_counterfactual_actionability") or {})
        session = str(row.get("_session") or "UNKNOWN").upper()
        session_mode = str(actionability.get("session_mode") or "UNKNOWN").upper()
        cutoff_known = actionability.get("cutoff_passed") is not None
        cutoff_passed = bool(actionability.get("cutoff_passed")) if cutoff_known else None
        cutoff_value = actionability.get("entry_cutoff_et")
        trade_guidance = actionability.get("trade_guidance_enabled")
        thesis_state = str(actionability.get("thesis_state") or "UNKNOWN").upper()
        direction = str(actionability.get("direction") or row.get("direction") or "UNKNOWN").upper()
        conviction_score = _f(actionability.get("conviction_score"))
        captured_conditions = list(actionability.get("blocking_conditions") or []) + list(
            actionability.get("dynamic_policy_blocking_conditions") or []
        )
        trigger_blockers = list(row.get("_blockers") or [])
        independent_trigger_blockers = [x for x in trigger_blockers if not _target_matches_condition(target_blocker, x)]
        independent_captured_conditions = [x for x in captured_conditions if not _target_matches_condition(target_blocker, x)]
        target_is_thesis_state = (
            (target_blocker == "THESIS_INVALIDATED" and thesis_state == "INVALIDATED")
            or (target_blocker == "THESIS_CONFLICTED" and thesis_state == "CONFLICTED")
        )
        target_is_conviction_gate = target_blocker == "CONVICTION_BELOW_ACTIONABLE_THRESHOLD"

        entry_window_source_present = bool(
            actionability.get("entry_window_source_present")
            or (
                actionability.get("session_intelligence_present")
                and actionability.get("entry_cutoff_et") not in (None, "")
                and actionability.get("cutoff_passed") is not None
            )
        )
        entry_window_source = str(actionability.get("entry_window_source") or (
            "SESSION_INTELLIGENCE" if actionability.get("session_intelligence_present") else "UNAVAILABLE"
        )).upper()
        market_session_authorized = session in {"MARKET_OPEN", "RTH", "REGULAR"}
        entry_geometry_available = _f(row.get("entry_reference")) is not None
        stop_geometry_available = _f(row.get("stop_reference")) is not None
        threshold_available = _f(row.get("_move_threshold_points")) is not None
        in_window = row.get("_window_integrity_status") == "IN_WINDOW"
        threshold_hit = bool(
            in_window and threshold_available and _f(row.get("mfe_points")) is not None
            and (_f(row.get("mfe_points")) or 0.0) >= (_f(row.get("_move_threshold_points")) or math.inf)
        )
        recommendation_action = str(actionability.get("recommendation_action") or "UNKNOWN").upper()
        recommendation_state = str(actionability.get("recommendation_state") or "UNKNOWN").upper()
        target_is_recommendation_gate = target_blocker == "RECOMMENDATION_LAYER_NO_TRADE"
        recommendation_layer_no_trade = bool(
            recommendation_action in _RECOMMENDATION_NO_TRADE_STATES
            or recommendation_state in _RECOMMENDATION_NO_TRADE_STATES
        )

        reason = "UNCLASSIFIED"
        eligible = False
        if win is False:
            state = "ABSTENTION_SUCCESS"
            reason = "CANONICAL_DIRECTIONAL_GRADE_INCORRECT"
        elif win is None:
            state = "NOT_CANONICALLY_GRADED"
            reason = "CANONICAL_GRADE_UNAVAILABLE"
        elif not market_session_authorized:
            state = "DIRECTIONALLY_CORRECT_NOT_TRADE_ELIGIBLE"
            reason = "SESSION_NOT_ENTRY_AUTHORIZED"
        elif not entry_window_source_present or not cutoff_known or not cutoff_value:
            state = "DIRECTIONALLY_CORRECT_NOT_TRADE_ELIGIBLE"
            reason = "ACTIONABILITY_WINDOW_EVIDENCE_UNAVAILABLE"
        elif cutoff_passed:
            state = "DIRECTIONALLY_CORRECT_NOT_TRADE_ELIGIBLE"
            reason = "OUTSIDE_ACTIONABILITY_WINDOW"
        elif session_mode == "STOP_TRADING":
            state = "DIRECTIONALLY_CORRECT_NOT_TRADE_ELIGIBLE"
            reason = "SESSION_NOT_ENTRY_AUTHORIZED"
        elif trade_guidance is False:
            state = "DIRECTIONALLY_CORRECT_NOT_TRADE_ELIGIBLE"
            reason = "TRADE_GUIDANCE_DISABLED"
        elif direction not in {"BULLISH", "BEARISH"}:
            state = "DIRECTIONALLY_CORRECT_NOT_TRADE_ELIGIBLE"
            reason = "DIRECTION_NOT_ACTIONABLE"
        elif thesis_state != "ACTIVE" and not target_is_thesis_state:
            state = "DIRECTIONALLY_CORRECT_NOT_TRADE_ELIGIBLE"
            reason = "INDEPENDENT_THESIS_STATE_DISQUALIFIER"
        elif conviction_score is not None and conviction_score < 55 and not target_is_conviction_gate:
            state = "DIRECTIONALLY_CORRECT_NOT_TRADE_ELIGIBLE"
            reason = "INDEPENDENT_CONVICTION_DISQUALIFIER"
        elif independent_trigger_blockers or independent_captured_conditions:
            state = "DIRECTIONALLY_CORRECT_NOT_TRADE_ELIGIBLE"
            reason = "INDEPENDENT_DISQUALIFIER_PRESENT"
        elif recommendation_layer_no_trade and not target_is_recommendation_gate:
            state = "DIRECTIONALLY_CORRECT_NOT_TRADE_ELIGIBLE"
            reason = "RECOMMENDATION_LAYER_NO_TRADE"
        elif target_blocker == "NO_EXPLICIT_BLOCKER" and actionability.get("ido_actionable") is False:
            state = "DIRECTIONALLY_CORRECT_NOT_TRADE_ELIGIBLE"
            reason = "IDO_ACTIONABLE_FALSE_WITHOUT_EXPLICIT_BLOCKER"
        elif not entry_geometry_available:
            state = "DIRECTIONALLY_CORRECT_NOT_TRADE_ELIGIBLE"
            reason = "MISSING_TRADE_GEOMETRY"
        elif not threshold_available:
            state = "DIRECTIONALLY_CORRECT_NOT_TRADE_ELIGIBLE"
            reason = "MISSING_REGRET_THRESHOLD"
        elif not in_window:
            state = "DIRECTIONALLY_CORRECT_NOT_TRADE_ELIGIBLE"
            reason = "OBSERVATION_WINDOW_INCOMPLETE"
        else:
            eligible = True
            if threshold_hit:
                state = "POTENTIAL_BLOCKER_REGRET"
                reason = "COUNTERFACTUAL_TRADE_ELIGIBLE_AND_THRESHOLD_MET"
            else:
                state = "COUNTERFACTUAL_TRADE_ELIGIBLE"
                reason = "COUNTERFACTUAL_TRADE_ELIGIBLE_THRESHOLD_NOT_MET"

        unexplained_no_trade = bool(
            target_blocker == "NO_EXPLICIT_BLOCKER"
            and win is True
            and eligible
            and not trigger_blockers
            and recommendation_action in {"UNKNOWN", "", "NONE"}
            and recommendation_state in {"UNKNOWN", "", "NONE"}
            and str(actionability.get("final_action") or "NO_TRADE").upper() in {"NO_TRADE", "STAND_DOWN", "ABSTAIN", "WATCH", "WATCH_ONLY"}
        )
        return {
            "trigger_id": row.get("trigger_id"),
            "decision_id": row.get("decision_id"),
            "triggered_at": row.get("triggered_at"),
            "session": session,
            "direction": direction,
            "confidence": _f(row.get("confidence")),
            "confidence_band": row.get("_confidence_band"),
            "market_open_elapsed_bucket": row.get("_market_open_elapsed_bucket"),
            "state": state,
            "reason": reason,
            "counterfactual_trade_eligible": eligible,
            "target_blocker": target_blocker,
            "canonical_directionally_correct": win,
            "market_session_authorized": market_session_authorized,
            "session_mode": session_mode,
            "entry_cutoff_et": cutoff_value,
            "cutoff_passed": cutoff_passed,
            "actionability_window_source_present": entry_window_source_present and cutoff_known and bool(cutoff_value),
            "entry_window_source": entry_window_source,
            "capture_version": actionability.get("capture_version"),
            "capture_provenance": dict(actionability.get("capture_provenance") or {}),
            "trade_guidance_enabled": trade_guidance,
            "thesis_state": thesis_state,
            "conviction_score": conviction_score,
            "independent_trigger_blockers": independent_trigger_blockers,
            "independent_captured_conditions": independent_captured_conditions,
            "entry_geometry_available": entry_geometry_available,
            "stop_geometry_available": stop_geometry_available,
            "movement_threshold_available": threshold_available,
            "movement_threshold_source": row.get("_move_threshold_source") or "UNAVAILABLE",
            "movement_threshold_absence_reason": row.get("_move_threshold_absence_reason"),
            "valid_in_window_excursion": in_window,
            "movement_threshold_met": threshold_hit,
            "current_policy_cutoff_et_reference": current_cutoff_et,
            "current_policy_cutoff_passed_reference": current_policy_cutoff_passed(row),
            "current_policy_reference_used_for_historical_qualification": False,
            "recommendation_action": recommendation_action,
            "recommendation_state": recommendation_state,
            "recommendation_layer_no_trade": recommendation_layer_no_trade,
            "unexplained_no_trade_with_passing_captured_gates": unexplained_no_trade,
        }

    def counterfactual_groups(dimensions: tuple[str, ...], *, expand_blocker: bool = False) -> list[Dict[str, Any]]:
        groups: Dict[tuple[str, ...], list[tuple[Dict[str, Any], Dict[str, Any]]]] = {}
        for row in abstention_rows:
            blockers = (row.get("_blockers") or ["NO_EXPLICIT_BLOCKER"]) if expand_blocker else ["NO_EXPLICIT_BLOCKER"]
            for blocker in blockers:
                q = qualify_counterfactual(row, str(blocker))
                key_parts = []
                for dimension in dimensions:
                    if dimension == "blocker":
                        key_parts.append(str(blocker))
                    else:
                        value = row.get(dimension)
                        if value is None:
                            value = row.get("_" + dimension, "UNKNOWN")
                        key_parts.append(str(value if value not in (None, "") else "UNKNOWN"))
                groups.setdefault(tuple(key_parts), []).append((row, q))
        out = []
        for key, pairs in groups.items():
            qs = [q for _, q in pairs]
            state_counts: Dict[str, int] = {}
            reason_counts: Dict[str, int] = {}
            for q in qs:
                state_counts[q["state"]] = state_counts.get(q["state"], 0) + 1
                reason_counts[q["reason"]] = reason_counts.get(q["reason"], 0) + 1
            item = {dimension: key[i] for i, dimension in enumerate(dimensions)}
            item.update({
                "sample_size": len(pairs),
                "state_counts": state_counts,
                "reason_counts": reason_counts,
                "counterfactual_trade_eligible": sum(1 for q in qs if q["counterfactual_trade_eligible"]),
                "potential_blocker_regret": state_counts.get("POTENTIAL_BLOCKER_REGRET", 0),
                "directionally_correct_not_trade_eligible": state_counts.get("DIRECTIONALLY_CORRECT_NOT_TRADE_ELIGIBLE", 0),
                "actionability_window_evidence_available": sum(1 for q in qs if q["actionability_window_source_present"]),
                "current_policy_reference_past_cutoff": sum(1 for q in qs if q["current_policy_cutoff_passed_reference"] is True),
                "unexplained_no_trade_with_passing_captured_gates": sum(
                    1 for q in qs if q["unexplained_no_trade_with_passing_captured_gates"]
                ),
            })
            out.append(item)
        out.sort(key=lambda x: (-x["potential_blocker_regret"], -x["counterfactual_trade_eligible"], -x["sample_size"]))
        return out

    all_counterfactual_pairs: list[tuple[Dict[str, Any], Dict[str, Any]]] = []
    for row in abstention_rows:
        for blocker in (row.get("_blockers") or ["NO_EXPLICIT_BLOCKER"]):
            all_counterfactual_pairs.append((row, qualify_counterfactual(row, str(blocker))))
    cf_state_counts: Dict[str, int] = {}
    cf_reason_counts: Dict[str, int] = {}
    target_absence_counts: Dict[str, int] = {}
    for row, q in all_counterfactual_pairs:
        cf_state_counts[q["state"]] = cf_state_counts.get(q["state"], 0) + 1
        cf_reason_counts[q["reason"]] = cf_reason_counts.get(q["reason"], 0) + 1
        if q.get("movement_threshold_absence_reason"):
            key = str(q["movement_threshold_absence_reason"])
            target_absence_counts[key] = target_absence_counts.get(key, 0) + 1

    no_explicit_rows = [row for row in abstention_rows if not row.get("_blockers")]
    no_explicit_details = [qualify_counterfactual(row, "NO_EXPLICIT_BLOCKER") for row in no_explicit_rows]
    no_explicit_reason_counts: Dict[str, int] = {}
    no_explicit_recommendation_counts: Dict[str, int] = {}
    for q in no_explicit_details:
        no_explicit_reason_counts[q["reason"]] = no_explicit_reason_counts.get(q["reason"], 0) + 1
        key = q.get("recommendation_action") or q.get("recommendation_state") or "UNKNOWN"
        no_explicit_recommendation_counts[str(key)] = no_explicit_recommendation_counts.get(str(key), 0) + 1

    def actionability_capture_readiness(group_rows: list[Dict[str, Any]]) -> Dict[str, Any]:
        fields = (
            "entry_cutoff_et", "cutoff_passed", "session_mode",
            "trade_guidance_enabled", "thesis_state", "conviction_score",
            "recommendation_action", "recommendation_state",
        )
        capture_versions: Dict[str, int] = {}
        entry_sources: Dict[str, int] = {}
        field_status_counts: Dict[str, Dict[str, int]] = {field: {} for field in fields}
        ready = 0
        current_release_rows = 0
        current_release_ready = 0
        for row in group_rows:
            actionability = dict(row.get("_counterfactual_actionability") or {})
            capture_version = str(actionability.get("capture_version") or "LEGACY_OR_UNKNOWN")
            capture_versions[capture_version] = capture_versions.get(capture_version, 0) + 1
            source = str(actionability.get("entry_window_source") or (
                "SESSION_INTELLIGENCE" if actionability.get("session_intelligence_present") else "UNAVAILABLE"
            )).upper()
            entry_sources[source] = entry_sources.get(source, 0) + 1
            source_present = bool(
                actionability.get("entry_window_source_present")
                or (
                    actionability.get("session_intelligence_present")
                    and actionability.get("entry_cutoff_et") not in (None, "")
                    and actionability.get("cutoff_passed") is not None
                )
            )
            window_ready = bool(
                source_present
                and actionability.get("entry_cutoff_et") not in (None, "")
                and actionability.get("cutoff_passed") is not None
            )
            if window_ready:
                ready += 1
            if str(row.get("_release_version") or "UNKNOWN") == VERSION:
                current_release_rows += 1
                if window_ready:
                    current_release_ready += 1
            provenance = dict(actionability.get("capture_provenance") or {})
            for field in fields:
                item = provenance.get(field)
                if isinstance(item, Mapping):
                    status = str(item.get("status") or "UNSPECIFIED").upper()
                elif field in actionability and actionability.get(field) not in (None, ""):
                    status = "LEGACY_VALUE_PRESENT"
                else:
                    status = "SOURCE_PATH_NOT_FOUND"
                field_status_counts[field][status] = field_status_counts[field].get(status, 0) + 1
        total = len(group_rows)
        try:
            from .historical_evidence_lifecycle import actionability_capture_audit
            live_audit = actionability_capture_audit(path=evidence_resolved, limit=100)
        except Exception as exc:
            live_audit = {
                "ok": False,
                "status": "AUDIT_ERROR",
                "current_release_rows": 0,
                "current_release_entry_window_ready": 0,
                "error": f"{type(exc).__name__}: {exc}",
            }
        pregrade_current_rows = int(live_audit.get("current_release_rows") or 0)
        pregrade_current_ready = int(live_audit.get("current_release_entry_window_ready") or 0)
        if current_release_rows and current_release_ready == current_release_rows:
            readiness_status = "CURRENT_RELEASE_READY"
        elif current_release_rows and current_release_ready > 0:
            readiness_status = "CURRENT_RELEASE_PARTIAL"
        elif current_release_rows:
            readiness_status = "CURRENT_RELEASE_NOT_READY"
        elif pregrade_current_rows and pregrade_current_ready > 0:
            readiness_status = "CURRENT_RELEASE_CAPTURED_AWAITING_QUALIFICATION_LINKAGE"
        elif pregrade_current_rows:
            readiness_status = "CURRENT_RELEASE_CAPTURE_PRESENT_ENTRY_WINDOW_NOT_READY"
        else:
            readiness_status = "WAITING_FOR_CURRENT_RELEASE_LIVE_CAPTURE"
        return {
            "schema_version": "apex.actionability_capture_readiness.v2",
            "status": readiness_status,
            "sample_size": total,
            "entry_window_evidence_available": ready,
            "entry_window_evidence_pct": round(100.0 * ready / total, 2) if total else None,
            "capture_version_counts": capture_versions,
            "entry_window_source_counts": entry_sources,
            "field_status_counts": field_status_counts,
            "current_release": VERSION,
            "current_release_rows": current_release_rows,
            "current_release_entry_window_evidence_available": current_release_ready,
            "current_release_entry_window_evidence_pct": (
                round(100.0 * current_release_ready / current_release_rows, 2)
                if current_release_rows else None
            ),
            "current_release_qualification_ready": bool(current_release_ready),
            "current_release_pregrade_rows": pregrade_current_rows,
            "current_release_pregrade_entry_window_ready": pregrade_current_ready,
            "current_release_pregrade_entry_window_ready_pct": (
                round(100.0 * pregrade_current_ready / pregrade_current_rows, 2)
                if pregrade_current_rows else None
            ),
            "live_capture_audit": live_audit,
            "historical_missing_policy_never_inferred": True,
            "production_effect": PRODUCTION_EFFECT,
            "execution_authority": False,
        }

    capture_readiness = actionability_capture_readiness(abstention_rows)

    counterfactual_regret = {
        "schema_version": "apex.counterfactual_regret_qualification.v3",
        "status": "READY" if abstention_rows else "WAITING_FOR_OBSERVATIONAL_NO_TRADE",
        "population_contract": "CANONICAL_OBSERVATIONAL_NO_TRADE_BLOCKER_TARGETED_QUALIFICATION",
        "sample_size": len(abstention_rows),
        "blocker_evaluations": len(all_counterfactual_pairs),
        "state_counts": cf_state_counts,
        "reason_counts": cf_reason_counts,
        "target_absence_provenance": target_absence_counts,
        "actionability_capture_readiness": capture_readiness,
        "by_blocker_session": counterfactual_groups(("blocker", "session"), expand_blocker=True),
        "by_blocker_direction_session": counterfactual_groups(("blocker", "direction", "session"), expand_blocker=True),
        "by_market_open_elapsed_blocker": counterfactual_groups(("market_open_elapsed_bucket", "blocker"), expand_blocker=True),
        "no_explicit_blocker_diagnostics": {
            "sample_size": len(no_explicit_rows),
            "reason_counts": no_explicit_reason_counts,
            "recommendation_action_or_state_counts": no_explicit_recommendation_counts,
            "counterfactual_trade_eligible": sum(1 for q in no_explicit_details if q["counterfactual_trade_eligible"]),
            "potential_blocker_regret": sum(1 for q in no_explicit_details if q["state"] == "POTENTIAL_BLOCKER_REGRET"),
            "recommendation_layer_no_trade": sum(1 for q in no_explicit_details if q["recommendation_layer_no_trade"]),
            "unexplained_no_trade_with_passing_captured_gates": sum(
                1 for q in no_explicit_details if q["unexplained_no_trade_with_passing_captured_gates"]
            ),
            "details": no_explicit_details[:50],
        },
        "qualification_contract": {
            "requires_persisted_actionability_window": True,
            "accepted_decision_time_entry_window_sources": ["SESSION_INTELLIGENCE", "TRADE_RISK_GUARD_POLICY"],
            "requires_entry_session_authorized": True,
            "requires_no_independent_disqualifier": True,
            "requires_entry_geometry": True,
            "requires_persisted_regret_threshold": True,
            "requires_valid_in_window_excursion": True,
            "requires_canonical_directional_grade_correct": True,
            "current_policy_reference_can_backfill_historical_actionability": False,
            "pregrade_live_capture_audit_separate_from_graded_qualification": True,
            "zero_graded_current_release_rows_does_not_imply_capture_failure": True,
            "stop_geometry_required_for_counterfactual_eligibility": False,
            "execution_viability_proven": False,
        },
        "current_policy_clock_reference": {
            "cutoff_et": current_cutoff_et,
            "source": "CURRENT_RUNTIME_TRADE_NO_NEW_AFTER_ET_OR_RISK_GUARD_DEFAULT",
            "historical_qualification_uses_reference": False,
            "interpretation": "Reference-only comparison. Historical actionability requires the decision-time cutoff persisted in the canonical snapshot.",
        },
        "legacy_abstention_regret_semantics": {
            "abstention_regret_potential_blocker_regret_is_movement_qualified_only": True,
            "actionability_qualified_regret_authority": "counterfactual_regret.POTENTIAL_BLOCKER_REGRET",
        },
        "production_effect": PRODUCTION_EFFECT,
        "behavioral_authority": False,
        "execution_authority": False,
        "broker_mutation": False,
    }

    band_order = ["<40", "40-49.9", "50-59.9", "60-69.9", "70-79.9", "80+", "UNKNOWN"]
    reliability_min_sample = 20

    def band_summary(group_rows: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
        groups: Dict[str, list[Dict[str, Any]]] = {}
        for row in group_rows:
            groups.setdefault(row["_confidence_band"], []).append(row)
        return [{"band": k, **summarize(groups[k])} for k in band_order if k in groups]

    def reliability_from_bands(bands: list[Dict[str, Any]]) -> Dict[str, Any]:
        comparable = [
            x for x in bands
            if x["band"] != "UNKNOWN"
            and x["canonical_graded"] >= reliability_min_sample
            and x["canonical_win_rate_pct"] is not None
        ]
        violations = []
        for left, right in zip(comparable, comparable[1:]):
            if right["canonical_win_rate_pct"] < left["canonical_win_rate_pct"]:
                violations.append({
                    "lower_confidence_band": left["band"],
                    "higher_confidence_band": right["band"],
                    "lower_band_win_rate_pct": left["canonical_win_rate_pct"],
                    "higher_band_win_rate_pct": right["canonical_win_rate_pct"],
                    "delta_pp": round(right["canonical_win_rate_pct"] - left["canonical_win_rate_pct"], 2),
                })
        if len(comparable) < 2:
            state = "INSUFFICIENT_COMPARABLE_BANDS"
        elif violations:
            state = "NON_MONOTONIC_OBSERVED_OUTCOMES"
        else:
            state = "MONOTONIC_IN_COMPARABLE_BANDS"
        return {
            "minimum_graded_per_comparable_band": reliability_min_sample,
            "comparable_band_count": len(comparable),
            "state": state,
            "monotonicity_violations": violations,
        }

    confidence_bands = band_summary(rows)
    confidence_reliability = {
        "score_contract": "ORDINAL_DECISION_SCORE_NOT_EMPIRICAL_PROBABILITY",
        "probability_calibration_metrics_supported": False,
        "probability_metric_reason": "Raw conviction is not contractually defined as a calibrated event probability.",
        **reliability_from_bands(confidence_bands),
        "interpretation": "Higher ordinal confidence should not be assumed better until cohort composition and repeated out-of-sample evidence support monotonic ordering.",
    }

    session_reliability = []
    for session in sorted({str(r["_session"]) for r in rows}):
        session_rows = [r for r in rows if str(r["_session"]) == session]
        bands = band_summary(session_rows)
        session_reliability.append({
            "session": session,
            "sample_size": len(session_rows),
            "bands": bands,
            **reliability_from_bands(bands),
        })
    confidence_reliability["by_session"] = session_reliability
    confidence_reliability["session_conditioning_enabled"] = True

    blocker_groups: Dict[str, list[Dict[str, Any]]] = {}
    for r in rows:
        for blocker in r["_blockers"]:
            blocker_groups.setdefault(blocker, []).append(r)
    blocker_effectiveness = [{"blocker": k, **summarize(v)} for k, v in blocker_groups.items()]
    blocker_effectiveness.sort(key=lambda x: (-x["canonical_graded"], -x["sample_size"], x["blocker"]))

    cohort_groups: Dict[tuple[str, str, str], list[Dict[str, Any]]] = {}
    for r in rows:
        key = (_u(r.get("source")), _u(r.get("trigger_type")), _u(r.get("direction")))
        cohort_groups.setdefault(key, []).append(r)
    directional_cohorts = [
        {"source": k[0], "trigger_type": k[1], "direction": k[2], **summarize(v)}
        for k, v in cohort_groups.items()
    ]
    directional_cohorts.sort(key=lambda x: (-x["canonical_graded"], -x["five_minute_observed"], -x["sample_size"]))

    def dim_value(row: Mapping[str, Any], dimension: str) -> str:
        if dimension == "blocker":
            raise ValueError("blocker requires expansion")
        value = row.get(dimension)
        if value is None:
            value = row.get("_" + dimension, "UNKNOWN")
        return str(value if value not in (None, "") else "UNKNOWN")

    def multi_groups(dimensions: tuple[str, ...], *, expand_blocker: bool = False) -> list[Dict[str, Any]]:
        groups: Dict[tuple[str, ...], list[Dict[str, Any]]] = {}
        for row in rows:
            blocker_values = (row["_blockers"] or ["NONE"]) if expand_blocker else [None]
            for blocker in blocker_values:
                key = tuple(blocker if d == "blocker" else dim_value(row, d) for d in dimensions)
                groups.setdefault(key, []).append(row)
        out = []
        for key, vals in groups.items():
            record = {dimension: key[i] for i, dimension in enumerate(dimensions)}
            record.update(summarize(vals))
            out.append(record)
        out.sort(key=lambda x: (-x["canonical_graded"], -x["sample_size"], tuple(str(x.get(d)) for d in dimensions)))
        return out

    cross_cohorts = {
        "direction_x_confidence": multi_groups(("direction", "confidence_band")),
        "confidence_x_session": multi_groups(("confidence_band", "session")),
        "direction_x_confidence_x_session": multi_groups(("direction", "confidence_band", "session")),
        "direction_x_blocker": multi_groups(("direction", "blocker"), expand_blocker=True),
        "confidence_x_blocker": multi_groups(("confidence_band", "blocker"), expand_blocker=True),
        "blocker_x_session": multi_groups(("blocker", "session"), expand_blocker=True),
        "session_x_direction": multi_groups(("session", "direction")),
        "grade_horizon_x_direction": multi_groups(("grade_horizon_seconds", "direction")),
        "decision_class_x_direction": multi_groups(("decision_class", "direction")),
        "decision_class_x_confidence": multi_groups(("decision_class", "confidence_band")),
        "release_x_direction": multi_groups(("release_version", "direction")),
    }

    decision_class_effectiveness = [
        {"decision_class": k, **summarize([r for r in rows if r["_decision_class"] == k])}
        for k in sorted({str(r["_decision_class"]) for r in rows})
    ]
    release_cohorts = [
        {"release_version": k, **summarize([r for r in rows if r["_release_version"] == k])}
        for k in sorted({str(r["_release_version"]) for r in rows})
    ]

    fragmentation: Dict[str, Any] = {"status": "UNAVAILABLE", "minimum_sample_per_bucket": 20,
                                     "graded_contexts": 0, "dimensions": {}}
    context_quality: Dict[str, Any] = {"status": "UNAVAILABLE", "fields": {}}
    if Path(evidence_resolved).exists():
        try:
            from .dynamic_state_outcome_calibration import calibration_summary, context_diversity_audit
            cs = calibration_summary(evidence_resolved)
            context_quality = context_diversity_audit(evidence_resolved)
            dimensions = {}
            ready_total = 0
            bucket_total = 0
            for dimension, buckets in (cs.get("dimensions") or {}).items():
                bucket_total += len(buckets)
                ready = [b for b in buckets if b.get("calibration_ready")]
                ready_total += len(ready)
                dimensions[dimension] = {
                    "bucket_count": len(buckets),
                    "ready_bucket_count": len(ready),
                    "largest_bucket_sample": max([int(b.get("sample_size") or 0) for b in buckets] or [0]),
                    "buckets": buckets,
                }
            fragmentation = {
                "status": cs.get("status"), "graded_contexts": cs.get("graded_contexts", 0),
                "minimum_sample_per_bucket": cs.get("minimum_sample_per_bucket", 20),
                "bucket_count": bucket_total, "ready_bucket_count": ready_total,
                "fragmentation_detected": bool(cs.get("graded_contexts", 0) >= cs.get("minimum_sample_per_bucket", 20)
                                               and ready_total == 0),
                "dimensions": dimensions,
            }
        except Exception as exc:
            fragmentation = {**fragmentation, "status": "DEGRADED",
                             "error": f"{type(exc).__name__}: {exc}"}
            context_quality = {"status": "DEGRADED", "fields": {},
                               "error": f"{type(exc).__name__}: {exc}"}

    observation_window_integrity = {
        "schema_version": "apex.trigger_observation_window_integrity.v1",
        "window_seconds": MAX_HOLD_SECONDS,
        "trigger_count": len(rows),
        "trigger_status_counts": {
            "IN_WINDOW": observation_window_counts.get("IN_WINDOW", 0),
            "LATE": observation_window_counts.get("LATE", 0),
            "WINDOW_MISSED": observation_window_counts.get("WINDOW_MISSED", 0),
            "OBSERVING": observation_window_counts.get("OBSERVING", 0),
            "NOT_APPLICABLE": observation_window_counts.get("NOT_APPLICABLE", 0),
        },
        "in_window_observation_count": sum(int(r.get("_in_window_observation_count") or 0) for r in rows),
        "late_observation_count": sum(int(r.get("_late_observation_count") or 0) for r in rows),
        "pre_trigger_observation_count": sum(int(r.get("_pre_trigger_observation_count") or 0) for r in rows),
        "historical_mfe_mae_recomputed_from_in_window_samples": True,
        "late_samples_excluded_from_five_minute_metrics": True,
        "late_first_sample_can_terminalize_as_five_minute_observed": False,
        "window_missed_outcome_label": "OBSERVATION_WINDOW_INCOMPLETE",
        "regret_requires_valid_in_window_excursion": True,
        "production_effect": PRODUCTION_EFFECT,
        "execution_authority": False,
    }
    try:
        from .outcome_grader import horizon_integrity
        canonical_grader_integrity = horizon_integrity(evidence_resolved)
    except Exception as exc:
        canonical_grader_integrity = {
            "ok": False, "status": "DEGRADED", "expected_canonical_horizon_seconds": 300,
            "error": f"{type(exc).__name__}: {exc}", "execution_authority": False,
        }

    return {
        **base, "sample_size": len(rows),
        "canonical_graded_links": sum(1 for r in rows if r.get("canonical_grade_status") == "GRADED"),
        "confidence_bands": confidence_bands,
        "confidence_reliability": confidence_reliability,
        "blocker_effectiveness": blocker_effectiveness,
        "directional_cohorts": directional_cohorts,
        "decision_class_effectiveness": decision_class_effectiveness,
        "release_cohorts": release_cohorts,
        "abstention_regret": abstention_regret,
        "counterfactual_regret": counterfactual_regret,
        "observation_window_integrity": observation_window_integrity,
        "canonical_grader_horizon_integrity": canonical_grader_integrity,
        "metadata_join": metadata_join,
        "cross_cohorts": cross_cohorts,
        "calibration_fragmentation": fragmentation,
        "calibration_context_quality": context_quality,
        "interpretation_guardrails": [
            "Cohort statistics are observational associations, not causal effects.",
            "Confidence is an ordinal decision score, not a calibrated event probability.",
            "Session-conditioned and decision-class cohorts must be inspected before interpreting confidence ordering.",
            "Metadata-conditioned cohorts are reliable only to the extent reported by metadata_join coverage diagnostics.",
            "Actionable trades and observational NO_TRADE counterfactuals are reported separately where canonical decision metadata exists.",
            "Legacy abstention_regret potential blocker regret is movement-qualified only; counterfactual_regret is authoritative for actionability-qualified regret.",
            "Actionability qualification uses decision-time entry-window evidence persisted from Session Intelligence when present or from the same Trade Risk Guard policy that governs new entries; the current cutoff remains reference-only for legacy history.",
            "Potential blocker regret is a counterfactual diagnostic and does not prove an executable options trade existed.",
            "Movement-threshold sufficiency uses only explicit persisted target evidence or a governed boundary margin and never fabricates missing thresholds.",
            "Five-minute excursion uses only persisted observations with elapsed time inside the configured window; late samples are excluded.",
            "A late-only or missed observation window is marked OBSERVATION_WINDOW_INCOMPLETE and is not regret-eligible.",
            "Five-minute excursion is not a canonical trade grade.",
            "No confidence band, blocker, context, or cohort statistic mutates production behavior.",
            "Calibration remains human-governed and requires existing integrity gates.",
        ],
    }




def actionability_capture_readiness_validation(*, evidence_path: Optional[str] = None,
                                                limit: int = 100) -> Dict[str, Any]:
    """Return pre-grade live capture truth directly from the canonical decision ledger."""
    from .evidence_pipeline import DEFAULT_DB as evidence_default_db
    from .historical_evidence_lifecycle import actionability_capture_audit
    resolved = evidence_path or str(evidence_default_db)
    out = actionability_capture_audit(path=resolved, limit=limit)
    return {
        **out,
        "production_effect": PRODUCTION_EFFECT,
        "behavioral_authority": False,
        "execution_authority": False,
        "broker_mutation": False,
    }


def counterfactual_regret_validation(*, symbol: str = "SPX", path: Optional[str] = None,
                                      evidence_path: Optional[str] = None) -> Dict[str, Any]:
    """Return strict actionability-qualified regret diagnostics without authority."""
    full = predictive_validation(symbol=symbol, path=path, evidence_path=evidence_path)
    block = dict(full.get("counterfactual_regret") or {})
    return {
        "ok": bool(full.get("ok")),
        "status": block.get("status") or full.get("status"),
        "version": VERSION,
        "schema_version": block.get("schema_version") or "apex.counterfactual_regret_qualification.v3",
        "symbol": _u(symbol, "SPX"),
        "metadata_join": full.get("metadata_join") or {},
        "counterfactual_regret": block,
        "production_effect": PRODUCTION_EFFECT,
        "behavioral_authority": False,
        "execution_authority": False,
        "broker_mutation": False,
    }


def abstention_regret_validation(*, symbol: str = "SPX", path: Optional[str] = None,
                                 evidence_path: Optional[str] = None) -> Dict[str, Any]:
    """Return movement-qualified abstention-regret diagnostics without behavioral authority."""
    full = predictive_validation(symbol=symbol, path=path, evidence_path=evidence_path)
    regret = dict(full.get("abstention_regret") or {})
    return {
        "ok": bool(full.get("ok")),
        "status": regret.get("status") or full.get("status"),
        "version": VERSION,
        "schema_version": regret.get("schema_version") or "apex.abstention_regret.v2",
        "symbol": _u(symbol, "SPX"),
        "metadata_join": full.get("metadata_join") or {},
        "abstention_regret": regret,
        "production_effect": PRODUCTION_EFFECT,
        "behavioral_authority": False,
        "execution_authority": False,
        "broker_mutation": False,
    }


def observation_integrity_validation(*, symbol: str = "SPX", path: Optional[str] = None,
                                     evidence_path: Optional[str] = None) -> Dict[str, Any]:
    """Return horizon-safe Trigger Observatory and canonical-grader integrity diagnostics."""
    full = predictive_validation(symbol=symbol, path=path, evidence_path=evidence_path)
    return {
        "ok": bool(full.get("ok")), "status": full.get("status"), "version": VERSION,
        "schema_version": "apex.five_minute_observation_integrity.v1",
        "symbol": _u(symbol, "SPX"),
        "trigger_observation_window": full.get("observation_window_integrity") or {},
        "canonical_grader_horizon": full.get("canonical_grader_horizon_integrity") or {},
        "production_effect": PRODUCTION_EFFECT, "behavioral_authority": False,
        "execution_authority": False, "broker_mutation": False,
    }


def history(*, symbol: str = "SPX", limit: int = 100, status: Optional[str] = None,
            path: Optional[str] = None) -> Dict[str, Any]:
    resolved = path or _path()
    if not Path(resolved).exists():
        return {"ok": True, "status": "WAITING_FOR_TRIGGERS", "triggers": [], "version": VERSION}
    initialize_store(resolved)
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

    maturation = {"observing": 0, "matured": 0, "overdue_observing": 0, "with_price_observations": 0,
                  "observation_window_incomplete": 0, "in_window": 0, "late": 0, "window_missed": 0}
    trigger_path = trigger_path or _path()
    if Path(trigger_path).exists():
        try:
            now_epoch = datetime.now(timezone.utc).timestamp()
            with canonical_connect(trigger_path, read_only=True, timeout=4) as tconn:
                tconn.row_factory = sqlite3.Row
                rows = tconn.execute("SELECT status,triggered_at,observation_count,observation_window_seconds,window_integrity_status FROM observed_trade_triggers").fetchall()
            for row in rows:
                status_value = str(row["status"] or "").upper()
                window_value = str(row["window_integrity_status"] or "").upper()
                if window_value == "IN_WINDOW": maturation["in_window"] += 1
                elif window_value == "LATE": maturation["late"] += 1
                elif window_value == "WINDOW_MISSED": maturation["window_missed"] += 1
                if status_value == "OBSERVING":
                    maturation["observing"] += 1
                    try:
                        if now_epoch - _epoch(row["triggered_at"]) >= int(row["observation_window_seconds"] or MAX_HOLD_SECONDS):
                            maturation["overdue_observing"] += 1
                    except Exception:
                        pass
                elif status_value == "OBSERVED":
                    maturation["matured"] += 1
                elif status_value == "OBSERVATION_WINDOW_INCOMPLETE":
                    maturation["observation_window_incomplete"] += 1
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
            "SELECT * FROM trade_trigger_price_observations WHERE trigger_id=? ORDER BY observed_at",
            (raw["trigger_id"],),
        ).fetchall()]
    evidence = {}
    blockers = []
    try: evidence = json.loads(raw.get("evidence_json") or "{}")
    except Exception: evidence = {}
    try: blockers = json.loads(raw.get("blocker_codes_json") or "[]")
    except Exception: blockers = []
    direction = raw.get("direction")
    metrics = _window_metrics(raw, observations)
    observations = (
        metrics.get("in_window_observations", [])
        + metrics.get("late_observations", [])
        + metrics.get("pre_trigger_observations", [])
    )
    in_window_prices = [float(x["price"]) for x in metrics.get("in_window_observations", []) if x.get("price") is not None]
    entry = _f(raw.get("entry_reference"))
    prices = list(in_window_prices)
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
        "mfe_points": metrics.get("window_mfe_points"), "mae_points": metrics.get("window_mae_points"),
        "outcome_label": metrics.get("window_outcome_label"),
        "observation_window_integrity": {
            "status": metrics.get("window_integrity_status"),
            "window_seconds": metrics.get("observation_window_seconds"),
            "in_window_observation_count": metrics.get("in_window_observation_count"),
            "late_observation_count": metrics.get("late_observation_count"),
            "pre_trigger_observation_count": metrics.get("pre_trigger_observation_count"),
            "first_in_window_observed_at": metrics.get("first_in_window_observed_at"),
            "last_in_window_observed_at": metrics.get("last_in_window_observed_at"),
            "first_late_observed_at": metrics.get("first_late_observed_at"),
        }, "canonical_grade_status": raw.get("canonical_grade_status"),
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
            "canonical_outcome_linkage": True, "canonical_decision_id_propagation": True, "blocked_reason_visibility": True, "trade_visualization": True, "learning_readiness_surface": True, "calibration_readiness_verification": True, "predictive_validation_surface": True, "calibration_fragmentation_diagnostics": True, "calibration_context_diversity_audit": True, "confidence_reliability_audit": True, "session_conditioned_reliability": True, "decision_class_separation": True, "release_cohort_attribution": True, "predictive_metadata_join_diagnostics": True, "metadata_parse_isolation": True, "context_capture_integrity_closure": True, "session_conditioned_abstention_regret": True, "blocker_effectiveness_validation": True, "counterfactual_tradeability_guardrails": True, "five_minute_observation_integrity": True, "late_observation_exclusion": True, "observation_window_incomplete_state": True, "canonical_grader_horizon_verification": True, "explicit_target_threshold_recovery": True, "actionability_window_capture": True, "decision_time_entry_risk_policy_capture": True, "actionability_capture_provenance": True, "actionability_capture_readiness": True, "pregrade_live_actionability_capture_audit": True, "capture_lifecycle_attribution": True, "string_recommendation_capture": True, "counterfactual_regret_qualification": True, "no_explicit_blocker_diagnostics": True, "recommendation_layer_blocker_attribution": True, "historical_current_cutoff_inference_disabled": True, "target_absence_provenance": True, "cross_cohort_decomposition": True, "trigger_effectiveness_observational_only": True,
            "execution_authority": False, "broker_mutation": False,
            "production_effect": PRODUCTION_EFFECT}
