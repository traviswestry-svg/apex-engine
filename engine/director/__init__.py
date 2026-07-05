"""engine/director/ — APEX Active Trade Director.

Turns the pre-entry Trade Assistant into a continuous, state-aware active
trade director for SPX 0DTE. Consumes existing engine outputs (canonical
market_state, institutional_intelligence, auction_intelligence,
dealer_positioning, strike_magnets, execution_intelligence and the live
flow snapshot). It does NOT duplicate their calculations.

Public surface:
    build_active_trade_director(context)  -> Directive (dataclass)
    register_director_routes(app, ...)    -> attaches /api/active_trade_director
    DIRECTOR_VERSION

All modules degrade gracefully: missing inputs never raise, they downgrade
confidence and annotate quality_flags. Nothing here bypasses broker
execution controls.
"""
from __future__ import annotations

DIRECTOR_VERSION = "8.0_ACTIVE_TRADE_DIRECTOR"

from .contracts import (  # noqa: E402
    DirectorContext,
    Directive,
    PositionView,
    FlowAcceleration,
    HoldLevel,
    ConflictReport,
)
from .director import build_active_trade_director, get_director  # noqa: E402
from .evaluator import backfill_outcomes, scorecard, score_directive  # noqa: E402

__all__ = [
    "DIRECTOR_VERSION",
    "DirectorContext",
    "Directive",
    "PositionView",
    "FlowAcceleration",
    "HoldLevel",
    "ConflictReport",
    "build_active_trade_director",
    "get_director",
    "backfill_outcomes",
    "scorecard",
    "score_directive",
]
