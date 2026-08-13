"""engine/premium_chain_pricing.py — APEX 7.7: price premium structures from the chain.

WHY THIS EXISTS
---------------
`premium_strategy` modelled its credit from the expected move and stamped the
output "verify on the live chain". That put the verification burden on a human at
the exact moment the number looked most authoritative — `Net credit 3.30 · POP
69% · Max profit $330` — and it was wrong by the entire premium: the real ticket
was a 0.10 DEBIT. Both call legs quoted 0.10 x 0.15, so the vertical collected
nothing, and no value of sigma recovers that. The information was never in the
model; it was in the chain.

THE CONVENTION
--------------
Executable, matching `flow_pl`'s CONSERVATIVE default:

    SELL a leg -> you receive the BID
    BUY  a leg -> you pay the ASK

Credit = sum(bid of shorts) - sum(ask of longs). Never mid. A midpoint credit is
a price nobody fills, and 0DTE wings are exactly where the mid lies most.

WHAT IT REFUSES TO DO
---------------------
Never invents a quote. If any leg is missing from the chain, or lacks a two-sided
market, the structure is UNPRICEABLE and says so. A partially-priced spread is
not a cheaper spread; it is an unknown one.
"""
from __future__ import annotations

import os
from typing import Any, Callable, Dict, List, Optional, Tuple

CHAIN_PRICING_VERSION = "7.7.0_PREMIUM_CHAIN_PRICING"

LIVE_BASIS = "live_chain_executable"
MODELED_BASIS = "modeled_from_expected_move"
UNPRICEABLE = "unpriceable_chain_unavailable"

# A short wing bidding at/below this carries no sellable premium: after paying the
# ask on the long leg, the vertical collects nothing. This is not an error — it is
# the reason a far-OTM 0DTE condor is worthless — but it must be surfaced, because
# it is precisely what the modelled path could not see. The live ticket that
# triggered this work had shorts bidding 0.10 and 0.20 against 0.15/0.25 longs.
_NO_PREMIUM_BID = float(os.getenv("PREMIUM_NO_PREMIUM_BID", "0.10"))


