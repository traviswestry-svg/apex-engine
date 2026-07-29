"""
APEX — Price-structure liquidity detection for the Daily Key Levels engine.

Location: engine/liquidity_structure.py
Implements the LiquidityProvider Protocol (Module 4) with real detection instead
of a stub. Everything here is deterministic price geometry computed from bars:

  * swing pivots (fractal highs/lows)
  * equal highs / equal lows (clustered pivots -> resting liquidity)
  * fair value gaps (3-bar imbalance), unfilled only
  * buy-side / sell-side liquidity (the nearest draw above / below spot)
  * optional: large resting option strikes (from OI) and dealer hedge zones

Honesty rule carried over from the rest of the engine: touch COUNTS are observed
facts and are reported (prior_reactions) and folded into a deterministic strength
score used for ordering. Interaction/break/reversal PROBABILITIES are NOT
fabricated — they stay FEED_REQUIRED until a calibrated model is injected.

Price structure is valid on SPX cash bars even though SPX volume is thin (pivots
and gaps are geometry, not volume). If you feed ES bars instead, pass
`basis_offset`/`instrument` so the emitted levels are translated into SPX points.
"""

from __future__ import annotations

from typing import Any, Optional, Sequence

try:
    from .daily_key_levels import (
        KeyLevel, LevelKind, LevelSource, FEED_REQUIRED, Maybe, present,
    )
except ImportError:
    from daily_key_levels import (
        KeyLevel, LevelKind, LevelSource, FEED_REQUIRED, Maybe, present,
    )


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def _h(b: Any) -> float: return float(b.h if hasattr(b, "h") else b["h"])
def _l(b: Any) -> float: return float(b.l if hasattr(b, "l") else b["l"])
def _c(b: Any) -> float: return float(b.c if hasattr(b, "c") else b["c"])


# --------------------------------------------------------------------------- #
# Detection primitives (pure)
# --------------------------------------------------------------------------- #

def swing_pivots(bars: Sequence, left: int, right: int):
    """Fractal pivots: index i is a swing high if its high is the strict max of
    the [i-left, i+right] window (ties disqualify, so we don't double-count a
    flat top as several pivots)."""
    highs, lows = [], []
    n = len(bars)
    for i in range(left, n - right):
        win = bars[i - left:i + right + 1]
        hi = _h(bars[i]); lo = _l(bars[i])
        if hi == max(_h(b) for b in win) and sum(1 for b in win if _h(b) == hi) == 1:
            highs.append(i)
        if lo == min(_l(b) for b in win) and sum(1 for b in win if _l(b) == lo) == 1:
            lows.append(i)
    return highs, lows


def cluster_levels(prices: list[tuple[float, int]], tol_pct: float):
    """Group (price, bar_index) pairs whose prices are within tol_pct.
    Returns clusters as (mean_price, touch_count, latest_index), largest first."""
    if not prices:
        return []
    pts = sorted(prices)
    clusters: list[list[tuple[float, int]]] = [[pts[0]]]
    for price, idx in pts[1:]:
        anchor = clusters[-1][0][0]
        if abs(price - anchor) <= anchor * tol_pct:
            clusters[-1].append((price, idx))
        else:
            clusters.append([(price, idx)])
    out = []
    for c in clusters:
        mean_p = sum(p for p, _ in c) / len(c)
        latest = max(i for _, i in c)
        out.append((round(mean_p, 2), len(c), latest))
    return out


def fair_value_gaps(bars: Sequence):
    """3-bar FVGs. Bullish: low[i+1] > high[i-1] (gap below price). Bearish:
    high[i+1] < low[i-1]. Returns (side, lo, hi, mid, idx)."""
    gaps = []
    for i in range(1, len(bars) - 1):
        prev_h, prev_l = _h(bars[i - 1]), _l(bars[i - 1])
        nxt_h, nxt_l = _h(bars[i + 1]), _l(bars[i + 1])
        if nxt_l > prev_h:                       # bullish imbalance
            gaps.append(("bull", prev_h, nxt_l, round((prev_h + nxt_l) / 2, 2), i))
        elif nxt_h < prev_l:                     # bearish imbalance
            gaps.append(("bear", nxt_h, prev_l, round((nxt_h + prev_l) / 2, 2), i))
    return gaps


