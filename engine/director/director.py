"""engine/director/director.py — the Active Trade Director (Part 3).

Consumes existing engine outputs (never recomputes them) and synthesises ONE
clear directive answering: what to do now, why, what level matters, what must
remain true, and what would change the decision.

Flow:
  1. Detect position (position.py)  — are we flat or in a trade?
  2. Update flow acceleration (snapshots.py)
  3. FLAT   -> pre-entry brain (conflict + scalp/conviction gating)
     IN POS -> active-management brain (thesis + hold-level + protect/scale/exit)
  4. Stabilise the raw directive (persistence.py) — hysteresis/confirm/cooldown
  5. Enforce the state machine (states.py) — never emit a contradiction
  6. Attach conditional guidance (Part 7), lifecycle checklist (Part 16),
     dynamic execution plan (Part 15)
  7. Log (store.py) + narrate (narrative.py)

Nothing here places orders or bypasses execution controls.
"""
from __future__ import annotations

import datetime as dt
import threading
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from . import DIRECTOR_VERSION
from .contracts import DirectorContext, Directive, PositionView
from .snapshots import get_flow_tracker
from .states import coerce_transition, contradicts_position, is_valid_transition
from .hold_level import build_hold_level
from .conflict import build_conflict_report
from .thesis import classify_thesis
from .lifecycle import scalp_vs_conviction, protect_profit, scale_decision, exit_decision
from .persistence import get_persistence
from .store import log_directive
from .narrative import get_narrator


_ET = ZoneInfo("America/New_York")


def _u(v: Any) -> str:
    return str(v or "").upper()


def _f(v: Any, d: Optional[float] = None) -> Optional[float]:
    try:
        if v is None or v == "":
            return d
        return float(v)
    except (TypeError, ValueError):
        return d


def _et_now() -> str:
    return dt.datetime.now(_ET).strftime("%Y-%m-%d %H:%M:%S ET")


