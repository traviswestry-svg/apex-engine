"""APEX 69.7.0 — Failed Breakdown Lifecycle Intelligence Foundation.

Persistent, deterministic and observational-only recognition of the sequence:

    significant level -> displacement -> sweep -> reclaim -> confirmation

The subsystem records evidence and emits advisory eligibility.  It never creates
a directional decision, changes consensus, sizes a position, or mutates broker
state.  All thresholds are explicit and all absent evidence stays absent.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence

from .canonical_persistence import connect as canonical_connect
from .persistent_store import persistent_sqlite_path

VERSION = "69.7.0"
SCHEMA_VERSION = "apex.failed_breakdown_lifecycle.v1"
PRODUCTION_EFFECT = "OBSERVATIONAL_ONLY"

ACTIVE_STATES = {
    "WATCHING_LEVEL", "APPROACHING", "ELEVATOR_DOWN_CONFIRMED", "SWEPT",
    "RECLAIMED", "CONFIRMATION_PENDING", "ENTRY_ELIGIBLE", "TP1_REACHED",
    "RUNNER_ACTIVE",
}
TERMINAL_STATES = {
    "NO_RECLAIM", "RECLAIM_FAILED", "ACCEPTANCE_FAILED", "INVALIDATED",
    "EXPIRED", "DATA_UNAVAILABLE", "COMPLETED",
}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


TOUCH_BAND_POINTS = _env_float("APEX_FBD_TOUCH_BAND_POINTS", 2.0)
SWEEP_MIN_POINTS = _env_float("APEX_FBD_SWEEP_MIN_POINTS", 3.0)
DISPLACEMENT_MIN_POINTS = _env_float("APEX_FBD_DISPLACEMENT_MIN_POINTS", 8.0)
DISPLACEMENT_WINDOW_SECONDS = _env_int("APEX_FBD_DISPLACEMENT_WINDOW_SECONDS", 300)
DISPLACEMENT_MIN_VELOCITY = _env_float("APEX_FBD_DISPLACEMENT_MIN_VELOCITY", 0.025)
RECLAIM_MAX_SECONDS = _env_int("APEX_FBD_RECLAIM_MAX_SECONDS", 600)
CONFIRM_HOLD_SECONDS = _env_int("APEX_FBD_CONFIRM_HOLD_SECONDS", 120)
CONFIRM_MARGIN_POINTS = _env_float("APEX_FBD_CONFIRM_MARGIN_POINTS", 5.0)
LIFECYCLE_EXPIRY_SECONDS = _env_int("APEX_FBD_LIFECYCLE_EXPIRY_SECONDS", 1800)
MIN_SIGNIFICANCE_SCORE = _env_float("APEX_FBD_MIN_SIGNIFICANCE_SCORE", 60.0)


def _db_path() -> str:
    return persistent_sqlite_path("APEX_FAILED_BREAKDOWN_DB", "apex_failed_breakdown.db")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Optional[datetime] = None) -> str:
    return (value or _now()).astimezone(timezone.utc).isoformat()


def _parse(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)


def _f(value: Any) -> Optional[float]:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _norm(value: Any, default: str = "UNKNOWN") -> str:
    text = str(value or "").strip().upper()
    return text or default


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS fbd_observations (
    observation_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, observed_at TEXT NOT NULL,
    price REAL NOT NULL, source TEXT NOT NULL, payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_fbd_observations_symbol_time
    ON fbd_observations(symbol, observed_at);

CREATE TABLE IF NOT EXISTS fbd_lifecycles (
    lifecycle_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, session_date TEXT NOT NULL,
    level_id TEXT NOT NULL, level_type TEXT NOT NULL, level_price REAL NOT NULL,
    level_source TEXT NOT NULL, significance_score REAL NOT NULL,
    approach_direction TEXT NOT NULL, state TEXT NOT NULL,
    started_at TEXT NOT NULL, updated_at TEXT NOT NULL, terminal_at TEXT,
    displacement_points REAL, displacement_seconds REAL, displacement_velocity REAL,
    sweep_price REAL, sweep_depth REAL, swept_at TEXT,
    reclaimed_at TEXT, time_to_reclaim_seconds REAL,
    confirmation_type TEXT, confirmed_at TEXT, time_to_confirmation_seconds REAL,
    target1_price REAL, target2_price REAL, invalidation_price REAL,
    target1_reached_at TEXT, target2_reached_at TEXT, maximum_favorable_excursion REAL,
    es_level_price REAL, spx_basis REAL, basis_observed_at TEXT,
    evidence_json TEXT NOT NULL, execution_authority INTEGER NOT NULL DEFAULT 0,
    production_effect TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_fbd_lifecycle_state
    ON fbd_lifecycles(symbol, state, updated_at);
CREATE UNIQUE INDEX IF NOT EXISTS ux_fbd_active_level
    ON fbd_lifecycles(symbol, session_date, level_id)
    WHERE terminal_at IS NULL;

CREATE TABLE IF NOT EXISTS fbd_events (
    event_id TEXT PRIMARY KEY, lifecycle_id TEXT NOT NULL, event_type TEXT NOT NULL,
    previous_state TEXT, new_state TEXT NOT NULL, observed_at TEXT NOT NULL,
    price REAL NOT NULL, evidence_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_fbd_events_lifecycle_time
    ON fbd_events(lifecycle_id, observed_at);
"""


