from __future__ import annotations

import copy
import datetime as dt
import threading
from typing import Any, Dict, Iterable

_LOCK = threading.RLock()
_LAST: Dict[str, Any] = {
    "ok": True,
    "status": "WAITING_FOR_MORNING_BRIEF",
    "version": "50.4.0_INSTITUTIONAL_STABILITY_VALIDATION",
    "generated_at": None,
    "duration_ms": None,
    "providers": {},
    "warnings": [],
    "errors": [],
    "sections": {},
    "cache": {},
}

def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return str(value)

def provider_record(status: str, latency_ms: float | None = None, error: str | None = None, **extra: Any) -> Dict[str, Any]:
    row = {"status": status, "latency_ms": round(float(latency_ms), 1) if latency_ms is not None else None, "error": error}
    row.update(extra)
    return _json_safe(row)

def validate_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    warnings = []
    errors = []
    structured = payload.get("structured") if isinstance(payload, dict) else None
    markdown = payload.get("markdown") if isinstance(payload, dict) else None
    if not isinstance(structured, dict):
        errors.append("structured payload missing")
    if not isinstance(markdown, str) or not markdown.strip():
        warnings.append("narrative markdown unavailable; deterministic output may be active")
    sections = {}
    for number in range(1, 18):
        marker = f"SECTION {number}"
        sections[str(number)] = bool(isinstance(markdown, str) and marker in markdown.upper())
    required = ["spot", "gamma_regime", "levels", "trade_map"]
    for key in required:
        if isinstance(structured, dict) and structured.get(key) is None:
            warnings.append(f"structured.{key} missing")
    return {"warnings": warnings, "errors": errors, "sections": sections}

def record(report: Dict[str, Any]) -> Dict[str, Any]:
    safe = _json_safe(report)
    safe.setdefault("version", "50.4.0_INSTITUTIONAL_STABILITY_VALIDATION")
    safe.setdefault("generated_at", dt.datetime.now(dt.timezone.utc).isoformat())
    with _LOCK:
        _LAST.clear(); _LAST.update(copy.deepcopy(safe))
    return safe

def latest() -> Dict[str, Any]:
    with _LOCK:
        return copy.deepcopy(_LAST)