def _f(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        out = float(v)
        return out if out == out and abs(out) != float("inf") else None
    except (TypeError, ValueError):
        return None


class _Chain:
    """One fetch per (symbol, expiration, side), indexed by strike."""

    def __init__(self, fetcher: Optional[Callable[[str, str, str], Any]]):
        self._fetcher = fetcher
        self._cache: Dict[Tuple[str, str, str], Dict[float, Dict[str, Any]]] = {}
        self.fetches = 0
        self.errors: List[str] = []

    def quote(self, symbol: str, expiration: str, side: str,
              strike: Optional[float]) -> Optional[Dict[str, Any]]:
        if not self._fetcher or not expiration or strike is None:
            return None
        side = (side or "").upper()
        if side not in ("CALL", "PUT"):
            return None
        key = (symbol, expiration, side)
        if key not in self._cache:
            index: Dict[float, Dict[str, Any]] = {}
            try:
                self.fetches += 1
                raw = self._fetcher(symbol, expiration, side)
                if raw:
                    from .options.options_data_bus import normalize_chain
                    for c in normalize_chain(raw, symbol=symbol, source="chain"):
                        if c.side != side:
                            continue
                        d = c.to_dict()
                        if d.get("strike") is not None:
                            index[float(d["strike"])] = d
            except Exception as e:
                self.errors.append(f"{symbol} {expiration} {side}: {e}")
            self._cache[key] = index
        return self._cache[key].get(float(strike))


def _leg_price(q: Optional[Dict[str, Any]], action: str) -> Tuple[Optional[float], List[str]]:
    """Executable price for one leg. SELL -> bid, BUY -> ask."""
    warns: List[str] = []
    if q is None:
        return None, ["no quote on the chain"]
    bid, ask = _f(q.get("bid")), _f(q.get("ask"))
    if bid is None or ask is None:
        return None, ["one-sided or missing market"]
    if ask < bid:
        return None, [f"crossed market ({bid} x {ask})"]
    px = bid if action == "SELL" else ask
    if action == "SELL" and bid <= _NO_PREMIUM_BID:
        warns.append(f"short leg bids at {bid:.2f} — at or below {_NO_PREMIUM_BID:.2f}, "
                     f"so it carries no sellable premium")
    return px, warns


def price_structure(
    *,
    strategy: str,
    legs: Dict[str, Any],
    symbol: str,
    expiration: str,
    chain_fetcher: Optional[Callable[[str, str, str], Any]],
    width: float,
) -> Dict[str, Any]:
    """Price a built structure from the live chain. Never raises.

    Returns the executable credit/debit and the per-leg quotes it used, or
    `available: False` with a reason. The caller decides what to do about it —
    this module never falls back to a model on its own.
    """
    out: Dict[str, Any] = {"available": False, "pricing_basis": UNPRICEABLE,
                           "version": CHAIN_PRICING_VERSION, "warnings": [],
                           "legs_priced": []}
    try:
        if chain_fetcher is None:
            out["warnings"].append("No chain fetcher wired — structure cannot be priced.")
            return out
        if not expiration:
            out["warnings"].append("No expiration resolved — structure cannot be priced.")
            return out

        spec = _leg_spec(strategy, legs)
        if not spec:
            out["warnings"].append(f"No leg specification for strategy {strategy!r}.")
            return out

        chain = _Chain(chain_fetcher)
        priced: List[Dict[str, Any]] = []
        leg_quotes: List[Dict[str, Any]] = []
        credit = 0.0
        for action, side, strike in spec:
            q = chain.quote(symbol, expiration, side, strike)
            if q is not None:
                leg_quotes.append(q)
            px, warns = _leg_price(q, action)
            row = {"action": action, "side": side, "strike": strike, "price": px,
                   "bid": _f((q or {}).get("bid")), "ask": _f((q or {}).get("ask")),
                   "spread_pct": _f((q or {}).get("spread_pct")),
                   "quote_age_seconds": _f((q or {}).get("quote_age_seconds"))}
            priced.append(row)
            for w in warns:
                out["warnings"].append(f"{action} {strike:g}{side[0]}: {w}")
            if px is None:
                out["legs_priced"] = priced
                out["chain_fetches"] = chain.fetches
                out["warnings"].append(
                    "Structure is UNPRICEABLE: at least one leg has no executable quote. "
                    "A partially-priced spread is not a cheaper spread — it is an unknown one.")
                out["warnings"].extend(chain.errors)
                return out
            credit += px if action == "SELL" else -px

        # Quality is assessed on the EXACT legs used to price the structure, not
        # the whole chain. A structure is only as trustworthy as the four quotes
        # it was built from — a pristine chain elsewhere doesn't rescue a stale
        # short leg. This makes execution feasibility a first-class part of the
        # price, so a degraded chain cannot outrank a verified one downstream.
        out["chain_quality"] = _assess_leg_quality(leg_quotes)

        out["legs_priced"] = priced
        out["chain_fetches"] = chain.fetches
        out["available"] = True
        out["pricing_basis"] = LIVE_BASIS
        out["entry_credit"] = round(credit, 2)
        out["is_credit"] = credit > 0
        out["max_profit"] = round(max(0.0, credit) * 100.0, 0)
        out["max_loss"] = round((width - credit) * 100.0, 0)
        out["risk_reward"] = (round((credit * 100.0) / ((width - credit) * 100.0), 2)
                              if (width - credit) > 0 and credit > 0 else 0.0)
        if credit <= 0:
            out["warnings"].append(
                f"Executable pricing is a DEBIT of {abs(credit):.2f}, not a credit. This "
                f"structure cannot profit: you pay to enter and the best case is losing "
                f"the debit.")
        if chain.errors:
            out["warnings"].extend(chain.errors)
        return out
    except Exception as e:  # pragma: no cover
        out["warnings"].append(f"chain pricing recovered: {e}")
        return out


def _assess_leg_quality(leg_quotes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Grade the quotes actually used to price the structure.

    Delegates to the chain-quality gate so there is ONE definition of chain
    quality in the system, not a second private copy that drifts. Returns a
    compact summary the ranking layer can act on: grade, score, and an
    execution_confidence in [0,1] used to cap confidence and break ranking ties
    so verified-quote structures outrank degraded-quote ones.
    """
    try:
        from .chain_quality import evaluate_chain_quality
        q = evaluate_chain_quality(leg_quotes)
    except Exception as e:  # pragma: no cover
        return {"available": False, "grade": "UNKNOWN", "score": None,
                "execution_confidence": 0.5, "note": f"quality assessment recovered: {e}"}
    if not q.get("available"):
        return {"available": False, "grade": "UNKNOWN", "score": None,
                "execution_confidence": 0.5,
                "note": "No quotes available to assess execution quality."}
    score = q.get("score") or 0.0
    conf = q.get("score_confidence_pct") or 0.0
    # execution_confidence blends WHAT the score is with HOW MUCH was measurable:
    # an unmeasurable chain is not a confident 1.0, it is a discount.
    execution_confidence = round((score / 100.0) * (conf / 100.0), 3)
    return {
        "available": True,
        "grade": q.get("grade"),
        "score": score,
        "score_confidence_pct": conf,
        "gate_passed": q.get("gate_passed"),
        "execution_confidence": execution_confidence,
        "crossed_quote_count": q.get("crossed_quote_count"),
        "locked_quote_count": q.get("locked_quote_count"),
        "stale_quote_count": q.get("stale_quote_count"),
        "shape_violation_count": q.get("shape_violation_count"),
        "fresh_quote_pct": q.get("fresh_quote_pct"),
        "warnings": q.get("warnings", []),
    }


def _leg_spec(strategy: str, legs: Dict[str, Any]) -> List[Tuple[str, str, float]]:
    """(action, side, strike) for each leg of a structure."""
    g = lambda k: _f(legs.get(k))  # noqa: E731
    if strategy == "IRON_CONDOR":
        ps, pl, cs, cl = g("put_short"), g("put_long"), g("call_short"), g("call_long")
        if None in (ps, pl, cs, cl):
            return []
        return [("SELL", "PUT", ps), ("BUY", "PUT", pl),
                ("SELL", "CALL", cs), ("BUY", "CALL", cl)]
    sell, buy = g("sell_leg"), g("buy_leg")
    if sell is None or buy is None:
        return []
    if strategy in ("BULL_PUT_CREDIT_SPREAD",):
        return [("SELL", "PUT", sell), ("BUY", "PUT", buy)]
    if strategy in ("BEAR_CALL_CREDIT_SPREAD",):
        return [("SELL", "CALL", sell), ("BUY", "CALL", buy)]
    if strategy in ("DEBIT_CALL_SPREAD",):
        return [("BUY", "CALL", buy), ("SELL", "CALL", sell)]
    if strategy in ("DEBIT_PUT_SPREAD",):
        return [("BUY", "PUT", buy), ("SELL", "PUT", sell)]
    return []
