"""APEX Institutional OS 8.0 engine package — Four Pillar + Dependency Scheduler."""

# ── 8.0 shared utilities (import first so engines can use them) ──────────────
# Import directly from the leaf modules using the same `from .<module> import`
# pattern used for every other engine import below (e.g. `from .gamma import`).
# The earlier `from . import common` routed through a nested `common` package
# during this package's own partial initialization, which triggered circular
# import failures on Python 3.14. Direct sibling-submodule imports avoid that.
from .math import sf, clamp
from .format import fmt_pts, fmt_m, fmt_pct, fmt_price
from .types import (
    EngineResult, DealerState, AuctionState, FlowState,
    GammaState, ExecutionState, TradePlan, MarketDrivers,
    InstitutionalContext, RiskState, VolatilityState,
)
from .cache import EngineCache
from .logging import apex_logger, engine_timer
from .scheduler import EngineScheduler

from .gamma import build_gamma_from_quantdata_response, normalize_index_level_v6
from .data_bus import build_market_state
from .diagnostics import DiagnosticsTrace
from .volume_profile import build_volume_profile, build_previous_day_profile
from .auction import build_auction_state
from .flow_tape import build_flow_tape
from .story import build_story_v3
from .trade_coach import build_trade_coach_v3
from .market_state import build_canonical_market_state
from .auction_intelligence import build_auction_intelligence
from .dealer_positioning import build_dealer_positioning
from .flow_intelligence import build_flow_intelligence_2
from .playbook import build_institutional_playbook
from .options_chain import build_options_chain_intelligence
from .volatility import build_volatility_intelligence
from .rotation import build_rotation_intelligence
from .institutional_intelligence import build_institutional_intelligence
from .market_drivers import build_market_drivers
from .strike_magnet import build_strike_magnets
from .execution_intelligence import build_execution_intelligence

__all__ = [
    "build_gamma_from_quantdata_response",
    "normalize_index_level_v6",
    "build_market_state",
    "DiagnosticsTrace",
    "build_volume_profile",
    "build_previous_day_profile",
    "build_auction_state",
    "build_flow_tape",
    "build_story_v3",
    "build_trade_coach_v3",
    "build_canonical_market_state",
    "build_auction_intelligence",
    "build_dealer_positioning",
    "build_flow_intelligence_2",
    "build_institutional_playbook",
    "build_options_chain_intelligence",
    "build_volatility_intelligence",
    "build_rotation_intelligence",
    "build_institutional_intelligence",
    "build_market_drivers",
    "build_strike_magnets",
    "build_execution_intelligence",
    # 8.0 common utilities
    "common",
    "sf", "clamp", "fmt_pts", "fmt_m", "fmt_pct", "fmt_price",
    "EngineResult", "DealerState", "AuctionState", "FlowState",
    "GammaState", "ExecutionState", "TradePlan", "MarketDrivers",
    "InstitutionalContext", "RiskState", "VolatilityState",
    "EngineCache", "apex_logger", "engine_timer",
    "EngineScheduler",
]
