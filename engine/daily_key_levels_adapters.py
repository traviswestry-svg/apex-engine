"""
APEX — Provider adapters for the Daily Key Levels engine.

Location: engine/daily_key_levels_adapters.py  (sits beside engine/daily_key_levels.py)

These implement the four Protocols in daily_key_levels.py by wrapping data that
has ALREADY been fetched once during Morning Readiness. Per the APEX rule
("engines must not fetch data independently — all network calls happen once and
results are passed down"), NONE of these adapters makes a network call and NONE
imports app.py. The Morning-Readiness caller in app.py fetches once and hands the
raw results in (see the wiring snippet at the bottom).

Source mapping (found in the repo):
  * Gamma + Volume Profile  -> the canonical market-state dict from
    build_canonical_market_state()  (already assembled, single source of truth)
  * Price bars              -> app.py get_daily_bars() / get_intraday_bars()
                               (Polygon aggs rows: t/o/h/l/c/v/vw)
  * Straddle / IV           -> engine/options chain (fetch_chain + normalize_chain)
  * active_gamma_flip       -> quantdata_flow_snapshot()  (real flip, not zero_gamma)
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Optional, Sequence

try:  # works as a package module...
    from .daily_key_levels import (
        Bar, GammaRegime, FEED_REQUIRED, Maybe, present, DailyKeyLevels,
    )
except ImportError:  # ...and standalone for testing
    from daily_key_levels import (
        Bar, GammaRegime, FEED_REQUIRED, Maybe, present, DailyKeyLevels,
    )

try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover
    _ET = dt.timezone(dt.timedelta(hours=-5))


def _f(v: Any) -> Maybe:
    """Coerce to float, else FEED_REQUIRED (never a fabricated 0)."""
    try:
        if v is None or v == "":
            return FEED_REQUIRED
        f = float(v)
        return f if f == f else FEED_REQUIRED  # reject NaN
    except (TypeError, ValueError):
        return FEED_REQUIRED


def _row_to_bar(r: dict) -> Bar:
    """Polygon aggs row (t/o/h/l/c/v) -> Bar. Delta not available from aggs."""
    return Bar(
        o=float(r.get("o", 0.0)), h=float(r.get("h", 0.0)),
        l=float(r.get("l", 0.0)), c=float(r.get("c", 0.0)),
        v=_f(r.get("v")),
    )


def _bar_et(r: dict) -> Optional[dt.datetime]:
    t = r.get("t")
    if t is None:
        return None
    return dt.datetime.fromtimestamp(float(t) / 1000.0, tz=dt.timezone.utc).astimezone(_ET)


# --------------------------------------------------------------------------- #
# MarketDataProvider — wraps already-fetched bars + options-derived straddle/IV
# --------------------------------------------------------------------------- #

class CanonicalMarketDataAdapter:
    """Pure wrapper over data fetched once in Morning Readiness.

    Nothing here calls the network. `daily_bars` and `intraday_1m_bars` are the
    raw lists returned by app.py get_daily_bars()/get_intraday_bars(mult=1).
    `overnight_bars` are ES globex rows if you have them (else previous-session
    overnight levels report [FEED REQUIRED], never a guess).
    """

    def __init__(
        self, *,
        daily_bars: Sequence[dict],
        intraday_1m_bars: Sequence[dict],
        overnight_bars: Optional[Sequence[dict]] = None,
        spot: Maybe = FEED_REQUIRED,
        straddle: Maybe = FEED_REQUIRED,
        iv: Maybe = FEED_REQUIRED,
        time_to_close_frac: Maybe = FEED_REQUIRED,
        atr_val: Maybe = FEED_REQUIRED,
        adr_val: Maybe = FEED_REQUIRED,
    ) -> None:
        self._daily = list(daily_bars or [])
        self._intraday = list(intraday_1m_bars or [])
        self._overnight = list(overnight_bars or [])
        self._spot = spot
        self._straddle = straddle
        self._iv = iv
        self._ttcf = time_to_close_frac
        self._atr = atr_val
        self._adr = adr_val

    def previous_session(self) -> dict:
        # last COMPLETED daily bar (date strictly before today's ET date)
        today = dt.datetime.now(_ET).date()
        completed = [r for r in self._daily
                     if (_bar_et(r).date() < today if _bar_et(r) else True)]
        row = (completed or self._daily)[-1] if (completed or self._daily) else None
        if not row:
            return {}
        return {
            "open": _f(row.get("o")), "high": _f(row.get("h")),
            "low": _f(row.get("l")), "close": _f(row.get("c")),
            # SPX cash has no settlement distinct from close -> don't fabricate one
            "settlement": FEED_REQUIRED,
        }

    def overnight_bars(self) -> Sequence[Bar]:
        return [_row_to_bar(r) for r in self._overnight]

    def opening_bars(self) -> Sequence[Bar]:
        # 1-min bars of the latest available RTH session (>= 09:30, <= 16:00 ET)
        rth = []
        for r in self._intraday:
            et = _bar_et(r)
            if et and (dt.time(9, 30) <= et.time() <= dt.time(16, 0)):
                rth.append((et.date(), r))
        if not rth:
            return []
        latest = max(d for d, _ in rth)
        return [_row_to_bar(r) for d, r in rth if d == latest]

    def spot(self) -> Maybe: return self._spot
    def atm_straddle(self) -> Maybe: return self._straddle
    def atm_iv(self) -> Maybe: return self._iv
    def time_to_close_frac(self) -> Maybe: return self._ttcf
    def atr(self, n: int = 14) -> Maybe: return self._atr
    def avg_daily_range(self, n: int = 20) -> Maybe: return self._adr


# --------------------------------------------------------------------------- #
# GammaProvider — wraps the canonical market-state dict (+ flow_snapshot)
# --------------------------------------------------------------------------- #

_REGIME_MAP = {
    "POSITIVE": GammaRegime.LONG_GAMMA,
    "NEGATIVE": GammaRegime.SHORT_GAMMA,
    "MIXED": GammaRegime.NEUTRAL_GAMMA,
    "UNAVAILABLE": GammaRegime.UNKNOWN,
}


class CanonicalGammaAdapter:
    """Reads gamma from the canonical state dict. flow_snapshot (optional) supplies
    the true active_gamma_flip, which the canonical dict doesn't carry."""

    def __init__(self, ms: dict, flow_snapshot: Optional[dict] = None) -> None:
        self._ms = ms or {}
        self._flow = flow_snapshot or {}

    def levels(self) -> dict:
        flip = _f(self._flow.get("active_gamma_flip"))
        if not present(flip):
            flip = _f(self._ms.get("zero_gamma"))   # fall back to zero gamma
        return {
            "gamma_flip": flip,
            "zero_gamma": _f(self._ms.get("zero_gamma")),
            "call_wall": _f(self._ms.get("call_wall")),
            "put_wall": _f(self._ms.get("put_wall")),
            # not carried by the canonical dict -> honest [FEED REQUIRED]
            "hi_gamma": FEED_REQUIRED,
            "lo_gamma": FEED_REQUIRED,
            "vol_trigger": FEED_REQUIRED,
        }

    def dealer_position(self) -> GammaRegime:
        return _REGIME_MAP.get(str(self._ms.get("gamma_regime") or "").upper(),
                               GammaRegime.UNKNOWN)

    def dealer_delta(self) -> Maybe:
        return _f(self._ms.get("dealer_delta"))   # absent in canonical -> FEED_REQUIRED


