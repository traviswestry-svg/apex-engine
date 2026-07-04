"""engine/execution/bracket_manager.py — APEX-managed bracket / OCO logic.

E*TRADE's native bracket/OCO behavior is not assumed. APEX tracks the parent entry,
the protective stop, and staged TP exits itself, enforcing the state machine and the
"never close more than held" invariant. In-memory store keyed by bracket_id, with a
non-fatal JSON snapshot so a restart can recover open brackets.

State machine:
  PLANNED → PREVIEWED → SENT → PARTIALLY_FILLED → FILLED → PROTECTED
          → TP1_HIT → TP2_HIT → TP3_HIT → CLOSED
  plus: REJECTED, CANCELED, ERROR, MANUAL_REVIEW_REQUIRED
"""
from __future__ import annotations

import datetime as dt
import json
import os
import threading
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

_STATES = [
    "PLANNED", "PREVIEWED", "SENT", "PARTIALLY_FILLED", "FILLED", "PROTECTED",
    "TP1_HIT", "TP2_HIT", "TP3_HIT", "CLOSED",
]
_TERMINAL = {"CLOSED", "REJECTED", "CANCELED"}
_SPECIAL = {"REJECTED", "CANCELED", "ERROR", "MANUAL_REVIEW_REQUIRED"}

# Allowed forward transitions (special states reachable from any non-terminal state).
_ALLOWED: Dict[str, set] = {
    "PLANNED": {"PREVIEWED", "REJECTED", "CANCELED", "ERROR"},
    "PREVIEWED": {"SENT", "REJECTED", "CANCELED", "ERROR"},
    "SENT": {"PARTIALLY_FILLED", "FILLED", "REJECTED", "CANCELED", "ERROR"},
    "PARTIALLY_FILLED": {"PARTIALLY_FILLED", "FILLED", "PROTECTED", "CANCELED", "ERROR", "MANUAL_REVIEW_REQUIRED"},
    "FILLED": {"PROTECTED", "CLOSED", "ERROR", "MANUAL_REVIEW_REQUIRED"},
    "PROTECTED": {"TP1_HIT", "TP2_HIT", "TP3_HIT", "CLOSED", "MANUAL_REVIEW_REQUIRED", "ERROR"},
    "TP1_HIT": {"TP2_HIT", "TP3_HIT", "CLOSED", "MANUAL_REVIEW_REQUIRED", "ERROR"},
    "TP2_HIT": {"TP3_HIT", "CLOSED", "MANUAL_REVIEW_REQUIRED", "ERROR"},
    "TP3_HIT": {"CLOSED", "MANUAL_REVIEW_REQUIRED", "ERROR"},
    "ERROR": {"MANUAL_REVIEW_REQUIRED", "CANCELED", "CLOSED"},
    "MANUAL_REVIEW_REQUIRED": {"CANCELED", "CLOSED", "PROTECTED"},
}


@dataclass
class BracketLeg:
    tag: str                          # ENTRY | STOP | TP1 | TP2 | TP3
    order_id: Optional[str] = None
    price: Optional[float] = None
    quantity: int = 0
    status: str = "PLANNED"           # PLANNED|WORKING|FILLED|CANCELED
    filled_qty: int = 0


@dataclass
class Bracket:
    bracket_id: str
    symbol: str
    osi_key: str
    side: str                         # CALL | PUT
    quantity: int
    state: str = "PLANNED"
    entry: Optional[BracketLeg] = None
    stop: Optional[BracketLeg] = None
    tps: List[BracketLeg] = field(default_factory=list)
    filled_qty: int = 0
    closed_qty: int = 0
    created_at: str = ""
    updated_at: str = ""
    history: List[Dict[str, Any]] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d

    @property
    def held_qty(self) -> int:
        return max(0, self.filled_qty - self.closed_qty)


