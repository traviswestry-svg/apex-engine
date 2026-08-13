"""
APEX — Instrument basis normalization for the Daily Key Levels engine.

Location: engine/instrument_basis.py

Why this exists: SPX is a cash index — no overnight session, no traded volume,
no settlement. The tradeable proxies that DO carry that data (ES futures, SPY)
live in a different coordinate system:

  * ES  = SPX + basis   (carry - dividends, plus a quarterly roll)
  * SPY ~ SPX / 10      (with slow dividend drift)

So a level computed on a proxy (e.g. an ES overnight high) is meaningless until
it is translated into SPX points. If you skip this, the Trade Map silently
compares two different rulers ("ES overnight high 7442" vs "SPX spot 7455").

The basis is directly observable: sample proxy spot and SPX spot at the same
instant and take the difference. spx = proxy * scale + offset.
"""

from __future__ import annotations

from typing import Iterable, Optional

try:
    from .daily_key_levels import KeyLevel, LevelKind, Maybe, FEED_REQUIRED, present
except ImportError:
    from daily_key_levels import KeyLevel, LevelKind, Maybe, FEED_REQUIRED, present


# Levels that are proxy-sourced when you feed ES/SPY data — they get normalized.
# RTH cash levels (PDH/PDL/close, opening range, IB) are NOT here: they stay SPX.
PROXY_OVERNIGHT_KINDS = frozenset({
    LevelKind.ON_HIGH, LevelKind.ON_LOW, LevelKind.ON_MID, LevelKind.ON_VWAP,
})
PROXY_SETTLE_KINDS = frozenset({LevelKind.PREV_SETTLE})
PROXY_ALL = PROXY_OVERNIGHT_KINDS | PROXY_SETTLE_KINDS


def basis_offset(proxy_spot: Maybe, spx_spot: Maybe, *, scale: float = 1.0) -> Maybe:
    """Offset such that  spx = proxy * scale + offset.

    ES:  scale=1.0   -> offset = spx_spot - es_spot
    SPY: scale=10.0  -> offset = spx_spot - spy_spot*10

    Returns FEED_REQUIRED if either spot is missing — never a guessed 0, because
    a wrong basis silently mislocates every proxy level.
    """
    if not present(proxy_spot) or not present(spx_spot):
        return FEED_REQUIRED
    return float(spx_spot) - float(proxy_spot) * scale


def normalize_levels(
    levels: Iterable[KeyLevel],
    *,
    offset: Maybe,
    scale: float = 1.0,
    kinds: Iterable[LevelKind] = PROXY_ALL,
    instrument: str = "ES",
) -> list[KeyLevel]:
    """Translate proxy-sourced levels into SPX points and tag them.

    Levels whose kind is in `kinds` and whose price is present get:
        price := price * scale + offset
        instrument := <proxy>, normalized := True
    Everything else is returned untouched. If `offset` is FEED_REQUIRED we do NOT
    translate — instead we blank the proxy level's price to FEED_REQUIRED, because
    an un-normalized proxy level is worse than an absent one (it's on the wrong
    ruler). SPX-native levels are never affected.
    """
    kinds = frozenset(kinds)
    out: list[KeyLevel] = []
    have_offset = present(offset)
    for lv in levels:
        if lv.kind not in kinds:
            out.append(lv)
            continue
        if not present(lv.price):
            out.append(lv)
            continue
        if have_offset:
            lv.price = round(float(lv.price) * scale + float(offset), 2)
            lv.instrument = instrument
            lv.normalized = True
        else:
            # cannot locate it correctly -> refuse to emit a mis-scaled number
            lv.price = FEED_REQUIRED
            lv.instrument = instrument
            lv.normalized = False
        out.append(lv)
    return out


def make_proxy_normalizer(
    *, proxy_spot: Maybe, spx_spot: Maybe, scale: float = 1.0,
    instrument: str = "ES", kinds: Iterable[LevelKind] = PROXY_ALL,
):
    """Return a level_postprocess callable for DailyKeyLevels.build(...).

    Usage:
        norm = make_proxy_normalizer(proxy_spot=es_spot, spx_spot=spx_spot)
        DailyKeyLevels.build(md, gp, vp, lp, level_postprocess=norm)
    """
    off = basis_offset(proxy_spot, spx_spot, scale=scale)

    def _postprocess(levels: list[KeyLevel]) -> list[KeyLevel]:
        return normalize_levels(levels, offset=off, scale=scale,
                                kinds=kinds, instrument=instrument)

    _postprocess.basis_offset = off  # exposed for the dashboard / diagnostics
    return _postprocess