# --------------------------------------------------------------------------- #
# VolumeProfileProvider — wraps the canonical market-state dict
# --------------------------------------------------------------------------- #

class CanonicalVolumeProfileAdapter:
    """Session POC/VAH/VAL/HVN/LVN come straight from the canonical dict.
    Composite/previous/naked POCs aren't in the canonical dict; if you want them,
    pass the fuller output of _volume_profile_bundle(days=N) via `extra`."""

    def __init__(self, ms: dict, extra: Optional[dict] = None) -> None:
        self._ms = ms or {}
        self._extra = extra or {}

    def levels(self) -> dict:
        e = self._extra
        return {
            "dev_poc": _f(self._ms.get("poc")),
            "vah": _f(self._ms.get("vah")),
            "val": _f(self._ms.get("val")),
            "hvns": list(self._ms.get("hvn") or []),
            "lvns": list(self._ms.get("lvn") or []),
            # only present if you supply the extended bundle; else FEED_REQUIRED-safe
            "prev_poc": _f(e.get("prev_poc")),
            "comp_poc": _f(e.get("comp_poc")),
            "comp_vah": _f(e.get("comp_vah")),
            "comp_val": _f(e.get("comp_val")),
            "naked_pocs": list(e.get("naked_pocs") or []),
            "virgin_pocs": list(e.get("virgin_pocs") or []),
        }


