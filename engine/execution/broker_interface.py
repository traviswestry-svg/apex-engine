"""engine/execution/broker_interface.py — broker-agnostic execution contract.

Defines the standard method surface every broker adapter must implement, plus the
normalized data models APEX uses internally so no broker-specific shape leaks past
the adapter boundary. The E*TRADE adapter (engine/brokers/etrade_adapter.py) is the
first concrete implementation; a future live adapter implements the same interface.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


# ── Normalized models ─────────────────────────────────────────────────────────

@dataclass
class OptionContract:
    """A single normalized option contract (broker/data-source agnostic)."""
    symbol: str                      # underlying, e.g. "SPX"
    osi_key: str                     # OSI / OCC key, e.g. "SPXW  260703C07485000"
    display_symbol: str              # human label, e.g. "SPX Jul 3 '26 $7485 CALL"
    expiration: str                  # ISO date "YYYY-MM-DD"
    strike: float
    side: str                        # "CALL" | "PUT"
    bid: Optional[float] = None
    ask: Optional[float] = None
    mid: Optional[float] = None
    last: Optional[float] = None
    volume: Optional[int] = None
    open_interest: Optional[int] = None
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None
    iv: Optional[float] = None
    spread_pct: Optional[float] = None      # (ask-bid)/mid * 100
    liquidity_score: Optional[float] = None  # 0..100
    quote_age_seconds: Optional[float] = None
    source: Optional[str] = None            # "quantdata" | "polygon" | "massive" | "etrade"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class OrderIntent:
    """A normalized instruction to open (or add to) an option position."""
    symbol: str                      # "SPX"
    osi_key: str
    side: str                        # option side "CALL" | "PUT"
    action: str                      # "BUY_OPEN" | "SELL_CLOSE"
    quantity: int
    order_type: str = "LIMIT"        # "LIMIT" | "MARKET" | "STOP" | "STOP_LIMIT"
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    time_in_force: str = "DAY"
    price_type_note: str = ""        # free-form APEX annotation
    tag: str = ""                    # APEX bracket leg tag: ENTRY|STOP|TP1|TP2|TP3|FLATTEN

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ChangeIntent:
    """A normalized instruction to change an existing working order."""
    order_id: str
    new_limit_price: Optional[float] = None
    new_stop_price: Optional[float] = None
    new_quantity: Optional[int] = None
    tag: str = ""                    # which bracket leg this modifies

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BrokerResult:
    """Uniform wrapper for every adapter call — mirrors the API envelope."""
    ok: bool
    mode: str = "sandbox"
    data: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = dt.datetime.now(dt.timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok, "mode": self.mode, "data": self.data,
            "warnings": self.warnings, "errors": self.errors, "timestamp": self.timestamp,
        }


def envelope(ok: bool, data: Any = None, *, mode: str = "sandbox",
             warnings: Optional[List[str]] = None, errors: Optional[List[str]] = None) -> Dict[str, Any]:
    """Build the consistent API response envelope used by every trade endpoint."""
    return BrokerResult(
        ok=ok, mode=mode, data=(data if isinstance(data, dict) else ({"result": data} if data is not None else {})),
        warnings=warnings or [], errors=errors or [],
    ).to_dict()


# ── Interface ─────────────────────────────────────────────────────────────────

class BrokerInterface:
    """Standard broker surface. All broker-specific logic lives behind the adapter."""

    name: str = "base"
    mode: str = "sandbox"

    def status(self) -> BrokerResult:
        raise NotImplementedError

    def list_accounts(self) -> BrokerResult:
        raise NotImplementedError

    def get_positions(self, account_id_key: str) -> BrokerResult:
        raise NotImplementedError

    def get_option_chain(self, symbol: str, expiration: dt.date, side: str) -> BrokerResult:
        raise NotImplementedError

    def preview_order(self, order_intent: OrderIntent) -> BrokerResult:
        raise NotImplementedError

    def place_order(self, preview_id: str, order_intent: OrderIntent) -> BrokerResult:
        raise NotImplementedError

    def preview_complex_order(self, order_intent: Any) -> BrokerResult:
        raise NotImplementedError

    def place_complex_order(self, preview_id: str, order_intent: Any) -> BrokerResult:
        raise NotImplementedError

    def cancel_order(self, order_id: str) -> BrokerResult:
        raise NotImplementedError

    def preview_change_order(self, order_id: str, change_intent: ChangeIntent) -> BrokerResult:
        raise NotImplementedError

    def place_change_order(self, order_id: str, preview_id: str, change_intent: ChangeIntent) -> BrokerResult:
        raise NotImplementedError