def gap_unfilled(gap, bars: Sequence) -> bool:
    """True if no later bar has traded back into the gap zone (lo, hi)."""
    _, lo, hi, _, idx = gap
    for b in bars[idx + 2:]:
        if _l(b) <= hi and _h(b) >= lo:          # overlap -> at least partially filled
            return False
    return True


# --------------------------------------------------------------------------- #
# Adapter
# --------------------------------------------------------------------------- #

class PriceStructureLiquidityAdapter:
    """Computes liquidity levels from bars. Pure — no network.

    bars            : sequence of Bar or {h,l,c} dicts (SPX RTH by default)
    spot            : current price, for BSL/SSL selection + strength proximity
    basis_offset    : add to every emitted price (use when bars are ES); 0 = SPX
    instrument      : tag applied to emitted levels
    option_strikes  : optional [(strike, open_interest), ...] -> large resting strikes
    """

    def __init__(
        self, *, bars: Sequence, spot: Maybe = FEED_REQUIRED,
        instrument: str = "SPX", basis_offset: float = 0.0,
        pivot_left: int = 3, pivot_right: int = 3, equal_tol_pct: float = 0.0005,
        max_swings: int = 6, max_fvgs: int = 6,
        option_strikes: Optional[Sequence[tuple]] = None,
    ) -> None:
        self._bars = list(bars or [])
        self._spot = spot
        self._instrument = instrument
        self._off = float(basis_offset or 0.0)
        self._pl, self._pr = pivot_left, pivot_right
        self._tol = equal_tol_pct
        self._max_swings, self._max_fvgs = max_swings, max_fvgs
        self._strikes = list(option_strikes or [])

    # -- helpers -------------------------------------------------------------
    def _mk(self, kind, price, *, touches=FEED_REQUIRED, strength=FEED_REQUIRED, label=""):
        return KeyLevel(
            kind=kind, price=round(price + self._off, 2), source=LevelSource.LIQUIDITY,
            strength_score=strength, prior_reactions=touches,
            label=label, instrument=self._instrument,
            normalized=(self._off != 0.0),
            # probabilities intentionally left FEED_REQUIRED (not fabricated)
        )

    def _strength(self, touches: int, latest_idx: int) -> float:
        n = max(1, len(self._bars))
        recency = latest_idx / n
        return round(_clamp01(0.3 + 0.15 * (touches - 1) + 0.2 * recency), 3)

    # -- Protocol ------------------------------------------------------------
    def levels(self) -> Sequence[KeyLevel]:
        if len(self._bars) < (self._pl + self._pr + 2):
            return []
        out: list[KeyLevel] = []
        hi_idx, lo_idx = swing_pivots(self._bars, self._pl, self._pr)

        hi_prices = [(_h(self._bars[i]), i) for i in hi_idx]
        lo_prices = [(_l(self._bars[i]), i) for i in lo_idx]
        hi_clusters = cluster_levels(hi_prices, self._tol)
        lo_clusters = cluster_levels(lo_prices, self._tol)

        # Equal highs/lows (clusters with >= 2 touches) and liquidity pools (>=3)
        eq_highs, eq_lows = [], []
        for price, touches, latest in hi_clusters:
            if touches >= 2:
                kind = LevelKind.LIQ_POOL if touches >= 3 else LevelKind.EQ_HIGH
                lvl = self._mk(kind, price, touches=touches,
                               strength=self._strength(touches, latest),
                               label=("Liquidity Pool (highs)" if touches >= 3 else "Equal Highs"))
                out.append(lvl); eq_highs.append(lvl)
        for price, touches, latest in lo_clusters:
            if touches >= 2:
                kind = LevelKind.LIQ_POOL if touches >= 3 else LevelKind.EQ_LOW
                lvl = self._mk(kind, price, touches=touches,
                               strength=self._strength(touches, latest),
                               label=("Liquidity Pool (lows)" if touches >= 3 else "Equal Lows"))
                out.append(lvl); eq_lows.append(lvl)

        # Prominent isolated swing highs/lows (single-touch), top-N by prominence
        singles_hi = [(p, t, i) for p, t, i in hi_clusters if t == 1]
        singles_lo = [(p, t, i) for p, t, i in lo_clusters if t == 1]
        for price, _, latest in sorted(singles_hi, key=lambda x: x[2], reverse=True)[:self._max_swings]:
            out.append(self._mk(LevelKind.SWING_HIGH, price, touches=1,
                                strength=self._strength(1, latest), label="Swing High"))
        for price, _, latest in sorted(singles_lo, key=lambda x: x[2], reverse=True)[:self._max_swings]:
            out.append(self._mk(LevelKind.SWING_LOW, price, touches=1,
                                strength=self._strength(1, latest), label="Swing Low"))

        # Unfilled fair value gaps (most recent first)
        fvgs = [g for g in fair_value_gaps(self._bars) if gap_unfilled(g, self._bars)]
        for side, lo, hi, mid, idx in sorted(fvgs, key=lambda g: g[4], reverse=True)[:self._max_fvgs]:
            out.append(self._mk(LevelKind.FVG, mid, touches=FEED_REQUIRED,
                                strength=self._strength(1, idx),
                                label=f"FVG ({side}, {round(lo,1)}-{round(hi,1)})"))

        # Buy-side / sell-side liquidity = nearest resting pool above / below spot
        if present(self._spot):
            spot = float(self._spot)
            above = [l for l in eq_highs if present(l.price) and l.price > spot]
            below = [l for l in eq_lows if present(l.price) and l.price < spot]
            if above:
                nearest = min(above, key=lambda l: l.price - spot)
                out.append(self._mk(LevelKind.BSL, nearest.price - self._off,
                                    touches=nearest.prior_reactions,
                                    strength=nearest.strength_score,
                                    label="Buy-side liquidity (draw above)"))
            if below:
                nearest = min(below, key=lambda l: spot - l.price)
                out.append(self._mk(LevelKind.SSL, nearest.price - self._off,
                                    touches=nearest.prior_reactions,
                                    strength=nearest.strength_score,
                                    label="Sell-side liquidity (draw below)"))

        # Large resting option strikes (from OI) — distinct from gamma walls
        if self._strikes:
            top = sorted(self._strikes, key=lambda s: s[1], reverse=True)[:3]
            max_oi = top[0][1] if top else 1
            for strike, oi in top:
                out.append(self._mk(LevelKind.OPT_STRIKE, float(strike) - self._off,
                                    touches=FEED_REQUIRED,
                                    strength=round(_clamp01(oi / max_oi), 3),
                                    label=f"Large OI strike ({int(oi):,})"))
        return out


