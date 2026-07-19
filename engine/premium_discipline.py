"""APEX 18.0.7 — Premium Discipline with governed adaptive calibration.

A deterministic, read-only approval gate for 0DTE premium-selling candidates.
It does not generate a trade and cannot place an order.  It answers whether a
candidate produced by the canonical Premium Strategy Engine is eligible to be
published as tradeable, records the reasons for refusal, and makes stand-downs
measurable rather than invisible.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

VERSION = "18.0.9_INSTITUTIONAL_PREMIUM_INTELLIGENCE"
APPROVE = "APPROVE"
REFUSE = "REFUSE"
NOT_APPLICABLE = "NOT_APPLICABLE"

_CREDIT = {"BULL_PUT_CREDIT_SPREAD", "BEAR_CALL_CREDIT_SPREAD", "IRON_CONDOR"}
_DEFAULT_THRESHOLD = 65.0


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return default if value is None else float(value)
    except (TypeError, ValueError):
        return default


def _u(value: Any) -> str:
    return str(value or "").strip().upper()


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _extract(last_result: Dict[str, Any]) -> Dict[str, Any]:
    lr = last_result if isinstance(last_result, dict) else {}
    inst = lr.get("institutional_intelligence") or {}
    market = lr.get("market_state") or {}
    vol = lr.get("volatility") or {}
    rng_wrap = lr.get("range_intelligence") or {}
    rng = rng_wrap.get("range_intelligence") if isinstance(rng_wrap, dict) else {}
    rng = rng or {}
    return {
        "session_state": _u(market.get("session_state")),
        "auction_state": _u(inst.get("auction_state") or market.get("auction_state")),
        "acceptance": _u(inst.get("acceptance")),
        "gamma_regime": _u(inst.get("gamma_regime") or market.get("gamma_regime")),
        "flow_bias": _u(inst.get("flow_bias") or market.get("flow_bias")),
        "flow_conviction": _f(inst.get("flow_conviction")),
        "flow_contradictions": list(inst.get("flow_contradictions") or []),
        "momentum_probability": _f(inst.get("momentum_probability")),
        "expansion_probability": _f(rng.get("expansion_probability")),
        "mean_reversion_probability": _f(rng.get("mean_reversion_probability")),
        "pin_probability": _f(inst.get("pin_probability") or rng.get("pin_probability")),
        "overall_score": _f(inst.get("overall_score") or inst.get("ici_score")),
        "vix": _f(vol.get("vix") or market.get("vix")),
        "vol_regime": _u(inst.get("vol_regime") or vol.get("regime")),
        "primary_risk": str(inst.get("primary_risk") or "").strip(),
    }


def evaluate_premium_eligibility(
    last_result: Dict[str, Any],
    candidate: Dict[str, Any],
    *,
    threshold: Optional[float] = None,
    weights: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Return an explainable approval/refusal decision for a premium candidate.

    The score is deliberately secondary to hard safety gates.  A high score can
    never override an unpriceable structure, closed session, active turn, or
    explicit NO_TRADE candidate.
    """
    threshold = _clamp(_f(threshold, _f(os.getenv("PREMIUM_ELIGIBILITY_THRESHOLD"), _DEFAULT_THRESHOLD)))
    base_weights = {"AUCTION": 0.20, "REGIME": 0.20, "GAMMA": 0.15, "FLOW": 0.15, "VOL": 0.10, "QUALITY": 0.20}
    supplied = weights if isinstance(weights, dict) else {}
    resolved_weights = {k: max(0.0, _f(supplied.get(k), v)) for k, v in base_weights.items()}
    weight_total = sum(resolved_weights.values()) or 1.0
    resolved_weights = {k: v / weight_total for k, v in resolved_weights.items()}
    c = candidate if isinstance(candidate, dict) else {}
    strategy = _u(c.get("strategy")) or "NO_TRADE"
    premium_kind = _u(c.get("premium_kind"))
    x = _extract(last_result)

    factors: List[Dict[str, Any]] = []
    blockers: List[str] = []
    warnings: List[str] = []

    def add(code: str, label: str, score: float, weight: float, detail: str) -> None:
        factors.append({"code": code, "label": label, "score": round(_clamp(score), 1),
                        "weight": weight, "detail": detail})

    if strategy == "NO_TRADE" or strategy not in _CREDIT or premium_kind not in {"", "CREDIT"}:
        return {
            "version": VERSION, "decision": NOT_APPLICABLE, "eligible": False,
            "score": 0.0, "threshold": threshold, "strategy": strategy,
            "blockers": ["Candidate is not a premium-selling credit structure."],
            "warnings": [], "factors": [],
            "headline": "PREMIUM DISCIPLINE — NOT APPLICABLE",
            "changes_trade_decisions": False,
        }

    session = x["session_state"]
    if session and session not in {"REGULAR", "RTH", "OPEN", "CASH_OPEN"}:
        blockers.append(f"Cash session is not open ({session}).")

    if c.get("tradeable") is False:
        blockers.append("Canonical premium engine marked the candidate non-tradeable.")
    if c.get("economics_available") is False:
        blockers.append("Executable chain economics are unavailable.")
    case = _u(c.get("case"))
    if "UNPRICEABLE" in case or "QUALITY_REJECT" in case:
        blockers.append(f"Candidate failed pricing/quality validation ({case}).")

    auction = x["auction_state"]
    active_turn = any(t in auction for t in ("BREAKOUT", "BREAKDOWN", "TREND", "EXPANSION", "DISCOVERY"))
    if active_turn and x["momentum_probability"] >= 55:
        blockers.append("Active directional turn/price discovery is incompatible with short-premium entry.")

    # 1. Auction/readability — 20%
    if any(t in auction for t in ("BALANCED", "ROTATION", "VALUE", "ACCEPT")):
        auction_score = 88
    elif active_turn:
        auction_score = 20
    elif not auction:
        auction_score = 45
        warnings.append("Auction state is unavailable.")
    else:
        auction_score = 55
    add("AUCTION", "Auction readability", auction_score, resolved_weights["AUCTION"],
        auction or "No auction state published")

    # 2. Mean-reversion vs expansion — 20%
    mr = x["mean_reversion_probability"]
    exp = x["expansion_probability"]
    regime_score = _clamp(50 + (mr - exp) * 0.6)
    add("REGIME", "Mean reversion versus expansion", regime_score, resolved_weights["REGIME"],
        f"mean_reversion={mr:.1f}, expansion={exp:.1f}")

    # 3. Gamma/pin containment — 15%
    gamma = x["gamma_regime"]
    pin = x["pin_probability"]
    gamma_base = 75 if "POSITIVE" in gamma else 30 if "NEGATIVE" in gamma else 50
    gamma_score = _clamp(gamma_base * 0.65 + pin * 0.35)
    add("GAMMA", "Gamma and pin containment", gamma_score, resolved_weights["GAMMA"],
        f"gamma={gamma or 'UNKNOWN'}, pin={pin:.1f}")

    # 4. Flow agreement / contradiction — 15%
    contradictions = len(x["flow_contradictions"])
    flow_score = _clamp(70 - contradictions * 18 + min(x["flow_conviction"], 30) * 0.4)
    if contradictions:
        warnings.append(f"{contradictions} flow contradiction(s) detected.")
    add("FLOW", "Flow stability", flow_score, resolved_weights["FLOW"],
        f"bias={x['flow_bias'] or 'UNKNOWN'}, conviction={x['flow_conviction']:.1f}, contradictions={contradictions}")

    # 5. Volatility suitability — 10%
    vix = x["vix"]
    if 15 <= vix <= 26:
        vol_score = 80
    elif 12 <= vix < 15 or 26 < vix <= 32:
        vol_score = 58
    elif vix <= 0:
        vol_score = 45
        warnings.append("VIX is unavailable.")
    else:
        vol_score = 30
    add("VOL", "Volatility suitability", vol_score, resolved_weights["VOL"],
        f"VIX={vix:.2f}, regime={x['vol_regime'] or 'UNKNOWN'}")

    # 6. Canonical candidate quality — 20%
    confidence = _f(c.get("confidence"))
    legs = c.get("legs") or {}
    pop = _f(legs.get("pop") or (c.get("pricing") or {}).get("pop")) * (100 if _f(legs.get("pop")) <= 1 else 1)
    quality_score = _clamp(confidence * 0.55 + pop * 0.45) if pop else _clamp(confidence * 0.75)
    add("QUALITY", "Candidate quality", quality_score, resolved_weights["QUALITY"],
        f"confidence={confidence:.1f}, probability={pop:.1f}" if pop else f"confidence={confidence:.1f}, probability unavailable")

    score = round(sum(f["score"] * f["weight"] for f in factors), 1)
    if score < threshold:
        blockers.append(f"Eligibility score {score:.1f} is below the governed threshold {threshold:.1f}.")

    decision = APPROVE if not blockers else REFUSE
    return {
        "version": VERSION,
        "decision": decision,
        "eligible": decision == APPROVE,
        "score": score,
        "threshold": threshold,
        "weights": {k: round(v, 4) for k, v in resolved_weights.items()},
        "strategy": strategy,
        "blockers": blockers,
        "warnings": warnings,
        "factors": factors,
        "headline": ("PREMIUM SELLING APPROVED" if decision == APPROVE
                     else "STAND DOWN — PREMIUM SELLING REFUSED"),
        "changes_trade_decisions": False,
        "governance_note": ("Advisory approval gate only. It does not submit, modify, "
                            "or cancel broker orders."),
    }