class NullLiquidityAdapter:
    """Placeholder until FVG / equal-high / liquidity-pool detection is built.
    Returns no levels rather than fabricated ones."""
    def levels(self) -> Sequence:
        return []


# --------------------------------------------------------------------------- #
# Pure helpers the Morning-Readiness caller uses to derive straddle/IV & T
# --------------------------------------------------------------------------- #

def compute_atm_straddle_iv(contracts_calls, contracts_puts, spot: float):
    """ATM straddle price + IV from normalized OptionContract lists.

    Pure. Picks the strike nearest spot present on BOTH sides; straddle = call.mid
    + put.mid; iv = mean of available ivs. Returns (straddle, iv), each Maybe.
    """
    if not present(_f(spot)) or not contracts_calls or not contracts_puts:
        return FEED_REQUIRED, FEED_REQUIRED
    calls = {c.strike: c for c in contracts_calls if getattr(c, "mid", None)}
    puts = {p.strike: p for p in contracts_puts if getattr(p, "mid", None)}
    common = set(calls) & set(puts)
    if not common:
        return FEED_REQUIRED, FEED_REQUIRED
    k = min(common, key=lambda s: abs(float(s) - float(spot)))
    c, p = calls[k], puts[k]
    straddle = _f(c.mid) if present(_f(c.mid)) else FEED_REQUIRED
    if present(straddle) and present(_f(p.mid)):
        straddle = float(c.mid) + float(p.mid)
    else:
        return FEED_REQUIRED, FEED_REQUIRED
    ivs = [float(x.iv) for x in (c, p) if getattr(x, "iv", None)]
    iv = (sum(ivs) / len(ivs)) if ivs else FEED_REQUIRED
    return straddle, iv


def intraday_time_to_close_frac(now_et: Optional[dt.datetime] = None) -> Maybe:
    """Fraction of a trading YEAR remaining until today's 16:00 ET close.
    Matches the IV-implied EM formula spot*iv*sqrt(T) for a 0DTE."""
    now = now_et or dt.datetime.now(_ET)
    close = now.replace(hour=16, minute=0, second=0, microsecond=0)
    mins_left = max(0.0, (close - now).total_seconds() / 60.0)
    return mins_left / (252.0 * 390.0)


# --------------------------------------------------------------------------- #
# Convenience: build the whole thing from Morning-Readiness context
# --------------------------------------------------------------------------- #

