"""APEX 18.1.5 — Execution Reality & Slippage.

Advisory-only execution-reality layer for the Premium Discipline Command
Center. It takes a modelled credit structure (priced at the mid) and asks the
only question that matters at the point of execution: *what would we actually
fill at, and does the trade still carry positive expected value once realistic
slippage is paid?*

A structure that looks good at the mid but only fills a tick or two worse can
flip from positive to negative expected value. This module makes that haircut
explicit before an order is ever contemplated, and shadow-records each
assessment so realised fills can later be compared against the model.

Design notes
------------
* Credits and strike widths are expressed in index points (e.g. ``1.50`` = a
  $1.50 credit = $150 per one-lot, since option economics are scaled ``* 100``
  elsewhere in the engine). Per-contract dollar figures are therefore
  ``points * 100``.
* Giving up ``s`` points of credit reduces per-contract expected value by
  exactly ``s * 100``: the max-profit leg falls by that amount and the
  max-loss leg rises by it, and ``pop * s + (1 - pop) * s == s``. The adjusted
  EV is therefore ``base_ev - slippage_per_contract`` regardless of the
  probability of profit — no re-derivation of ``pop`` is required.
* This layer never routes an order. Every payload carries
  ``advisory_only=True`` and ``execution_authority=False``.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sqlite3
from typing import Any, Dict, List, Optional

VERSION = "18.1.5_EXECUTION_REALITY_SLIPPAGE"

DEFAULT_MODEL = "MID_MINUS_ONE_TICK"

# Slippage models expressed in *ticks* of credit given up versus the modelled
# mid. NATURAL/WORST_CASE and SPREAD_PENALTY are resolved from measured leg
# quotes instead of a fixed tick count (see _slippage_points).
_TICK_MODELS: Dict[str, int] = {
    "MID": 0,
    "MID_MINUS_ONE_TICK": 1,
    "MID_MINUS_TWO_TICKS": 2,
    "MID_MINUS_THREE_TICKS": 3,
}
_MEASURED_MODELS = {"NATURAL", "WORST_CASE", "SPREAD_PENALTY"}


def _f(v: Any, d: float = 0.0) -> float:
    try:
        return d if v is None else float(v)
    except (TypeError, ValueError):
        return d


def _tick_size() -> float:
    """SPX option tick. Configurable, but 0.05 is the correct default."""
    t = _f(os.getenv("APEX_EXECUTION_TICK_SIZE"), 0.05)
    return t if t > 0 else 0.05


def _normalise_model(model: Optional[str]) -> str:
    m = str(model or DEFAULT_MODEL).strip().upper()
    if m in _TICK_MODELS or m in _MEASURED_MODELS:
        return m
    return DEFAULT_MODEL


def _premium_intelligence(source: Dict[str, Any]) -> Dict[str, Any]:
    """Accept either full expectancy-intelligence or a raw ranking payload."""
    if not isinstance(source, dict):
        return {}
    pi = source.get("premium_intelligence")
    return pi if isinstance(pi, dict) else source


def _winning_ranking_row(pi: Dict[str, Any], strategy: Optional[str]) -> Dict[str, Any]:
    rankings = pi.get("rankings") if isinstance(pi.get("rankings"), list) else []
    if strategy:
        for row in rankings:
            if isinstance(row, dict) and row.get("strategy") == strategy:
                return row
    for row in rankings:
        if isinstance(row, dict) and int(_f(row.get("rank"), 0)) == 0:
            return row
    return rankings[0] if rankings and isinstance(rankings[0], dict) else {}


def _measured_leg_spread(pricing: Dict[str, Any]) -> Optional[float]:
    """Sum of per-leg bid/ask spreads, in points, when quotes are present."""
    legs = pricing.get("legs_priced")
    if not isinstance(legs, list) or not legs:
        return None
    total = 0.0
    seen = False
    for leg in legs:
        if not isinstance(leg, dict):
            continue
        bid, ask = _f(leg.get("bid")), _f(leg.get("ask"))
        if ask > 0 and ask >= bid:
            total += (ask - bid)
            seen = True
    return round(total, 4) if seen else None


def _slippage_points(model: str, pricing: Dict[str, Any]) -> float:
    """Credit given up (points) under the requested model."""
    tick = _tick_size()
    if model in _TICK_MODELS:
        return round(_TICK_MODELS[model] * tick, 4)
    spread = _measured_leg_spread(pricing)
    if spread is None:
        # No quotes to measure — fall back to the conservative default.
        return round(_TICK_MODELS[DEFAULT_MODEL] * tick, 4)
    if model == "SPREAD_PENALTY":
        return round(max(tick, spread / 2.0), 4)
    # NATURAL / WORST_CASE: cross the full measured spread, floored at one tick.
    return round(max(tick, spread), 4)


def _assess(candidate: Dict[str, Any], *, model: str,
            base_ev_per_contract: Optional[float]) -> Dict[str, Any]:
    """Core slippage assessment for one priced candidate."""
    strategy = candidate.get("strategy") if isinstance(candidate, dict) else None
    pricing = candidate.get("pricing") if isinstance(candidate, dict) else None
    pricing = pricing if isinstance(pricing, dict) else {}
    warnings: List[str] = []

    tradeable = bool(candidate.get("tradeable")) and bool(candidate.get("economics_available"))
    priceable = bool(pricing.get("available"))
    target_credit = _f(pricing.get("entry_credit"))

    if not priceable or target_credit <= 0:
        warnings.append("Structure is unpriceable at the mid; no realistic fill can be modelled.")
        return {
            "strategy": strategy, "model": model, "status": "REJECTED",
            "target_credit": round(target_credit, 2), "realistic_fill_credit": 0.0,
            "slippage_points": 0.0, "slippage_per_contract": 0.0,
            "measured_leg_spread": _measured_leg_spread(pricing),
            "base_expected_value": (round(base_ev_per_contract, 2) if base_ev_per_contract is not None else None),
            "execution_adjusted_expected_value": None,
            "credit_capture_pct": None, "warnings": warnings,
            "advisory_only": True, "execution_authority": False,
        }

    slippage = _slippage_points(model, pricing)
    realistic = round(max(0.0, target_credit - slippage), 2)
    slippage_per_contract = round(slippage * 100.0, 2)
    capture_pct = round(100.0 * realistic / target_credit, 1) if target_credit > 0 else 0.0

    adjusted_ev: Optional[float] = None
    if base_ev_per_contract is not None:
        adjusted_ev = round(base_ev_per_contract - slippage_per_contract, 2)

    if not tradeable:
        status = "REJECTED"
        warnings.append("Candidate is not tradeable; execution reality is advisory context only.")
    elif realistic <= 0:
        status = "REJECTED"
        warnings.append("Realistic fill credit collapses to zero once slippage is paid.")
    elif adjusted_ev is not None and adjusted_ev <= 0:
        status = "MARGINAL"
        warnings.append("Slippage erases the modelled expected value; stand down unless the fill improves.")
    elif adjusted_ev is None:
        status = "MARGINAL"
        warnings.append("Expected value is unavailable; treat the adjusted credit as advisory only.")
    else:
        status = "EXECUTABLE"

    return {
        "strategy": strategy, "model": model, "status": status,
        "target_credit": round(target_credit, 2),
        "realistic_fill_credit": realistic,
        "slippage_points": round(slippage, 4),
        "slippage_per_contract": slippage_per_contract,
        "measured_leg_spread": _measured_leg_spread(pricing),
        "base_expected_value": (round(base_ev_per_contract, 2) if base_ev_per_contract is not None else None),
        "execution_adjusted_expected_value": adjusted_ev,
        "credit_capture_pct": capture_pct,
        "warnings": warnings,
        "advisory_only": True, "execution_authority": False,
    }


def build_execution_reality(expectancy_intelligence: Dict[str, Any],
                            *, model: Optional[str] = None) -> Dict[str, Any]:
    """Assess the recommended candidate's realistic fill and adjusted EV.

    Accepts either the full expectancy-intelligence payload (with a
    ``premium_intelligence`` ranking) or a raw ranking. Returns a dict whose
    ``state`` is ``"EXECUTABLE"`` only when the recommended structure survives
    slippage with positive expected value — the flag the portfolio risk
    governor gates on.
    """
    model = _normalise_model(model)
    pi = _premium_intelligence(expectancy_intelligence or {})

    if not pi or not pi.get("available"):
        return {
            "version": VERSION, "available": False, "model": model,
            "state": "NO_CANDIDATE", "recommendation": None,
            "reason": "No ranked premium candidate is available.",
            "advisory_only": True, "execution_authority": False,
        }

    candidate = pi.get("recommended_candidate")
    strategy = pi.get("recommendation")
    if not isinstance(candidate, dict) or strategy in (None, "NO_TRADE"):
        return {
            "version": VERSION, "available": True, "model": model,
            "state": "NO_CANDIDATE", "recommendation": None,
            "reason": "The ranking recommends NO_TRADE.",
            "advisory_only": True, "execution_authority": False,
        }

    row = _winning_ranking_row(pi, strategy)
    base_ev = _f(row.get("expected_value")) if row.get("expected_value") is not None else None
    recommendation = _assess(candidate, model=model, base_ev_per_contract=base_ev)
    state = "EXECUTABLE" if recommendation["status"] == "EXECUTABLE" else "NOT_EXECUTABLE"

    return {
        "version": VERSION, "available": True, "model": model, "state": state,
        "recommendation": recommendation,
        "advisory_only": True, "execution_authority": False,
        "governance_note": ("Execution reality models a realistic fill and its expected value; "
                            "it may block or downgrade a recommendation but never transmits an order."),
    }


def evaluate_candidate_execution(candidate: Dict[str, Any],
                                 *, model: Optional[str] = None,
                                 base_expected_value: Optional[float] = None) -> Dict[str, Any]:
    """Assess a single supplied candidate (used by shadow-fill requests)."""
    model = _normalise_model(model)
    if not isinstance(candidate, dict):
        return {
            "strategy": None, "model": model, "status": "REJECTED",
            "target_credit": 0.0, "realistic_fill_credit": 0.0,
            "slippage_points": 0.0, "slippage_per_contract": 0.0,
            "measured_leg_spread": None, "base_expected_value": None,
            "execution_adjusted_expected_value": None, "credit_capture_pct": None,
            "warnings": ["No candidate supplied."],
            "advisory_only": True, "execution_authority": False,
        }
    base_ev = _f(base_expected_value) if base_expected_value is not None else None
    return _assess(candidate, model=model, base_ev_per_contract=base_ev)


class ExecutionRealityStore:
    """Shadow-records execution-reality assessments and grades them against
    the credit that was actually filled, so the slippage model can be
    validated over time."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or os.getenv("DB_PATH", "apex_tracking.db")
        self._init()

    def _connect(self):
        c = sqlite3.connect(self.db_path, timeout=10)
        c.row_factory = sqlite3.Row
        return c

    def _init(self):
        directory = os.path.dirname(self.db_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with self._connect() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS premium_execution_reality_shadows (
                id INTEGER PRIMARY KEY AUTOINCREMENT, shadow_key TEXT UNIQUE NOT NULL,
                ts TEXT NOT NULL, ticker TEXT NOT NULL, strategy TEXT, model TEXT,
                status TEXT, target_credit REAL, shadow_fill_credit REAL,
                modeled_slippage REAL, payload_json TEXT NOT NULL,
                actual_fill_credit REAL, realized_slippage REAL, slippage_error REAL,
                fill_latency_ms INTEGER, details_json TEXT, graded_at TEXT
            )""")
            c.execute("CREATE INDEX IF NOT EXISTS idx_per_shadow_ticker "
                      "ON premium_execution_reality_shadows(ticker, id)")
            c.commit()

    def record_shadow(self, ticker: str, recommendation: Dict[str, Any],
                      observed_at: Optional[dt.datetime] = None) -> Dict[str, Any]:
        rec = recommendation if isinstance(recommendation, dict) else {}
        now = observed_at or dt.datetime.now(dt.timezone.utc)
        if isinstance(now, str):
            now = dt.datetime.fromisoformat(now)
        if now.tzinfo is None:
            now = now.replace(tzinfo=dt.timezone.utc)
        minute = now.replace(second=0, microsecond=0).isoformat()
        shadow_credit = _f(rec.get("realistic_fill_credit"))
        raw = json.dumps({"ticker": ticker.upper(), "minute": minute,
                          "strategy": rec.get("strategy"), "model": rec.get("model"),
                          "credit": shadow_credit}, sort_keys=True)
        key = hashlib.sha256(raw.encode()).hexdigest()
        with self._connect() as c:
            c.execute("""INSERT OR IGNORE INTO premium_execution_reality_shadows
                (shadow_key, ts, ticker, strategy, model, status, target_credit,
                 shadow_fill_credit, modeled_slippage, payload_json)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                      (key, now.isoformat(), ticker.upper(), rec.get("strategy"),
                       rec.get("model"), rec.get("status"), _f(rec.get("target_credit")),
                       shadow_credit, _f(rec.get("slippage_points")),
                       json.dumps(rec, sort_keys=True, default=str)))
            c.commit()
            row = c.execute("SELECT * FROM premium_execution_reality_shadows WHERE shadow_key=?",
                            (key,)).fetchone()
        d = dict(row) if row else {"shadow_key": key}
        d["execution_id"] = d.get("id")
        d["recorded"] = True
        return d

    def record_actual(self, execution_id: int, *, actual_fill_credit: float,
                      fill_latency_ms: Optional[int] = None,
                      details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        actual = _f(actual_fill_credit)
        with self._connect() as c:
            existing = c.execute("SELECT shadow_fill_credit, modeled_slippage FROM "
                                 "premium_execution_reality_shadows WHERE id=?",
                                 (int(execution_id),)).fetchone()
            if existing is None:
                raise ValueError(f"No shadow execution found for id {execution_id}.")
            shadow_credit = _f(existing["shadow_fill_credit"])
            target_credit = shadow_credit + _f(existing["modeled_slippage"])
            realized_slippage = round(target_credit - actual, 4)
            slippage_error = round(realized_slippage - _f(existing["modeled_slippage"]), 4)
            c.execute("""UPDATE premium_execution_reality_shadows
                SET actual_fill_credit=?, realized_slippage=?, slippage_error=?,
                    fill_latency_ms=?, details_json=?, graded_at=?
                WHERE id=?""",
                      (actual, realized_slippage, slippage_error,
                       int(fill_latency_ms) if fill_latency_ms is not None else None,
                       json.dumps(details or {}, sort_keys=True, default=str),
                       dt.datetime.now(dt.timezone.utc).isoformat(), int(execution_id)))
            c.commit()
            row = c.execute("SELECT * FROM premium_execution_reality_shadows WHERE id=?",
                            (int(execution_id),)).fetchone()
        return dict(row) if row else {"id": execution_id}

    def recent(self, limit: int = 100) -> List[Dict[str, Any]]:
        limit = max(1, min(int(limit), 500))
        with self._connect() as c:
            rows = c.execute("SELECT * FROM premium_execution_reality_shadows "
                             "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["payload"] = json.loads(d.get("payload_json") or "{}")
            except (TypeError, ValueError):
                d["payload"] = {}
            out.append(d)
        return out

    def scorecard(self) -> Dict[str, Any]:
        with self._connect() as c:
            total = c.execute("SELECT COUNT(*) AS n FROM "
                              "premium_execution_reality_shadows").fetchone()["n"]
            rows = c.execute("SELECT modeled_slippage, realized_slippage, slippage_error "
                             "FROM premium_execution_reality_shadows "
                             "WHERE actual_fill_credit IS NOT NULL").fetchall()
        graded = len(rows)
        if not graded:
            return {"version": VERSION, "shadow_count": int(total), "graded_count": 0,
                    "average_modeled_slippage": None, "average_realized_slippage": None,
                    "average_slippage_error": None, "model_understates_pct": None,
                    "fill_quality": "NO_DATA", "advisory_only": True}
        modeled = [_f(r["modeled_slippage"]) for r in rows]
        realized = [_f(r["realized_slippage"]) for r in rows]
        errors = [_f(r["slippage_error"]) for r in rows]
        understates = sum(1 for e in errors if e > 0)
        avg_err = sum(errors) / graded
        fill_quality = ("BETTER_THAN_MODELLED" if avg_err < -0.01
                        else "WORSE_THAN_MODELLED" if avg_err > 0.01
                        else "IN_LINE")
        return {
            "version": VERSION, "shadow_count": int(total), "graded_count": graded,
            "average_modeled_slippage": round(sum(modeled) / graded, 4),
            "average_realized_slippage": round(sum(realized) / graded, 4),
            "average_slippage_error": round(avg_err, 4),
            "model_understates_pct": round(100.0 * understates / graded, 1),
            "fill_quality": fill_quality, "advisory_only": True,
        }