def initialize_store(path: Optional[str] = None) -> Dict[str, Any]:
    resolved = path or _db_path()
    with canonical_connect(resolved, timeout=10) as conn:
        conn.executescript(_SCHEMA)
        conn.commit()
    return {
        "ok": True, "status": "READY", "path": resolved, "version": VERSION,
        "schema_version": SCHEMA_VERSION, "execution_authority": False,
        "production_effect": PRODUCTION_EFFECT,
    }


def _level_id(symbol: str, level: Mapping[str, Any]) -> str:
    supplied = level.get("level_id") or level.get("id")
    if supplied:
        return str(supplied)
    raw = f"{symbol}|{_norm(level.get('type') or level.get('kind'))}|{_f(level.get('price'))}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def _significance(level: Mapping[str, Any]) -> float:
    supplied = _f(level.get("significance_score") or level.get("strength"))
    if supplied is not None:
        return round(max(0.0, min(100.0, supplied if supplied > 1 else supplied * 100)), 2)
    kind = _norm(level.get("type") or level.get("kind"))
    base = 35.0
    if kind in {"PREV_DAY_LOW", "PREV_DAY_HIGH", "PDL", "PDH"}: base += 35
    if kind in {"SWING_LOW", "SWING_HIGH", "EQUAL_LOWS", "EQUAL_HIGHS"}: base += 25
    if kind in {"VAL", "VAH", "PUT_WALL", "CALL_WALL", "GAMMA_FLIP"}: base += 20
    touches = int(_f(level.get("prior_reactions") or level.get("touch_count")) or 0)
    base += min(20.0, touches * 5.0)
    confluence = int(_f(level.get("confluence_count")) or 0)
    base += min(15.0, confluence * 5.0)
    return round(min(100.0, base), 2)


def _rank_targets(price: float, levels: Sequence[Mapping[str, Any]]) -> tuple[Optional[float], Optional[float]]:
    above = sorted({p for p in (_f(x.get("price")) for x in levels) if p is not None and p > price + TOUCH_BAND_POINTS})
    return (above[0] if above else None, above[1] if len(above) > 1 else None)


def _event(conn, row: Mapping[str, Any], event_type: str, new_state: str,
           observed_at: str, price: float, evidence: Mapping[str, Any]) -> None:
    previous = str(row.get("state") or "WATCHING_LEVEL")
    conn.execute(
        "INSERT INTO fbd_events VALUES(?,?,?,?,?,?,?,?,?)",
        (str(uuid.uuid4()), row["lifecycle_id"], event_type, previous, new_state,
         observed_at, price, _json(evidence), _iso()),
    )


def _observation_window(conn, symbol: str, observed_at: datetime) -> list[tuple[datetime, float]]:
    start = observed_at.timestamp() - DISPLACEMENT_WINDOW_SECONDS
    rows = conn.execute(
        "SELECT observed_at,price FROM fbd_observations WHERE symbol=? AND observed_at>=? ORDER BY observed_at",
        (symbol, datetime.fromtimestamp(start, timezone.utc).isoformat()),
    ).fetchall()
    return [(_parse(r[0]), float(r[1])) for r in rows]


