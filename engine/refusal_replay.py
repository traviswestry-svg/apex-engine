"""APEX 18.0.6 — Trade Refusal Replay Engine.

Deterministically grades refused 0DTE credit structures after the cash session.
The engine uses only the candidate captured at decision time and injected SPX
bars. It never reconstructs missing strikes, quotes, or intent and remains
strictly advisory/read-only with respect to broker execution.
"""
from __future__ import annotations

import datetime as dt
import json
from typing import Any, Callable, Dict, List, Optional, Tuple

from .premium_discipline import REFUSE, RefusalLedger

VERSION = "18.0.6_TRADE_REFUSAL_REPLAY"
AVOIDED_LOSS = "AVOIDED_LOSS"
AVOIDED_STOP = "AVOIDED_STOP"
MISSED_WIN = "MISSED_WIN"
NEUTRAL = "NEUTRAL"
NOT_EXECUTABLE = "NOT_EXECUTABLE"
NO_DATA = "NO_DATA"

_CREDIT = {"BULL_PUT_CREDIT_SPREAD", "BEAR_CALL_CREDIT_SPREAD", "IRON_CONDOR"}
_DEADBAND_DOLLARS = 25.0
_SETTLE_HOUR_ET = 16

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover
    ET = dt.timezone.utc


def _f(value: Any) -> Optional[float]:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _parse_ts(value: Any) -> Optional[dt.datetime]:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone.utc)
    except (TypeError, ValueError):
        return None


def _bar_ts_ms(bar: Dict[str, Any]) -> Optional[float]:
    for key in ("t", "timestamp", "ts", "time"):
        value = bar.get(key)
        number = _f(value)
        if number is not None:
            if number < 10_000_000_000:  # seconds -> ms
                number *= 1000
            return number
    return None


def _bar_price(bar: Dict[str, Any], *keys: str) -> Optional[float]:
    for key in keys:
        value = _f(bar.get(key))
        if value is not None:
            return value
    return None


def _settle_credit(strategy: str, legs: Dict[str, Any], close_px: float) -> Tuple[Optional[float], str]:
    width = _f(legs.get("width")) or 10.0
    credit = _f(legs.get("entry_credit"))
    if credit is None or credit <= 0:
        return None, "missing executable entry credit"
    if strategy == "BULL_PUT_CREDIT_SPREAD":
        short = _f(legs.get("sell_leg"))
        if short is None:
            return None, "missing short put"
        intrinsic = max(0.0, min(width, short - close_px))
        return (credit - intrinsic) * 100.0, f"close={close_px:.2f}; short_put={short:.2f}; credit={credit:.2f}"
    if strategy == "BEAR_CALL_CREDIT_SPREAD":
        short = _f(legs.get("sell_leg"))
        if short is None:
            return None, "missing short call"
        intrinsic = max(0.0, min(width, close_px - short))
        return (credit - intrinsic) * 100.0, f"close={close_px:.2f}; short_call={short:.2f}; credit={credit:.2f}"
    if strategy == "IRON_CONDOR":
        put_short = _f(legs.get("put_short"))
        call_short = _f(legs.get("call_short"))
        if put_short is None or call_short is None:
            return None, "missing condor short strikes"
        put_intrinsic = max(0.0, min(width, put_short - close_px))
        call_intrinsic = max(0.0, min(width, close_px - call_short))
        return ((credit - put_intrinsic - call_intrinsic) * 100.0,
                f"close={close_px:.2f}; shorts={put_short:.2f}/{call_short:.2f}; credit={credit:.2f}")
    return None, f"unsupported structure {strategy}"


def _path_metrics(strategy: str, legs: Dict[str, Any], bars: List[Dict[str, Any]]) -> Dict[str, Any]:
    highs = [_bar_price(b, "h", "high") for b in bars]
    lows = [_bar_price(b, "l", "low") for b in bars]
    highs = [x for x in highs if x is not None]
    lows = [x for x in lows if x is not None]
    session_high = max(highs) if highs else None
    session_low = min(lows) if lows else None
    breached = False
    breach_side = None
    breach_price = None
    if strategy == "BULL_PUT_CREDIT_SPREAD":
        short = _f(legs.get("sell_leg"))
        if short is not None and session_low is not None and session_low <= short:
            breached, breach_side, breach_price = True, "PUT", session_low
    elif strategy == "BEAR_CALL_CREDIT_SPREAD":
        short = _f(legs.get("sell_leg"))
        if short is not None and session_high is not None and session_high >= short:
            breached, breach_side, breach_price = True, "CALL", session_high
    elif strategy == "IRON_CONDOR":
        put_short = _f(legs.get("put_short")); call_short = _f(legs.get("call_short"))
        put_breach = put_short is not None and session_low is not None and session_low <= put_short
        call_breach = call_short is not None and session_high is not None and session_high >= call_short
        if put_breach or call_breach:
            breached = True
            if put_breach and call_breach:
                breach_side, breach_price = "BOTH", None
            elif put_breach:
                breach_side, breach_price = "PUT", session_low
            else:
                breach_side, breach_price = "CALL", session_high
    return {
        "short_strike_breached": breached,
        "breach_side": breach_side,
        "breach_price": breach_price,
        "session_high_after_decision": session_high,
        "session_low_after_decision": session_low,
        "bars_used": len(bars),
    }


