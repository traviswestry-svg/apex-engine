"""APEX 68.6.0 — Decision Outcome Attribution & Abstention Effectiveness.

Observational effectiveness layer over the canonical evidence pipeline.  This
module never changes live decisions, risk, execution authority, or calibration
activation.  It measures what happened after both actionable and abstained
canonical decisions, attributes gate opportunity cost/protection, and reports
entry/exit quality only when evidence supports those classifications.
"""
from __future__ import annotations

import json
import os
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

from .canonical_persistence import connection as canonical_connection
from .evidence_pipeline import DEFAULT_DB

VERSION = "68.6.0"
SCHEMA_VERSION = "apex.decision_outcome_attribution.v1"
DEFAULT_HORIZON = int(os.getenv("APEX_ATTRIBUTION_HORIZON_SECONDS", os.getenv("APEX_GRADING_HORIZON_SECONDS", "300")))
MISSED_MFE_THRESHOLD_POINTS = float(os.getenv("APEX_ABSTENTION_MFE_THRESHOLD_POINTS", "5.0"))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS decision_effectiveness_attribution(
    decision_id TEXT PRIMARY KEY,
    captured_at TEXT NOT NULL,
    ticker TEXT NOT NULL,
    action_class TEXT NOT NULL,
    action TEXT,
    direction TEXT,
    entry_price REAL,
    confidence REAL,
    learning_eligible INTEGER NOT NULL DEFAULT 0,
    counterfactual_eligible INTEGER NOT NULL DEFAULT 0,
    gates_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    horizon_seconds INTEGER,
    graded_at TEXT,
    won INTEGER,
    directional_move REAL,
    mfe REAL,
    mae REAL,
    missed_opportunity INTEGER,
    protective_abstention INTEGER,
    entry_quality TEXT,
    outcome_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_dea_status ON decision_effectiveness_attribution(status,captured_at);
CREATE INDEX IF NOT EXISTS idx_dea_class ON decision_effectiveness_attribution(action_class,status);
CREATE INDEX IF NOT EXISTS idx_dea_entry_quality ON decision_effectiveness_attribution(entry_quality);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _f(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _u(value: Any, default: str = "") -> str:
    text = str(value if value is not None else default).strip().upper()
    return text or default


def _b(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on", "blocked", "fail", "failed"}


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)


def _walk_gates(value: Any, prefix: str = "", depth: int = 0, out: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, Dict[str, Any]]:
    out = out if out is not None else {}
    if depth > 7:
        return out
    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            key = str(raw_key)
            name = f"{prefix}.{key}" if prefix else key
            low = key.lower()
            if low in {"blocking_conditions", "blockers", "failures", "failed_gates"} and isinstance(item, (list, tuple, set)):
                for gate in list(item)[:30]:
                    g = _u(gate)
                    if g:
                        out[f"{name}:{g}"] = {"gate": f"{name}:{g}", "state": "BLOCKED", "blocked": True}
            elif ("gate" in low or low in {"authorization", "decision_state", "state"}) and isinstance(item, (str, int, float, bool)):
                state = _u(item, "UNKNOWN")
                blocked = state in {"BLOCK", "BLOCKED", "FAIL", "FAILED", "SUPPRESS", "STAND_DOWN", "STOP_TRADING", "TIMEFRAME_CONFLICT", "DATA_LIMITED", "WATCH_ONLY", "NO_TRADE"}
                out[name] = {"gate": name, "state": state, "blocked": blocked}
            _walk_gates(item, name, depth + 1, out)
    elif isinstance(value, (list, tuple)):
        for idx, item in enumerate(list(value)[:20]):
            _walk_gates(item, f"{prefix}[{idx}]", depth + 1, out)
    return out


def extract_gates(snapshot: Mapping[str, Any]) -> list[Dict[str, Any]]:
    gates = list(_walk_gates(snapshot).values())
    gates.sort(key=lambda x: x["gate"])
    return gates[:120]


def _action_class(snapshot: Mapping[str, Any]) -> str:
    action = _u(snapshot.get("action") or snapshot.get("decision_state") or snapshot.get("state"), "STAND_DOWN")
    eligible = bool(snapshot.get("learning_eligible"))
    if eligible and action not in {"NO_TRADE", "STAND_DOWN", "WATCH", "WATCH_ONLY", "ABSTAIN", "NONE"}:
        return "ACTIONABLE"
    return "ABSTAIN"


def _insert_context(conn: sqlite3.Connection, decision_id: str, observed_at: str, snapshot: Mapping[str, Any]) -> bool:
    direction = _u(snapshot.get("direction") or "NEUTRAL", "NEUTRAL")
    action = _u(snapshot.get("action") or snapshot.get("decision_state") or "STAND_DOWN", "STAND_DOWN")
    action_class = _action_class(snapshot)
    entry = _f(snapshot.get("entry_reference") if snapshot.get("entry_reference") is not None else snapshot.get("entry_price"))
    counterfactual = action_class == "ABSTAIN" and direction in {"BULLISH", "BEARISH"} and entry is not None
    before = conn.total_changes
    conn.execute(
        """INSERT OR IGNORE INTO decision_effectiveness_attribution(
           decision_id,captured_at,ticker,action_class,action,direction,entry_price,confidence,
           learning_eligible,counterfactual_eligible,gates_json,status)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,'PENDING')""",
        (
            decision_id, observed_at, _u(snapshot.get("ticker"), "SPX"), action_class, action, direction,
            entry, _f(snapshot.get("confidence")), int(bool(snapshot.get("learning_eligible"))),
            int(counterfactual), json.dumps(extract_gates(snapshot), separators=(",", ":"), sort_keys=True),
        ),
    )
    return conn.total_changes > before


def capture_context(conn: sqlite3.Connection, decision_id: str, observed_at: str, snapshot: Mapping[str, Any]) -> bool:
    """Freeze attribution context at decision time.  Idempotent and non-authoritative."""
    ensure_schema(conn)
    return _insert_context(conn, decision_id, observed_at, snapshot)


def _explicit_entry_quality(snapshot: Mapping[str, Any]) -> Optional[str]:
    flat = json.dumps(snapshot, default=str).upper()
    if '"CHASED": TRUE' in flat or '"CHASE": TRUE' in flat or '"LATE_ENTRY": TRUE' in flat:
        return "CHASED_ENTRY" if "CHASE" in flat else "LATE_ENTRY"
    explicit = _u(snapshot.get("entry_timing") or snapshot.get("entry_quality"))
    allowed = {"EARLY_ENTRY", "OPTIMAL_ENTRY", "LATE_ENTRY", "CHASED_ENTRY", "MISSED_PULLBACK", "MISSED_CONTINUATION"}
    return explicit if explicit in allowed else None


def _entry_quality(snapshot: Mapping[str, Any], mfe: float, mae: float) -> str:
    explicit = _explicit_entry_quality(snapshot)
    if explicit:
        return explicit
    threshold = max(1.0, MISSED_MFE_THRESHOLD_POINTS * 0.4)
    if mfe >= threshold and abs(mae) <= max(1.0, 0.35 * abs(mfe)):
        return "OPTIMAL_ENTRY"
    if mae <= -threshold and mfe >= threshold and mfe >= abs(mae) * 0.75:
        return "EARLY_ENTRY"
    return "UNASSESSED"


def _snapshot_for_decision(conn: sqlite3.Connection, decision_id: str) -> Dict[str, Any]:
    row = conn.execute("SELECT snapshot_json FROM decisions WHERE decision_id=?", (decision_id,)).fetchone()
    if not row:
        return {}
    try:
        return json.loads(row["snapshot_json"] or "{}")
    except Exception:
        return {}


def grade_pending(path: str | Path = DEFAULT_DB, horizon_seconds: int = DEFAULT_HORIZON, limit: int = 500, now: Optional[datetime] = None) -> Dict[str, int]:
    """Grade attribution rows independently of the canonical calibration grader.

    This independence is deliberate: abstention counterfactuals never enter
    grading_results and therefore cannot contaminate 68.3–68.5 calibration.
    """
    current = now or datetime.now(timezone.utc)
    counts = {"graded": 0, "not_matured": 0, "missing_price": 0, "unassessable": 0, "errors": 0}
    with canonical_connection(path, read_only=False, timeout=4.0, wal=True, heal=True) as conn:
        ensure_schema(conn)
        rows = conn.execute(
            "SELECT * FROM decision_effectiveness_attribution WHERE status='PENDING' ORDER BY captured_at LIMIT ?",
            (int(limit),),
        ).fetchall()
        for row in rows:
            try:
                observed = datetime.fromisoformat(str(row["captured_at"]).replace("Z", "+00:00"))
                if (current - observed).total_seconds() < horizon_seconds:
                    counts["not_matured"] += 1
                    continue
                entry = _f(row["entry_price"])
                direction = _u(row["direction"], "NEUTRAL")
                if entry is None or direction not in {"BULLISH", "BEARISH"}:
                    conn.execute(
                        "UPDATE decision_effectiveness_attribution SET status='UNASSESSABLE',horizon_seconds=?,graded_at=?,outcome_json=? WHERE decision_id=?",
                        (horizon_seconds, current.isoformat(), json.dumps({"reason": "DIRECTION_OR_ENTRY_UNAVAILABLE"}), row["decision_id"]),
                    )
                    counts["unassessable"] += 1
                    continue
                end = datetime.fromtimestamp(observed.timestamp() + horizon_seconds, timezone.utc).isoformat()
                prices = conn.execute(
                    "SELECT price FROM price_samples WHERE ticker=? AND observed_at>=? AND observed_at<=? ORDER BY observed_at",
                    (row["ticker"], row["captured_at"], end),
                ).fetchall()
                if not prices:
                    counts["missing_price"] += 1
                    continue
                sign = 1.0 if direction == "BULLISH" else -1.0
                vals = [float(x["price"]) for x in prices]
                directional = [(p - entry) * sign for p in vals]
                move = directional[-1]
                mfe = max(directional)
                mae = min(directional)
                won = move > 0
                action_class = _u(row["action_class"])
                missed = None
                protective = None
                if action_class == "ABSTAIN":
                    missed = bool(mfe >= MISSED_MFE_THRESHOLD_POINTS and move > 0)
                    protective = bool(move <= 0 or mfe < MISSED_MFE_THRESHOLD_POINTS)
                snapshot = _snapshot_for_decision(conn, str(row["decision_id"]))
                quality = _entry_quality(snapshot, mfe, mae) if action_class == "ACTIONABLE" else "NOT_APPLICABLE"
                outcome = {
                    "won": won, "directional_move": round(move, 4), "mfe": round(mfe, 4), "mae": round(mae, 4),
                    "horizon_seconds": horizon_seconds, "action_class": action_class,
                    "counterfactual": action_class == "ABSTAIN", "missed_opportunity": missed,
                    "protective_abstention": protective, "entry_quality": quality,
                    "missed_mfe_threshold_points": MISSED_MFE_THRESHOLD_POINTS,
                }
                conn.execute(
                    """UPDATE decision_effectiveness_attribution SET status='GRADED',horizon_seconds=?,graded_at=?,won=?,
                       directional_move=?,mfe=?,mae=?,missed_opportunity=?,protective_abstention=?,entry_quality=?,outcome_json=?
                       WHERE decision_id=?""",
                    (
                        horizon_seconds, current.isoformat(), int(won), move, mfe, mae,
                        None if missed is None else int(missed), None if protective is None else int(protective),
                        quality, json.dumps(outcome, separators=(",", ":"), sort_keys=True), row["decision_id"],
                    ),
                )
                counts["graded"] += 1
            except Exception:
                counts["errors"] += 1
        conn.commit()
    return counts


def initialize_store(path: str | Path = DEFAULT_DB, backfill_limit: int = 5000) -> Dict[str, Any]:
    """Controlled writer-side schema initialization plus bounded historical context backfill."""
    backfilled = 0
    examined = 0
    with canonical_connection(path, read_only=False, timeout=4.0, wal=True, heal=True) as conn:
        ensure_schema(conn)
        has_decisions = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='decisions'"
        ).fetchone()
        if has_decisions:
            rows = conn.execute(
                """SELECT d.decision_id,d.observed_at,d.ticker,d.direction,d.action,d.entry_price,d.confidence,
                          d.learning_eligible,d.snapshot_json
                   FROM decisions d
                   LEFT JOIN decision_effectiveness_attribution a ON a.decision_id=d.decision_id
                   WHERE a.decision_id IS NULL ORDER BY d.observed_at DESC LIMIT ?""",
                (max(0, min(int(backfill_limit), 20000)),),
            ).fetchall()
            for row in rows:
                examined += 1
                try:
                    snap = json.loads(row["snapshot_json"] or "{}")
                except Exception:
                    snap = {}
                snap = dict(snap)
                snap.setdefault("decision_id", row["decision_id"])
                snap.setdefault("ticker", row["ticker"])
                snap.setdefault("direction", row["direction"])
                snap.setdefault("action", row["action"])
                snap.setdefault("entry_reference", row["entry_price"])
                snap.setdefault("confidence", row["confidence"])
                snap.setdefault("learning_eligible", bool(row["learning_eligible"]))
                backfilled += int(_insert_context(conn, str(row["decision_id"]), str(row["observed_at"]), snap))
        conn.commit()
    return {
        "ok": True, "status": "READY", "version": VERSION, "path": str(path),
        "initialized": True, "persistent_render_path": str(path).startswith("/data/"),
        "backfill_examined": examined, "backfilled_contexts": backfilled,
        "backfill_is_context_only": True, "execution_authority": False,
    }


def _open_read(path: str | Path):
    return canonical_connection(path, read_only=True, timeout=0.35, wal=False, heal=False, busy_timeout_ms=250)


def _availability(path: str | Path) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {"status": "MISSING_DB", "read_available": False, "initialized": False, "degraded": False}
    try:
        with _open_read(path) as conn:
            exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='decision_effectiveness_attribution'").fetchone()
        if not exists:
            return {"status": "EMPTY_NOT_INITIALIZED", "read_available": True, "initialized": False, "degraded": False}
        return {"status": "READY", "read_available": True, "initialized": True, "degraded": False}
    except sqlite3.OperationalError as exc:
        text = str(exc).lower()
        status = "BUSY" if "locked" in text or "busy" in text else "READ_ERROR"
        return {"status": status, "read_available": False, "initialized": True, "degraded": True, "error": type(exc).__name__}
    except Exception as exc:
        return {"status": "READ_ERROR", "read_available": False, "initialized": True, "degraded": True, "error": type(exc).__name__}


def _pct(n: int, d: int) -> Optional[float]:
    return round(100.0 * n / d, 2) if d else None


def summary(path: str | Path = DEFAULT_DB) -> Dict[str, Any]:
    availability = _availability(path)
    base = {"ok": not availability.get("degraded", False), "version": VERSION, "schema_version": SCHEMA_VERSION, **availability, "execution_authority": False}
    if availability["status"] != "READY":
        return {**base, "counts": {}, "abstention_effectiveness": {}, "entry_effectiveness": {}, "gate_effectiveness": []}
    try:
        with _open_read(path) as conn:
            rows = conn.execute("SELECT * FROM decision_effectiveness_attribution").fetchall()
    except Exception as exc:
        return {**base, "ok": False, "status": "READ_ERROR", "degraded": True, "error": type(exc).__name__, "counts": {}, "abstention_effectiveness": {}, "entry_effectiveness": {}, "gate_effectiveness": []}
    total = len(rows)
    graded = [r for r in rows if r["status"] == "GRADED"]
    abst = [r for r in graded if r["action_class"] == "ABSTAIN"]
    actionable = [r for r in graded if r["action_class"] == "ACTIONABLE"]
    missed = sum(int(r["missed_opportunity"] or 0) for r in abst)
    protective = sum(int(r["protective_abstention"] or 0) for r in abst)
    entry_counts = Counter(str(r["entry_quality"] or "UNASSESSED") for r in actionable)

    gates: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"gate": "", "evaluations": 0, "blocked": 0, "blocked_graded_abstentions": 0, "missed_after_block": 0, "protected_after_block": 0, "passed_actionable": 0, "wins_after_pass": 0})
    for r in graded:
        try:
            items = json.loads(r["gates_json"] or "[]")
        except Exception:
            items = []
        for item in items:
            name = str(item.get("gate") or "UNKNOWN")
            g = gates[name]
            g["gate"] = name
            g["evaluations"] += 1
            blocked = bool(item.get("blocked"))
            g["blocked"] += int(blocked)
            if blocked and r["action_class"] == "ABSTAIN":
                g["blocked_graded_abstentions"] += 1
                g["missed_after_block"] += int(r["missed_opportunity"] or 0)
                g["protected_after_block"] += int(r["protective_abstention"] or 0)
            if not blocked and r["action_class"] == "ACTIONABLE":
                g["passed_actionable"] += 1
                g["wins_after_pass"] += int(r["won"] or 0)
    gate_rows = []
    for g in gates.values():
        g["opportunity_cost_rate_pct"] = _pct(g["missed_after_block"], g["blocked_graded_abstentions"])
        g["protective_rate_pct"] = _pct(g["protected_after_block"], g["blocked_graded_abstentions"])
        g["win_rate_after_pass_pct"] = _pct(g["wins_after_pass"], g["passed_actionable"])
        gate_rows.append(g)
    gate_rows.sort(key=lambda x: (x["blocked_graded_abstentions"], x["evaluations"]), reverse=True)

    return {
        **base,
        "status": "READY",
        "counts": {
            "captured": total, "graded": len(graded), "pending": sum(r["status"] == "PENDING" for r in rows),
            "unassessable": sum(r["status"] == "UNASSESSABLE" for r in rows),
            "actionable_graded": len(actionable), "abstentions_graded": len(abst),
        },
        "abstention_effectiveness": {
            "graded_abstentions": len(abst), "missed_opportunities": missed, "protective_abstentions": protective,
            "missed_opportunity_rate_pct": _pct(missed, len(abst)), "protective_rate_pct": _pct(protective, len(abst)),
            "threshold_points": MISSED_MFE_THRESHOLD_POINTS,
            "counterfactual_is_observational_only": True,
        },
        "entry_effectiveness": {
            "graded_actionable": len(actionable), "classification_counts": dict(entry_counts),
            "empirical_late_entry_inference_disabled": True,
            "note": "LATE_ENTRY/CHASED_ENTRY require explicit decision-time evidence; post-decision prices alone do not fabricate them.",
        },
        "gate_effectiveness": gate_rows[:100],
        "governance": {
            "changes_trade_decisions": False, "changes_execution_authority": False,
            "feeds_calibration_automatically": False, "human_review_required_for_policy_change": True,
            "abstention_counterfactuals_excluded_from_grading_results": True,
        },
    }


