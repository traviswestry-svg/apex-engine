"""engine/flow_pl.py — APEX 9 Step 4: Theoretical Flow P/L.

Read-only analytical tracking of what an observed print *would* be worth now.

WHAT THIS IS NOT
----------------
This is **not** proof of anyone's position or profit. The tape shows transactions,
not books. We do not know whether a print opened or closed a position (no open
interest — see Step 2), whether it is one leg of a spread, whether it is hedged
elsewhere, or what the participant's net exposure is. Every payload carries:

    THEORETICAL_PL_LABEL

verbatim, and it is not optional decoration — it is the honest scope of the number.

MARKING MODEL
-------------
`entry_mark` is the **observed execution price of the print**. That is a fact, not
a model: it is what actually traded. We never had the quote at trade time, so we
do not pretend to reconstruct one.

`current_mark` comes from the live chain (`engine/options/options_data_bus.py`),
by one of five methods:

    BID           — what you'd receive selling into the bid
    ASK           — what you'd pay lifting the ask
    MIDPOINT      — (bid+ask)/2; flattering on wide spreads (see below)
    CONSERVATIVE  — DEFAULT. Marks at the side you would actually have to
                    transact against to CLOSE: a long marks to the BID, a short
                    marks to the ASK. Always the worse side, deliberately.
    THEORETICAL   — Black-Scholes from the chain's IV. Modelled, and stamped so.

Why CONSERVATIVE is the default: on a 0.05 x 5.00 market the midpoint is 2.525 —
a number no one can transact at. Midpoint marking silently manufactures paper
profit precisely where liquidity is worst, which is exactly where a trader most
needs the truth. `mark_methodology` is stamped on every record.

DIRECTION
---------
Whether a print is long or short comes from the classifier's observed
`execution_aggression` (at/above ask → LONG; at/below bid → SHORT). A midpoint
fill does not reveal the initiator, so the side is UNKNOWN and **no P/L is
computed at all** — a signed number would be a coin flip dressed as analysis.

MULTIPLIER
----------
No provider in this codebase supplies a contract multiplier. Rather than assume
100 blindly (wrong for adjusted contracts after splits/specials), it is inferred
from the provider's own arithmetic: `premium / (trade_price * contracts)`. A
non-standard result is used *and* warned about; an uninferable one falls back to
100 with a warning.

WHAT WE STILL CANNOT KNOW
-------------------------
* IV at trade time — the chain gives IV *now*, so `iv_change` is measured from
  the first observation onward, never from the print itself. Labelled as such.
* Package construction — an uncertain spread/roll is never reported as a naked
  directional position; `intent_uncertainty` from Step 3 drives an explicit
  warning instead.
* Contracts outside the chain's strike window (default ±5% of spot) have no
  quote at all and are reported unmarkable rather than estimated.
"""
from __future__ import annotations

import datetime as dt
import math
import os
from typing import Any, Dict, List, Optional, Tuple

FLOW_PL_VERSION = "9.4.0_FLOW_PL"

FLOW_PL_ENABLED = os.getenv("FLOW_PL_ENABLED", "true").lower() == "true"

THEORETICAL_PL_LABEL = (
    "Theoretical directional P/L based on observed prints; actual position "
    "structure and realized performance are unknown."
)

# ── Mark methods ───────────────────────────────────────────────────────────
BID = "bid"
ASK = "ask"
MIDPOINT = "midpoint"
CONSERVATIVE = "conservative_executable_mark"
THEORETICAL = "theoretical_value"
MARK_METHODS = (BID, ASK, MIDPOINT, CONSERVATIVE, THEORETICAL)
DEFAULT_MARK_METHOD = os.getenv("FLOW_PL_MARK_METHOD", CONSERVATIVE)

LONG = "LONG"
SHORT = "SHORT"
UNKNOWN_SIDE = "UNKNOWN"

_DEFAULT_MULTIPLIER = float(os.getenv("FLOW_PL_DEFAULT_MULTIPLIER", "100"))
_STALE_QUOTE_S = float(os.getenv("FLOW_PL_STALE_QUOTE_S", "60"))
_WIDE_SPREAD_PCT = float(os.getenv("FLOW_PL_WIDE_SPREAD_PCT", "25"))
_ILLIQUID_SCORE = float(os.getenv("FLOW_PL_ILLIQUID_SCORE", "35"))
_RISK_FREE = float(os.getenv("FLOW_PL_RISK_FREE", "0.04"))


