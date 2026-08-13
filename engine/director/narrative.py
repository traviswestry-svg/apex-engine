"""engine/director/narrative.py — active trade storytelling (Part 17).

Produces a running, human-readable timeline of the trade lifecycle
("buyer flow begins accelerating → price reclaims developing POC → ENTER SCALP
CALL → buyer flow +22% → HOLD CALL → Target 1 → SCALE OUT 50% → hold level fails
→ EXIT REMAINING"). It records material events only (directive changes, flow
class changes, thesis changes, scale/exit) so the log stays signal, not noise.

This feeds the existing Signal Log and a future Replay Engine. It is an in-memory
ring per symbol; the durable copy lives in the directive DB (store.py).
"""
from __future__ import annotations

import datetime as dt
import threading
from collections import defaultdict, deque
from typing import Any, Deque, Dict, List, Optional


_MAX_EVENTS = 200


class TradeNarrator:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._events: Dict[str, Deque[Dict[str, Any]]] = defaultdict(lambda: deque(maxlen=_MAX_EVENTS))
        self._last: Dict[str, Dict[str, str]] = defaultdict(dict)

    def reset(self, symbol: Optional[str] = None) -> None:
        with self._lock:
            if symbol is None:
                self._events.clear(); self._last.clear()
            else:
                self._events.pop(symbol.upper(), None)
                self._last.pop(symbol.upper(), None)

    def observe(self, symbol: str, directive: Dict[str, Any]) -> None:
        """Record material transitions from a fresh directive."""
        symbol = symbol.upper()
        d = directive or {}
        with self._lock:
            last = self._last[symbol]
            now_et = d.get("updated_at_et") or dt.datetime.now(dt.timezone.utc).strftime("%H:%M:%S")

            def _emit(kind: str, text: str):
                self._events[symbol].append({"ts": now_et, "kind": kind, "text": text})

            directive_v = d.get("directive", "")
            if directive_v and directive_v != last.get("directive"):
                _emit("DIRECTIVE", f"{directive_v.replace('_', ' ')} — {d.get('reason','')}".strip(" —"))
                last["directive"] = directive_v

            flow = d.get("flow_state", "")
            if flow and flow != last.get("flow") and flow != "FLOW_UNKNOWN":
                pct = d.get("flow_change_pct") or 0.0
                extra = f" ({pct:+.0f}%)" if pct else ""
                _emit("FLOW", f"{flow.replace('_', ' ').title()}{extra}")
                last["flow"] = flow

            thesis = d.get("thesis_status", "")
            if thesis and thesis not in ("", "THESIS_NONE") and thesis != last.get("thesis"):
                _emit("THESIS", thesis.replace("THESIS_", "Thesis ").replace("_", " ").title())
                last["thesis"] = thesis

    def timeline(self, symbol: str) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._events.get(symbol.upper(), ()))


_NARRATOR: Optional[TradeNarrator] = None
_NARRATOR_LOCK = threading.Lock()


def get_narrator() -> TradeNarrator:
    global _NARRATOR
    if _NARRATOR is None:
        with _NARRATOR_LOCK:
            if _NARRATOR is None:
                _NARRATOR = TradeNarrator()
    return _NARRATOR
