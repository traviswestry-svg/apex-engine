"""APEX 50 — institutional data registry.

A small, dependency-free source-of-truth for values consumed by the Morning
Brief, Evening Recap and diagnostics.  It records value, source, timestamp,
freshness, confidence and fallback state without fabricating missing data.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional


@dataclass(frozen=True)
class DataPoint:
    key: str
    value: Any
    source: str
    observed_at: str
    confidence: float = 1.0
    fallback: bool = False
    status: str = "AVAILABLE"
    applicable: bool = True
    reason: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


class DataRegistry:
    def __init__(self, *, generated_at: Optional[datetime] = None) -> None:
        self.generated_at = generated_at or datetime.now(timezone.utc)
        self._points: Dict[str, DataPoint] = {}

    def put(self, key: str, value: Any, *, source: str, confidence: float = 1.0,
            fallback: bool = False, observed_at: Optional[datetime] = None,
            reason: Optional[str] = None, applicable: bool = True) -> DataPoint:
        missing = value is None or value == "" or value == "[FEED REQUIRED]"
        point = DataPoint(
            key=key,
            value=None if missing else value,
            source=source,
            observed_at=(observed_at or self.generated_at).astimezone(timezone.utc).isoformat(),
            confidence=max(0.0, min(1.0, float(confidence))),
            fallback=bool(fallback),
            status=("NOT_APPLICABLE" if not applicable else ("MISSING" if missing else "AVAILABLE")),
            reason=reason if (missing or not applicable) else None,
            applicable=bool(applicable),
        )
        self._points[key] = point
        return point

    def missing(self, key: str, *, source: str, reason: str) -> DataPoint:
        return self.put(key, None, source=source, confidence=0.0, reason=reason)

    def get(self, key: str) -> Optional[DataPoint]:
        return self._points.get(key)

    def values(self) -> Iterable[DataPoint]:
        return self._points.values()

    def report(self) -> dict:
        points = list(self.values())
        applicable_points = [p for p in points if p.applicable]
        total = len(applicable_points)
        available = sum(p.status == "AVAILABLE" for p in applicable_points)
        providers: Dict[str, dict] = {}
        for point in points:
            row = providers.setdefault(point.source, {"total": 0, "available": 0, "fallbacks": 0, "not_applicable": 0})
            row["not_applicable"] += int(not point.applicable)
            if point.applicable:
                row["total"] += 1
                row["available"] += int(point.status == "AVAILABLE")
            row["fallbacks"] += int(point.fallback)
        for row in providers.values():
            row["score"] = round(100.0 * row["available"] / row["total"], 1) if row["total"] else 0.0
        return {
            "version": "50.1.0_DATA_VALIDATION_DIAGNOSTICS",
            "generated_at": self.generated_at.astimezone(timezone.utc).isoformat(),
            "score": round(100.0 * available / total, 1) if total else 0.0,
            "available": available,
            "total": total,
            "missing": [p.to_dict() for p in points if p.status == "MISSING"],
            "not_applicable": [p.to_dict() for p in points if p.status == "NOT_APPLICABLE"],
            "fallbacks": [p.to_dict() for p in points if p.fallback],
            "providers": providers,
            "points": {p.key: p.to_dict() for p in points},
        }