def grade_refusal(candidate: Dict[str, Any], bars: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Grade one refused candidate from already-windowed forward bars."""
    strategy = str(candidate.get("strategy") or "").upper()
    legs = candidate.get("legs") if isinstance(candidate.get("legs"), dict) else {}
    if strategy not in _CREDIT:
        return {"outcome": NOT_EXECUTABLE, "pnl": None,
                "notes": "Refused candidate was not an executable credit structure.", "metrics": {}}
    if not bars:
        return {"outcome": NO_DATA, "pnl": None,
                "notes": "No forward bars were available for replay.", "metrics": {}}
    close_px = _bar_price(bars[-1], "c", "close")
    if close_px is None:
        return {"outcome": NO_DATA, "pnl": None,
                "notes": "Forward bars contained no settlement close.", "metrics": {}}
    pnl, detail = _settle_credit(strategy, legs, close_px)
    if pnl is None:
        return {"outcome": NOT_EXECUTABLE, "pnl": None,
                "notes": f"Counterfactual could not be priced: {detail}.", "metrics": {}}
    metrics = _path_metrics(strategy, legs, bars)
    if metrics["short_strike_breached"]:
        outcome = AVOIDED_STOP
        reason = "a short strike was touched or breached after refusal"
    elif pnl > _DEADBAND_DOLLARS:
        outcome = MISSED_WIN
        reason = "the refused structure would have expired profitably without a short-strike breach"
    elif pnl < -_DEADBAND_DOLLARS:
        outcome = AVOIDED_LOSS
        reason = "the refused structure would have settled at a loss"
    else:
        outcome = NEUTRAL
        reason = "the counterfactual result was inside the replay deadband"
    return {
        "outcome": outcome,
        "pnl": round(pnl, 2),
        "notes": f"{outcome}: {reason}; {detail}; modeled P&L {pnl:+.2f}/contract.",
        "metrics": metrics,
    }


def replay_due_refusals(
    ledger: RefusalLedger,
    get_intraday_bars: Callable[..., List[Dict[str, Any]]],
    *,
    now_et: Optional[dt.datetime] = None,
    limit: int = 300,
) -> Dict[str, Any]:
    """Grade mature, ungraded refusals and persist results idempotently."""
    now_et = now_et or dt.datetime.now(ET)
    if now_et.tzinfo is None:
        now_et = now_et.replace(tzinfo=ET)
    rows = ledger.ungraded_refusals(limit=limit)
    bars_cache: Dict[str, List[Dict[str, Any]]] = {}
    graded = deferred = 0
    outcomes: Dict[str, int] = {}

    for row in rows:
        try:
            session_date = dt.date.fromisoformat(row["session_date"])
        except (TypeError, ValueError):
            ledger.grade(row["id"], NOT_EXECUTABLE, None, "Invalid session_date; replay impossible.")
            graded += 1; outcomes[NOT_EXECUTABLE] = outcomes.get(NOT_EXECUTABLE, 0) + 1
            continue
        ready = now_et.date() > session_date or (now_et.date() == session_date and now_et.hour >= _SETTLE_HOUR_ET)
        if not ready:
            deferred += 1
            continue
        rec_utc = _parse_ts(row["ts"])
        if rec_utc is None:
            ledger.grade(row["id"], NOT_EXECUTABLE, None, "Invalid decision timestamp; replay impossible.")
            graded += 1; outcomes[NOT_EXECUTABLE] = outcomes.get(NOT_EXECUTABLE, 0) + 1
            continue
        ticker = row["ticker"] or "SPX"
        if ticker not in bars_cache:
            try:
                bars_cache[ticker] = list(get_intraday_bars(ticker, 5, 7) or [])
            except Exception:
                bars_cache[ticker] = []
        close_et = dt.datetime.combine(session_date, dt.time(_SETTLE_HOUR_ET, 0), tzinfo=ET)
        start_ms = rec_utc.timestamp() * 1000
        end_ms = close_et.astimezone(dt.timezone.utc).timestamp() * 1000
        forward = [b for b in bars_cache[ticker]
                   if _bar_ts_ms(b) is not None and start_ms <= _bar_ts_ms(b) <= end_ms]
        if not forward:
            if now_et.date() <= session_date + dt.timedelta(days=2):
                deferred += 1
                continue
            result = {"outcome": NO_DATA, "pnl": None,
                      "notes": "No settlement bars available after the two-day retry window.", "metrics": {}}
        else:
            try:
                candidate = json.loads(row["candidate_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                candidate = {}
            result = grade_refusal(candidate, forward)
        ledger.grade(row["id"], result["outcome"], result["pnl"], result["notes"], result.get("metrics"))
        graded += 1
        outcomes[result["outcome"]] = outcomes.get(result["outcome"], 0) + 1

    return {"version": VERSION, "examined": len(rows), "graded": graded,
            "deferred": deferred, "outcomes": outcomes}
