"""engine/execution/trade_risk_guard.py — pre-trade and pre-change risk validation.

Pure, deterministic checks (no I/O) so they're fully unit-testable. Every order and
every drag/change passes through here before any broker call. Returns a RiskDecision
with allow/deny + human-readable reasons. Fail-closed: anything unexpected denies.
"""
from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")


def _envf(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default


def _envi(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


def _envb(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() == "true"


@dataclass
class RiskLimits:
    """Configurable guard rails, all overridable by env var."""
    symbol_whitelist: tuple = ("SPX", "SPXW")
    sandbox_only: bool = True                     # ETRADE_ENABLE_TRADING flips this
    require_confirmation: bool = True
    max_contracts: int = 10
    max_risk_per_trade: float = 1000.0            # dollars
    max_daily_loss: float = 2500.0                # dollars
    no_new_trades_after_et: str = "11:30"         # HH:MM ET
    session_open_et: str = "09:30"
    session_close_et: str = "16:00"
    max_spread_pct: float = 12.0                  # reject wider than this
    max_quote_age_seconds: float = 20.0
    cooldown_seconds: int = 30

    @classmethod
    def from_env(cls) -> "RiskLimits":
        return cls(
            sandbox_only=not _envb("ETRADE_ENABLE_TRADING", False),
            require_confirmation=_envb("ETRADE_REQUIRE_CONFIRMATION", True),
            max_contracts=_envi("TRADE_MAX_CONTRACTS", 10),
            max_risk_per_trade=_envf("TRADE_MAX_RISK_PER_TRADE", 1000.0),
            max_daily_loss=_envf("TRADE_MAX_DAILY_LOSS", 2500.0),
            no_new_trades_after_et=os.getenv("TRADE_NO_NEW_AFTER_ET", "11:30"),
            max_spread_pct=_envf("TRADE_MAX_SPREAD_PCT", 12.0),
            max_quote_age_seconds=_envf("TRADE_MAX_QUOTE_AGE_SEC", 20.0),
            cooldown_seconds=_envi("TRADE_COOLDOWN_SEC", 30),
        )


@dataclass
class RiskDecision:
    allow: bool
    reasons: List[str] = field(default_factory=list)   # why denied (or warnings if allowed)
    warnings: List[str] = field(default_factory=list)
    requires_confirmation: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allow": self.allow, "reasons": self.reasons, "warnings": self.warnings,
            "requires_confirmation": self.requires_confirmation,
        }

    @classmethod
    def deny(cls, *reasons: str) -> "RiskDecision":
        return cls(allow=False, reasons=list(reasons), requires_confirmation=True)


def _hhmm_to_min(s: str) -> int:
    try:
        h, m = s.split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return 0


def _now_et_minutes(now: Optional[dt.datetime] = None) -> int:
    n = now or dt.datetime.now(EASTERN)
    if n.tzinfo is None:
        n = n.replace(tzinfo=EASTERN)
    else:
        n = n.astimezone(EASTERN)
    return n.hour * 60 + n.minute


def entry_window_policy_snapshot(*, now: Optional[dt.datetime] = None,
                                 session_state: Optional[str] = None,
                                 limits: Optional[RiskLimits] = None) -> Dict[str, Any]:
    """Return the exact decision-time entry-window policy used by the risk guard.

    APEX 69.9.7 uses this as observational provenance only.  The helper reads the
    same ``RiskLimits`` contract already consumed by ``validate_trade`` and complex
    entry validation; it does not approve an order, mutate policy, or contact a
    broker.  Supplying ``now`` makes the result deterministic and lets the evidence
    lifecycle freeze the policy against the canonical decision timestamp.
    """
    limits = limits or RiskLimits.from_env()
    raw_now = now or dt.datetime.now(EASTERN)
    if raw_now.tzinfo is None:
        local_now = raw_now.replace(tzinfo=EASTERN)
    else:
        local_now = raw_now.astimezone(EASTERN)

    cutoff = str(limits.no_new_trades_after_et or "").strip()
    cutoff_minutes = 0
    cutoff_parse_ok = False
    if cutoff:
        try:
            hh, mm = [int(x) for x in cutoff.split(":", 1)]
            cutoff_parse_ok = 0 <= hh <= 23 and 0 <= mm <= 59
            cutoff_minutes = hh * 60 + mm if cutoff_parse_ok else 0
        except Exception:
            cutoff_parse_ok = False
    cutoff_passed = (_now_et_minutes(local_now) >= cutoff_minutes) if cutoff_parse_ok else None
    market_session = str(session_state or "UNKNOWN").upper()
    session_authorized = market_session in {"MARKET_OPEN", "RTH", "REGULAR"}
    entry_window_authorized = bool(session_authorized and cutoff_passed is False)
    return {
        "schema_version": "apex.entry_window_policy_snapshot.v1",
        "source_module": "engine.execution.trade_risk_guard",
        "source_policy": "RiskLimits.no_new_trades_after_et",
        "source_environment_key": "TRADE_NO_NEW_AFTER_ET",
        "entry_cutoff_et": cutoff or None,
        "cutoff_parse_ok": cutoff_parse_ok,
        "cutoff_passed": cutoff_passed,
        "market_session": market_session,
        "market_session_authorized": session_authorized,
        "entry_window_authorized": entry_window_authorized,
        "observed_at_et": local_now.isoformat(),
        "production_effect": "NONE",
        "execution_authority": False,
    }


# ── Entry validation ──────────────────────────────────────────────────────────

def validate_entry(
    *,
    contract: Dict[str, Any],
    quantity: int,
    entry_premium: float,
    stop_premium: float,
    limits: Optional[RiskLimits] = None,
    session_state: str = "MARKET_OPEN",
    now: Optional[dt.datetime] = None,
    last_order_epoch: Optional[float] = None,
    now_epoch: Optional[float] = None,
    live_trading_enabled: bool = False,
) -> RiskDecision:
    """Validate a new entry order intent. Denies on any violation (fail-closed)."""
    limits = limits or RiskLimits.from_env()
    reasons: List[str] = []
    warnings: List[str] = []

    # SPX-only
    sym = str(contract.get("symbol", "")).upper()
    if sym not in limits.symbol_whitelist:
        reasons.append(f"Only {'/'.join(limits.symbol_whitelist)} permitted in V1 (got {sym or 'unknown'}).")

    # side — V1 supports single-leg
    side = str(contract.get("side", "")).upper()
    if side not in ("CALL", "PUT"):
        reasons.append("Unsupported or missing option side (V1 single-leg CALL/PUT only).")

    # expiration not in the past
    exp = str(contract.get("expiration", ""))
    try:
        if exp and dt.date.fromisoformat(exp) < (now or dt.datetime.now(EASTERN)).date():
            reasons.append(f"Contract expired ({exp}).")
    except Exception:
        reasons.append("Contract expiration unparseable.")

    # quote integrity
    bid, ask = contract.get("bid"), contract.get("ask")
    if bid is None or ask is None:
        reasons.append("Missing bid/ask — no order on an incomplete quote.")
    spread_pct = contract.get("spread_pct")
    if spread_pct is not None and spread_pct > limits.max_spread_pct:
        reasons.append(f"Spread {spread_pct:.1f}% exceeds max {limits.max_spread_pct:.1f}%.")
    q_age = contract.get("quote_age_seconds")
    if q_age is not None and q_age > limits.max_quote_age_seconds:
        reasons.append(f"Quote stale ({q_age:.0f}s > {limits.max_quote_age_seconds:.0f}s).")

    # quantity / risk sizing
    if quantity is None or quantity <= 0:
        reasons.append("Quantity must be a positive integer.")
    elif quantity > limits.max_contracts:
        reasons.append(f"Quantity {quantity} exceeds max {limits.max_contracts} contracts.")

    # per-trade dollar risk: (entry - stop) * 100 * qty for long options
    if entry_premium is not None and stop_premium is not None and quantity:
        per_contract_risk = max(0.0, (entry_premium - stop_premium)) * 100.0
        trade_risk = per_contract_risk * quantity
        if stop_premium >= entry_premium:
            reasons.append("Stop must be below entry premium for a long option.")
        if trade_risk > limits.max_risk_per_trade:
            reasons.append(f"Trade risk ${trade_risk:,.0f} exceeds max ${limits.max_risk_per_trade:,.0f}.")
    else:
        reasons.append("Entry and stop premium required to size risk.")

    # time window
    if session_state != "MARKET_OPEN":
        reasons.append("Market is not in RTH — no new entries.")
    else:
        mins = _now_et_minutes(now)
        if mins >= _hhmm_to_min(limits.no_new_trades_after_et):
            reasons.append(f"Past the no-new-trades cutoff ({limits.no_new_trades_after_et} ET).")
        if mins >= _hhmm_to_min(limits.session_close_et):
            reasons.append("Session closed.")

    # cooldown / duplicate
    if last_order_epoch is not None and now_epoch is not None:
        if (now_epoch - last_order_epoch) < limits.cooldown_seconds:
            reasons.append(f"Cooldown active ({limits.cooldown_seconds}s between orders).")

    # live-trading gate
    if live_trading_enabled and not _envb("ETRADE_ENABLE_TRADING", False):
        reasons.append("Live trading requested but ETRADE_ENABLE_TRADING is not true — refusing.")

    if not reasons:
        return RiskDecision(allow=True, reasons=[], warnings=warnings,
                            requires_confirmation=limits.require_confirmation)
    return RiskDecision(allow=False, reasons=reasons, warnings=warnings,
                        requires_confirmation=True)


# ── Line-drag / change validation ─────────────────────────────────────────────

def validate_line_drag(
    *,
    line: str,                       # ENTRY | STOP | BREAKEVEN | TP1 | TP2 | TP3
    new_price: float,
    entry_premium: float,
    current_premium: Optional[float],
    levels: Dict[str, float],        # current values keyed by line name
    side: str = "CALL",
    position_qty: int = 0,
    exit_qty: Optional[int] = None,
    breakeven_armed: bool = False,
    limits: Optional[RiskLimits] = None,
    allow_increase_risk: bool = False,
) -> RiskDecision:
    """Validate a dragged line before opening a change-order preview. Long-option
    semantics (premiums, not underlying): TPs are above entry, stop below entry."""
    limits = limits or RiskLimits.from_env()
    reasons: List[str] = []

    if new_price is None or new_price <= 0:
        return RiskDecision.deny("New price must be positive.")

    tp1 = levels.get("TP1"); tp2 = levels.get("TP2"); tp3 = levels.get("TP3")
    stop = levels.get("STOP")

    if line == "STOP":
        # Stop must stay below entry and below TP1 (can't cross a target).
        if new_price >= entry_premium and not allow_increase_risk:
            reasons.append("Stop cannot be at or above entry premium.")
        if tp1 is not None and new_price >= tp1:
            reasons.append("Stop cannot be dragged above TP1.")
        # Risk ceiling
        risk = max(0.0, (entry_premium - new_price)) * 100.0 * max(1, position_qty or 1)
        if risk > limits.max_risk_per_trade and not allow_increase_risk:
            reasons.append(f"New stop raises risk to ${risk:,.0f} (> ${limits.max_risk_per_trade:,.0f}).")
        # No moving stop lower after breakeven armed
        if breakeven_armed and stop is not None and new_price < stop and not allow_increase_risk:
            reasons.append("Breakeven is armed — cannot move stop lower without explicit approval.")

    elif line in ("TP1", "TP2", "TP3"):
        # Targets must be above entry for long calls/puts (premium terms).
        if new_price <= entry_premium:
            reasons.append(f"{line} cannot be at or below entry premium for a long option.")
        # Ordering TP1 < TP2 < TP3
        order = {"TP1": (None, tp2), "TP2": (tp1, tp3), "TP3": (tp2, None)}
        lo, hi = order[line]
        if lo is not None and new_price <= lo:
            reasons.append(f"{line} must be above the lower target.")
        if hi is not None and new_price >= hi:
            reasons.append(f"{line} must be below the higher target.")

    elif line == "ENTRY":
        if position_qty and position_qty > 0:
            reasons.append("Entry is locked after fill.")

    elif line == "BREAKEVEN":
        pass  # informational line; no order side effects

    # Exit quantity can never exceed held contracts
    if exit_qty is not None and position_qty is not None and exit_qty > position_qty:
        reasons.append(f"Sell-to-close qty {exit_qty} exceeds position {position_qty}.")

    if reasons:
        return RiskDecision(allow=False, reasons=reasons, requires_confirmation=True)
    return RiskDecision(allow=True, reasons=[], requires_confirmation=limits.require_confirmation)


def validate_exit_quantity(exit_qty: int, position_qty: int) -> RiskDecision:
    """Standalone guard: a sell-to-close can never exceed what's held."""
    if exit_qty is None or exit_qty <= 0:
        return RiskDecision.deny("Exit quantity must be positive.")
    if position_qty is None or position_qty <= 0:
        return RiskDecision.deny("No open position to close.")
    if exit_qty > position_qty:
        return RiskDecision.deny(f"Sell-to-close qty {exit_qty} exceeds position {position_qty}.")
    return RiskDecision(allow=True)

# ── Complex strategy entry validation ────────────────────────────────────────
def validate_complex_entry(*, intent: Any, economics: Dict[str, Any],
                           limits: Optional[RiskLimits] = None,
                           session_state: str = "MARKET_OPEN",
                           now: Optional[dt.datetime] = None,
                           last_order_epoch: Optional[float] = None,
                           now_epoch: Optional[float] = None,
                           live_trading_enabled: bool = False) -> RiskDecision:
    """Fail-closed validation for defined-risk multi-leg option entries."""
    limits = limits or RiskLimits.from_env()
    reasons: List[str] = []
    symbol = str(getattr(intent, "symbol", "") or "").upper()
    qty = int(getattr(intent, "quantity", 0) or 0)
    legs = tuple(getattr(intent, "legs", ()) or ())
    if symbol not in limits.symbol_whitelist:
        reasons.append(f"Only {'/'.join(limits.symbol_whitelist)} permitted (got {symbol or 'unknown'}).")
    if not (2 <= len(legs) <= 4):
        reasons.append("Complex entry must contain 2 to 4 option legs.")
    if qty <= 0 or qty > limits.max_contracts:
        reasons.append(f"Strategy quantity must be between 1 and {limits.max_contracts}.")
    for leg in legs:
        if not getattr(leg, "osi_key", ""):
            reasons.append("Every strategy leg requires a resolved OSI key.")
            break
        age = getattr(leg, "quote_age_seconds", None)
        if age is not None and float(age) > limits.max_quote_age_seconds:
            reasons.append(f"Strategy contains stale quote ({float(age):.0f}s > {limits.max_quote_age_seconds:.0f}s).")
            break
        if getattr(leg, "bid", None) is None or getattr(leg, "ask", None) is None:
            reasons.append("Every strategy leg requires a complete bid/ask quote.")
            break
    max_loss = (economics or {}).get("max_loss")
    if max_loss is None:
        reasons.append("Defined maximum loss is required for complex entry.")
    else:
        try:
            if float(max_loss) > limits.max_risk_per_trade:
                reasons.append(f"Strategy risk ${float(max_loss):,.0f} exceeds max ${limits.max_risk_per_trade:,.0f}.")
        except Exception:
            reasons.append("Strategy maximum loss is invalid.")
    if session_state != "MARKET_OPEN":
        reasons.append("Market is not in RTH — no new strategy entries.")
    else:
        mins = _now_et_minutes(now)
        if mins >= _hhmm_to_min(limits.no_new_trades_after_et):
            reasons.append(f"Past the no-new-trades cutoff ({limits.no_new_trades_after_et} ET).")
    if last_order_epoch is not None and now_epoch is not None and now_epoch - last_order_epoch < limits.cooldown_seconds:
        reasons.append(f"Cooldown active ({limits.cooldown_seconds}s between orders).")
    if live_trading_enabled and not _envb("ETRADE_ENABLE_TRADING", False):
        reasons.append("Live trading requested but ETRADE_ENABLE_TRADING is not true — refusing.")
    return RiskDecision(allow=not reasons, reasons=reasons, requires_confirmation=True)