def decision_fingerprint(session_date: str, ticker: str, candidate: Dict[str, Any], decision: Dict[str, Any]) -> str:
    payload = {
        "session_date": session_date, "ticker": ticker,
        "strategy": candidate.get("strategy"), "case": candidate.get("case"),
        "legs": candidate.get("legs") or {}, "decision": decision.get("decision"),
        "blockers": decision.get("blockers") or [],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:24]


class RefusalLedger:
    """SQLite-backed, idempotent ledger for approved and refused decisions."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or os.getenv("DB_PATH", "apex_tracking.db")
        self._init()

    def _connect(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path, timeout=10)
        c.row_factory = sqlite3.Row
        return c

    def _init(self) -> None:
        directory = os.path.dirname(self.db_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with self._connect() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS premium_discipline_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fingerprint TEXT NOT NULL UNIQUE,
                ts TEXT NOT NULL,
                session_date TEXT NOT NULL,
                ticker TEXT NOT NULL,
                strategy TEXT NOT NULL,
                decision TEXT NOT NULL,
                eligibility_score REAL,
                threshold REAL,
                blockers_json TEXT NOT NULL,
                warnings_json TEXT NOT NULL,
                candidate_json TEXT NOT NULL,
                decision_json TEXT NOT NULL,
                counterfactual_outcome TEXT,
                counterfactual_pnl REAL,
                counterfactual_notes TEXT,
                graded_at TEXT
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_pdd_session ON premium_discipline_decisions(session_date, ticker)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_pdd_decision ON premium_discipline_decisions(decision, counterfactual_outcome)")
            existing = {row[1] for row in c.execute("PRAGMA table_info(premium_discipline_decisions)").fetchall()}
            for name, ddl in (
                ("counterfactual_metrics_json", "TEXT"),
                ("replay_version", "TEXT"),
            ):
                if name not in existing:
                    c.execute(f"ALTER TABLE premium_discipline_decisions ADD COLUMN {name} {ddl}")
            c.commit()

    def record(self, *, session_date: str, ticker: str, candidate: Dict[str, Any], decision: Dict[str, Any]) -> Dict[str, Any]:
        fp = decision_fingerprint(session_date, ticker, candidate, decision)
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as c:
            c.execute("""INSERT OR IGNORE INTO premium_discipline_decisions
                (fingerprint, ts, session_date, ticker, strategy, decision,
                 eligibility_score, threshold, blockers_json, warnings_json,
                 candidate_json, decision_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (fp, now, session_date, ticker, candidate.get("strategy") or "NO_TRADE",
                 decision.get("decision"), _f(decision.get("score")), _f(decision.get("threshold")),
                 json.dumps(decision.get("blockers") or []), json.dumps(decision.get("warnings") or []),
                 json.dumps(candidate, default=str), json.dumps(decision, default=str)))
            c.commit()
            row = c.execute("SELECT id, fingerprint, ts FROM premium_discipline_decisions WHERE fingerprint=?", (fp,)).fetchone()
        return {"recorded": True, "id": row["id"], "fingerprint": row["fingerprint"], "ts": row["ts"]}

    def ungraded_refusals(self, limit: int = 300) -> List[Dict[str, Any]]:
        limit = max(1, min(int(limit), 1000))
        with self._connect() as c:
            rows = c.execute(
                "SELECT * FROM premium_discipline_decisions "
                "WHERE decision=? AND counterfactual_outcome IS NULL "
                "ORDER BY id ASC LIMIT ?", (REFUSE, limit)).fetchall()
        return [dict(r) for r in rows]

    def grade(self, row_id: int, outcome: str, pnl: Optional[float], notes: str,
              metrics: Optional[Dict[str, Any]] = None) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as c:
            cur = c.execute(
                "UPDATE premium_discipline_decisions SET counterfactual_outcome=?, "
                "counterfactual_pnl=?, counterfactual_notes=?, graded_at=?, "
                "counterfactual_metrics_json=?, replay_version=? "
                "WHERE id=? AND counterfactual_outcome IS NULL",
                (outcome, pnl, notes, now, json.dumps(metrics or {}, default=str),
                 "18.0.6_TRADE_REFUSAL_REPLAY", int(row_id)))
            c.commit()
        return cur.rowcount == 1

    def replay_scorecard(self) -> Dict[str, Any]:
        with self._connect() as c:
            rows = c.execute(
                "SELECT counterfactual_outcome, counterfactual_pnl FROM premium_discipline_decisions "
                "WHERE decision=? AND counterfactual_outcome IS NOT NULL", (REFUSE,)).fetchall()
            pending = c.execute(
                "SELECT COUNT(*) FROM premium_discipline_decisions WHERE decision=? "
                "AND counterfactual_outcome IS NULL", (REFUSE,)).fetchone()[0]
        counts: Dict[str, int] = {}
        for row in rows:
            key = row["counterfactual_outcome"] or "UNKNOWN"
            counts[key] = counts.get(key, 0) + 1
        protected = counts.get("AVOIDED_LOSS", 0) + counts.get("AVOIDED_STOP", 0)
        missed = counts.get("MISSED_WIN", 0) + counts.get("FALSE_REJECTION", 0)
        actionable = protected + missed
        pnl_values = [_f(r["counterfactual_pnl"]) for r in rows if r["counterfactual_pnl"] is not None]
        return {
            "available": True, "version": "18.0.6_TRADE_REFUSAL_REPLAY",
            "graded": len(rows), "pending": pending, "outcomes": counts,
            "capital_protecting_refusals": protected, "missed_winners": missed,
            "refusal_precision_pct": round(100 * protected / actionable, 1) if actionable else None,
            "modeled_counterfactual_pnl_total": round(sum(pnl_values), 2) if pnl_values else None,
        }

    def recent(self, limit: int = 50, decision: Optional[str] = None) -> List[Dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        sql = "SELECT * FROM premium_discipline_decisions"
        args: List[Any] = []
        if decision:
            sql += " WHERE decision=?"; args.append(_u(decision))
        sql += " ORDER BY id DESC LIMIT ?"; args.append(limit)
        with self._connect() as c:
            rows = c.execute(sql, args).fetchall()
        return [dict(r) for r in rows]

    def scorecard(self) -> Dict[str, Any]:
        with self._connect() as c:
            rows = c.execute("SELECT decision, counterfactual_outcome, eligibility_score FROM premium_discipline_decisions").fetchall()
        total = len(rows)
        approved = sum(1 for r in rows if r["decision"] == APPROVE)
        refused = sum(1 for r in rows if r["decision"] == REFUSE)
        graded_refusals = [r for r in rows if r["decision"] == REFUSE and r["counterfactual_outcome"]]
        correct = sum(1 for r in graded_refusals if r["counterfactual_outcome"] in {"AVOIDED_LOSS", "AVOIDED_STOP"})
        false = sum(1 for r in graded_refusals if r["counterfactual_outcome"] in {"MISSED_WIN", "FALSE_REJECTION"})
        avg = round(sum(_f(r["eligibility_score"]) for r in rows) / total, 1) if total else None
        return {
            "available": True, "total": total, "approved": approved, "refused": refused,
            "approval_rate_pct": round(100 * approved / total, 1) if total else None,
            "graded_refusals": len(graded_refusals), "correct_refusals": correct,
            "false_rejections": false,
            "refusal_precision_pct": round(100 * correct / len(graded_refusals), 1) if graded_refusals else None,
            "avg_eligibility_score": avg,
        }
