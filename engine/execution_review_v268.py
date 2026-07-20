"""APEX 26.8 — Execution Review Engine (advisory, deterministic).

Grades EXECUTION quality independent of forecast quality: entry quality, exit
quality, timing, slippage, spread capture, risk control, profit efficiency, and
management quality. A good forecast executed poorly scores low here; a modest
forecast executed cleanly scores high. Read-only; ``production_effect`` NONE.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Optional

VERSION = "26.8.0_EXECUTION_REVIEW"
SCHEMA_VERSION = "apex.execution_review.v268.v1"

DIMENSIONS = ("entry_quality", "exit_quality", "execution_timing", "slippage_quality",
              "spread_capture", "risk_control", "profit_efficiency", "management_quality")
GRADES = ("A+", "A", "A-", "B+", "B", "B-", "C", "D", "F", "NOT_GRADEABLE")


def _number(value: Any, default: float = 0.0) -> float:
    try:
        n = float(value)
        return n if math.isfinite(n) else default
    except (TypeError, ValueError):
        return default


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _round(v: Any, p: int = 2) -> Optional[float]:
    return None if v is None else round(float(v), p)


def _grade(score: float) -> str:
    for cut, g in ((95, "A+"), (90, "A"), (85, "A-"), (80, "B+"), (75, "B"),
                   (70, "B-"), (60, "C"), (50, "D")):
        if score >= cut:
            return g
    return "F"


def review(trade: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    t = _mapping(trade)
    plan = _mapping(t.get("plan"))
    entry_plan = _mapping(plan.get("entry"))
    fills = _mapping(t.get("fills"))
    exit_rec = _mapping(t.get("exit"))

    entry_price = _number(fills.get("entry_fill_price"))
    intended_entry = _number(entry_plan.get("recommended_limit_price") or t.get("intended_entry"))
    expected_slippage = _number(entry_plan.get("expected_slippage"), 0.02)
    exit_price = _number(fills.get("exit_fill_price"))
    intended_exit = _number(exit_rec.get("target_premium") or t.get("intended_exit"))
    spread = _number(t.get("spread"))
    mfe = _number(t.get("mfe"))
    mae = _number(t.get("mae"))
    realized = _number(t.get("realized_r"))

    if entry_price <= 0 or not fills:
        return {"ok": True, "execution_grade": "NOT_GRADEABLE",
                "reason": "No fill data supplied.", "production_effect": "NONE"}

    # Entry quality: fill vs intended, scaled by expected slippage.
    entry_err = abs(entry_price - intended_entry) if intended_entry else 0.0
    entry_quality = _clamp(100 - (entry_err / max(0.01, expected_slippage)) * 25)
    # Slippage quality: realized vs expected.
    slippage_quality = _clamp(100 - (entry_err / max(0.01, expected_slippage)) * 30)
    # Spread capture: fraction of spread paid.
    spread_capture = _clamp(100 - (entry_err / max(0.01, spread)) * 100) if spread > 0 else 70.0
    # Exit quality.
    if exit_price > 0 and intended_exit:
        exit_err = abs(exit_price - intended_exit)
        exit_quality = _clamp(100 - (exit_err / max(0.01, intended_exit)) * 60)
    else:
        exit_quality = 60.0
    # Timing: MFE captured (did we hold to capture favorable excursion?).
    if mfe > 0 and realized:
        execution_timing = _clamp((realized / max(0.1, mfe)) * 100) if mfe else 60.0
    else:
        execution_timing = 60.0
    # Risk control: did loss stay within adverse expectation?
    risk_control = _clamp(100 - (mae / max(0.1, expected_slippage * 10)) * 20) if mae > 0 else 80.0
    # Profit efficiency: realized vs MFE.
    profit_efficiency = _clamp((realized / max(0.1, mfe)) * 100) if mfe > 0 else 60.0
    # Management quality: presence of management actions taken.
    mgmt_actions = t.get("management_actions_taken")
    management_quality = _clamp(75 + (10 if mgmt_actions else -5))

    scores = {
        "entry_quality": _round(entry_quality),
        "exit_quality": _round(exit_quality),
        "execution_timing": _round(execution_timing),
        "slippage_quality": _round(slippage_quality),
        "spread_capture": _round(spread_capture),
        "risk_control": _round(risk_control),
        "profit_efficiency": _round(profit_efficiency),
        "management_quality": _round(management_quality),
    }
    composite = sum(_number(v) for v in scores.values()) / len(scores)
    grade = _grade(composite)

    return {
        "ok": True,
        "version": VERSION,
        "schema_version": SCHEMA_VERSION,
        "execution_grade": grade,
        "execution_score": _round(composite),
        "dimensions": scores,
        "graded_on": "EXECUTION_QUALITY_INDEPENDENT_OF_FORECAST",
        "production_effect": "NONE",
    }


def status() -> dict[str, Any]:
    return {"status": "READY", "engine": "EXECUTION_REVIEW", "version": VERSION,
            "dimensions": list(DIMENSIONS), "grades": list(GRADES),
            "read_only": True, "production_effect": "NONE"}
