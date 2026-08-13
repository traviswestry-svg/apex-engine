"""APEX 18.0.1 complex options order construction and validation.

Broker-neutral, leg-based representation for single- and multi-leg strategies.
No order is submitted by this module; it only constructs and validates tickets.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, asdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

ACTIONS = {"BUY_OPEN", "SELL_OPEN", "BUY_CLOSE", "SELL_CLOSE"}
SIDES = {"CALL", "PUT"}
MAX_LEGS = 4

@dataclass(frozen=True)
class ComplexLeg:
    action: str
    side: str
    strike: float
    expiration: str
    quantity: int
    osi_key: str = ""
    display_symbol: str = ""
    bid: Optional[float] = None
    ask: Optional[float] = None
    mid: Optional[float] = None
    delta: Optional[float] = None
    iv: Optional[float] = None
    volume: Optional[int] = None
    open_interest: Optional[int] = None
    quote_age_seconds: Optional[float] = None
    source: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

@dataclass(frozen=True)
class ComplexOrderIntent:
    symbol: str
    strategy: str
    legs: Tuple[ComplexLeg, ...]
    quantity: int
    price_effect: str  # NET_CREDIT | NET_DEBIT | EVEN
    limit_price: float
    time_in_force: str = "DAY"
    order_type: str = "LIMIT"
    all_or_none: bool = False
    recommendation_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["legs"] = [x.to_dict() for x in self.legs]
        return d


def _f(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _find_contract(contracts: Iterable[Dict[str, Any]], strike: float, side: str) -> Optional[Dict[str, Any]]:
    candidates = [c for c in contracts if str(c.get("side", "")).upper() == side and _f(c.get("strike")) is not None]
    exact = [c for c in candidates if abs(float(c["strike"]) - strike) < 0.001]
    return exact[0] if exact else None


def strategy_blueprint(strategy: str, legs: Dict[str, Any]) -> List[Tuple[str, str, float]]:
    """Return (action, side, strike) tuples in broker display order."""
    s = str(strategy or "").upper()
    if s == "IRON_CONDOR":
        return [
            ("BUY_OPEN", "PUT", float(legs["put_long"])),
            ("SELL_OPEN", "PUT", float(legs["put_short"])),
            ("SELL_OPEN", "CALL", float(legs["call_short"])),
            ("BUY_OPEN", "CALL", float(legs["call_long"])),
        ]
    if s in {"PUT_CREDIT_SPREAD", "BULL_PUT_SPREAD"}:
        return [("BUY_OPEN", "PUT", float(legs["buy_leg"])), ("SELL_OPEN", "PUT", float(legs["sell_leg"]))]
    if s in {"CALL_CREDIT_SPREAD", "BEAR_CALL_SPREAD"}:
        return [("SELL_OPEN", "CALL", float(legs["sell_leg"])), ("BUY_OPEN", "CALL", float(legs["buy_leg"]))]
    if s in {"CALL_DEBIT_SPREAD", "BULL_CALL_SPREAD"}:
        return [("BUY_OPEN", "CALL", float(legs["buy_leg"])), ("SELL_OPEN", "CALL", float(legs["sell_leg"]))]
    if s in {"PUT_DEBIT_SPREAD", "BEAR_PUT_SPREAD"}:
        return [("BUY_OPEN", "PUT", float(legs["buy_leg"])), ("SELL_OPEN", "PUT", float(legs["sell_leg"]))]
    if s in {"LONG_CALL", "CALL"}:
        return [("BUY_OPEN", "CALL", float(legs.get("strike") or legs.get("buy_leg")))]
    if s in {"LONG_PUT", "PUT"}:
        return [("BUY_OPEN", "PUT", float(legs.get("strike") or legs.get("buy_leg")))]
    raise ValueError(f"Unsupported or incomplete strategy: {strategy}")


def build_ticket(*, recommendation: Dict[str, Any], expiration: str,
                 call_contracts: Sequence[Dict[str, Any]], put_contracts: Sequence[Dict[str, Any]],
                 quantity: int = 1, limit_price: Optional[float] = None,
                 now: Optional[dt.date] = None) -> Dict[str, Any]:
    strategy = str(recommendation.get("strategy") or "").upper()
    raw_legs = recommendation.get("legs") or {}
    blueprint = strategy_blueprint(strategy, raw_legs)
    qty = max(1, int(quantity or 1))
    resolved: List[ComplexLeg] = []
    errors: List[str] = []
    warnings: List[str] = []
    for action, side, strike in blueprint:
        book = call_contracts if side == "CALL" else put_contracts
        c = _find_contract(book, strike, side)
        if not c:
            errors.append(f"Unable to resolve {side} {strike:g} for {expiration}.")
            resolved.append(ComplexLeg(action, side, strike, expiration, qty))
            continue
        resolved.append(ComplexLeg(
            action=action, side=side, strike=strike, expiration=expiration, quantity=qty,
            osi_key=str(c.get("osi_key") or c.get("osiKey") or ""),
            display_symbol=str(c.get("display_symbol") or ""), bid=_f(c.get("bid")), ask=_f(c.get("ask")),
            mid=_f(c.get("mid")), delta=_f(c.get("delta")), iv=_f(c.get("iv")),
            volume=c.get("volume"), open_interest=c.get("open_interest"),
            quote_age_seconds=_f(c.get("quote_age_seconds")), source=c.get("source"),
        ))
    # executable net prices: buy legs use ask; sell legs use bid
    executable = 0.0
    midpoint = 0.0
    quote_complete = True
    for leg in resolved:
        sign = 1 if leg.action.startswith("SELL") else -1
        px = leg.bid if sign == 1 else leg.ask
        if px is None:
            quote_complete = False
        else:
            executable += sign * px
        if leg.mid is None:
            quote_complete = False
        else:
            midpoint += sign * leg.mid
        if leg.quote_age_seconds is not None and leg.quote_age_seconds > 30:
            errors.append(f"Stale quote for {leg.side} {leg.strike:g} ({leg.quote_age_seconds:.0f}s).")
    price_effect = "NET_CREDIT" if midpoint > 0 else ("NET_DEBIT" if midpoint < 0 else "EVEN")
    suggested = abs(round(midpoint if quote_complete else executable, 2))
    chosen = abs(float(limit_price)) if limit_price is not None else suggested
    if any(not leg.osi_key for leg in resolved): errors.append("One or more exact OCC/OSI contract identifiers are missing.")
    if not quote_complete: errors.append("One or more legs lack a complete executable quote.")
    today = now or dt.date.today()
    try: dte = (dt.date.fromisoformat(expiration) - today).days
    except ValueError: dte = None; errors.append("Expiration must be YYYY-MM-DD.")
    economics = calculate_economics(strategy, resolved, chosen, qty)
    ticket = ComplexOrderIntent("SPX", strategy, tuple(resolved), qty, price_effect, chosen)
    state = "ARMED_READY_FOR_PREVIEW" if not errors else "ARMED_EXECUTION_BLOCKED"
    return {
        "state": state, "ready_for_preview": not errors, "intent": ticket.to_dict(),
        "expiration": expiration, "dte": dte, "strategy_label": recommendation.get("strategy_label") or strategy.replace("_", " ").title(),
        "net_bid": round(abs(executable), 2) if quote_complete else None,
        "strategy_mid": round(abs(midpoint), 2) if quote_complete else None,
        "recommended_limit": chosen, "economics": economics,
        "errors": list(dict.fromkeys(errors)), "warnings": warnings,
    }


def calculate_economics(strategy: str, legs: Sequence[ComplexLeg], limit_price: float, quantity: int) -> Dict[str, Any]:
    multiplier = 100
    s = strategy.upper()
    max_profit = max_loss = None
    breakevens: List[float] = []
    if s == "IRON_CONDOR" and len(legs) == 4:
        put_long, put_short, call_short, call_long = [x.strike for x in legs]
        width = max(put_short-put_long, call_long-call_short)
        max_profit = limit_price * multiplier * quantity
        max_loss = max(0.0, (width-limit_price) * multiplier * quantity)
        breakevens = [round(put_short-limit_price, 2), round(call_short+limit_price, 2)]
    elif len(legs) == 2:
        width = abs(legs[1].strike-legs[0].strike)
        credit = s in {"PUT_CREDIT_SPREAD", "BULL_PUT_SPREAD", "CALL_CREDIT_SPREAD", "BEAR_CALL_SPREAD"}
        if credit:
            max_profit = limit_price*multiplier*quantity; max_loss=max(0.0,(width-limit_price)*multiplier*quantity)
        else:
            max_loss=limit_price*multiplier*quantity; max_profit=max(0.0,(width-limit_price)*multiplier*quantity)
    elif len(legs) == 1:
        max_loss = limit_price*multiplier*quantity
    return {"max_profit": None if max_profit is None else round(max_profit,2), "max_loss": None if max_loss is None else round(max_loss,2), "breakevens": breakevens, "multiplier": multiplier}


def validate_ticket(ticket: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    intent = ticket.get("intent") or ticket
    legs = intent.get("legs") or []
    if not 1 <= len(legs) <= MAX_LEGS: errors.append("Complex order must contain between 1 and 4 legs.")
    expirations = {str(x.get("expiration")) for x in legs}
    if len(expirations) != 1: errors.append("All legs must use the same expiration for this ticket.")
    for i, leg in enumerate(legs, 1):
        if leg.get("action") not in ACTIONS: errors.append(f"Leg {i} has an invalid action.")
        if leg.get("side") not in SIDES: errors.append(f"Leg {i} has an invalid option side.")
        if not leg.get("osi_key"): errors.append(f"Leg {i} is missing its OCC/OSI contract key.")
        if int(leg.get("quantity") or 0) <= 0: errors.append(f"Leg {i} quantity must be positive.")
    if float(intent.get("limit_price") or 0) <= 0: errors.append("A positive net limit price is required.")
    return errors
