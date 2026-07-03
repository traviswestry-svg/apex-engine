"""engine/types.py — lightweight APEX 8.0 typed contracts.

These models are intentionally permissive for the 7.0.1/8.0 foundation release.
They provide stable import targets without forcing a full engine rewrite yet.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class EngineResult:
    ok: bool = True
    status: str = "OK"
    data: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    error: Optional[str] = None
    elapsed_ms: Optional[float] = None


@dataclass
class DealerState:
    gamma: Dict[str, Any] = field(default_factory=dict)
    delta: Dict[str, Any] = field(default_factory=dict)
    charm: Dict[str, Any] = field(default_factory=dict)
    vega: Dict[str, Any] = field(default_factory=dict)
    hedging_pressure: Dict[str, Any] = field(default_factory=dict)
    pin_probability: Dict[str, Any] = field(default_factory=dict)
    momentum_probability: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AuctionState:
    auction_state: Dict[str, Any] = field(default_factory=dict)
    acceptance: Dict[str, Any] = field(default_factory=dict)
    poc_migration: Dict[str, Any] = field(default_factory=dict)
    excess: Dict[str, Any] = field(default_factory=dict)
    hvbo: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FlowState:
    flow_bias: str = "MIXED"
    net_premium: float = 0.0
    call_premium: float = 0.0
    put_premium: float = 0.0
    tape_summary: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GammaState:
    regime_label: str = "MIXED_GAMMA"
    gex_score: float = 50.0
    call_wall: Optional[float] = None
    put_wall: Optional[float] = None
    zero_gamma: Optional[float] = None


@dataclass
class ExecutionState:
    execution_score: float = 0.0
    stage: str = "WATCH"
    probability: float = 0.0
    direction: str = "NEUTRAL"


@dataclass
class TradePlan:
    side: str = "NONE"
    entry: Optional[float] = None
    stop: Optional[float] = None
    targets: List[float] = field(default_factory=list)
    invalidation: Optional[float] = None
    probability: float = 0.0


@dataclass
class MarketDrivers:
    drivers: List[Dict[str, Any]] = field(default_factory=list)
    dominant_theme: str = "UNKNOWN"


@dataclass
class RiskState:
    approved: bool = False
    risk_level: str = "UNKNOWN"
    notes: List[str] = field(default_factory=list)


@dataclass
class VolatilityState:
    volatility_regime: str = "NORMAL"
    expected_vol_path: str = "STABLE"
    vix: float = 0.0


@dataclass
class InstitutionalContext:
    market_state: Dict[str, Any] = field(default_factory=dict)
    dealer: DealerState = field(default_factory=DealerState)
    auction: AuctionState = field(default_factory=AuctionState)
    flow: FlowState = field(default_factory=FlowState)
    gamma: GammaState = field(default_factory=GammaState)
    execution: ExecutionState = field(default_factory=ExecutionState)
    risk: RiskState = field(default_factory=RiskState)
    volatility: VolatilityState = field(default_factory=VolatilityState)