def observe(*, symbol: str, price: float, levels: Sequence[Mapping[str, Any]],
            observed_at: Any = None, source: str = "CANONICAL_DATA_BUS",
            relative_volume: Any = None, tick_alignment: Any = None,
            absorption: Any = None, es_price: Any = None, spx_basis: Any = None,
            basis_observed_at: Any = None, path: Optional[str] = None) -> Dict[str, Any]:
    """Capture one real observation and advance eligible long failed-break lifecycles."""
    initialize_store(path)
    at = _parse(observed_at or _iso())
    at_iso = at.isoformat()
    symbol = _norm(symbol, "SPX")
    px = _f(price)
    if px is None:
        return {"ok": False, "status": "DATA_UNAVAILABLE", "reason": "PRICE_REQUIRED",
                "execution_authority": False, "production_effect": PRODUCTION_EFFECT}
    clean_levels = []
    for raw in levels or []:
        if not isinstance(raw, Mapping):
            continue
        lp = _f(raw.get("price"))
        if lp is None:
            continue
        item = dict(raw); item["price"] = lp
        item["level_id"] = _level_id(symbol, item)
        item["significance_score"] = _significance(item)
        clean_levels.append(item)

    payload = {"relative_volume": _f(relative_volume), "tick_alignment": tick_alignment,
               "absorption": absorption, "level_count": len(clean_levels)}
    transitions = []
    with canonical_connect(path or _db_path(), timeout=10) as conn:
        conn.row_factory = __import__("sqlite3").Row
        conn.execute(
            "INSERT INTO fbd_observations VALUES(?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), symbol, at_iso, px, source, _json(payload), _iso()),
        )
        window = _observation_window(conn, symbol, at)
        window_high = max((p for _, p in window), default=px)
        first_at = min((t for t, _ in window), default=at)
        displacement = max(0.0, window_high - px)
        displacement_seconds = max(1.0, (at - first_at).total_seconds())
        velocity = displacement / displacement_seconds
        elevator = displacement >= DISPLACEMENT_MIN_POINTS and velocity >= DISPLACEMENT_MIN_VELOCITY

        # Start lifecycles only for significant support-like levels approached from above.
        for level in clean_levels:
            lp = float(level["price"]); sig = float(level["significance_score"])
            if sig < MIN_SIGNIFICANCE_SCORE:
                continue
            if px > lp + max(TOUCH_BAND_POINTS, DISPLACEMENT_MIN_POINTS):
                continue
            # A long failed breakdown must approach the level from above. If the
            # first observed price is already below it, require real window
            # evidence that price traded above the level earlier; otherwise this
            # is an unrelated overhead level, not a swept support candidate.
            if px < lp - TOUCH_BAND_POINTS and window_high < lp + TOUCH_BAND_POINTS:
                continue
            existing = conn.execute(
                "SELECT * FROM fbd_lifecycles WHERE symbol=? AND session_date=? AND level_id=? AND terminal_at IS NULL",
                (symbol, at.date().isoformat(), level["level_id"]),
            ).fetchone()
            if existing is None:
                t1, t2 = _rank_targets(lp, clean_levels)
                lifecycle_id = str(uuid.uuid4())
                evidence = {"level": level, "source": source, "initial_observation": payload}
                conn.execute(
                    """INSERT INTO fbd_lifecycles(
                       lifecycle_id,symbol,session_date,level_id,level_type,level_price,level_source,
                       significance_score,approach_direction,state,started_at,updated_at,
                       displacement_points,displacement_seconds,displacement_velocity,target1_price,
                       target2_price,invalidation_price,es_level_price,spx_basis,basis_observed_at,
                       evidence_json,execution_authority,production_effect)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?)""",
                    (lifecycle_id, symbol, at.date().isoformat(), level["level_id"],
                     _norm(level.get("type") or level.get("kind")), lp,
                     str(level.get("source") or source), sig, "FROM_ABOVE",
                     "ELEVATOR_DOWN_CONFIRMED" if elevator else "APPROACHING", at_iso, at_iso,
                     displacement, displacement_seconds, velocity, t1, t2,
                     lp - max(TOUCH_BAND_POINTS, SWEEP_MIN_POINTS), _f(level.get("es_price")),
                     _f(spx_basis), str(basis_observed_at or "") or None, _json(evidence), PRODUCTION_EFFECT),
                )
                row = dict(conn.execute("SELECT * FROM fbd_lifecycles WHERE lifecycle_id=?", (lifecycle_id,)).fetchone())
                _event(conn, row, "LIFECYCLE_STARTED", row["state"], at_iso, px,
                       {"elevator_down": elevator, "displacement_points": displacement, "velocity": velocity})
                transitions.append({"lifecycle_id": lifecycle_id, "state": row["state"]})

        active = conn.execute(
            "SELECT * FROM fbd_lifecycles WHERE symbol=? AND terminal_at IS NULL ORDER BY started_at",
            (symbol,),
        ).fetchall()
        for raw in active:
            row = dict(raw); state = row["state"]; lp = float(row["level_price"])
            started = _parse(row["started_at"]); age = (at - started).total_seconds()
            update: Dict[str, Any] = {"updated_at": at_iso}
            new_state = state; event_type = None; ev: Dict[str, Any] = {}
            if age > LIFECYCLE_EXPIRY_SECONDS and state not in {"ENTRY_ELIGIBLE"}:
                new_state = "EXPIRED"; event_type = "LIFECYCLE_EXPIRED"; update["terminal_at"] = at_iso
            elif state in {"APPROACHING", "ELEVATOR_DOWN_CONFIRMED"}:
                if elevator and state == "APPROACHING":
                    new_state = "ELEVATOR_DOWN_CONFIRMED"; event_type = "DISPLACEMENT_CONFIRMED"
                if px <= lp - SWEEP_MIN_POINTS:
                    new_state = "SWEPT"; event_type = "LEVEL_SWEPT"
                    update.update(sweep_price=px, sweep_depth=lp-px, swept_at=at_iso,
                                  displacement_points=displacement,
                                  displacement_seconds=displacement_seconds,
                                  displacement_velocity=velocity)
                    ev = {"sweep_depth": lp-px, "elevator_down": elevator}
            elif state == "SWEPT":
                swept_at = _parse(row["swept_at"])
                elapsed = (at - swept_at).total_seconds()
                if px >= lp:
                    new_state = "RECLAIMED"; event_type = "LEVEL_RECLAIMED"
                    update.update(reclaimed_at=at_iso, time_to_reclaim_seconds=elapsed)
                    ev = {"time_to_reclaim_seconds": elapsed}
                elif elapsed > RECLAIM_MAX_SECONDS:
                    new_state = "NO_RECLAIM"; event_type = "RECLAIM_WINDOW_EXPIRED"; update["terminal_at"] = at_iso
            elif state in {"RECLAIMED", "CONFIRMATION_PENDING"}:
                reclaimed_at = _parse(row["reclaimed_at"])
                elapsed = (at - reclaimed_at).total_seconds()
                if px < lp - TOUCH_BAND_POINTS:
                    new_state = "RECLAIM_FAILED"; event_type = "RECLAIM_FAILED"; update["terminal_at"] = at_iso
                elif px >= lp + CONFIRM_MARGIN_POINTS and elapsed >= CONFIRM_HOLD_SECONDS:
                    new_state = "ENTRY_ELIGIBLE"; event_type = "NON_ACCEPTANCE_CONFIRMED"
                    update.update(confirmation_type="RECLAIM_MARGIN_HOLD", confirmed_at=at_iso,
                                  time_to_confirmation_seconds=elapsed)
                    ev = {"margin_points": px-lp, "hold_seconds": elapsed,
                          "tick_alignment": tick_alignment, "absorption": absorption}
                elif elapsed > 0:
                    new_state = "CONFIRMATION_PENDING"
                    if state != new_state: event_type = "CONFIRMATION_PENDING"
            elif state in {"ENTRY_ELIGIBLE", "TP1_REACHED", "RUNNER_ACTIVE"}:
                invalidation = _f(row.get("invalidation_price"))
                target1 = _f(row.get("target1_price"))
                target2 = _f(row.get("target2_price"))
                confirmed_price = lp + CONFIRM_MARGIN_POINTS
                prior_mfe = _f(row.get("maximum_favorable_excursion")) or 0.0
                update["maximum_favorable_excursion"] = max(prior_mfe, px - confirmed_price)
                if invalidation is not None and px <= invalidation:
                    new_state = "COMPLETED" if state in {"TP1_REACHED", "RUNNER_ACTIVE"} else "INVALIDATED"
                    event_type = "RUNNER_STOPPED" if new_state == "COMPLETED" else "POST_CONFIRMATION_INVALIDATED"
                    update["terminal_at"] = at_iso
                elif target2 is not None and px >= target2 and state != "RUNNER_ACTIVE":
                    new_state = "RUNNER_ACTIVE"; event_type = "TARGET2_REACHED"
                    update["target2_reached_at"] = at_iso
                    if not row.get("target1_reached_at"): update["target1_reached_at"] = at_iso
                elif target1 is not None and px >= target1 and state == "ENTRY_ELIGIBLE":
                    new_state = "TP1_REACHED"; event_type = "TARGET1_REACHED"
                    update["target1_reached_at"] = at_iso

            if new_state != state or event_type:
                update["state"] = new_state
                assignments = ",".join(f"{key}=?" for key in update)
                conn.execute(f"UPDATE fbd_lifecycles SET {assignments} WHERE lifecycle_id=?",
                             (*update.values(), row["lifecycle_id"]))
                _event(conn, row, event_type or "STATE_UPDATED", new_state, at_iso, px, ev)
                transitions.append({"lifecycle_id": row["lifecycle_id"], "from": state, "state": new_state})
        conn.commit()

    current = current_state(symbol=symbol, path=path)
    return {"ok": True, "status": "CAPTURED", "transitions": transitions,
            "current": current, "execution_authority": False,
            "production_effect": PRODUCTION_EFFECT}


