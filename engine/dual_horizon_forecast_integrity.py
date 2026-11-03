"""Read-only dual-horizon and opening-drive evidence diagnostics.

A live refresh is not a remaining-session forecast and must never replace the
immutable first pre-outcome Morning Brief used by Evening Recap grading.
"""
from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo
import math

ET = ZoneInfo('America/New_York')
OPENING = {'or5': ('or5_high', 'or5_low', time(9, 35)),
           'or15': ('or15_high', 'or15_low', time(9, 45)),
           'ib': ('ib_high', 'ib_low', time(10, 30))}


def _num(value):
    if isinstance(value, bool):
        return None
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (ValueError, TypeError):
        return None


def opening_range_evidence(levels, *, now_et=None, target_session_date=None):
    """Report availability, never synthesize an absent opening range."""
    now = now_et or datetime.now(ET)
    if now.tzinfo is None:
        raise ValueError('now_et must be timezone-aware')
    now = now.astimezone(ET)
    same_day = target_session_date == now.date().isoformat()
    found = {}
    for level in levels or ():
        kind = getattr(getattr(level, 'kind', None), 'value', None)
        if kind is None and isinstance(level, dict):
            kind = level.get('kind')
        price = getattr(level, 'price', None) if not isinstance(level, dict) else level.get('price')
        if kind and _num(price) is not None:
            found[kind] = _num(price)
    rows = {}
    for name, (hi, lo, cutoff) in OPENING.items():
        ready = hi in found and lo in found and found[hi] >= found[lo]
        if ready:
            state = 'OBSERVED'
        elif not same_day or now.time() < cutoff:
            state = 'NOT_YET_DUE_OR_DIFFERENT_SESSION'
        else:
            state = 'MISSING_AFTER_WINDOW'
        rows[name] = {'state': state, 'high': found.get(hi), 'low': found.get(lo),
                      'window_end_et': cutoff.isoformat(), 'source': 'daily_key_levels'}
    return {'authority': 'OBSERVATIONAL_ONLY', 'as_of_et': now.isoformat(),
            'target_session_date': target_session_date, 'windows': rows}


def classify_horizon(*, mode, source_session_date, target_session_date, spot, expected_move, now_et=None):
    """Classify the presented forecast without claiming it predicts remaining range."""
    now = now_et or datetime.now(ET)
    if now.tzinfo is None:
        raise ValueError('now_et must be timezone-aware')
    now = now.astimezone(ET)
    spot = _num(spot)
    move = _num(expected_move)
    live = (source_session_date == target_session_date == now.date().isoformat()
            and now.time() >= time(9, 30) and str(mode).upper() != 'NEXT_SESSION_PREP')
    return {
        'authority': 'DIAGNOSTIC_ONLY',
        'track': 'LIVE_REVISION' if live else 'PRE_OUTCOME_OR_SESSION_PREP',
        'expected_move_semantics': 'RECOMPUTED_SPOT_CENTERED_BAND_NOT_REMAINING_SESSION',
        'spot_reference': spot, 'one_sigma': move,
        'expected_low': round(spot - move, 2) if spot is not None and move is not None else None,
        'expected_high': round(spot + move, 2) if spot is not None and move is not None else None,
        'immutable_baseline_replaced': False,
        'official_grading_authority': False,
        'remaining_session_move_estimated': False,
        'as_of_et': now.isoformat(),
    }
