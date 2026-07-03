"""engine/common — APEX 8.0 shared utilities barrel.

The 8.0 refactor points engine/__init__.py and several modules at
`engine.common`. The underlying implementations live in the sibling leaf
modules (engine.types, engine.math, engine.format, engine.cache,
engine.logging); this package re-exports them under the `common` namespace
so both `from .common import X` and `from .common.<sub> import X` resolve.

Kept as a thin re-export layer so there is a single source of truth and no
duplicated logic. Leaf modules have no intra-engine imports, so importing
this package early in engine/__init__.py cannot create a cycle.
"""

from ..math import sf, clamp, pct_chg, pts_dist, pct_dist
from ..format import fmt_pts, fmt_m, fmt_pct, fmt_price
from ..cache import EngineCache
from ..logging import apex_logger, engine_timer, EngineTimer
from ..types import (
    EngineResult,
    GammaState,
    DealerState,
    AuctionState,
    FlowState,
    MarketDrivers,
    VolatilityState,
    RiskState,
    ExecutionState,
    TradePlan,
    InstitutionalContext,
)

__all__ = [
    "sf", "clamp", "pct_chg", "pts_dist", "pct_dist",
    "fmt_pts", "fmt_m", "fmt_pct", "fmt_price",
    "EngineCache", "apex_logger", "engine_timer", "EngineTimer",
    "EngineResult", "GammaState", "DealerState", "AuctionState", "FlowState",
    "MarketDrivers", "VolatilityState", "RiskState", "ExecutionState",
    "TradePlan", "InstitutionalContext",
]