def _extract_levels(snapshot: Mapping[str, Any]) -> list[dict[str, Any]]:
    levels: list[dict[str, Any]] = []
    seen: set[tuple[str, float]] = set()
    def add(kind: str, value: Any, source: str, strength: Any = None):
        price = _f(value)
        if price is None: return
        key = (_norm(kind), round(price, 4))
        if key in seen: return
        seen.add(key); levels.append({"type": kind, "price": price, "source": source,
                                      "strength": strength})
    candidates = [snapshot.get("daily_key_levels"), snapshot.get("key_levels"),
                  (snapshot.get("structure") or {}).get("levels"),
                  (snapshot.get("institutional_market_structure") or {}).get("structure_levels")]
    for block in candidates:
        if isinstance(block, Mapping): block = block.get("levels") or block.get("all_levels") or block
        if isinstance(block, Sequence) and not isinstance(block, (str, bytes)):
            for item in block:
                if isinstance(item, Mapping):
                    add(str(item.get("type") or item.get("kind") or item.get("label") or "LEVEL"),
                        item.get("price"), str(item.get("source") or "DATA_BUS"),
                        item.get("significance_score") or item.get("strength"))
    structure = snapshot.get("structure") if isinstance(snapshot.get("structure"), Mapping) else {}
    market = snapshot.get("market_state") if isinstance(snapshot.get("market_state"), Mapping) else {}
    gamma = snapshot.get("gamma_regime") if isinstance(snapshot.get("gamma_regime"), Mapping) else {}
    for kind, value in (("PDL", structure.get("pdl") or market.get("pdl")),
                        ("SWING_LOW", structure.get("swing_low") or structure.get("support")),
                        ("VAL", market.get("val")), ("PUT_WALL", market.get("put_wall") or gamma.get("put_wall"))):
        add(kind, value, "CANONICAL_DATA_BUS")
    return levels


