"""APEX 65.7 canonical live execution boundary.

All single-leg broker submissions must pass here. Preview registration creates a
short-lived execution record; placement re-validates risk immediately before the
irreversible broker call and enforces idempotency.
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from engine.execution.broker_interface import BrokerResult, OrderIntent, ChangeIntent
from engine.execution import trade_risk_guard as guard


def _mode(adapter: Any) -> str:
    return getattr(adapter, "mode", "sandbox")


def _preview_ttl() -> float:
    try:
        return max(1.0, float(os.getenv("APEX_EXECUTION_PREVIEW_TTL_SECONDS", "30")))
    except Exception:
        return 30.0


@dataclass
class PreviewRecord:
    created_at: float
    contract: Dict[str, Any]
    quantity: int
    entry_premium: float
    stop_premium: float
    session_state: str
    intent: OrderIntent
    consumed: bool = False


@dataclass
class ComplexPreviewRecord:
    created_at: float
    intent: Any
    economics: Dict[str, Any]
    session_state: str
    consumed: bool = False


@dataclass
class ChangePreviewRecord:
    created_at: float
    order_id: str
    change_intent: ChangeIntent
    risk_context: Dict[str, Any]
    consumed: bool = False


class CanonicalExecutionBoundary:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._previews: Dict[str, PreviewRecord] = {}
        self._complex_previews: Dict[str, ComplexPreviewRecord] = {}
        self._change_previews: Dict[str, ChangePreviewRecord] = {}

    def register_preview(self, preview_id: str, *, contract: Dict[str, Any], quantity: int,
                         entry_premium: float, stop_premium: float, session_state: str,
                         intent: OrderIntent) -> None:
        if not preview_id:
            return
        with self._lock:
            self._previews[str(preview_id)] = PreviewRecord(
                created_at=time.time(), contract=dict(contract), quantity=int(quantity),
                entry_premium=float(entry_premium), stop_premium=float(stop_premium),
                session_state=str(session_state), intent=intent,
            )


    def register_complex_preview(self, preview_id: str, *, intent: Any, economics: Dict[str, Any],
                                 session_state: str) -> None:
        if not preview_id:
            return
        with self._lock:
            self._complex_previews[str(preview_id)] = ComplexPreviewRecord(
                created_at=time.time(), intent=intent, economics=dict(economics or {}),
                session_state=str(session_state),
            )

    def execute_complex(self, *, adapter: Any, preview_id: str, intent: Any,
                        economics: Dict[str, Any], session_state: str,
                        last_order_epoch: Optional[float]) -> BrokerResult:
        if not preview_id:
            return BrokerResult(ok=False, mode=_mode(adapter), errors=["Missing preview_id; strategy must be previewed before placement."])
        now_epoch = time.time()
        with self._lock:
            rec = self._complex_previews.get(str(preview_id))
            if rec is None:
                return BrokerResult(ok=False, mode=_mode(adapter), errors=["Unknown strategy preview_id; create a fresh preview before placement."])
            if rec.consumed:
                return BrokerResult(ok=False, mode=_mode(adapter), errors=["Strategy preview already consumed; duplicate submission blocked."])
            if now_epoch - rec.created_at > _preview_ttl():
                self._complex_previews.pop(str(preview_id), None)
                return BrokerResult(ok=False, mode=_mode(adapter), errors=["Strategy preview expired; create a fresh preview before placement."])
            if getattr(rec.intent, "to_dict", lambda: rec.intent)() != getattr(intent, "to_dict", lambda: intent)():
                return BrokerResult(ok=False, mode=_mode(adapter), errors=["Strategy intent changed after preview; create a fresh preview."])

        decision = guard.validate_complex_entry(
            intent=intent, economics=economics, session_state=session_state,
            last_order_epoch=last_order_epoch, now_epoch=now_epoch,
            live_trading_enabled=bool(getattr(adapter, "trading_enabled", False)),
        )
        if not decision.allow:
            return BrokerResult(ok=False, mode=_mode(adapter), data={"risk": decision.to_dict()},
                                errors=decision.reasons, warnings=decision.warnings)
        with self._lock:
            rec = self._complex_previews.get(str(preview_id))
            if rec is None or rec.consumed:
                return BrokerResult(ok=False, mode=_mode(adapter), errors=["Strategy preview is no longer executable."])
            rec.consumed = True
        result = adapter.place_complex_order(preview_id, intent)
        if not result.ok:
            with self._lock:
                self._complex_previews.pop(str(preview_id), None)
        return result

    def register_change_preview(self, preview_id: str, *, order_id: str, change_intent: ChangeIntent,
                                risk_context: Dict[str, Any]) -> None:
        if not preview_id:
            return
        with self._lock:
            self._change_previews[str(preview_id)] = ChangePreviewRecord(
                created_at=time.time(), order_id=str(order_id or ""), change_intent=change_intent,
                risk_context=dict(risk_context or {}),
            )

    def execute_change(self, *, adapter: Any, preview_id: str, order_id: str,
                       change_intent: ChangeIntent, risk_context: Dict[str, Any]) -> BrokerResult:
        if not preview_id or not order_id:
            return BrokerResult(ok=False, mode=_mode(adapter), errors=["order_id and preview_id are required for order changes."])
        with self._lock:
            rec = self._change_previews.get(str(preview_id))
            if rec is None:
                return BrokerResult(ok=False, mode=_mode(adapter), errors=["Unknown change preview_id; preview the change again."])
            if rec.consumed:
                return BrokerResult(ok=False, mode=_mode(adapter), errors=["Change preview already consumed; duplicate mutation blocked."])
            if time.time() - rec.created_at > _preview_ttl():
                self._change_previews.pop(str(preview_id), None)
                return BrokerResult(ok=False, mode=_mode(adapter), errors=["Change preview expired; preview the change again."])
            if rec.order_id != str(order_id) or rec.change_intent.to_dict() != change_intent.to_dict():
                return BrokerResult(ok=False, mode=_mode(adapter), errors=["Change intent differs from preview; preview the change again."])

        decision = guard.validate_line_drag(**risk_context)
        if not decision.allow:
            return BrokerResult(ok=False, mode=_mode(adapter), data={"risk": decision.to_dict()}, errors=decision.reasons)
        with self._lock:
            rec = self._change_previews.get(str(preview_id))
            if rec is None or rec.consumed:
                return BrokerResult(ok=False, mode=_mode(adapter), errors=["Change preview is no longer executable."])
            rec.consumed = True
        result = adapter.place_change_order(order_id, preview_id, change_intent)
        if not result.ok:
            with self._lock:
                self._change_previews.pop(str(preview_id), None)
        return result

    def execute_cancel(self, *, adapter: Any, order_id: str) -> BrokerResult:
        if not order_id:
            return BrokerResult(ok=False, mode=_mode(adapter), errors=["order_id required"])
        return adapter.cancel_order(order_id)

    def execute_single_leg(self, *, adapter: Any, preview_id: str, intent: OrderIntent,
                           contract: Dict[str, Any], quantity: int, entry_premium: float,
                           stop_premium: float, session_state: str,
                           last_order_epoch: Optional[float]) -> BrokerResult:
        if not preview_id:
            return BrokerResult(ok=False, mode=getattr(adapter, "mode", "sandbox"),
                                errors=["Missing preview_id; order must be previewed before placement."])
        now_epoch = time.time()
        with self._lock:
            rec = self._previews.get(str(preview_id))
            if rec is None:
                return BrokerResult(ok=False, mode=getattr(adapter, "mode", "sandbox"),
                                    errors=["Unknown preview_id; create a fresh preview before placement."])
            if rec.consumed:
                return BrokerResult(ok=False, mode=getattr(adapter, "mode", "sandbox"),
                                    errors=["Preview already consumed; duplicate order submission blocked."])
            if now_epoch - rec.created_at > _preview_ttl():
                self._previews.pop(str(preview_id), None)
                return BrokerResult(ok=False, mode=getattr(adapter, "mode", "sandbox"),
                                    errors=["Preview expired; create a fresh preview before placement."])

        # Re-run the full risk guard at the last irreversible boundary using the
        # current placement payload. Never trust preview-time approval alone.
        decision = guard.validate_entry(
            contract=contract,
            quantity=quantity,
            entry_premium=entry_premium,
            stop_premium=stop_premium,
            session_state=session_state,
            last_order_epoch=last_order_epoch,
            now_epoch=now_epoch,
            live_trading_enabled=bool(getattr(adapter, "trading_enabled", False)),
        )
        if not decision.allow:
            return BrokerResult(ok=False, mode=getattr(adapter, "mode", "sandbox"),
                                data={"risk": decision.to_dict()}, errors=decision.reasons,
                                warnings=decision.warnings)

        with self._lock:
            rec = self._previews.get(str(preview_id))
            if rec is None or rec.consumed:
                return BrokerResult(ok=False, mode=getattr(adapter, "mode", "sandbox"),
                                    errors=["Preview is no longer executable."])
            # Reserve before broker I/O so concurrent duplicate requests cannot pass.
            rec.consumed = True
        result = adapter.place_order(preview_id, intent)
        if not result.ok:
            # Broker rejection is safe to retry only through a new broker preview.
            with self._lock:
                self._previews.pop(str(preview_id), None)
        return result


_BOUNDARY = CanonicalExecutionBoundary()


def get_execution_boundary() -> CanonicalExecutionBoundary:
    return _BOUNDARY
