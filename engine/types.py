"""engine/common/types.py — APEX 8.0 typed engine contracts.

Replaces loose dict[str, Any] passing between engines with
dataclasses that provide IDE autocomplete, validation, and
eliminates string-key typo bugs.

Design rules:
  - All fields have sensible defaults (engines degrade gracefully).
  - to_dict() always available for JSON serialization.
  - from_dict() for rehydrating from cached/API responses.
  - No Pydantic dependency — stdlib dataclasses only.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


# ── Base ─────────────────────────────────────────────────────────────────────

@dataclass
class EngineResult:
    """Base class for all engine outputs."""
    available:    bool  = False
    version:      str   = "8.0"
    error:        Optional[str] = None
    execution_ms: float = 0.0
    quality_flags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def unavailable(cls, reason: str) -> "EngineResult":
        return cls(available=False, error=reason, quality_flags=[f"UNAVAILABLE: {reason}"])


# ── Gamma / Dealer ────────────────────────────────────────────────────────────

@dataclass
class GammaState(EngineResult):
    regime:          str   = "NEUTRAL_GAMMA"   # POSITIVE_GAMMA | NEGATIVE_GAMMA | NEUTRAL_GAMMA
    gex_score:       float = 50.0
    net_ratio:       float = 0.0
    call_wall:       float = 0.0
    put_wall:        float = 0.0
    zero_gamma:      float = 0.0
    expected_vol:    str   = "NORMAL"
    dealer_response: str   = "NEUTRAL"
    behavior:        str   = ""


@dataclass
class DealerState(EngineResult):
    gamma_regime:       str   = "NEUTRAL_GAMMA"
    delta_bias:         str   = "NEUTRAL"        # BUYING | SELLING | NEUTRAL
    delta_confidence:   float = 50.0
    charm:              str   = "NEUTRAL"        # POSITIVE | NEGATIVE | NEUTRAL
    charm_bias:         str   = "NO_DRIFT"
    vega:               str   = "MEDIUM"         # HIGH | MEDIUM | LOW
    hedging_level:      str   = "LOW"            # HIGH | MEDIUM | LOW | NONE
    pin_probability:    float = 0.0
    momentum_probability: float = 50.0
    dealer_summary:     str   = ""


# ── Auction / Volume ──────────────────────────────────────────────────────────

@dataclass
class AuctionState(EngineResult):
    state:         str   = "UNKNOWN"
    confidence:    float = 0.0
    would_trade:   bool  = False
    poc_migration: str   = "STABLE"   # RISING | FALLING | STABLE
    acceptance:    str   = ""         # ACCEPTING | REJECTED | TESTING
    poc:           float = 0.0
    vah:           float = 0.0
    val:           float = 0.0
    vwap:          float = 0.0
    excess_detected: bool = False
    excess_type:   str   = ""
    narrative:     str   = ""


# ── Institutional Flow ────────────────────────────────────────────────────────

@dataclass
class FlowState(EngineResult):
    bias:             str   = "MIXED"    # BULLISH | BEARISH | MIXED
    conviction:       float = 50.0
    urgency:          str   = "LOW"      # HIGH | MEDIUM | LOW
    intent:           str   = "MIXED"   # BULLISH_ACCUMULATION | BEARISH_DISTRIBUTION | MIXED
    sweep_pressure:   float = 0.0
    block_conviction: float = 0.0
    split_accumulation: float = 0.0
    sweep_count:      int   = 0
    net_premium:      float = 0.0
    call_premium:     float = 0.0
    put_premium:      float = 0.0
    call_ratio_pct:   float = 50.0
    contradictions:   List[str] = field(default_factory=list)
    narrative:        str   = ""


# ── Market Drivers ────────────────────────────────────────────────────────────

@dataclass
class MarketDrivers(EngineResult):
    market_bias:      str   = "MIXED"
    leadership:       str   = "MIXED"
    leadership_label: str   = ""
    breadth:          str   = "MIXED"
    driver_score:     float = 50.0
    net_impact_pts:   float = 0.0
    interpretation:   str   = ""
    story_line:       str   = ""


# ── Volatility ────────────────────────────────────────────────────────────────

@dataclass
class VolatilityState(EngineResult):
    vix:              float = 0.0
    regime:           str   = "NORMAL"  # COMPRESSION | NORMAL | ELEVATED | EXPANSION
    iv_rank:          float = 50.0
    term_structure:   str   = "FLAT"    # CONTANGO | BACKWARDATION | FLAT
    expected_path:    str   = "STABLE"  # EXPANDING | COMPRESSING | STABLE
    dealer_vega_risk: str   = "MEDIUM"
    vol_summary:      str   = ""


# ── Risk ─────────────────────────────────────────────────────────────────────

@dataclass
class RiskState(EngineResult):
    approved:       bool  = True
    risk_note:      str   = ""
    stop:           Optional[float] = None
    target1:        Optional[float] = None
    target2:        Optional[float] = None
    risk_pts:       float = 0.0
    reward_pts:     float = 0.0
    risk_reward:    float = 0.0


# ── Execution ─────────────────────────────────────────────────────────────────

@dataclass
class ExecutionState(EngineResult):
    exec_probability: float = 0.0
    stage:            str   = "WATCH"    # WATCH | PREPARE | ARMED | EXECUTE
    stage_color:      str   = "#64748b"
    trigger_active:   bool  = False
    trigger_label:    str   = "NOT READY"
    timing:           str   = "EARLY"   # PERFECT | GOOD | EARLY | LATE | MISSED
    narrative:        str   = ""
    invalidation:     str   = ""
    why_bullets:      List[Dict[str, Any]] = field(default_factory=list)


# ── Trade Plan ────────────────────────────────────────────────────────────────

@dataclass
class TradePlan(EngineResult):
    decision:       str   = "NO_TRADE"
    side:           str   = ""    # CALL | PUT
    entry_zone:     str   = ""
    stop:           Optional[float] = None
    target1:        Optional[float] = None
    target2:        Optional[float] = None
    contract_hint:  str   = ""
    invalidation:   str   = ""
    holding_time:   str   = "5–15 min"
    readiness:      float = 0.0
    dealer_behavior_expected:  str = ""
    auction_behavior_expected: str = ""
    flow_confirmation_needed:  str = ""


# ── Canonical Institutional Context ──────────────────────────────────────────

@dataclass
class InstitutionalContext(EngineResult):
    """The single object every UI component consumes. Built by institutional_intelligence.py."""
    # Scores
    overall_score:         float = 50.0
    market_structure_score: float = 50.0
    dealer_score:          float = 50.0
    institutional_score:   float = 50.0
    execution_score:       float = 50.0
    # Bias
    institutional_bias:    str   = "NEUTRAL"
    dealer_bias:           str   = "NEUTRAL"
    auction_bias:          str   = "DEVELOPING"
    flow_bias:             str   = "MIXED"
    # Key states
    gamma_regime:          str   = "NEUTRAL_GAMMA"
    delta_bias:            str   = "NEUTRAL"
    poc_migration:         str   = "STABLE"
    acceptance:            str   = ""
    auction_state:         str   = ""
    flow_conviction:       float = 50.0
    flow_urgency:          str   = "LOW"
    # Execution
    decision_state:        str   = "NO_TRADE"
    decision_recommendation: str = ""
    ici_score:             float = 0.0
    pine_confirmed:        bool  = False
    # Narratives
    executive_summary:     str   = ""
    highest_probability_scenario: str = ""
    primary_risk:          str   = ""
    # Evidence
    evidence:              List[Dict[str, Any]] = field(default_factory=list)
    bull_signals:          int   = 0
    bear_signals:          int   = 0
    # Session
    session_state:         str   = "UNKNOWN"
