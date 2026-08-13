from __future__ import annotations

import copy
import datetime as dt
import threading
from typing import Any, Dict, Iterable, List, Tuple

try:
    from engine.version import VALIDATION_VERSION
except Exception:  # pragma: no cover - safe standalone fallback
    VALIDATION_VERSION = "50.4.1_VALIDATION_CONSISTENCY_HOTFIX"

_LOCK = threading.RLock()
_LAST: Dict[str, Any] = {
    "ok": True,
    "status": "WAITING_FOR_MORNING_BRIEF",
    "version": VALIDATION_VERSION,
    "generated_at": None,
    "duration_ms": None,
    "timing": {},
    "providers": {},
    "warnings": [],
    "errors": [],
    "sections": {},
    "section_profile": None,
    "cache": {},
}

EXECUTIVE_SECTIONS: Tuple[int, ...] = (1, 2, 15, 16, 17)
FULL_SECTIONS: Tuple[int, ...] = tuple(range(1, 18))


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return str(value)


def provider_record(status: str, latency_ms: float | None = None, error: str | None = None, **extra: Any) -> Dict[str, Any]:
    row = {
        "status": status,
        "latency_ms": round(float(latency_ms), 1) if latency_ms is not None else None,
        "error": error,
    }
    row.update(extra)
    return _json_safe(row)


def _section_presence(markdown: str | None) -> Dict[str, bool]:
    text = markdown.upper() if isinstance(markdown, str) else ""
    return {str(number): f"SECTION {number}" in text for number in FULL_SECTIONS}


def _section_profile(payload: Dict[str, Any], sections: Dict[str, bool]) -> Tuple[str, Tuple[int, ...]]:
    explicit = str(payload.get("section_profile") or payload.get("brief_profile") or "").strip().upper()
    if explicit in {"FULL", "FULL_17", "INSTITUTIONAL_FULL"}:
        return "FULL_17", FULL_SECTIONS
    if explicit in {"EXECUTIVE", "EXECUTIVE_5", "COMPACT"}:
        return "EXECUTIVE_5", EXECUTIVE_SECTIONS

    # The current production brief intentionally carries the executive narrative
    # plus deterministic Sections 15-17. Presence of 15-17 without any of 3-14
    # is therefore the compact profile, not evidence of truncation.
    middle_present = any(sections[str(n)] for n in range(3, 15))
    if all(sections[str(n)] for n in EXECUTIVE_SECTIONS) and not middle_present:
        return "EXECUTIVE_5", EXECUTIVE_SECTIONS
    return "FULL_17", FULL_SECTIONS


def _numeric(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _gamma_warnings(payload: Dict[str, Any], structured: Dict[str, Any]) -> List[str]:
    warnings: List[str] = []
    spot = _numeric(structured.get("spot"))
    regime = str(structured.get("gamma_regime") or "unknown").strip().lower()
    levels = structured.get("levels") if isinstance(structured.get("levels"), list) else []
    by_kind = {
        str(row.get("kind")): _numeric(row.get("price"))
        for row in levels
        if isinstance(row, dict) and row.get("kind")
    }
    flip = by_kind.get("gamma_flip")
    zero = by_kind.get("zero_gamma")
    trigger = by_kind.get("volatility_trigger")

    if regime in {"", "unknown", "unavailable", "none"}:
        warnings.append("Dealer gamma regime unavailable; directional gamma logic is disabled")

    present = [v for v in (flip, zero, trigger) if v is not None]
    if len(present) == 3 and max(present) - min(present) < 0.01:
        warnings.append("Gamma flip, zero gamma, and volatility trigger are identical; provider provenance should be confirmed")

    if spot and flip and abs(flip - spot) >= 150.0:
        warnings.append(f"Gamma flip is {abs(flip - spot):.2f} points from spot and is contextual rather than locally actionable")
    return warnings


def _settlement_warnings(payload: Dict[str, Any]) -> List[str]:
    settlement = payload.get("settlement_normalization")
    if not isinstance(settlement, dict):
        return []
    raw = _numeric(settlement.get("raw_es_settlement"))
    normalized = _numeric(settlement.get("normalized_spx_settlement"))
    basis = _numeric(settlement.get("basis_adjustment"))
    if raw is None or normalized is None:
        return []
    expected = normalized - raw
    if basis is None or abs(expected - basis) > 0.05:
        return ["Settlement normalization metadata is inconsistent"]
    return []


def validate_payload(payload: Dict[str, Any], *, duration_ms: float | None = None) -> Dict[str, Any]:
    warnings: List[str] = []
    errors: List[str] = []
    structured = payload.get("structured") if isinstance(payload, dict) else None
    markdown = payload.get("markdown") if isinstance(payload, dict) else None

    if not isinstance(structured, dict):
        errors.append("structured payload missing")
        structured = {}
    if not isinstance(markdown, str) or not markdown.strip():
        warnings.append("Narrative markdown unavailable; deterministic output may be active")

    sections = _section_presence(markdown)
    profile, required_sections = _section_profile(payload, sections)
    missing_required = [n for n in required_sections if not sections[str(n)]]
    if missing_required:
        warnings.append("Missing required Morning Brief sections: " + ", ".join(map(str, missing_required)))

    required_keys = ("spot", "gamma_regime", "levels", "trade_map")
    for key in required_keys:
        if structured.get(key) is None:
            warnings.append(f"structured.{key} missing")

    warnings.extend(_gamma_warnings(payload, structured))
    warnings.extend(_settlement_warnings(payload))

    if duration_ms is not None and duration_ms > 30000:
        warnings.append(f"Morning Brief generation exceeded 30 seconds ({duration_ms / 1000.0:.1f}s)")

    profile_history = payload.get("profile_history") or {}
    profile_history_state = "AVAILABLE"
    if isinstance(profile_history, dict):
        prior = int(profile_history.get("prior_sessions_loaded") or 0)
        if profile_history.get("saved") and prior == 0:
            profile_history_state = "INITIALIZING"
        elif profile_history.get("saved") is False:
            profile_history_state = "DEGRADED"
            warnings.append("Profile history was not saved")

    return {
        "warnings": list(dict.fromkeys(warnings)),
        "errors": errors,
        "sections": sections,
        "section_profile": profile,
        "required_sections": [str(n) for n in required_sections],
        "missing_required_sections": [str(n) for n in missing_required],
        "profile_history_state": profile_history_state,
    }


def derive_status(errors: Iterable[str], warnings: Iterable[str]) -> str:
    if list(errors):
        return "FAILED"
    if list(warnings):
        return "DEGRADED"
    return "HEALTHY"


def record(report: Dict[str, Any]) -> Dict[str, Any]:
    safe = _json_safe(report)
    safe.setdefault("version", VALIDATION_VERSION)
    safe.setdefault("generated_at", dt.datetime.now(dt.timezone.utc).isoformat())
    with _LOCK:
        _LAST.clear()
        _LAST.update(copy.deepcopy(safe))
    return safe


def latest() -> Dict[str, Any]:
    with _LOCK:
        return copy.deepcopy(_LAST)
