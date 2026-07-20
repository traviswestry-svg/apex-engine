"""APEX 24.4 - Multi-Timeframe Intelligence.

A hierarchical market model over eight timeframes (Weekly, Daily, 4H, 1H, 15M,
5M, 3M, 1M). It produces higher-timeframe bias, lower-timeframe confirmation, an
alignment score, trend agreement, conflict detection, and institutional
directional confidence, and exposes a compact integration signal that the
Trading Brain, Forecast Engine, Playbook Engine, Execution Intelligence, and
Portfolio Intelligence can consume (they read ``last['multi_timeframe']`` when it
is populated).

Deterministic and read-only / advisory: this module computes a directional
alignment view from per-timeframe trend inputs. It never places, modifies, or
cancels orders, resizes positions, or bypasses kill switches.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

VERSION = "24.4.0_MULTI_TIMEFRAME_INTELLIGENCE"
SCHEMA_VERSION = "apex.multi_timeframe_v244.v1"

# Canonical timeframe hierarchy with institutional weights (higher timeframes
# dominate directional bias) and tier membership.
TIMEFRAMES = ("W", "D", "4H", "1H", "15M", "5M", "3M", "1M")
WEIGHTS = {"W": 8.0, "D": 6.0, "4H": 5.0, "1H": 4.0, "15M": 3.0, "5M": 2.0, "3M": 1.5, "1M": 1.0}
HIGHER = ("W", "D", "4H")
INTERMEDIATE = ("1H", "15M")
LOWER = ("5M", "3M", "1M")

# Accepts several spellings for each timeframe key from upstream data.
_ALIASES = {
    "W": ("W", "WK", "WEEK", "WEEKLY", "1W"),
    "D": ("D", "DAY", "DAILY", "1D"),
    "4H": ("4H", "H4", "240", "240M"),
    "1H": ("1H", "H1", "60", "60M", "HOUR", "HOURLY"),
    "15M": ("15M", "M15", "15"),
    "5M": ("5M", "M5", "5"),
    "3M": ("3M", "M3", "3"),
    "1M": ("1M", "M1", "1", "MIN", "MINUTE"),
}

_DIR = {"BULLISH": 1, "BUY": 1, "LONG": 1, "UP": 1,
        "BEARISH": -1, "SELL": -1, "SHORT": -1, "DOWN": -1,
        "NEUTRAL": 0, "FLAT": 0, "MIXED": 0}


def _num(v: Any, default: float = 0.0) -> float:
    try:
        x = float(v)
        return x if x == x else default
    except Exception:
        return default


def _dir_of(value: Any) -> int:
    if isinstance(value, (int, float)):
        return 1 if value > 0 else (-1 if value < 0 else 0)
    return _DIR.get(str(value or "").strip().upper(), 0)


def _label(sign: int) -> str:
    return "BULLISH" if sign > 0 else ("BEARISH" if sign < 0 else "NEUTRAL")


def _read_timeframes(source: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Normalize per-timeframe trend inputs from a ``last``-style dict.

    Reads from ``multi_timeframe`` / ``timeframe_trends`` / ``timeframes`` (or a
    flat mapping keyed by timeframe). Each value may be a dict
    ({trend, strength}) or a bare trend token / number.
    """
    source = dict(source or {})
    raw = (source.get("multi_timeframe") or source.get("timeframe_trends")
           or source.get("timeframes") or source)
    if not isinstance(raw, Mapping):
        raw = {}
    # Build a case-insensitive lookup of provided keys.
    provided = {str(k).strip().upper(): v for k, v in raw.items()}
    result: dict[str, dict[str, Any]] = {}
    for tf in TIMEFRAMES:
        value = None
        for alias in _ALIASES[tf]:
            if alias in provided:
                value = provided[alias]
                break
        if value is None:
            result[tf] = {"available": False, "trend": "NEUTRAL", "direction": 0, "strength": 0.0}
            continue
        if isinstance(value, Mapping):
            direction = _dir_of(value.get("trend", value.get("direction")))
            strength = _num(value.get("strength"), 50.0 if direction else 0.0)
        else:
            direction = _dir_of(value)
            strength = 50.0 if direction else 0.0
        result[tf] = {"available": True, "trend": _label(direction),
                      "direction": direction, "strength": round(max(0.0, min(100.0, strength)), 2)}
    return result


def _tier_bias(tfs: Mapping[str, Mapping[str, Any]], tier: tuple) -> dict[str, Any]:
    avail = [(tf, tfs[tf]) for tf in tier if tfs.get(tf, {}).get("available")]
    if not avail:
        return {"bias": "NEUTRAL", "direction": 0, "signed": 0.0, "weight": 0.0,
                "avg_strength": 0.0, "available": 0}
    total_w = sum(WEIGHTS[tf] for tf, _ in avail)
    signed = sum(WEIGHTS[tf] * d["direction"] for tf, d in avail)
    avg_strength = round(sum(d["strength"] for _, d in avail) / len(avail), 2)
    sign = 1 if signed > 0 else (-1 if signed < 0 else 0)
    return {"bias": _label(sign), "direction": sign, "signed": round(signed, 3),
            "weight": round(total_w, 3), "avg_strength": avg_strength, "available": len(avail)}