# --------------------------------------------------------------------------- #
# Demo
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    try:
        from daily_key_levels import Bar
    except ImportError:
        from .daily_key_levels import Bar

    # Synthetic session: double-top at ~7460 (equal highs), a swing low ~7420,
    # and a bullish FVG around bar 12.
    seq = []
    path = [7440, 7445, 7452, 7460, 7451, 7443, 7435, 7428, 7420, 7429, 7438,
            7447, 7455, 7461, 7453, 7446, 7440, 7448, 7458, 7460, 7452, 7444]
    for i, c in enumerate(path):
        # inject an upside gap between bar 10 and 12
        h = c + 3 + (6 if i == 11 else 0)
        l = c - 3 + (6 if i == 11 else 0)
        seq.append(Bar(o=c, h=h, l=l, c=c, v=1000))

    adp = PriceStructureLiquidityAdapter(
        bars=seq, spot=7450.0, pivot_left=2, pivot_right=2, equal_tol_pct=0.0008,
        option_strikes=[(7500, 42000), (7400, 51000), (7450, 30000)],
    )
    for lv in adp.levels():
        d = lv.to_dict(7450.0)
        pr = d["prior_reactions"]
        print(f'  {d["kind"]:<14} {d["price"]:>9}  touches={pr}  '
              f'strength={d["strength"]}  reaction_prob={d["reaction_prob"]}  | {d["label"]}')