class ActiveTradeDirector:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._last: Dict[str, Directive] = {}

    def last(self, symbol: str) -> Optional[Directive]:
        with self._lock:
            return self._last.get(symbol.upper())

    # ── main entry ─────────────────────────────────────────────────────────────
    def build(self, ctx: DirectorContext) -> Directive:
        symbol = (ctx.symbol or "SPX").upper()
        ms = ctx.market_state or {}
        ii = ctx.institutional or {}
        price = _f(ctx.price) or _f(ms.get("price"))

        tracker = get_flow_tracker()
        if ctx.flow_snapshot:
            tracker.record(symbol, ctx.flow_snapshot)
        flow_acc = tracker.compute(symbol)

        pos = ctx.position or PositionView()
        holding = pos.active and pos.side in ("CALL", "PUT")

        d = Directive(symbol=symbol, market_open=ctx.market_open, version=DIRECTOR_VERSION)
        d.updated_at_et = _et_now()
        d.flow_state = flow_acc.classification
        d.flow_change_pct = flow_acc.change_pct
        d.flow_acceleration = flow_acc.to_dict()
        d.auction_state = _u(ii.get("auction_state") or ms.get("auction_state"))
        d.poc_migration = _u(ii.get("poc_migration") or ms.get("poc_migration")) or "STABLE"
        d.position = pos.to_dict()
        if price:
            d.position.setdefault("current_price", round(price, 2))

        prev = self.last(symbol)
        d.previous_directive = prev.directive if prev else ""

        if ctx.data_stale:
            d.quality_flags.append("DATA_STALE")
        if not ctx.market_open:
            return self._finalize(symbol, self._market_closed(d, holding, pos), holding)

        if holding:
            raw = self._manage_open(d, ctx, pos, flow_acc, ms, ii, price)
        else:
            raw = self._pre_entry(d, ctx, flow_acc, ms, ii, price)

        return self._finalize(symbol, raw, holding)

    # ── FLAT: pre-entry brain ──────────────────────────────────────────────────
    def _pre_entry(self, d, ctx, flow_acc, ms, ii, price) -> Directive:
        persist = get_persistence()
        if persist.in_cooldown(ctx.symbol):
            d.directive = "COOLDOWN"; d.position_state = "COOLDOWN"
            d.confidence = 40; d.urgency = "LOW"
            d.reason = "Post-exit cooldown — no new entry yet."
            d.reasons = [d.reason, "Avoiding immediate re-entry churn after the last exit."]
            d.next_action = "OBSERVE"
            d.next_action_trigger = "Cooldown elapses and a fresh clean setup forms."
            d.checklist = self._checklist_flat(ctx, ii, flow_acc, conflict=None)
            return d

        approved = _u(ms.get("approved_side") or ii.get("institutional_bias"))
        side = "CALL" if ("CALL" in approved or approved in ("BULLISH", "POSITIVE")) else \
               ("PUT" if ("PUT" in approved or approved in ("BEARISH", "NEGATIVE")) else "")

        conflict = build_conflict_report(
            market_state=ms, institutional=ii, auction=ctx.auction, dealer=ctx.dealer,
            flow_class=flow_acc.classification, side_hint=side,
            data_stale=ctx.data_stale, market_open=ctx.market_open,
        )
        d.conflict = conflict.to_dict()

        if not side or conflict.permitted_type == "NONE":
            d.directive = "NO_TRADE" if conflict.hard_veto else "OBSERVE"
            d.position_state = "NO_TRADE" if conflict.hard_veto else "OBSERVING"
            d.confidence = 45
            d.reason = conflict.summary or "No approved side yet."
            d.reasons = [d.reason] + conflict.veto_reasons[:2]
            d.next_action = "WATCH"
            d.next_action_trigger = "An approved side and clean flow acceleration appear."
            d.checklist = self._checklist_flat(ctx, ii, flow_acc, conflict)
            return d

        hold = build_hold_level(side, ms, ctx.dealer, entry_price=_f(ms.get("entry_zone")))
        pine_fresh = bool(ms.get("signal_fresh") or (ctx.signal or {}).get("fresh_signal"))
        rr = _f((ctx.risk or {}).get("risk_reward")) or _f(ms.get("risk_reward"))

        gate = scalp_vs_conviction(
            side=side, conflict_alignment=conflict.alignment, permitted_type=conflict.permitted_type,
            flow_acc=flow_acc, execution=ctx.execution, market_state=ms, hold_level=hold,
            pine_fresh=pine_fresh, risk_reward=rr,
        )
        d.trade_type = gate["trade_type"]
        d.side = side
        self._attach_levels(d, ms, hold, side)

        if gate["approved"]:
            if gate["trade_type"] == "CONVICTION":
                d.directive = f"ENTER_{side}"; d.position_state = f"ENTER_{side}"
                bonus = conflict.bull_signals if side == "CALL" else conflict.bear_signals
                d.confidence = min(95, 70 + bonus * 3); d.urgency = "URGENT"
            else:
                d.directive = f"ENTER_SCALP_{side}"; d.position_state = f"ENTER_SCALP_{side}"
                d.confidence = 72; d.urgency = "ELEVATED"
            d.reason = f"{gate['trade_type'].title()} {side} approved — " + "; ".join(gate["reasons"][:2])
            d.reasons = gate["reasons"] + [conflict.summary]
            d.next_action = "MANAGE_POSITION_ON_FILL"
            d.next_action_trigger = "Order fills — Director switches to active management."
        else:
            ready = (side == "CALL" and _u(flow_acc.classification) == "BUYERS_ACCELERATING") or \
                    (side == "PUT" and _u(flow_acc.classification) == "SELLERS_ACCELERATING")
            if ready:
                d.directive = f"SCALP_READY_{side}"; d.position_state = f"SCALP_READY_{side}"
                d.confidence = 62; d.urgency = "ELEVATED"
                d.reason = f"Short-term {side} flow accelerating — waiting on trigger."
            else:
                d.directive = f"WATCHING_{side}S"; d.position_state = f"WATCHING_{side}S"
                d.confidence = 55; d.urgency = "NORMAL"
                d.reason = f"Institutional filter favours {side} — waiting for flow + trigger."
            d.reasons = gate["reasons"] + [conflict.summary]
            d.next_action = f"ENTER_{side}"
            d.next_action_trigger = "; ".join(gate["reasons"][:2]) or "Flow accelerates and Pine confirms."

        d.checklist = self._checklist_flat(ctx, ii, flow_acc, conflict)
        d.conditional_guidance = self._conditional_flat(d, side, hold)
        return d

    # ── IN POSITION: active-management brain ───────────────────────────────────
    def _manage_open(self, d, ctx, pos, flow_acc, ms, ii, price) -> Directive:
        side = _u(pos.side)
        d.side = side
        d.trade_type = "SCALP"
        d.position_state = f"IN_{side}"

        hold = build_hold_level(side, ms, ctx.dealer,
                                entry_price=_f(pos.entry_price) or _f(ms.get("entry_zone")))
        # Anchor/trail the hold level so a genuine break can fire level failure
        # instead of the level chasing price down.
        anchor = get_persistence().anchor_hold_level(
            ctx.symbol, computed_level=hold.level, direction=hold.direction,
            source=hold.source, price=price, holding=True,
        )
        if anchor.get("level") is not None:
            hold.available = True
            hold.level = anchor["level"]
            hold.source = anchor["source"] or hold.source
            hold.direction = anchor["direction"] or hold.direction
            if price:
                hold.distance_from_price = round((hold.level - price), 2)
            if anchor.get("trailed"):
                hold.reason = f"Trailed hold {hold.direction.lower()} {hold.level} ({hold.source})."
        self._attach_levels(d, ms, hold, side, position=pos)

        thesis_status, thesis_score, thesis_ev = classify_thesis(
            side=side, market_state=ms, institutional=ii, flow_acc=flow_acc,
            hold_level=hold, time_in_trade_s=pos.time_in_trade_s,
        )
        d.thesis_status = thesis_status
        d.confidence = int(max(20, min(97, thesis_score)))

        ex = exit_decision(side=side, thesis_status=thesis_status, market_state=ms,
                           flow_acc=flow_acc, hold_level=hold, position=pos.to_dict())
        scale = scale_decision(side=side, market_state=ms, flow_acc=flow_acc,
                               position=pos.to_dict(), time_in_trade_s=pos.time_in_trade_s)
        protect = protect_profit(side=side, market_state=ms, flow_acc=flow_acc, hold_level=hold,
                                 position=pos.to_dict(), time_in_trade_s=pos.time_in_trade_s)

        if ex["exit"]:
            d.directive = "EXIT_CALL_NOW" if side == "CALL" else "EXIT_PUT_NOW"
            if ex["kind"] == "EXIT_FLOW_REVERSAL":
                d.position_state = "EXIT_FLOW_REVERSAL"
            elif ex["kind"] == "EXIT_LEVEL_FAILURE":
                d.position_state = "EXIT_LEVEL_FAILURE"
            elif ex["kind"] == "EXIT_TARGET":
                d.position_state = "EXIT_TARGET_REACHED"; d.directive = "SCALE_OUT_75"
            else:
                d.position_state = "EXIT_IMMEDIATELY"; d.directive = "EXIT_IMMEDIATELY"
            d.urgency = ex["urgency"]
            d.reason = "; ".join(ex["reasons"][:2]) or "Exit condition met."
            d.reasons = ex["reasons"] + thesis_ev[:2]
            d.next_action = "FLATTEN_OR_SCALE_REMAINDER"
            d.next_action_trigger = "Confirm exit fill; Director moves to cooldown."
            setattr(d, "_exit_signals", {
                "flow_reversal": ex["kind"] == "EXIT_FLOW_REVERSAL",
                "level_failure": ex["kind"] == "EXIT_LEVEL_FAILURE",
                "emergency": ex["urgency"] == "CRITICAL",
            })
        elif scale["action"] in ("SCALE_OUT_25", "SCALE_OUT_50", "SCALE_OUT_75"):
            d.directive = scale["action"]; d.position_state = "SCALE_OUT"; d.urgency = "ELEVATED"
            d.reason = "; ".join(scale["reasons"][:2])
            d.reasons = scale["reasons"] + thesis_ev[:2]
            d.next_action = "HOLD_RUNNER" if scale["action"] != "SCALE_OUT_75" else "EXIT_REMAINDER"
            d.next_action_trigger = "Runner loses hold level or flow reverses."
        elif protect["trigger"]:
            d.directive = "PROTECT_PROFIT"; d.position_state = "PROTECT_PROFIT"; d.urgency = "ELEVATED"
            g = protect["guidance"].replace("_", " ").title()
            d.reason = f"Trade working but weakening — {g}. " + "; ".join(protect["reasons"][:2])
            d.reasons = protect["reasons"] + thesis_ev[:2]
            d.next_action = protect["guidance"]
            d.next_action_trigger = "Flow acceleration falls further or hold level is tested."
        else:
            d.directive = "HOLD_CALL" if side == "CALL" else "HOLD_PUT"
            d.position_state = "HOLD_IF_LEVEL_HOLDS" if hold.available else f"HOLD_{side}"
            d.urgency = "NORMAL" if thesis_status in ("THESIS_STRENGTHENING", "THESIS_INTACT") else "ELEVATED"
            d.reason = self._hold_reason(side, flow_acc, d.poc_migration, hold, thesis_status)
            d.reasons = thesis_ev or [d.reason]
            d.next_action = "PROTECT_PROFIT"
            d.next_action_trigger = "Flow acceleration weakens near Target 1 or price tests the hold level."

        d.risk_status = self._risk_status(thesis_status, ms)
        d.checklist = self._checklist_open(pos, ms, ii, flow_acc, hold, thesis_status)
        d.conditional_guidance = self._conditional_open(d, side, hold, flow_acc)
        return d

    # ── finalize ────────────────────────────────────────────────────────────────
    def _finalize(self, symbol, d, holding) -> Directive:
        persist = get_persistence()
        if not holding:
            persist.anchor_hold_level(symbol, computed_level=None, direction="",
                                      source="", price=None, holding=False)
        exit_signals = getattr(d, "_exit_signals", {})

        has_call = holding and d.side == "CALL"
        has_put = holding and d.side == "PUT"
        if contradicts_position(d.position_state, has_call, has_put):
            d.quality_flags.append(f"COERCED: {d.position_state} contradicted position")
            safe, _ = coerce_transition(f"IN_{d.side}" if holding else "FLAT", d.position_state)
            d.position_state = safe

        stab = persist.stabilize(
            symbol, proposed_directive=d.directive, proposed_state=d.position_state,
            holding=holding, exit_signals=exit_signals,
        )
        prev = self.last(symbol)
        prev_state = prev.position_state if prev else "FLAT"

        if stab["directive"] != d.directive:
            d.directive = stab["directive"]
            d.position_state = stab["state"]
        d.persistence_note = stab["note"]
        d.previous_directive = stab.get("previous") or d.previous_directive

        legal = is_valid_transition(prev_state, d.position_state)
        d.state_transition = f"{prev_state} -> {d.position_state}" + ("" if legal else " (coerced)")

        d.updated_at = dt.datetime.now(dt.timezone.utc).isoformat()
        d.updated_at_et = _et_now()

        payload = d.to_dict()
        payload.pop("_exit_signals", None)
        get_narrator().observe(symbol, payload)
        log_directive(payload)

        with self._lock:
            self._last[symbol] = d
        return d

    # ── helpers ─────────────────────────────────────────────────────────────────
    def _attach_levels(self, d, ms, hold, side, position=None) -> None:
        if hold.available:
            d.hold_level = hold.level
            d.hold_level_source = hold.source
            d.hold_level_reason = hold.reason
            atr_buf = max(0.25, abs(hold.distance_from_price) * 0.15)
            if hold.direction == "ABOVE" and hold.level:
                d.invalidation_level = round(hold.level - atr_buf, 2)
            elif hold.level:
                d.invalidation_level = round(hold.level + atr_buf, 2)
        if position and (position.target1 or position.target2):
            d.target_1, d.target_2, d.target_3 = position.target1, position.target2, position.target3
        else:
            d.target_1 = _f(ms.get("target1"))
            d.target_2 = _f(ms.get("target2"))

    def _hold_reason(self, side, flow_acc, poc, hold, thesis) -> str:
        bits = [_u(flow_acc.classification).replace("_", " ").title()]
        if poc in ("RISING", "FALLING"):
            bits.append(f"POC {poc.lower()}")
        if hold.available:
            bits.append(f"hold {hold.direction.lower()} {hold.level}")
        return " • ".join(bits)

    def _risk_status(self, thesis, ms) -> str:
        if thesis == "THESIS_INVALIDATED":
            return "BREACHED"
        if thesis in ("THESIS_WEAKENING", "THESIS_CONFLICTED"):
            return "ELEVATED"
        if _u(ms.get("flip_risk")) in ("HIGH", "ELEVATED"):
            return "ELEVATED"
        return "CONTROLLED"

    def _market_closed(self, d, holding, pos) -> Directive:
        d.directive = "STAND_DOWN"
        d.position_state = f"IN_{_u(pos.side)}" if holding and _u(pos.side) in ("CALL", "PUT") else "OBSERVING"
        d.confidence = 30; d.urgency = "LOW"
        d.reason = "Market is not in a tradeable session."
        d.reasons = [d.reason, "Treat signals as planning information only."]
        d.risk_status = "CONTROLLED"
        d.next_action = "WAIT_FOR_OPEN"
        d.next_action_trigger = "Regular session opens."
        d.quality_flags.append("MARKET_CLOSED")
        return d

    # ── conditional guidance (Part 7) ───────────────────────────────────────────
    def _conditional_flat(self, d, side, hold) -> List[str]:
        g = []
        if hold.available:
            g.append(f"ENTER {side} only while price holds {hold.direction.lower()} {hold.level} ({hold.source}).")
        g.append(f"Require fresh flow acceleration AND a Pine {side} trigger before entering.")
        g.append("Do not enter against a hard veto or into stale data.")
        return g

    def _conditional_open(self, d, side, hold, flow_acc) -> List[str]:
        g = []
        if hold.available:
            g.append(f"HOLD {side} WHILE PRICE HOLDS {hold.direction} {hold.level}.")
            g.append(f"EXIT IF {hold.level} FAILS AND opposing flow accelerates.")
        g.append(f"CONTINUE HOLDING while {'buyer' if side == 'CALL' else 'seller'} flow stays dominant.")
        if d.target_1:
            g.append(f"HOLD THROUGH TARGET 1 ({d.target_1}) IF POC keeps migrating the right way.")
        g.append("DO NOT EXIT ON PRICE ALONE — require flow/level confirmation.")
        g.append("PROTECT PROFIT IF flow acceleration falls below threshold.")
        return g

    # ── lifecycle checklists (Part 16) ──────────────────────────────────────────
    def _checklist_flat(self, ctx, ii, flow_acc, conflict) -> List[Dict[str, Any]]:
        ms = ctx.market_state or {}
        side_ok = _u(ms.get("approved_side")) in ("CALL", "PUT") or \
                  _u(ii.get("institutional_bias")) not in ("", "NEUTRAL")
        auction_ok = "ACCEPT" in _u(ii.get("acceptance") or ms.get("auction_state"))
        flow_ok = _u(flow_acc.classification) in (
            "BUYERS_ACCELERATING", "SELLERS_ACCELERATING", "BUYERS_STEADY", "SELLERS_STEADY")
        exec_ok = bool((ctx.execution or {}).get("trigger_active")) or \
                  _u((ctx.execution or {}).get("stage")) in ("ARMED", "EXECUTE")
        pine_ok = bool(ms.get("signal_fresh") or (ctx.signal or {}).get("fresh_signal"))
        veto_ok = not (conflict.hard_veto if conflict else False)
        risk_ok = bool((ctx.risk or {}).get("approved", True))
        return [
            {"label": "Market open", "ok": ctx.market_open},
            {"label": "Institutional side agrees", "ok": side_ok},
            {"label": "Auction agrees", "ok": auction_ok},
            {"label": "Flow confirms", "ok": flow_ok},
            {"label": "Execution confirms", "ok": exec_ok},
            {"label": "Pine trigger fresh", "ok": pine_ok},
            {"label": "No hard veto", "ok": veto_ok},
            {"label": "Risk acceptable", "ok": risk_ok},
        ]

    def _checklist_open(self, pos, ms, ii, flow_acc, hold, thesis) -> List[Dict[str, Any]]:
        side = _u(pos.side)
        thesis_ok = thesis in ("THESIS_STRENGTHENING", "THESIS_INTACT")
        flow_ok = (side == "CALL" and _u(flow_acc.classification).startswith("BUYERS")) or \
                  (side == "PUT" and _u(flow_acc.classification).startswith("SELLERS"))
        auction_ok = "ACCEPT" in _u(ii.get("acceptance") or ms.get("auction_state"))
        price = _f(ms.get("price"))
        hold_ok = True
        if hold.available and hold.level and price:
            hold_ok = (price >= hold.level) if hold.direction == "ABOVE" else (price <= hold.level)
        reversal_class = "BEARISH_FLOW_REVERSAL" if side == "CALL" else "BULLISH_FLOW_REVERSAL"
        accel_against = "SELLERS_ACCELERATING" if side == "CALL" else "BUYERS_ACCELERATING"
        no_reversal = _u(flow_acc.classification) not in (reversal_class, accel_against)
        exit_inactive = thesis != "THESIS_INVALIDATED" and hold_ok
        return [
            {"label": "Position confirmed", "ok": pos.confidence in ("CONFIRMED", "LIKELY", "MANUAL")},
            {"label": "Thesis intact", "ok": thesis_ok},
            {"label": "Flow supports position", "ok": flow_ok},
            {"label": "Auction supports position", "ok": auction_ok},
            {"label": "Hold level intact", "ok": hold_ok},
            {"label": "No opposing flow reversal", "ok": no_reversal},
            {"label": "Risk controlled", "ok": thesis != "THESIS_INVALIDATED"},
            {"label": "Exit trigger inactive", "ok": exit_inactive},
        ]


_DIRECTOR: Optional[ActiveTradeDirector] = None
_DIRECTOR_LOCK = threading.Lock()


def get_director() -> ActiveTradeDirector:
    global _DIRECTOR
    if _DIRECTOR is None:
        with _DIRECTOR_LOCK:
            if _DIRECTOR is None:
                _DIRECTOR = ActiveTradeDirector()
    return _DIRECTOR


def build_active_trade_director(ctx: DirectorContext) -> Directive:
    """Public convenience wrapper."""
    return get_director().build(ctx)
