"""engine/director/contracts.py — typed contracts for the Active Trade Director.

stdlib dataclasses only (matches engine/types.py convention). Every field has a
default so partial inputs never break serialization. All string enums are kept as
module-level frozensets/constants so the state machine and tests share one source
of truth (no stringly-typed typos scattered across files).
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


# ── Position lifecycle states (Part 1) ───────────────────────────────────────

POSITION_STATES: frozenset = frozenset({
    "FLAT",
    "OBSERVING",
    "WATCHING_CALLS",
    "WATCHING_PUTS",
    "SCALP_READY_CALL",
    "SCALP_READY_PUT",
    "ENTER_SCALP_CALL",
    "ENTER_SCALP_PUT",
    "ENTER_CALL",
    "ENTER_PUT",
    "IN_CALL",
    "IN_PUT",
    "HOLD_CALL",
    "HOLD_PUT",
    "HOLD_FOR_TARGET",
    "HOLD_IF_LEVEL_HOLDS",
    "CAUTION",
    "PROTECT_PROFIT",
    "SCALE_OUT",
    "EXIT_FLOW_REVERSAL",
    "EXIT_LEVEL_FAILURE",
    "EXIT_TARGET_REACHED",
    "EXIT_IMMEDIATELY",
    "COOLDOWN",
    "NO_TRADE",
})

# States that mean "we currently hold an open position".
IN_POSITION_STATES: frozenset = frozenset({
    "IN_CALL", "IN_PUT", "HOLD_CALL", "HOLD_PUT",
    "HOLD_FOR_TARGET", "HOLD_IF_LEVEL_HOLDS",
    "PROTECT_PROFIT", "SCALE_OUT",
})

# States that mean "exit the current position now".
# Entry / flat directives — "get into a position" verbs. If one of these is the
# last-emitted directive while a position is actually live, the anti-churn
# debounce must NOT keep emitting it (position truth overrides hysteresis).
ENTRY_DIRECTIVES: frozenset = frozenset({
    "OBSERVE", "WATCHING_CALLS", "WATCHING_PUTS",
    "SCALP_READY_CALL", "SCALP_READY_PUT",
    "ENTER_SCALP_CALL", "ENTER_SCALP_PUT",
    "ENTER_CALL", "ENTER_PUT",
})

EXIT_STATES: frozenset = frozenset({
    "EXIT_FLOW_REVERSAL", "EXIT_LEVEL_FAILURE",
    "EXIT_TARGET_REACHED", "EXIT_IMMEDIATELY",
})

# Directives are the operator-facing action verbs (Part 3 / Part 14).
DIRECTIVES: frozenset = frozenset({
    "OBSERVE",
    "WATCHING_CALLS",
    "WATCHING_PUTS",
    "SCALP_READY_CALL",
    "SCALP_READY_PUT",
    "ENTER_SCALP_CALL",
    "ENTER_SCALP_PUT",
    "ENTER_CALL",
    "ENTER_PUT",
    "HOLD_CALL",
    "HOLD_PUT",
    "PROTECT_PROFIT",
    "SCALE_OUT_25",
    "SCALE_OUT_50",
    "SCALE_OUT_75",
    "HOLD_RUNNER",
    "EXIT_CALL_NOW",
    "EXIT_PUT_NOW",
    "EXIT_IMMEDIATELY",
    "COOLDOWN",
    "NO_TRADE",
    "STAND_DOWN",
})

# Flow acceleration classifications (Part 4).
FLOW_CLASSES: frozenset = frozenset({
    "BUYERS_ACCELERATING", "BUYERS_STEADY", "BUYERS_WEAKENING",
    "SELLERS_ACCELERATING", "SELLERS_STEADY", "SELLERS_WEAKENING",
    "FLOW_BALANCED", "FLOW_CONFLICTED",
    "BULLISH_FLOW_REVERSAL", "BEARISH_FLOW_REVERSAL",
    "FLOW_EXHAUSTION", "FLOW_UNKNOWN",
})

# Thesis classifications (Part 8).
THESIS_CLASSES: frozenset = frozenset({
    "THESIS_STRENGTHENING", "THESIS_INTACT", "THESIS_WEAKENING",
    "THESIS_CONFLICTED", "THESIS_INVALIDATED", "THESIS_NONE",
})

TRADE_TYPES: frozenset = frozenset({"SCALP", "CONVICTION", "NONE"})
URGENCY: frozenset = frozenset({"LOW", "NORMAL", "ELEVATED", "URGENT", "CRITICAL"})


def _iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


# ── Position detection view (Part 2) ─────────────────────────────────────────

@dataclass
class PositionView:
    """What APEX actually believes about the trader's position, and how it knows.

    detection sources, highest confidence first:
      BROKER_POSITION  — confirmed live broker portfolio position
      BROKER_FILL      — APEX bracket entry recorded FILLED
      APEX_EXECUTION   — APEX bracket working / partially filled
      MANUAL           — trader-confirmed manual position (ACTIVE_POSITION)
      NONE             — no confirmed position
    """
    active:          bool  = False
    source:          str   = "NONE"     # BROKER_POSITION|BROKER_FILL|APEX_EXECUTION|MANUAL|NONE
    confidence:      str   = "NONE"      # CONFIRMED|LIKELY|MANUAL|NONE
    side:            str   = ""          # CALL | PUT
    symbol:          str   = ""
    osi_key:         str   = ""
    quantity:        int   = 0
    held_qty:        int   = 0
    entry_price:     Optional[float] = None
    option_entry_price: Optional[float] = None
    option_symbol:   str   = ""
    stop:            Optional[float] = None
    target1:         Optional[float] = None
    target2:         Optional[float] = None
    target3:         Optional[float] = None
    opened_at:       Optional[str]   = None
    time_in_trade_s: float = 0.0
    unrealized_pnl:  Optional[float] = None
    bracket_id:      str   = ""
    order_stage:     str   = ""          # SIGNAL_GENERATED|ORDER_SUBMITTED|ORDER_FILLED|POSITION_ACTIVE|POSITION_CLOSED
    notes:           List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ── Flow acceleration (Part 4) ───────────────────────────────────────────────

@dataclass
class FlowAcceleration:
    available:            bool  = False
    classification:       str   = "FLOW_UNKNOWN"
    samples:              int   = 0
    window_seconds:       float = 0.0
    call_premium_velocity: float = 0.0   # premium $/min
    put_premium_velocity: float = 0.0
    net_flow_velocity:    float = 0.0
    net_flow_acceleration: float = 0.0   # velocity change / min
    flow_score_change:    float = 0.0
    order_score_change:   float = 0.0
    sweep_arrival_rate:   float = 0.0    # sweeps/min
    sweep_velocity:       float = 0.0    # change in sweep arrival rate
    buyer_dominance_change: float = 0.0
    seller_dominance_change: float = 0.0
    flow_persistence:     float = 0.0    # 0..1 fraction of aligned windows
    flow_exhaustion:      bool  = False
    flow_reversal:        str   = ""     # BULLISH | BEARISH | ""
    change_pct:           float = 0.0    # net-flow change over the window, %
    quality_flags:        List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ── Dynamic hold level (Part 6) ──────────────────────────────────────────────

@dataclass
class HoldLevel:
    available:           bool  = False
    direction:           str   = ""      # ABOVE (for CALL) | BELOW (for PUT)
    level:               Optional[float] = None
    source:              str   = ""      # DEVELOPING_POC | VWAP | SESSION_POC | VAL | VAH | ...
    strength:            str   = "LOW"   # HIGH | MEDIUM | LOW
    distance_from_price: float = 0.0
    distance_in_atr:     float = 0.0
    reason:              str   = ""
    candidates:          List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ── Conflict / veto report (Part 12) ─────────────────────────────────────────

@dataclass
class ConflictReport:
    alignment:      str   = "MIXED"      # STRONG_ALIGNMENT | MIXED | CONFLICT | VETO
    permitted_type: str   = "NONE"       # CONVICTION | SCALP | NONE
    hard_veto:      bool  = False
    veto_reasons:   List[str] = field(default_factory=list)
    conflicts:      List[str] = field(default_factory=list)
    agreements:     List[str] = field(default_factory=list)
    bull_signals:   int   = 0
    bear_signals:   int   = 0
    summary:        str   = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ── Director inputs (Part 3) ─────────────────────────────────────────────────

@dataclass
class DirectorContext:
    """Everything the Director needs, pulled from existing engine outputs.

    app.py builds this from STATE['last_result'] + the live flow snapshot +
    the position detector. The Director never fetches data itself.
    """
    symbol:                str  = "SPX"
    market_open:           bool = False
    session_state:         str  = "UNKNOWN"
    price:                 Optional[float] = None
    now_iso:               str  = field(default_factory=_iso)

    market_state:          Dict[str, Any] = field(default_factory=dict)
    institutional:         Dict[str, Any] = field(default_factory=dict)
    auction:               Dict[str, Any] = field(default_factory=dict)
    dealer:                Dict[str, Any] = field(default_factory=dict)
    strike_magnets:        Dict[str, Any] = field(default_factory=dict)
    execution:             Dict[str, Any] = field(default_factory=dict)
    flow_snapshot:         Dict[str, Any] = field(default_factory=dict)
    risk:                  Dict[str, Any] = field(default_factory=dict)
    signal:                Dict[str, Any] = field(default_factory=dict)  # last Pine signal
    position:              PositionView   = field(default_factory=PositionView)

    data_stale:            bool = False
    stale_reason:          str  = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["position"] = self.position.to_dict()
        return d


# ── Directive (Part 3 / Part 20 output) ──────────────────────────────────────

@dataclass
class Directive:
    ok:                  bool  = True
    symbol:              str   = "SPX"
    market_open:         bool  = False

    directive:           str   = "OBSERVE"
    position_state:      str   = "FLAT"
    side:                str   = ""          # CALL | PUT
    trade_type:          str   = "NONE"      # SCALP | CONVICTION | NONE
    confidence:          int   = 50
    urgency:             str   = "NORMAL"
    thesis_status:       str   = "THESIS_NONE"

    reason:              str   = ""
    reasons:             List[str] = field(default_factory=list)

    flow_state:          str   = "FLOW_UNKNOWN"
    flow_change_pct:     float = 0.0
    auction_state:       str   = ""
    poc_migration:       str   = "STABLE"
    risk_status:         str   = "CONTROLLED"

    hold_level:          Optional[float] = None
    hold_level_source:   str   = ""
    hold_level_reason:   str   = ""
    invalidation_level:  Optional[float] = None

    target_1:            Optional[float] = None
    target_2:            Optional[float] = None
    target_3:            Optional[float] = None

    next_action:         str   = ""
    next_action_trigger: str   = ""

    conditional_guidance: List[str] = field(default_factory=list)
    checklist:           List[Dict[str, Any]] = field(default_factory=list)
    conflict:            Dict[str, Any] = field(default_factory=dict)
    flow_acceleration:   Dict[str, Any] = field(default_factory=dict)
    position:            Dict[str, Any] = field(default_factory=dict)

    previous_directive:  str   = ""
    state_transition:    str   = ""
    persistence_note:    str   = ""

    quality_flags:       List[str] = field(default_factory=list)
    version:             str   = ""
    updated_at:          str   = field(default_factory=_iso)
    updated_at_et:       str   = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
