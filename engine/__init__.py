"""engine/common — APEX 8.0 shared utilities barrel.

Re-exports the shared utilities that live in the sibling leaf modules
(engine.types, engine.math, engine.format, engine.cache, engine.logging)
under the `common` namespace, so both `from engine.common import X` and
`from engine.common.<sub> import X` resolve.

Uses ABSOLUTE imports (from engine.<mod>) rather than relative (from ..<mod>)
so import resolution is identical regardless of how the package is loaded
(gunicorn app:app, direct import, or submodule import) and across Python
versions. The leaf modules have no intra-engine imports, so importing this
package early in engine/__init__.py cannot create a cycle.
"""

from engine.math import sf, clamp, pct_chg, pts_dist, pct_dist
from engine.format import fmt_pts, fmt_m, fmt_pct, fmt_price
from engine.cache import EngineCache
from engine.logging import apex_logger, engine_timer, EngineTimer
from engine.types import (
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
