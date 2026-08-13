"""engine/director/position.py — position detection hierarchy (Part 2).

APEX cannot manage a position it isn't sure exists. This resolves, in priority
order:

    1. Confirmed broker position   (E*TRADE portfolio)      -> CONFIRMED
    2. Confirmed broker order fill  (bracket entry FILLED)   -> CONFIRMED
    3. APEX confirmation-gated exec (bracket WORKING/PARTIAL)-> LIKELY
    4. Manual trader confirmation   (ACTIVE_POSITION)        -> MANUAL
    5. No confirmed position                                 -> NONE

A generated ENTER recommendation is NEVER treated as a position. The order
lifecycle stage (SIGNAL_GENERATED / ORDER_SUBMITTED / ORDER_FILLED /
POSITION_ACTIVE / POSITION_CLOSED) is surfaced so the dashboard can distinguish
"we told you to enter" from "you are in".

All inputs are injected as callables so this module has no import-time
dependency on app.py or a live broker connection; each source is wrapped in a
try/except and simply skipped if unavailable.
"""
from __future__ import annotations

import datetime as dt
import time
from typing import Any, Callable, Dict, List, Optional

from .contracts import PositionView


def _f(v: Any, d: Optional[float] = None) -> Optional[float]:
    try:
        if v is None or v == "":
            return d
        return float(v)
    except (TypeError, ValueError):
        return d


def _age_seconds(iso_or_et: Optional[str]) -> float:
    if not iso_or_et:
        return 0.0
    for parse in (
        lambda s: dt.datetime.fromisoformat(s),
        lambda s: dt.datetime.strptime(s.replace(" ET", ""), "%Y-%m-%d %H:%M:%S"),
    ):
        try:
            t = parse(iso_or_et)
            if t.tzinfo is None:
                # treat naive timestamps as UTC-ish; only used for coarse time-in-trade
                return max(0.0, time.time() - t.timestamp())
            return max(0.0, dt.datetime.now(dt.timezone.utc).timestamp() - t.timestamp())
        except Exception:
            continue
    return 0.0


def _side_from_osi(osi_key: str) -> str:
    """SPXW  260703C07485000 -> CALL. Falls back to empty."""
    if not osi_key:
        return ""
    key = osi_key.upper()
    # OSI: 6-char root, YYMMDD, C/P, 8-digit strike. Find the C/P after the date.
    for i in range(len(key) - 9, -1, -1):
        c = key[i]
        if c in ("C", "P") and i + 9 <= len(key) and key[i + 1:i + 9].isdigit():
            return "CALL" if c == "C" else "PUT"
    if "CALL" in key:
        return "CALL"
    if "PUT" in key:
        return "PUT"
    return ""


