"""Canonical compatibility-route registration boundary for APEX 65.5+.

This module isolates the legacy institutional roadmap registrar from ``app.py``
without changing any route paths or handler behavior.  The roadmap module still
owns its compatibility API surface; future migrations can move route families
behind this boundary incrementally.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

VERSION = "65.5"


def register_institutional_compatibility_routes(application: Any, *, last_result_provider: Optional[Callable[..., Any]] = None) -> None:
    """Delegate to the existing roadmap registrar with behavior preserved."""
    from engine.institutional_roadmap_routes import register_institutional_roadmap_routes

    register_institutional_roadmap_routes(
        application,
        last_result_provider=last_result_provider,
    )
