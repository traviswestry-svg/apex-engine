"""Shadow-only walk-forward calibration for immutable APEX morning forecasts.

Only completed, verified prior-session records are eligible. This module never
writes forecasts, labels, orders, or canonical outcome evidence.
"""
from __future__ import annotations

import math
from statistics import median

VERSION = '69.10.47-adaptive-morning-shadow-v1'
MIN_SESSIONS = 20
MAX_SESSIONS = 120


def number(value):
    if isinstance(value, bool):
        return None
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _eligible(row, target_date):
    if not isinstance(row, dict) or not row.get('forecast_provenance_verified'):
        return False
    date = row.get('session_date')
    if not isinstance(date, str) or not (len(date) == 10 and date < target_date):
        return False
    if row.get('outcome_complete') is not True:
        return False
    values = [number(row.get(k)) for k in ('forecast_spot', 'forecast_one_sigma', 'actual_high', 'actual_low')]
    return all(v is not None for v in values) and values[1] > 0 and values[3] <= values[2]


def calibrate(*, target_date, forecast_spot, forecast_one_sigma, history, min_sessions=MIN_SESSIONS):
    """Return bounded shadow candidate; never replace official expected-move fields.

    History schema is intentionally explicit: callers must supply verified frozen
    pre-outcome forecasts and complete realized high/low outcomes. Duplicate dates
    fail closed rather than weighting a repeatedly revised session multiple times.
    """
    base = {'version': VERSION, 'authority': 'SHADOW_ONLY_NO_FORECAST_OR_EXECUTION_CHANGE',
            'target_session_date': target_date, 'state': 'INSUFFICIENT_VERIFIED_HISTORY',
            'eligible_sessions': 0, 'candidate': None}
    spot, em = number(forecast_spot), number(forecast_one_sigma)
    if not isinstance(target_date, str) or len(target_date) != 10 or spot is None or em is None or em <= 0:
        return {**base, 'state': 'INVALID_FORECAST_INPUT'}
    unique = {}
    duplicates = set()
    for row in history or ():
        if _eligible(row, target_date):
            day = row['session_date']
            if day in unique:
                duplicates.add(day)
            else:
                unique[day] = row
    for day in duplicates:
        unique.pop(day, None)
    rows = [unique[d] for d in sorted(unique)[-MAX_SESSIONS:]]
    base['eligible_sessions'] = len(rows)
    base['duplicate_dates_excluded'] = len(duplicates)
    if len(rows) < max(MIN_SESSIONS, int(min_sessions)):
        return base
    width_ratios, center_offsets = [], []
    for row in rows:
        prior_em = number(row['forecast_one_sigma'])
        high, low = number(row['actual_high']), number(row['actual_low'])
        prior_spot = number(row['forecast_spot'])
        width_ratios.append((high - low) / (2 * prior_em))
        center_offsets.append(((high + low) / 2 - prior_spot) / prior_em)
    # Guardrails: bounded suggestions, not authority to change the official forecast.
    width_factor = min(1.5, max(0.75, median(width_ratios)))
    center_factor = min(0.5, max(-0.5, median(center_offsets)))
    candidate_center = spot + center_factor * em
    candidate_halfwidth = em * width_factor
    return {**base, 'state': 'SHADOW_CANDIDATE_READY',
            'training_end_session': rows[-1]['session_date'],
            'candidate': {'center': round(candidate_center, 2),
                          'lower': round(candidate_center - candidate_halfwidth, 2),
                          'upper': round(candidate_center + candidate_halfwidth, 2),
                          'one_sigma': round(candidate_halfwidth, 2),
                          'width_factor': round(width_factor, 4),
                          'center_offset_sigma': round(center_factor, 4)},
            'method': 'MEDIAN_PRIOR_SESSION_NORMALIZED_WIDTH_AND_CENTER_SHADOW'}


def walk_forward(history, *, min_sessions=MIN_SESSIONS):
    """Compare shadow vs frozen baseline on strictly earlier verified sessions.

    Scores range-center absolute error and absolute high/low boundary errors;
    no outcome is ever included in its own training window.
    """
    records = sorted((r for r in (history or ()) if isinstance(r, dict) and isinstance(r.get('session_date'), str)),
                     key=lambda r: r['session_date'])
    results = []
    for row in records:
        day = row['session_date']
        if not _eligible(row, '9999-12-31'):
            continue
        candidate = calibrate(target_date=day, forecast_spot=row['forecast_spot'],
                              forecast_one_sigma=row['forecast_one_sigma'], history=records,
                              min_sessions=min_sessions).get('candidate')
        if candidate is None:
            continue
        spot, em = number(row['forecast_spot']), number(row['forecast_one_sigma'])
        hi, lo = number(row['actual_high']), number(row['actual_low'])
        baseline_error = (abs(spot + em - hi) + abs(spot - em - lo)) / 2
        shadow_error = (abs(candidate['upper'] - hi) + abs(candidate['lower'] - lo)) / 2
        results.append({'session_date': day, 'baseline_boundary_mae': round(baseline_error, 4),
                        'shadow_boundary_mae': round(shadow_error, 4)})
    n = len(results)
    return {'version': VERSION, 'state': 'EVALUATED' if n else 'INSUFFICIENT_HOLDOUT',
            'holdout_sessions': n, 'rows': results,
            'baseline_boundary_mae': round(sum(r['baseline_boundary_mae'] for r in results)/n, 4) if n else None,
            'shadow_boundary_mae': round(sum(r['shadow_boundary_mae'] for r in results)/n, 4) if n else None,
            'promotion_authority': False}