def observe_snapshot(snapshot: Optional[Mapping[str, Any]], *, path: Optional[str] = None) -> Dict[str, Any]:
    s = dict(snapshot or {})
    market = s.get("market_state") if isinstance(s.get("market_state"), Mapping) else {}
    price = _f(market.get("price") or s.get("spot") or s.get("price") or (s.get("flow") or {}).get("stock_price"))
    if price is None:
        return {"ok": False, "status": "DATA_UNAVAILABLE", "reason": "CANONICAL_PRICE_UNAVAILABLE",
                "execution_authority": False, "production_effect": PRODUCTION_EFFECT}
    tick = s.get("tick_momentum") if isinstance(s.get("tick_momentum"), Mapping) else {}
    micro = s.get("market_microstructure") if isinstance(s.get("market_microstructure"), Mapping) else {}
    return observe(symbol=str(s.get("ticker") or "SPX"), price=price, levels=_extract_levels(s),
                   observed_at=s.get("timestamp") or s.get("observed_at") or _iso(),
                   relative_volume=(s.get("volume") or {}).get("relative_volume") if isinstance(s.get("volume"), Mapping) else None,
                   tick_alignment=tick.get("alignment_state"),
                   absorption=(micro.get("interaction") or {}).get("absorption_candidate") if isinstance(micro, Mapping) else None,
                   path=path)