def abstention_detail(path: str | Path = DEFAULT_DB, limit: int = 100) -> Dict[str, Any]:
    availability = _availability(path)
    if availability["status"] != "READY":
        return {"ok": not availability.get("degraded", False), "version": VERSION, **availability, "items": []}
    with _open_read(path) as conn:
        rows = conn.execute(
            """SELECT decision_id,captured_at,ticker,action,direction,confidence,horizon_seconds,directional_move,mfe,mae,
                      missed_opportunity,protective_abstention,gates_json,outcome_json
               FROM decision_effectiveness_attribution WHERE action_class='ABSTAIN' AND status='GRADED'
               ORDER BY captured_at DESC LIMIT ?""", (max(1, min(int(limit), 500)),)
        ).fetchall()
    items = []
    for r in rows:
        item = dict(r)
        for key in ("gates_json", "outcome_json"):
            try:
                item[key[:-5] if key.endswith("_json") else key] = json.loads(item.pop(key) or ("[]" if key == "gates_json" else "{}"))
            except Exception:
                item[key[:-5] if key.endswith("_json") else key] = [] if key == "gates_json" else {}
        items.append(item)
    return {"ok": True, "version": VERSION, "schema_version": SCHEMA_VERSION, **availability, "items": items, "execution_authority": False}


