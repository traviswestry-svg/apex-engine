"""engine/director/snapshots.py — flow acceleration intelligence (Part 4).

Absolute flow tells you how much premium exists; it does not tell you whether
buying/selling is *increasing, decelerating or reversing*. This module keeps a
short in-memory rolling history of the existing flow snapshot per symbol and
derives velocity (1st derivative), acceleration (2nd derivative), persistence,
exhaustion and reversal from it.

It reuses the existing `quantdata_flow_snapshot` output (net_premium,
call_premium, put_premium, flow_score, order_flow_score, sweep_count,
call_ratio_pct, stock_price). It does NOT invent cumulative delta and it does not
label options-flow as underlying delta.

Thresholds are deliberately conservative and configurable via env; 0DTE flow is
noisy, so classification requires a minimum sample window before it will call
anything other than *_STEADY / FLOW_UNKNOWN.
"""
from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque
from typing import Any, Deque, Dict, List, Optional

from .contracts import FlowAcceleration


def _f(v: Any, d: float = 0.0) -> float:
    try:
        if v is None:
            return d
        return float(v)
    except (TypeError, ValueError):
        return d


# ── Config ───────────────────────────────────────────────────────────────────

_MAX_SAMPLES     = int(os.getenv("DIRECTOR_FLOW_MAX_SAMPLES", "120"))   # ~10 min @ 5s
_MIN_SAMPLES     = int(os.getenv("DIRECTOR_FLOW_MIN_SAMPLES", "3"))
_MIN_WINDOW_S    = _f(os.getenv("DIRECTOR_FLOW_MIN_WINDOW_S", "10"))
# Net-flow velocity ($/min) magnitude above which flow is "moving" not "steady".
_VEL_MOVING      = _f(os.getenv("DIRECTOR_FLOW_VEL_MOVING", "8_000_000".replace("_", "")))
# Acceleration ($/min/min) magnitude above which flow is "accelerating".
_ACC_STRONG      = _f(os.getenv("DIRECTOR_FLOW_ACC_STRONG", "4_000_000".replace("_", "")))
_PERSIST_WINDOWS = int(os.getenv("DIRECTOR_FLOW_PERSIST_WINDOWS", "6"))


class _Sample:
    __slots__ = ("t", "net", "call", "put", "flow", "order", "sweeps", "call_ratio", "price")

    def __init__(self, snap: Dict[str, Any]):
        self.t          = time.time()
        self.net        = _f(snap.get("net_premium"))
        self.call       = _f(snap.get("call_premium"))
        self.put        = _f(snap.get("put_premium"))
        self.flow       = _f(snap.get("flow_score"), 50.0)
        self.order      = _f(snap.get("order_flow_score"), 50.0)
        self.sweeps     = _f(snap.get("sweep_count"))
        self.call_ratio = _f(snap.get("call_ratio_pct"), 50.0)
        self.price      = _f(snap.get("stock_price") or snap.get("price"))