def current_state(*, symbol: str = "SPX", path: Optional[str] = None) -> Dict[str, Any]:
    resolved = path or _db_path()
    if not Path(resolved).exists():
        return {"ok": True, "status": "WAITING_FOR_OBSERVATIONS", "active": [],
                "version": VERSION, "execution_authority": False, "production_effect": PRODUCTION_EFFECT}
    with canonical_connect(resolved, read_only=True, timeout=4) as conn:
        conn.row_factory = __import__("sqlite3").Row
        rows = conn.execute(
            "SELECT * FROM fbd_lifecycles WHERE symbol=? AND terminal_at IS NULL ORDER BY updated_at DESC",
            (_norm(symbol, "SPX"),),
        ).fetchall()
    active = []
    for raw in rows:
        row = dict(raw); row["evidence"] = json.loads(row.pop("evidence_json") or "{}")
        row["entry_advisory_eligible"] = row["state"] == "ENTRY_ELIGIBLE"
        active.append(row)
    return {"ok": True, "status": "READY" if active else "WATCHING", "active": active,
            "active_count": len(active), "version": VERSION, "schema_version": SCHEMA_VERSION,
            "execution_authority": False, "production_effect": PRODUCTION_EFFECT}


def history(*, symbol: str = "SPX", lifecycle_id: Optional[str] = None,
            limit: int = 100, path: Optional[str] = None) -> Dict[str, Any]:
    resolved = path or _db_path()
    if not Path(resolved).exists():
        return {"ok": True, "lifecycles": [], "events": [], "version": VERSION}
    limit = max(1, min(int(limit), 1000))
    with canonical_connect(resolved, read_only=True, timeout=4) as conn:
        conn.row_factory = __import__("sqlite3").Row
        if lifecycle_id:
            rows = conn.execute("SELECT * FROM fbd_lifecycles WHERE lifecycle_id=?", (lifecycle_id,)).fetchall()
            events = conn.execute("SELECT * FROM fbd_events WHERE lifecycle_id=? ORDER BY observed_at", (lifecycle_id,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM fbd_lifecycles WHERE symbol=? ORDER BY updated_at DESC LIMIT ?",
                                (_norm(symbol, "SPX"), limit)).fetchall()
            events = []
    return {"ok": True, "lifecycles": [dict(x) for x in rows], "events": [dict(x) for x in events],
            "version": VERSION, "execution_authority": False, "production_effect": PRODUCTION_EFFECT}


def capability() -> Dict[str, Any]:
    return {
        "ok": True, "version": VERSION, "schema_version": SCHEMA_VERSION,
        "status": "OBSERVATIONAL", "states": sorted(ACTIVE_STATES | TERMINAL_STATES),
        "inputs": ["canonical_spx_price", "governed_levels", "optional_tick_momentum",
                   "optional_microstructure_absorption"],
        "outputs": ["persistent_lifecycle", "chronological_events", "advisory_entry_eligibility",
                    "level_to_level_targets"],
        "automatic_promotion": False, "changes_trade_decisions": False,
        "execution_authority": False, "production_effect": PRODUCTION_EFFECT,
    }