def build_daily_key_levels(
    *,
    canonical_ms: dict,
    flow_snapshot: Optional[dict] = None,
    daily_bars: Sequence[dict],
    intraday_1m_bars: Sequence[dict],
    overnight_bars: Optional[Sequence[dict]] = None,
    straddle: Maybe = FEED_REQUIRED,
    iv: Maybe = FEED_REQUIRED,
    time_to_close_frac: Maybe = FEED_REQUIRED,
    atr_val: Maybe = FEED_REQUIRED,
    adr_val: Maybe = FEED_REQUIRED,
    vp_extra: Optional[dict] = None,
) -> DailyKeyLevels:
    spot = _f((flow_snapshot or {}).get("stock_price"))
    md = CanonicalMarketDataAdapter(
        daily_bars=daily_bars, intraday_1m_bars=intraday_1m_bars,
        overnight_bars=overnight_bars, spot=spot, straddle=straddle, iv=iv,
        time_to_close_frac=time_to_close_frac, atr_val=atr_val, adr_val=adr_val,
    )
    gp = CanonicalGammaAdapter(canonical_ms, flow_snapshot)
    vp = CanonicalVolumeProfileAdapter(canonical_ms, vp_extra)
    return DailyKeyLevels.build(md, gp, vp, NullLiquidityAdapter())


# --------------------------------------------------------------------------- #
# Demo with realistic fake payloads mirroring the repo's actual return shapes
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    now = dt.datetime.now(_ET)
    ms_ts = lambda hh, mm, day_off=0: int(
        (now.replace(hour=hh, minute=mm, second=0, microsecond=0)
         + dt.timedelta(days=day_off)).timestamp() * 1000)

    # canonical market-state dict (subset, real keys from engine/market_state.py)
    canonical_ms = {
        "price": 7455.0, "poc": 7448.0, "vah": 7460.0, "val": 7435.0,
        "hvn": [7448.0, 7410.0], "lvn": [7475.0],
        "call_wall": 7500.0, "put_wall": 7400.0, "zero_gamma": 7438.0,
        "gamma_regime": "POSITIVE",
    }
    # quantdata_flow_snapshot subset (real keys from app.py:2642)
    flow_snapshot = {"stock_price": 7455.0, "active_gamma_flip": 7440.0,
                     "call_wall": 7500.0, "put_wall": 7400.0, "zero_gamma": 7438.0}

    # Polygon daily aggs rows (t/o/h/l/c/v) — last completed session is "yesterday"
    daily_bars = [
        {"t": ms_ts(16, 0, -2), "o": 7380, "h": 7420, "l": 7360, "c": 7405, "v": 2_000_000},
        {"t": ms_ts(16, 0, -1), "o": 7405, "h": 7442, "l": 7398, "c": 7430, "v": 2_200_000},
    ]
    # 1-min intraday rows for today's RTH open (first 60 min)
    intraday = []
    base = 7436.0
    for i in range(60):
        t = now.replace(hour=9, minute=30, second=0, microsecond=0) + dt.timedelta(minutes=i)
        px = base + i * 0.1
        intraday.append({"t": int(t.timestamp() * 1000), "o": px, "h": px + 3,
                         "l": px - 3, "c": px + 1, "v": 800})

    dkl = build_daily_key_levels(
        canonical_ms=canonical_ms, flow_snapshot=flow_snapshot,
        daily_bars=daily_bars, intraday_1m_bars=intraday,
        straddle=58.0, iv=0.14,
        time_to_close_frac=intraday_time_to_close_frac(now),
        atr_val=62.0, adr_val=55.0,
    )

    import json
    d = dkl.to_dict()
    print("spot:", d["spot"], "| gamma_regime:", d["gamma_regime"])
    print("\nprev-session + gamma levels (real values from wrapped sources):")
    for lv in d["levels"]:
        if lv["kind"] in ("prev_day_high", "prev_day_low", "prev_close",
                          "prev_settlement", "gamma_flip", "zero_gamma",
                          "call_wall", "put_wall", "developing_poc", "vah", "val",
                          "em_upper", "em_lower", "high_gamma_strike"):
            print(f'  {lv["kind"]:<18} {lv["price"]}')
    print("\ntrade map:")
    for t in d["trade_map"]:
        print(f'  {t["condition"]} -> {t["implication"]}')
    print("\ntop 5 ranked:")
    for r in d["ranked"][:5]:
        print(f'  {r["rank"]}. {r["kind"]:<18} {r["price"]}  (imp {r["importance"]})')
