"""APEX 69.10.8 — canonical persistent-storage capacity policy.

Operations-only policy shared by runtime health and governed storage-retention
observability.  It never deletes data and has no trading or execution authority.
"""
from __future__ import annotations

import os
from typing import Any

VERSION = "69.10.8"
DEFAULT_WARN_FREE_PCT = 25.0
DEFAULT_CRITICAL_FREE_PCT = 15.0


def _env_float(primary: str, legacy: str, default: float) -> tuple[float, str]:
    raw = os.getenv(primary)
    source = primary
    if raw in (None, ""):
        raw = os.getenv(legacy)
        source = legacy
    if raw in (None, ""):
        return float(default), "DEFAULT"
    try:
        return float(raw), source
    except (TypeError, ValueError):
        return float(default), f"INVALID_{source}_DEFAULTED"


def policy() -> dict[str, Any]:
    warn, warn_source = _env_float("APEX_STORAGE_WARN_FREE_PCT", "APEX_DISK_WARN_FREE_PCT", DEFAULT_WARN_FREE_PCT)
    critical, critical_source = _env_float(
        "APEX_STORAGE_CRITICAL_FREE_PCT", "APEX_DISK_CRITICAL_FREE_PCT", DEFAULT_CRITICAL_FREE_PCT
    )
    parse_valid = not warn_source.startswith("INVALID_") and not critical_source.startswith("INVALID_")
    valid = parse_valid and 0.0 <= critical < warn <= 100.0
    if not valid:
        warn, critical = DEFAULT_WARN_FREE_PCT, DEFAULT_CRITICAL_FREE_PCT
    return {
        "version": VERSION,
        "warn_free_pct": float(warn),
        "critical_free_pct": float(critical),
        "configuration_valid": bool(valid),
        "warn_source": warn_source,
        "critical_source": critical_source,
        "automatic_cleanup": False,
        "decision_authority": False,
        "execution_authority": False,
    }


def classify_free_pct(free_pct: Any) -> dict[str, Any]:
    p = policy()
    try:
        free = float(free_pct)
    except (TypeError, ValueError):
        return {**p, "free_pct": None, "state": "UNKNOWN", "operator_action_required": True}
    if free <= p["critical_free_pct"]:
        state = "CRITICAL"
    elif free <= p["warn_free_pct"]:
        state = "WARNING"
    else:
        state = "PASS"
    return {
        **p,
        "free_pct": free,
        "state": state,
        "operator_action_required": state in {"WARNING", "CRITICAL"},
    }