def alignment(source: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    """Compute the full multi-timeframe alignment view."""
    tfs = _read_timeframes(source or {})
    avail = [(tf, tfs[tf]) for tf in TIMEFRAMES if tfs[tf]["available"]]
    total_w = sum(WEIGHTS[tf] for tf, _ in avail)
    signed = sum(WEIGHTS[tf] * d["direction"] for tf, d in avail)
    dominant_sign = 1 if signed > 0 else (-1 if signed < 0 else 0)
    alignment_score = round(abs(signed) / total_w * 100, 2) if total_w else 0.0
    agree_w = sum(WEIGHTS[tf] for tf, d in avail if d["direction"] == dominant_sign and dominant_sign != 0)
    trend_agreement = round(agree_w / total_w * 100, 2) if total_w else 0.0

    htf = _tier_bias(tfs, HIGHER)
    itf = _tier_bias(tfs, INTERMEDIATE)
    ltf = _tier_bias(tfs, LOWER)
    lower_confirmation = bool(htf["direction"] != 0 and ltf["direction"] == htf["direction"])

    directional_confidence = round(
        0.5 * alignment_score + 0.3 * htf["avg_strength"] + 0.2 * (100.0 if lower_confirmation else 0.0), 2)

    return {
        "ok": True, "status": "READY", "version": VERSION, "schema_version": SCHEMA_VERSION,
        "dominant_bias": _label(dominant_sign),
        "alignment_score": alignment_score,
        "trend_agreement_pct": trend_agreement,
        "higher_timeframe_bias": htf,
        "intermediate_timeframe_bias": itf,
        "lower_timeframe_bias": ltf,
        "lower_timeframe_confirmation": lower_confirmation,
        "institutional_directional_confidence": directional_confidence,
        "timeframes": tfs,
        "available_timeframes": [tf for tf, _ in avail],
        "read_only": True, "production_effect": "NONE",
    }


def conflicts(source: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    """Detect directional conflicts across the timeframe hierarchy."""
    view = alignment(source)
    tfs = view["timeframes"]
    dominant = view["dominant_bias"]
    dominant_sign = _dir_of(dominant)
    htf = view["higher_timeframe_bias"]
    ltf = view["lower_timeframe_bias"]
    found = []

    if htf["direction"] != 0 and ltf["direction"] != 0 and htf["direction"] != ltf["direction"]:
        found.append({"code": "HTF_LTF_CONFLICT", "severity": "HIGH",
                      "detail": f"Higher timeframe is {htf['bias']} while lower timeframe is {ltf['bias']}."})
    if htf["bias"] == "NEUTRAL":
        found.append({"code": "NEUTRAL_HIGHER_TIMEFRAME", "severity": "MEDIUM",
                      "detail": "Higher timeframes provide no directional edge."})
    for tf in TIMEFRAMES:
        d = tfs[tf]
        if d["available"] and dominant_sign != 0 and d["direction"] != 0 and d["direction"] != dominant_sign:
            found.append({"code": "TIMEFRAME_DISAGREEMENT", "severity": "LOW",
                          "timeframe": tf, "detail": f"{tf} is {d['trend']} against the {dominant} book."})

    return {"ok": True, "status": "READY", "version": VERSION,
            "dominant_bias": dominant, "conflict_count": len(found), "conflicts": found,
            "has_conflict": bool(found), "read_only": True, "production_effect": "NONE"}


def integration_signals(source: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    """Compact signal for consumption by Brain / Forecast / Playbook / Execution /
    Portfolio engines."""
    view = alignment(source)
    return {
        "engine": "MULTI_TIMEFRAME_INTELLIGENCE", "version": VERSION,
        "bias": view["dominant_bias"],
        "alignment_score": view["alignment_score"],
        "directional_confidence": view["institutional_directional_confidence"],
        "higher_timeframe_bias": view["higher_timeframe_bias"]["bias"],
        "lower_timeframe_confirmation": view["lower_timeframe_confirmation"],
        "consumers": ["TRADING_BRAIN", "FORECAST_ENGINE", "PLAYBOOK_ENGINE",
                      "EXECUTION_INTELLIGENCE", "PORTFOLIO_INTELLIGENCE"],
        "advisory_only": True,
    }


def build_multi_timeframe(last: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    """Mission-Control-facing payload. Safe on empty/sparse input."""
    view = alignment(last or {})
    view["conflicts"] = conflicts(last or {})["conflicts"]
    view["integration"] = integration_signals(last or {})
    return view


def status() -> dict[str, Any]:
    return {
        "status": "READY", "engine": "MULTI_TIMEFRAME_INTELLIGENCE",
        "version": VERSION, "schema_version": SCHEMA_VERSION,
        "timeframes": list(TIMEFRAMES), "weights": WEIGHTS,
        "tiers": {"higher": list(HIGHER), "intermediate": list(INTERMEDIATE), "lower": list(LOWER)},
        "integration_consumers": ["TRADING_BRAIN", "FORECAST_ENGINE", "PLAYBOOK_ENGINE",
                                  "EXECUTION_INTELLIGENCE", "PORTFOLIO_INTELLIGENCE"],
        "deterministic": True, "read_only": True, "advisory_only": True,
        "broker_order_submission_enabled": False, "production_effect": "NONE",
    }