def exit_effectiveness(limit: int = 500) -> Dict[str, Any]:
    """Read actual completed Trade Director outcomes without inventing exits."""
    try:
        from .trade_director_institutional_learning import learning_db_path
        path = Path(learning_db_path())
    except Exception as exc:
        return {"ok": False, "available": False, "status": "LEARNING_STORE_UNAVAILABLE", "error": type(exc).__name__, "version": VERSION}
    if not path.exists():
        return {"ok": True, "available": False, "status": "NO_COMPLETED_TRADE_STORE", "version": VERSION, "trades": 0}
    try:
        with canonical_connection(path, read_only=True, timeout=0.35, wal=False, heal=False, busy_timeout_ms=250) as conn:
            exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='institutional_learning_ledger'").fetchone()
            if not exists:
                return {"ok": True, "available": False, "status": "NO_COMPLETED_TRADE_SCHEMA", "version": VERSION, "trades": 0}
            rows = conn.execute(
                "SELECT trade_id,mfe,mae,r_multiple,outcome_context_json,closed_at FROM institutional_learning_ledger ORDER BY closed_at DESC LIMIT ?",
                (max(1, min(int(limit), 2000)),),
            ).fetchall()
    except Exception as exc:
        return {"ok": False, "available": False, "status": "READ_ERROR", "error": type(exc).__name__, "version": VERSION}
    efficiencies = []
    with_mfe = 0
    for r in rows:
        mfe = _f(r["mfe"])
        if mfe in (None, 0):
            continue
        with_mfe += 1
        try:
            outcome = json.loads(r["outcome_context_json"] or "{}")
        except Exception:
            outcome = {}
        captured = _f(outcome.get("captured_move") if outcome.get("captured_move") is not None else outcome.get("realized_move"))
        if captured is None:
            # R multiple is not treated as movement unless the stored outcome explicitly says so.
            continue
        efficiencies.append(max(-100.0, min(100.0, 100.0 * captured / mfe)))
    return {
        "ok": True, "available": True, "status": "READY", "version": VERSION,
        "trades": len(rows), "trades_with_mfe": with_mfe, "trades_with_exit_efficiency": len(efficiencies),
        "avg_exit_capture_pct": round(sum(efficiencies) / len(efficiencies), 2) if efficiencies else None,
        "unrealized_mfe_measurement_requires_stored_captured_move": True,
        "execution_authority": False,
    }
