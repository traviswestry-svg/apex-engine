from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")


@dataclass
class DiagnosticsTrace:
    """Small serializable trace object for APEX 6.0 diagnostics mode."""

    name: str
    stages: List[Dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: dt.datetime.now(dt.timezone.utc).isoformat())
    created_at_et: str = field(default_factory=lambda: dt.datetime.now(EASTERN).strftime("%Y-%m-%d %H:%M:%S ET"))

    def add(self, stage: str, payload: Dict[str, Any]) -> None:
        self.stages.append({"stage": stage, "payload": payload})

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "created_at": self.created_at,
            "created_at_et": self.created_at_et,
            "stages": self.stages,
        }