class BracketManager:
    def __init__(self, snapshot_path: Optional[str] = None) -> None:
        self._lock = threading.RLock()
        self._store: Dict[str, Bracket] = {}
        self._snapshot_path = snapshot_path or os.getenv(
            "BRACKET_SNAPSHOT_PATH", os.path.join("data", "trade_audit", "brackets_state.json"))
        self._load()

    # ── lifecycle ──────────────────────────────────────────────────────────
    def create(self, *, symbol: str, osi_key: str, side: str, quantity: int,
               entry_price: float, stop_price: float,
               tp_prices: List[float]) -> Bracket:
        with self._lock:
            bid = uuid.uuid4().hex[:12]
            now = dt.datetime.now(dt.timezone.utc).isoformat()
            b = Bracket(
                bracket_id=bid, symbol=symbol, osi_key=osi_key, side=side, quantity=quantity,
                state="PLANNED", created_at=now, updated_at=now,
                entry=BracketLeg(tag="ENTRY", price=entry_price, quantity=quantity),
                stop=BracketLeg(tag="STOP", price=stop_price, quantity=quantity),
                tps=[BracketLeg(tag=f"TP{i+1}", price=p, quantity=0) for i, p in enumerate(tp_prices[:3])],
            )
            b.history.append({"ts": now, "event": "CREATE", "state": "PLANNED"})
            self._store[bid] = b
            self._save()
            return b

    def get(self, bracket_id: str) -> Optional[Bracket]:
        with self._lock:
            return self._store.get(bracket_id)

    def open_brackets(self) -> List[Bracket]:
        with self._lock:
            return [b for b in self._store.values() if b.state not in _TERMINAL]

    # ── transitions ────────────────────────────────────────────────────────
    def can_transition(self, current: str, target: str) -> bool:
        if target == current and current in ("PARTIALLY_FILLED",):
            return True
        return target in _ALLOWED.get(current, set())

    def transition(self, bracket_id: str, target: str, *, note: str = "",
                   **updates: Any) -> Bracket:
        with self._lock:
            b = self._store.get(bracket_id)
            if not b:
                raise KeyError(f"unknown bracket {bracket_id}")
            if target not in _STATES and target not in _SPECIAL:
                raise ValueError(f"invalid state {target}")
            if b.state in _TERMINAL:
                raise ValueError(f"bracket {bracket_id} is terminal ({b.state})")
            if not self.can_transition(b.state, target):
                raise ValueError(f"illegal transition {b.state} → {target}")
            prev = b.state
            b.state = target
            b.updated_at = dt.datetime.now(dt.timezone.utc).isoformat()
            for k, v in updates.items():
                if hasattr(b, k):
                    setattr(b, k, v)
            if note:
                b.note = note
            b.history.append({"ts": b.updated_at, "event": "TRANSITION",
                              "from": prev, "to": target, "note": note})
            self._save()
            return b

    # ── fills & exits ──────────────────────────────────────────────────────
    def record_fill(self, bracket_id: str, filled_qty: int) -> Bracket:
        with self._lock:
            b = self._store[bracket_id]
            b.filled_qty = min(b.quantity, b.filled_qty + max(0, filled_qty))
            if b.entry:
                b.entry.filled_qty = b.filled_qty
                b.entry.status = "FILLED" if b.filled_qty >= b.quantity else "WORKING"
            if b.filled_qty >= b.quantity and self.can_transition(b.state, "FILLED"):
                self.transition(bracket_id, "FILLED", note="entry fully filled")
            elif b.filled_qty > 0 and self.can_transition(b.state, "PARTIALLY_FILLED"):
                self.transition(bracket_id, "PARTIALLY_FILLED", note="entry partial")
            return self._store[bracket_id]

    def record_exit(self, bracket_id: str, tag: str, exit_qty: int) -> Bracket:
        """Record a stop/TP exit. Enforces that total closed never exceeds held."""
        with self._lock:
            b = self._store[bracket_id]
            # Already flat or terminal: log the attempt and return without an illegal
            # transition. This is the "prevent closing more than held" invariant.
            if b.state in _TERMINAL or b.held_qty <= 0:
                b.history.append({"ts": dt.datetime.now(dt.timezone.utc).isoformat(),
                                  "event": "EXIT_IGNORED", "tag": tag,
                                  "requested": exit_qty, "held": b.held_qty, "state": b.state})
                self._save()
                return b
            remaining = b.held_qty
            if exit_qty > remaining:
                # Prevent closing more than held — clamp to what's left.
                b.history.append({"ts": dt.datetime.now(dt.timezone.utc).isoformat(),
                                  "event": "EXIT_CLAMPED", "tag": tag,
                                  "requested": exit_qty, "remaining": remaining})
                exit_qty = remaining
            b.closed_qty += exit_qty
            # advance TP state
            tag_state = {"TP1": "TP1_HIT", "TP2": "TP2_HIT", "TP3": "TP3_HIT"}.get(tag)
            if tag == "STOP":
                if self.can_transition(b.state, "CLOSED"):
                    self.transition(bracket_id, "CLOSED", note="stopped out")
            elif tag_state and self.can_transition(b.state, tag_state):
                self.transition(bracket_id, tag_state, note=f"{tag} hit")
            if b.held_qty == 0 and b.state not in _TERMINAL and self.can_transition(b.state, "CLOSED"):
                self.transition(bracket_id, "CLOSED", note="position flat")
            self._save()
            return self._store[bracket_id]

    def flatten(self, bracket_id: str, note: str = "emergency flatten") -> Bracket:
        """Emergency flatten: close all held, cancel remaining exits."""
        with self._lock:
            b = self._store[bracket_id]
            b.closed_qty = b.filled_qty
            for leg in ([b.stop] + list(b.tps)):
                if leg and leg.status == "WORKING":
                    leg.status = "CANCELED"
            if b.state not in _TERMINAL:
                # ERROR/REVIEW states may not allow CLOSED directly; force via review.
                if self.can_transition(b.state, "CLOSED"):
                    self.transition(bracket_id, "CLOSED", note=note)
                else:
                    self.transition(bracket_id, "MANUAL_REVIEW_REQUIRED", note=note)
            return self._store[bracket_id]

    # ── persistence (non-fatal) ────────────────────────────────────────────
    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._snapshot_path), exist_ok=True)
            with open(self._snapshot_path, "w", encoding="utf-8") as fh:
                json.dump({k: v.to_dict() for k, v in self._store.items()}, fh, default=str)
        except Exception as e:
            print(f"bracket snapshot save error (non-fatal): {e}", flush=True)

    def _load(self) -> None:
        try:
            if not os.path.exists(self._snapshot_path):
                return
            with open(self._snapshot_path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            for bid, d in raw.items():
                entry = BracketLeg(**d["entry"]) if d.get("entry") else None
                stop = BracketLeg(**d["stop"]) if d.get("stop") else None
                tps = [BracketLeg(**t) for t in d.get("tps", [])]
                d2 = {k: v for k, v in d.items() if k not in ("entry", "stop", "tps")}
                self._store[bid] = Bracket(entry=entry, stop=stop, tps=tps, **d2)
        except Exception as e:
            print(f"bracket snapshot load error (non-fatal): {e}", flush=True)


# Module-level singleton used by the routes.
_MANAGER: Optional[BracketManager] = None
_MANAGER_LOCK = threading.Lock()


def get_bracket_manager() -> BracketManager:
    global _MANAGER
    with _MANAGER_LOCK:
        if _MANAGER is None:
            _MANAGER = BracketManager()
        return _MANAGER