def _f(v: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if v is None or v == "":
            return default
        x = float(v)
        if x != x or x in (float("inf"), float("-inf")):
            return default
        return x
    except (TypeError, ValueError):
        return default


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _bs_price(spot: float, strike: float, t_years: float, iv: float,
              side: str, r: float = _RISK_FREE) -> Optional[float]:
    """Black-Scholes value. Used ONLY for the THEORETICAL mark method.

    Deliberately not the default: it prices what a model thinks the contract is
    worth, not what anyone will pay for it.
    """
    if spot <= 0 or strike <= 0 or iv <= 0 or t_years <= 0:
        return None
    try:
        d1 = (math.log(spot / strike) + (r + 0.5 * iv * iv) * t_years) / (iv * math.sqrt(t_years))
        d2 = d1 - iv * math.sqrt(t_years)
        disc = math.exp(-r * t_years)
        if side == "CALL":
            return spot * _norm_cdf(d1) - strike * disc * _norm_cdf(d2)
        return strike * disc * _norm_cdf(-d2) - spot * _norm_cdf(-d1)
    except (ValueError, OverflowError, ZeroDivisionError):
        return None


def resolve_position_side(event: Dict[str, Any]) -> Tuple[str, Optional[str]]:
    """LONG / SHORT / UNKNOWN from the classifier's observed aggression.

    Returns (side, warning). UNKNOWN is not a failure — it is the correct answer
    when the tape does not reveal who initiated.
    """
    agg = str(event.get("execution_aggression") or "").upper()
    if agg in ("AGGRESSIVE_BUY", "BUY"):
        return LONG, None
    if agg in ("AGGRESSIVE_SELL", "SELL"):
        return SHORT, None
    if agg == "PASSIVE_MID":
        return UNKNOWN_SIDE, ("Midpoint fill — the initiating side is not observable, so no "
                              "directional P/L can be computed for this print.")
    return UNKNOWN_SIDE, ("Execution side is not observable; no directional P/L can be "
                          "computed for this print.")


def infer_multiplier(facts: Dict[str, Any]) -> Tuple[float, Optional[str]]:
    """Infer the contract multiplier from the provider's own premium arithmetic.

    No feed here supplies a multiplier. Assuming 100 is right for standard
    contracts and silently wrong for adjusted ones, so we derive it and say so
    when it is not 100.
    """
    px = _f(facts.get("trade_price"))
    qty = _f(facts.get("contracts"))
    prem = _f(facts.get("premium"))
    if not px or not qty or not prem or px <= 0 or qty <= 0 or prem <= 0:
        return _DEFAULT_MULTIPLIER, ("Contract multiplier not inferable from this print; "
                                     f"assuming {_DEFAULT_MULTIPLIER:g}.")
    raw = prem / (px * qty)
    for standard in (100.0, 10.0, 1000.0, 1.0):
        if abs(raw - standard) / standard < 0.02:
            if standard != 100.0:
                return standard, (f"Non-standard contract multiplier inferred ({standard:g}) — "
                                  f"likely an adjusted contract; P/L scaled accordingly.")
            return 100.0, None
    return _DEFAULT_MULTIPLIER, (f"Implied multiplier {raw:.2f} does not match a standard value; "
                                 f"falling back to {_DEFAULT_MULTIPLIER:g}. P/L may be misscaled.")


def compute_mark(contract: Optional[Dict[str, Any]], method: str, side: str, *,
                 spot: Optional[float] = None, t_years: Optional[float] = None,
                 option_side: Optional[str] = None
                 ) -> Tuple[Optional[float], str, List[str]]:
    """Resolve the current mark. Returns (mark, methodology, warnings)."""
    warnings: List[str] = []
    if not contract:
        return None, method, ["No chain quote available for this contract."]

    bid = _f(contract.get("bid"))
    ask = _f(contract.get("ask"))
    mid = _f(contract.get("mid"))
    spread_pct = _f(contract.get("spread_pct"))
    age = _f(contract.get("quote_age_seconds"))
    liq = _f(contract.get("liquidity_score"))

    if age is not None and age > _STALE_QUOTE_S:
        warnings.append(f"Stale quote — {age:.0f}s old; mark may not be executable.")
    if spread_pct is not None and spread_pct > _WIDE_SPREAD_PCT:
        warnings.append(f"Wide market ({spread_pct:.0f}% of mid) — any mark here is indicative, "
                        f"not executable.")
    if liq is not None and liq < _ILLIQUID_SCORE:
        warnings.append(f"Illiquid contract (liquidity score {liq:.0f}/100) — treat the mark "
                        f"with caution.")
    if bid is not None and bid <= 0:
        warnings.append("Zero bid — the contract cannot currently be sold; a long position "
                        "marks to zero regardless of theoretical value.")

    if method == THEORETICAL:
        iv = _f(contract.get("iv"))
        strike = _f(contract.get("strike"))
        if iv and spot and strike and t_years and option_side:
            val = _bs_price(spot, strike, t_years, iv, option_side)
            if val is not None:
                warnings.append("Theoretical mark is model-derived (Black-Scholes on chain IV), "
                                "not a price anyone has offered.")
                return round(val, 4), THEORETICAL, warnings
        warnings.append("Theoretical mark unavailable (needs IV, spot and time to expiry); "
                        "no mark produced.")
        return None, THEORETICAL, warnings

    if method == BID:
        return bid, BID, warnings
    if method == ASK:
        return ask, ASK, warnings
    if method == MIDPOINT:
        if mid is None and bid is not None and ask is not None:
            mid = round((bid + ask) / 2.0, 4)
        if spread_pct is not None and spread_pct > _WIDE_SPREAD_PCT:
            warnings.append("Midpoint on a wide market flatters the mark — no one transacts at "
                            "the middle of 0.05 x 5.00.")
        return mid, MIDPOINT, warnings

    # CONSERVATIVE (default): mark at the side you must trade against to close.
    if side == LONG:
        if bid is None:
            return None, CONSERVATIVE, warnings + ["No bid — a long position cannot be marked "
                                                   "conservatively."]
        return bid, CONSERVATIVE, warnings
    if side == SHORT:
        if ask is None:
            return None, CONSERVATIVE, warnings + ["No ask — a short position cannot be marked "
                                                   "conservatively."]
        return ask, CONSERVATIVE, warnings
    return None, CONSERVATIVE, warnings + ["Position side unknown — no conservative mark."]


def compute_event_pl(event: Dict[str, Any], contract: Optional[Dict[str, Any]], *,
                     method: str = DEFAULT_MARK_METHOD,
                     spot: Optional[float] = None,
                     entry_spot: Optional[float] = None,
                     entry_iv: Optional[float] = None,
                     t_years: Optional[float] = None) -> Dict[str, Any]:
    """Theoretical P/L for one classified print. Never raises."""
    try:
        facts = event.get("observable_facts") or {}
        side, side_warn = resolve_position_side(event)
        multiplier, mult_warn = infer_multiplier(facts)
        warnings: List[str] = [w for w in (side_warn, mult_warn) if w]

        entry_mark = _f(facts.get("trade_price"))
        qty = _f(facts.get("contracts"), 0.0) or 0.0
        opt_side = (facts.get("contract_type") or "").upper()

        base = {
            "event_id": event.get("event_id"),
            "ticker": facts.get("ticker"),
            "contract_type": opt_side,
            "strike": facts.get("strike"),
            "expiration": facts.get("expiration"),
            "entry_time_et": facts.get("time_et"),
            "position_side": side,
            "contracts": int(qty) if qty else 0,
            "multiplier": multiplier,
            "entry_mark": entry_mark,
            "entry_mark_basis": "observed execution price of the print",
            "mark_methodology": method,
            "label": THEORETICAL_PL_LABEL,
            "flow_pl_version": FLOW_PL_VERSION,
        }

        if side == UNKNOWN_SIDE:
            base.update({"current_mark": None, "estimated_pl_dollars": None,
                         "estimated_return_pct": None, "markable": False,
                         "warnings": warnings})
            return base

        current_mark, methodology, mark_warn = compute_mark(
            contract, method, side, spot=spot, t_years=t_years, option_side=opt_side)
        warnings += mark_warn
        base["mark_methodology"] = methodology

        # Quote context (reported whether or not a mark was produced).
        if contract:
            base["spread_width"] = (round(_f(contract.get("ask"), 0.0) - _f(contract.get("bid"), 0.0), 4)
                                    if contract.get("ask") is not None and contract.get("bid") is not None
                                    else None)
            base["spread_pct"] = _f(contract.get("spread_pct"))
            base["quote_freshness_seconds"] = _f(contract.get("quote_age_seconds"))
            base["liquidity_quality"] = _f(contract.get("liquidity_score"))
            base["current_iv"] = _f(contract.get("iv"))
            base["quote_source"] = contract.get("source")
        else:
            base.update({"spread_width": None, "spread_pct": None,
                         "quote_freshness_seconds": None, "liquidity_quality": None,
                         "current_iv": None, "quote_source": None})

        # Underlying move — from the spot recorded at first observation, not at
        # trade time (we never had that), so it is labelled honestly.
        if entry_spot and spot:
            base["underlying_move_since_first_observation"] = round(spot - entry_spot, 2)
        else:
            base["underlying_move_since_first_observation"] = None

        cur_iv = _f((contract or {}).get("iv"))
        if entry_iv and cur_iv:
            base["iv_change_since_first_observation"] = round(cur_iv - entry_iv, 4)
        else:
            base["iv_change_since_first_observation"] = None

        if current_mark is None or entry_mark is None or qty <= 0:
            base.update({"current_mark": current_mark, "estimated_pl_dollars": None,
                         "estimated_return_pct": None, "markable": False,
                         "warnings": warnings})
            return base

        sign = 1.0 if side == LONG else -1.0
        pl = (current_mark - entry_mark) * sign * qty * multiplier
        cost_basis = entry_mark * qty * multiplier
        ret_pct = (pl / cost_basis * 100.0) if cost_basis else None

        base.update({
            "current_mark": round(current_mark, 4),
            "estimated_pl_dollars": round(pl, 2),
            "estimated_return_pct": round(ret_pct, 2) if ret_pct is not None else None,
            "markable": True,
            "warnings": warnings,
        })
        return base
    except Exception as e:  # pragma: no cover - P/L must never break the pipeline
        return {"event_id": event.get("event_id"), "markable": False,
                "estimated_pl_dollars": None, "warnings": [f"P/L recovered from error: {e}"],
                "label": THEORETICAL_PL_LABEL, "flow_pl_version": FLOW_PL_VERSION}


def compute_cluster_pl(cluster: Dict[str, Any], member_pls: List[Dict[str, Any]]
                       ) -> Dict[str, Any]:
    """Aggregate member P/L into a cluster record, weighted by contract quantity.

    Preserves every member's entry timestamp and mark; reports both aggregate and
    member-level P/L. Refuses to present an uncertain package as a naked
    directional position.
    """
    warnings: List[str] = []
    markable = [m for m in member_pls if m.get("markable")]
    unmarkable = [m for m in member_pls if not m.get("markable")]

    total_pl = sum(_f(m.get("estimated_pl_dollars"), 0.0) or 0.0 for m in markable)
    cost = sum((_f(m.get("entry_mark"), 0.0) or 0.0) * (m.get("contracts") or 0) *
               (_f(m.get("multiplier"), 100.0) or 100.0) for m in markable)
    qty_total = sum(m.get("contracts") or 0 for m in markable)

    # Contract-weighted average entry mark (spec: weight entries by quantity).
    num = sum((_f(m.get("entry_mark"), 0.0) or 0.0) * (m.get("contracts") or 0) for m in markable)
    w_entry = round(num / qty_total, 4) if qty_total else None
    num_c = sum((_f(m.get("current_mark"), 0.0) or 0.0) * (m.get("contracts") or 0) for m in markable)
    w_current = round(num_c / qty_total, 4) if qty_total else None

    if unmarkable:
        warnings.append(
            f"{len(unmarkable)}/{len(member_pls)} member print(s) could not be marked "
            f"(no quote, unknown side, or outside the chain's strike window). Cluster P/L "
            f"covers only the marked subset and understates or overstates the whole.")

    # The package-construction warning the spec requires.
    iu = (cluster.get("intent_uncertainty") or {})
    intents = cluster.get("intent_summary") or {}
    spread_legs = intents.get("spread_leg_candidate", 0)
    rolls = intents.get("likely_roll", 0)
    package_unknown = bool(spread_legs or rolls) or (_f(iu.get("score"), 0.0) or 0.0) >= 0.4
    if package_unknown:
        warnings.append(
            "True package construction is unknown. Some member prints pair with other "
            "strikes or expirations, so this cluster may be a leg of a spread or a roll "
            "rather than a naked directional position — in which case the P/L below does "
            "not describe the participant's actual risk.")

    return {
        "cluster_id": cluster.get("cluster_id"),
        "cluster_key": cluster.get("cluster_key"),
        "ticker": cluster.get("ticker"),
        "option_type": cluster.get("option_type"),
        "expiration": cluster.get("expiration"),
        "strike_range": cluster.get("strike_range"),
        "directional_interpretation": cluster.get("directional_interpretation"),
        "member_count": len(member_pls),
        "marked_member_count": len(markable),
        "unmarked_member_count": len(unmarkable),
        "weighted_entry_mark": w_entry,
        "weighted_current_mark": w_current,
        "total_contracts_marked": qty_total,
        "cost_basis_dollars": round(cost, 2) if cost else None,
        "estimated_pl_dollars": round(total_pl, 2) if markable else None,
        "estimated_return_pct": round(total_pl / cost * 100.0, 2) if cost else None,
        "package_construction_known": not package_unknown,
        "intent_uncertainty": iu,
        "members": member_pls,
        "warnings": warnings,
        "label": THEORETICAL_PL_LABEL,
        "flow_pl_version": FLOW_PL_VERSION,
    }


def years_to_expiry(expiration: Optional[str], now: Optional[dt.datetime] = None
                    ) -> Optional[float]:
    """Fraction of a year to expiry. None if unparseable or already expired."""
    if not expiration:
        return None
    try:
        exp = dt.date.fromisoformat(str(expiration)[:10])
    except ValueError:
        return None
    today = (now or dt.datetime.now(dt.timezone.utc)).date()
    days = (exp - today).days
    if days < 0:
        return None
    # A 0DTE contract still has intraday life; floor it rather than divide by zero.
    return max(days, 0.25) / 365.0


def is_expired(expiration: Optional[str], now: Optional[dt.datetime] = None) -> bool:
    if not expiration:
        return False
    try:
        exp = dt.date.fromisoformat(str(expiration)[:10])
    except ValueError:
        return False
    return exp < (now or dt.datetime.now(dt.timezone.utc)).date()


def health() -> Dict[str, Any]:
    return {
        "enabled": FLOW_PL_ENABLED,
        "flow_pl_version": FLOW_PL_VERSION,
        "mark_methods": list(MARK_METHODS),
        "default_mark_method": DEFAULT_MARK_METHOD,
        "thresholds": {
            "stale_quote_seconds": _STALE_QUOTE_S,
            "wide_spread_pct": _WIDE_SPREAD_PCT,
            "illiquid_liquidity_score": _ILLIQUID_SCORE,
            "default_multiplier": _DEFAULT_MULTIPLIER,
            "risk_free_rate": _RISK_FREE,
        },
        "label": THEORETICAL_PL_LABEL,
        "known_limits": [
            "entry_mark is the observed print price; the quote at trade time was never available.",
            "IV and spot deltas are measured from first observation, not from the print.",
            "Midpoint marking flatters wide markets; CONSERVATIVE is the default for that reason.",
            "Contracts outside the chain's strike window (default +/-5% of spot) have no quote "
            "and are reported unmarkable rather than estimated.",
            "No feed supplies a contract multiplier; it is inferred from premium arithmetic.",
            "A midpoint-filled print has no observable side, so no P/L is computed for it.",
        ],
    }