def detect_position(
    *,
    symbol: str = "SPX",
    broker_positions_provider: Optional[Callable[[], List[Dict[str, Any]]]] = None,
    open_brackets_provider: Optional[Callable[[], List[Dict[str, Any]]]] = None,
    manual_position_provider: Optional[Callable[[], Dict[str, Any]]] = None,
    current_price: Optional[float] = None,
) -> PositionView:
    """Resolve the single best position view. Never raises."""
    symbol = (symbol or "SPX").upper()

    # 1 ── broker portfolio ----------------------------------------------------
    try:
        if broker_positions_provider:
            for p in (broker_positions_provider() or []):
                qty = _f(p.get("quantity"), 0.0) or 0.0
                if qty == 0:
                    continue
                sec = str(p.get("security_type") or p.get("securityType") or "").upper()
                osi = str(p.get("osi_key") or p.get("symbol") or "")
                side = _side_from_osi(osi)
                if sec and "OPT" not in sec and side == "":
                    continue  # not an option position we manage
                pv = PositionView(
                    active=True, source="BROKER_POSITION", confidence="CONFIRMED",
                    side=side, symbol=symbol, osi_key=osi, quantity=int(abs(qty)),
                    held_qty=int(abs(qty)), entry_price=_f(p.get("cost_basis")),
                    unrealized_pnl=_f(p.get("unrealized_pnl") or p.get("market_value")),
                    order_stage="POSITION_ACTIVE",
                    notes=["Confirmed live broker portfolio position."],
                )
                return pv
    except Exception as e:  # pragma: no cover - defensive
        pass

    # 2 & 3 ── APEX bracket ----------------------------------------------------
    _working_fallback: Optional[PositionView] = None
    try:
        if open_brackets_provider:
            brackets = open_brackets_provider() or []
            # prefer filled brackets (real position) over merely working ones
            filled = [b for b in brackets if str(b.get("state", "")).upper()
                      in ("FILLED", "PARTIALLY_FILLED")]
            working = [b for b in brackets if str(b.get("state", "")).upper()
                       in ("WORKING", "SUBMITTED", "PLANNED")]
            chosen, source, conf, stage = None, "", "", ""
            if filled:
                chosen, source, conf = filled[0], "BROKER_FILL", "CONFIRMED"
                stage = "ORDER_FILLED"
            elif working:
                chosen, source, conf = working[0], "APEX_EXECUTION", "LIKELY"
                st = str(working[0].get("state", "")).upper()
                stage = "ORDER_SUBMITTED" if st in ("WORKING", "SUBMITTED") else "SIGNAL_GENERATED"
            if chosen is not None:
                entry = chosen.get("entry") or {}
                stop = chosen.get("stop") or {}
                tps = chosen.get("tps") or []
                qty = int(_f(chosen.get("quantity"), 0.0) or 0.0)
                held = int(_f(chosen.get("filled_qty"), 0.0) or 0.0) - int(_f(chosen.get("closed_qty"), 0.0) or 0.0)
                pv = PositionView(
                    active=(source == "BROKER_FILL"),
                    source=source, confidence=conf,
                    side=str(chosen.get("side", "")).upper(),
                    symbol=symbol, osi_key=str(chosen.get("osi_key", "")),
                    quantity=qty, held_qty=max(0, held),
                    entry_price=_f(entry.get("price")),
                    stop=_f(stop.get("price")),
                    target1=_f(tps[0].get("price")) if len(tps) > 0 else None,
                    target2=_f(tps[1].get("price")) if len(tps) > 1 else None,
                    target3=_f(tps[2].get("price")) if len(tps) > 2 else None,
                    opened_at=chosen.get("created_at"),
                    time_in_trade_s=_age_seconds(chosen.get("created_at")),
                    bracket_id=str(chosen.get("bracket_id", "")),
                    order_stage=stage,
                    notes=[f"APEX bracket {chosen.get('state')} (id {chosen.get('bracket_id','')})."],
                )
                if source == "BROKER_FILL":
                    return pv
                # working-only: keep looking for a manual confirmation that
                # supersedes it, but remember this as the fallback.
                _working_fallback = pv
    except Exception:
        _working_fallback = None

    # 4 ── manual confirmation -------------------------------------------------
    try:
        if manual_position_provider:
            m = manual_position_provider() or {}
            if m and str(m.get("status", "")).upper() == "OPEN" and str(m.get("side", "")).upper() in ("CALL", "PUT"):
                return PositionView(
                    active=True, source="MANUAL", confidence="MANUAL",
                    side=str(m.get("side")).upper(), symbol=str(m.get("ticker", symbol)).upper(),
                    quantity=int(_f(m.get("original_quantity"), _f(m.get("quantity"), 1.0)) or 1.0),
                    held_qty=int(_f(m.get("quantity"), 1.0) or 1.0),
                    entry_price=_f(m.get("entry_price")),
                    option_entry_price=_f(m.get("option_entry_price")),
                    option_symbol=str(m.get("option_symbol") or ""),
                    stop=_f(m.get("stop")),
                    target1=_f(m.get("target1")),
                    target2=_f(m.get("target2")),
                    opened_at=m.get("entered_at_iso") or m.get("entered_at"),
                    time_in_trade_s=_age_seconds(m.get("entered_at_iso") or m.get("entered_at")),
                    order_stage="POSITION_ACTIVE",
                    notes=["Trader-confirmed manual position."] + ([str(m.get("notes"))] if m.get("notes") else []),
                )
    except Exception:
        pass

    # 3 (fallback) ── a working (not yet filled) bracket, if nothing better ----
    if _working_fallback is not None:
        return _working_fallback

    # 5 ── nothing confirmed ---------------------------------------------------
    return PositionView(active=False, source="NONE", confidence="NONE",
                        order_stage="", notes=["No confirmed position."])