class FlowAccelerationTracker:
    """Thread-safe, per-symbol rolling flow history + derivative classifier."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._hist: Dict[str, Deque[_Sample]] = defaultdict(lambda: deque(maxlen=_MAX_SAMPLES))

    # ── ingestion ────────────────────────────────────────────────────────────

    def record(self, symbol: str, snapshot: Dict[str, Any]) -> None:
        """Append a live flow snapshot. Skips empty/zero snapshots so a data
        outage doesn't poison the derivative window with fake zeros."""
        if not snapshot:
            return
        s = _Sample(snapshot)
        if s.call == 0 and s.put == 0 and s.net == 0:
            return
        with self._lock:
            self._hist[symbol.upper()].append(s)

    def reset(self, symbol: Optional[str] = None) -> None:
        with self._lock:
            if symbol is None:
                self._hist.clear()
            else:
                self._hist.pop(symbol.upper(), None)

    def sample_count(self, symbol: str) -> int:
        with self._lock:
            return len(self._hist.get(symbol.upper(), ()))

    # ── derivatives ────────────────────────────────────────────────────────────

    def compute(self, symbol: str) -> FlowAcceleration:
        with self._lock:
            hist: List[_Sample] = list(self._hist.get(symbol.upper(), ()))

        acc = FlowAcceleration()
        acc.samples = len(hist)
        if len(hist) < _MIN_SAMPLES:
            acc.classification = "FLOW_UNKNOWN"
            acc.quality_flags.append(f"WARMING_UP: {len(hist)}/{_MIN_SAMPLES} samples")
            return acc

        first, last = hist[0], hist[-1]
        window_s = max(1e-6, last.t - first.t)
        acc.window_seconds = round(window_s, 1)
        if window_s < _MIN_WINDOW_S:
            acc.classification = "FLOW_UNKNOWN"
            acc.quality_flags.append(f"SHORT_WINDOW: {acc.window_seconds}s")
            return acc

        acc.available = True
        per_min = 60.0 / window_s

        # 1st derivatives over the full window (premium $/min).
        acc.call_premium_velocity = round((last.call - first.call) * per_min, 1)
        acc.put_premium_velocity  = round((last.put - first.put) * per_min, 1)
        acc.net_flow_velocity     = round((last.net - first.net) * per_min, 1)
        acc.flow_score_change     = round(last.flow - first.flow, 2)
        acc.order_score_change    = round(last.order - first.order, 2)
        acc.buyer_dominance_change  = round(last.call_ratio - first.call_ratio, 2)
        acc.seller_dominance_change = round((100 - last.call_ratio) - (100 - first.call_ratio), 2)

        # Sweep arrival rate & its change (compare 2nd half vs 1st half).
        mid = len(hist) // 2
        if mid >= 1:
            first_half = hist[:mid]
            second_half = hist[mid:]
            fh_s = max(1e-6, first_half[-1].t - first_half[0].t) if len(first_half) > 1 else window_s / 2
            sh_s = max(1e-6, second_half[-1].t - second_half[0].t) if len(second_half) > 1 else window_s / 2
            fh_rate = (first_half[-1].sweeps - first_half[0].sweeps) * (60.0 / fh_s) if len(first_half) > 1 else 0.0
            sh_rate = (second_half[-1].sweeps - second_half[0].sweeps) * (60.0 / sh_s) if len(second_half) > 1 else 0.0
            acc.sweep_arrival_rate = round(max(0.0, sh_rate), 2)
            acc.sweep_velocity = round(sh_rate - fh_rate, 2)

        # 2nd derivative: net-flow acceleration = (2nd-half velocity - 1st-half velocity)/min.
        if mid >= 1 and len(hist) - mid >= 1:
            fh = hist[:mid + 1]
            sh = hist[mid:]
            fh_s = max(1e-6, fh[-1].t - fh[0].t)
            sh_s = max(1e-6, sh[-1].t - sh[0].t)
            v1 = (fh[-1].net - fh[0].net) * (60.0 / fh_s)
            v2 = (sh[-1].net - sh[0].net) * (60.0 / sh_s)
            half_span_min = max(1e-6, (sh[len(sh) // 2].t - fh[len(fh) // 2].t) / 60.0)
            acc.net_flow_acceleration = round((v2 - v1) / half_span_min, 1)

        # Persistence: fraction of the last N deltas that share the dominant sign.
        acc.flow_persistence = round(self._persistence(hist), 3)

        # Change %: net-flow change relative to starting magnitude.
        base = abs(first.net) if abs(first.net) > 1 else max(1.0, abs(first.call) + abs(first.put))
        acc.change_pct = round((last.net - first.net) / base * 100.0, 1)

        # Reversal & exhaustion & classification.
        acc.flow_reversal = self._reversal(hist)
        acc.flow_exhaustion = self._exhaustion(acc)
        acc.classification = self._classify(acc)
        return acc

    # ── helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _persistence(hist: List[_Sample]) -> float:
        deltas = [hist[i].net - hist[i - 1].net for i in range(1, len(hist))]
        tail = deltas[-_PERSIST_WINDOWS:]
        if not tail:
            return 0.0
        pos = sum(1 for d in tail if d > 0)
        neg = sum(1 for d in tail if d < 0)
        return max(pos, neg) / len(tail)

    @staticmethod
    def _reversal(hist: List[_Sample]) -> str:
        """Net-flow velocity sign flip confirmed across the last 3 windows.

        Requires the late reversal move to be decisive (its magnitude at least as
        large as the prior trend move, and above a floor) so that mild
        deceleration is classified as *_WEAKENING, not a full reversal.
        """
        if len(hist) < 4:
            return ""
        recent = hist[-4:]
        d = [recent[i].net - recent[i - 1].net for i in range(1, len(recent))]
        if len(d) < 3:
            return ""
        early = d[0]
        late = d[-2] + d[-1]
        floor = _VEL_MOVING  # reuse the "moving" magnitude as a decisiveness floor
        if early < 0 and d[-1] > 0 and d[-2] > 0 and abs(late) >= max(abs(early), floor):
            return "BULLISH"
        if early > 0 and d[-1] < 0 and d[-2] < 0 and abs(late) >= max(abs(early), floor):
            return "BEARISH"
        return ""

    @staticmethod
    def _exhaustion(acc: FlowAcceleration) -> bool:
        """Premium still rising in absolute terms but new-flow velocity fading
        and acceleration turning against it — the classic exhaustion tell."""
        rising = acc.net_flow_velocity > 0
        falling = acc.net_flow_velocity < 0
        decel_up = rising and acc.net_flow_acceleration < -_ACC_STRONG
        decel_dn = falling and acc.net_flow_acceleration > _ACC_STRONG
        return bool(decel_up or decel_dn)

    @staticmethod
    def _classify(acc: FlowAcceleration) -> str:
        v, a = acc.net_flow_velocity, acc.net_flow_acceleration
        if acc.flow_reversal == "BULLISH":
            return "BULLISH_FLOW_REVERSAL"
        if acc.flow_reversal == "BEARISH":
            return "BEARISH_FLOW_REVERSAL"
        if acc.flow_exhaustion:
            return "FLOW_EXHAUSTION"

        moving = abs(v) >= _VEL_MOVING
        if not moving:
            # Near-flat net velocity. Balanced unless score/dominance disagree.
            if abs(acc.buyer_dominance_change) < 3 and abs(acc.flow_score_change) < 4:
                return "FLOW_BALANCED"
            # score & dominance disagree in sign -> conflicted
            if (acc.flow_score_change > 0) != (acc.buyer_dominance_change > 0) \
               and abs(acc.flow_score_change) >= 4 and abs(acc.buyer_dominance_change) >= 3:
                return "FLOW_CONFLICTED"
            return "BUYERS_STEADY" if v >= 0 else "SELLERS_STEADY"

        buyers = v > 0
        if buyers:
            if a >= _ACC_STRONG:
                return "BUYERS_ACCELERATING"
            if a <= -_ACC_STRONG:
                return "BUYERS_WEAKENING"
            return "BUYERS_STEADY"
        else:
            if a <= -_ACC_STRONG:
                return "SELLERS_ACCELERATING"
            if a >= _ACC_STRONG:
                return "SELLERS_WEAKENING"
            return "SELLERS_STEADY"


# Module-level singleton so the scanner and the API share one history.
_TRACKER: Optional[FlowAccelerationTracker] = None
_TRACKER_LOCK = threading.Lock()


def get_flow_tracker() -> FlowAccelerationTracker:
    global _TRACKER
    if _TRACKER is None:
        with _TRACKER_LOCK:
            if _TRACKER is None:
                _TRACKER = FlowAccelerationTracker()
    return _TRACKER
