"""Freeze independently labelled volatility candidates from already acquired market data.

This is *not* SPX implied volatility and never changes canonical forecast selection.
No network calls, post-decision bars, or outcome-conditioned calibration.
"""
from __future__ import annotations

from datetime import datetime, timedelta, time, timezone
from math import isfinite, log, sqrt
from statistics import stdev
from zoneinfo import ZoneInfo

SCHEMA = 'DECISION_TIME_VOLATILITY_SHADOW_CANDIDATES_V1'
ET = ZoneInfo('America/New_York')


def _dt(value):
    try:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            # Polygon aggregate timestamps are milliseconds.
            return datetime.fromtimestamp(value / 1000, timezone.utc)
        if isinstance(value, str):
            d = datetime.fromisoformat(value.replace('Z', '+00:00'))
            return d.astimezone(timezone.utc) if d.tzinfo else None
    except (ValueError, TypeError, OverflowError, OSError):
        pass
    return None


def _num(value):
    if isinstance(value, bool):
        return None
    try:
        f = float(value)
        return f if isfinite(f) else None
    except (ValueError, TypeError):
        return None


def capture(futures_context, *, decision_at, reference_spot, existing_availability=None, bar_minutes=5):
    """Freeze research candidate from pre-fetched, completed ES aggregates.

    Converts realized five-minute return dispersion to a regular-session
    horizon using a *fixed*, uncalibrated sqrt(N) proxy. This is NOT
    an options-derived, independently verified, or tradable prediction.
    """
    decision = _dt(decision_at)
    spot = _num(reference_spot)
    ctx = futures_context if isinstance(futures_context, dict) else {}
    et = decision.astimezone(ET) if decision else None
    out = {
        'schema': SCHEMA, 'mode': 'SHADOW_PRE_OUTCOME_ONLY',
        'decision_at': decision.isoformat() if decision else None,
        'provider': ctx.get('provider') or 'MASSIVE_POLYGON_ES_AGGREGATES',
        'provider_status': ctx.get('status'), 'ticker': ctx.get('ticker'),
        'selected_canonical_expected_move_unchanged': True,
        'official_forecast_mutated': False, 'official_scoring_mutated': False,
        'production_promotion': False,
        'candidate': {'status': 'NOT_AVAILABLE', 'reason': 'NO_COMPLETE_VERIFIED_ES_SAMPLE',
                      'one_sigma_spx_points': None, 'basis': 'ES_OVERNIGHT_REALIZED_VOL_PROXY',
                      'source_is_spx_implied_volatility': False,
                      'source_verified_as_spx_options_quote': False,
                      'performance_calibrated': False},
        'source_options_availability': ((existing_availability or {}).get('availability')
                                        if isinstance(existing_availability, dict) else None),
        'note': ('Already-fetched ES futures data only; no additional provider request. '
                 'Volatility is historical realized ES variation projected by fixed sqrt-time scaling, '
                 'not SPX implied volatility. No future observations or historical backfill.'),
    }
    candidate = out['candidate']
    if (not et or not spot or spot <= 0 or not isinstance(ctx.get('bars'), list)
            or ctx.get('status') != 'ok' or not str(ctx.get('ticker') or '').startswith('ES')
            or not isinstance(bar_minutes, int) or bar_minutes <= 0):
        candidate['reason'] = 'MISSING_DECISION_TIME_SPOT_OR_ES_PROVIDER_EVIDENCE'
        return out
    if et.weekday() >= 5 or not (time(0, 0) <= et.time() < time(9, 30)):
        candidate['reason'] = 'OUTSIDE_TARGET_PREMARKET_RESEARCH_WINDOW'
        return out
    start = datetime.combine(et.date() - timedelta(days=1), time(18), ET).astimezone(timezone.utc)
    sample = []
    for bar in ctx['bars'][:5000]:
        if not isinstance(bar, dict):
            continue
        ts = _dt(bar.get('t'))
        close = _num(bar.get('c'))
        if ts and start <= ts and ts + timedelta(minutes=bar_minutes) <= decision and close and close > 0:
            sample.append((ts, close))
    sample.sort(key=lambda p: p[0])
    stamps = [p[0] for p in sample]
    if (len(sample) < 31 or len(set(stamps)) != len(stamps) or
            sample[0][0] > start + timedelta(minutes=30) or
            sample[-1][0] + timedelta(minutes=bar_minutes) < decision - timedelta(minutes=20) or
            any(b[0] - a[0] != timedelta(minutes=bar_minutes) for a, b in zip(sample, sample[1:]))):
        candidate['reason'] = 'ES_BARS_INCOMPLETE_DUPLICATE_GAPPED_OR_STALE'
        candidate['sample_bar_count'] = len(sample)
        return out
    changes = [log(b[1] / a[1]) for a, b in zip(sample, sample[1:])]
    sigma = stdev(changes)
    # Fixed target: 09:30–16:00 ET = 78 five-minute periods.  This
    # neither represents a 24h IV horizon nor captures overnight jumps.
    scale = sqrt(78)
    projected = spot * sigma * scale
    if not isfinite(projected) or projected <= 0:
        candidate['reason'] = 'INSUFFICIENT_OR_ZERO_REALIZED_VARIATION'
        return out
    candidate.update({
        'status': 'DESCRIPTIVE_PROXY_AVAILABLE', 'reason': 'ES_COMPLETED_BARS_VALID',
        'one_sigma_spx_points': round(projected, 6),
        'last_completed_bar_at': (sample[-1][0] + timedelta(minutes=bar_minutes)).isoformat(),
        'first_bar_at': sample[0][0].isoformat(),
        'sample_bar_count': len(sample), 'return_count': len(changes),
        'five_min_log_return_sample_sigma': round(sigma, 10),
        'horizon_bars': 78, 'horizon': 'SPX_US_REGULAR_SESSION_09_30_TO_16_00_ET',
        'assumed_bar_minutes': bar_minutes, 'method': 'SPX_SPOT_TIMES_ES_REALIZED_5M_SIGMA_TIMES_SQRT_78',
        'source_event_timestamp_verified': True,
        'provider_entitlement_verified': False,
    })
    return out


def visibility(morning):
    """Return only the archived candidate; missing historical data is never fabricated."""
    structured = morning.get('structured') if isinstance(morning, dict) else None
    prov = ((structured or {}).get('forecast_provenance_diagnostics') or {}).get('expected_move') or {}
    row = prov.get('shadow_volatility_source_candidates')
    return {
        'schema': 'DECISION_TIME_VOLATILITY_SHADOW_VISIBILITY_V1',
        'status': 'FROZEN_SHADOW_CANDIDATES_AVAILABLE' if isinstance(row, dict) and row.get('schema') == SCHEMA else 'LEGACY_SHADOW_CANDIDATES_NOT_ARCHIVED',
        'frozen_candidates': row if isinstance(row, dict) and row.get('schema') == SCHEMA else None,
        'mode': 'READ_ONLY_CANONICAL_ARCHIVE', 'production_promotion': False,
    }
