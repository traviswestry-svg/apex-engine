"""engine/director/persistence.py — directive persistence & hysteresis (Part 13).

The Director must not flip-flop on one noisy 5-second snapshot, but it also must
not stay in HOLD once several independent thesis conditions have failed. This
module is the memory layer that enforces:

  - minimum directive duration (don't churn directives sub-second)
  - confirmation windows (an EXIT proposed from HOLD must persist N reads)
  - state hysteresis (raising the bar to leave a state)
  - flow-reversal / hold-level-failure confirmation counters
  - cooldown after exit and after a stop
  - re-entry gating

It is pure bookkeeping keyed by symbol; it holds no market data and makes no
network calls. The Director proposes a raw directive; `stabilize()` returns the
directive that should actually be emitted plus a note explaining any hold-back.
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .contracts import EXIT_STATES, IN_POSITION_STATES


_MIN_DIRECTIVE_S      = float(os.getenv("DIRECTOR_MIN_DIRECTIVE_S", "8"))
_EXIT_CONFIRM_READS   = int(os.getenv("DIRECTOR_EXIT_CONFIRM_READS", "2"))
_REVERSAL_CONFIRM     = int(os.getenv("DIRECTOR_REVERSAL_CONFIRM_READS", "2"))
_LEVELFAIL_CONFIRM    = int(os.getenv("DIRECTOR_LEVELFAIL_CONFIRM_READS", "2"))
_COOLDOWN_EXIT_S      = float(os.getenv("DIRECTOR_COOLDOWN_EXIT_S", "60"))
_COOLDOWN_STOP_S      = float(os.getenv("DIRECTOR_COOLDOWN_STOP_S", "120"))


@dataclass
class _SymbolMemory:
    emitted_directive: str = ""
    emitted_state: str = ""
    emitted_at: float = 0.0
    prev_directive: str = ""
    # confirmation counters
    pending_directive: str = ""
    pending_count: int = 0
    reversal_count: int = 0
    levelfail_count: int = 0
    exit_count: int = 0
    # cooldown
    cooldown_until: float = 0.0
    cooldown_reason: str = ""
    # trailing hold-level anchor (set while a position is open)
    anchor_level: Optional[float] = None
    anchor_dir: str = ""
    anchor_source: str = ""


class DirectivePersistence:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._mem: Dict[str, _SymbolMemory] = {}

    def _m(self, symbol: str) -> _SymbolMemory:
        return self._mem.setdefault(symbol.upper(), _SymbolMemory())

    def reset(self, symbol: Optional[str] = None) -> None:
        with self._lock:
            if symbol is None:
                self._mem.clear()
            else:
                self._mem.pop(symbol.upper(), None)

    def in_cooldown(self, symbol: str) -> bool:
        with self._lock:
            return time.time() < self._m(symbol).cooldown_until

    def start_cooldown(self, symbol: str, *, kind: str = "exit") -> None:
        with self._lock:
            m = self._m(symbol)
            dur = _COOLDOWN_STOP_S if kind == "stop" else _COOLDOWN_EXIT_S
            m.cooldown_until = time.time() + dur
            m.cooldown_reason = f"cooldown after {kind}"

    def anchor_hold_level(
        self, symbol: str, *, computed_level: Optional[float], direction: str,
        source: str, price: Optional[float], holding: bool,
    ) -> Dict[str, Any]:
        """Trail the hold level for an open position so a genuine break can fire
        EXIT_LEVEL_FAILURE. While holding: anchor on first read, then ratchet only
        in the favourable direction (up for CALL/ABOVE, down for PUT/BELOW) and
        never loosen. When flat: clear the anchor. Returns the effective level
        {level, source, direction, trailed(bool)}.
        """
        with self._lock:
            m = self._m(symbol)
            if not holding:
                m.anchor_level = None; m.anchor_dir = ""; m.anchor_source = ""
                return {"level": computed_level, "source": source, "direction": direction, "trailed": False}

            if computed_level is None and m.anchor_level is None:
                return {"level": None, "source": source, "direction": direction, "trailed": False}

            # first anchor
            if m.anchor_level is None:
                m.anchor_level = computed_level
                m.anchor_dir = direction or m.anchor_dir
                m.anchor_source = source
                return {"level": m.anchor_level, "source": m.anchor_source,
                        "direction": m.anchor_dir, "trailed": False}

            direction = direction or m.anchor_dir
            trailed = False
            # ratchet only toward safety, and only while price still respects the anchor
            if computed_level is not None and price is not None:
                if direction == "ABOVE" and price > m.anchor_level and computed_level > m.anchor_level:
                    m.anchor_level = computed_level; m.anchor_source = source; trailed = True
                elif direction == "BELOW" and price < m.anchor_level and computed_level < m.anchor_level:
                    m.anchor_level = computed_level; m.anchor_source = source; trailed = True
            return {"level": m.anchor_level, "source": m.anchor_source,
                    "direction": direction, "trailed": trailed}

    def stabilize(
        self,
        symbol: str,
        *,
        proposed_directive: str,
        proposed_state: str,
        holding: bool,
        exit_signals: Dict[str, bool] | None = None,
    ) -> Dict[str, Any]:
        """Apply hysteresis/confirmation. Returns:
            {directive, state, changed, note, confirmations}
        """
        exit_signals = exit_signals or {}
        now = time.time()
        with self._lock:
            m = self._m(symbol)

            # first ever emit
            if not m.emitted_directive:
                return self._emit(m, proposed_directive, proposed_state, now,
                                  note="Initial directive.")

            # ── confirmation counters (only meaningful while holding) ──────────
            note_bits = []
            is_exit = proposed_state in EXIT_STATES or proposed_directive in ("EXIT_CALL_NOW", "EXIT_PUT_NOW", "EXIT_IMMEDIATELY")

            if exit_signals.get("flow_reversal"):
                m.reversal_count += 1
            else:
                m.reversal_count = 0
            if exit_signals.get("level_failure"):
                m.levelfail_count += 1
            else:
                m.levelfail_count = 0

            # CRITICAL urgency (emergency) bypasses confirmation windows.
            emergency = exit_signals.get("emergency", False)

            # If we're proposing an EXIT out of a HOLD, require confirmation unless emergency.
            leaving_hold_for_exit = holding and is_exit and m.emitted_state in IN_POSITION_STATES
            if leaving_hold_for_exit and not emergency:
                m.exit_count += 1
                need = _EXIT_CONFIRM_READS
                # reversal / level-failure have their own confirm thresholds
                if exit_signals.get("flow_reversal") and m.reversal_count < _REVERSAL_CONFIRM:
                    return self._hold_prev(m, now,
                        note=f"Flow reversal unconfirmed ({m.reversal_count}/{_REVERSAL_CONFIRM}) — staying in {m.emitted_directive}.")
                if exit_signals.get("level_failure") and m.levelfail_count < _LEVELFAIL_CONFIRM:
                    return self._hold_prev(m, now,
                        note=f"Hold-level failure unconfirmed ({m.levelfail_count}/{_LEVELFAIL_CONFIRM}) — staying in {m.emitted_directive}.")
                if m.exit_count < need:
                    return self._hold_prev(m, now,
                        note=f"Exit condition unconfirmed ({m.exit_count}/{need}) — staying in {m.emitted_directive}.")
                note_bits.append("Exit confirmed across window.")
            else:
                m.exit_count = 0

            # ── minimum directive duration (anti-churn) ────────────────────────
            same = proposed_directive == m.emitted_directive
            age = now - m.emitted_at
            if not same and age < _MIN_DIRECTIVE_S and not emergency and not (is_exit and not leaving_hold_for_exit):
                # Batch identical proposals; only switch once a new directive
                # persists across the minimum window.
                if proposed_directive == m.pending_directive:
                    m.pending_count += 1
                else:
                    m.pending_directive = proposed_directive
                    m.pending_count = 1
                return self._hold_prev(m, now,
                    note=f"Debouncing → {proposed_directive} ({round(_MIN_DIRECTIVE_S - age,1)}s left).")

            note = " ".join(note_bits) if note_bits else ("Directive changed." if not same else "Directive stable.")
            emitted = self._emit(m, proposed_directive, proposed_state, now, note=note)

            # start cooldown when we actually emit an exit
            if is_exit:
                m.cooldown_until = now + _COOLDOWN_EXIT_S
                m.cooldown_reason = "cooldown after exit"
            return emitted

    # ── helpers ────────────────────────────────────────────────────────────────
    def _emit(self, m: _SymbolMemory, directive: str, state: str, now: float, *, note: str) -> Dict[str, Any]:
        changed = directive != m.emitted_directive
        if changed:
            m.prev_directive = m.emitted_directive
        m.emitted_directive = directive
        m.emitted_state = state
        m.emitted_at = now
        m.pending_directive = ""
        m.pending_count = 0
        return {"directive": directive, "state": state, "changed": changed,
                "note": note, "previous": m.prev_directive,
                "confirmations": {"reversal": m.reversal_count, "level_failure": m.levelfail_count,
                                  "exit": m.exit_count}}

    def _hold_prev(self, m: _SymbolMemory, now: float, *, note: str) -> Dict[str, Any]:
        return {"directive": m.emitted_directive, "state": m.emitted_state, "changed": False,
                "note": note, "previous": m.prev_directive,
                "confirmations": {"reversal": m.reversal_count, "level_failure": m.levelfail_count,
                                  "exit": m.exit_count}}


_PERSIST: Optional[DirectivePersistence] = None
_PERSIST_LOCK = threading.Lock()


def get_persistence() -> DirectivePersistence:
    global _PERSIST
    if _PERSIST is None:
        with _PERSIST_LOCK:
            if _PERSIST is None:
                _PERSIST = DirectivePersistence()
    return _PERSIST
