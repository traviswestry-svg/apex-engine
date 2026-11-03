"""Read-only, decision-time ES feature availability explanations.

Metadata only: no provider calls, no reconstruction, no trading authority.
"""
from __future__ import annotations
from datetime import datetime, timedelta, time, timezone
from zoneinfo import ZoneInfo
from .premarket_feature_provider import _dt, _number

ET = ZoneInfo('America/New_York')
ES_KEYS = ('overnight_es_return', 'overnight_vwap_displacement', 'premarket_gap',
           'prior_day_range_position', 'premarket_trend_strength')


def diagnose(futures_context, *, decision_at, target_session_date, available=None, bar_minutes=5):
    """Explain missing inputs using only the contemporaneous fetched context.

    Results are captured at decision time; archived sessions are never rehydrated.
    """
    available = available or {}
    context = futures_context if isinstance(futures_context, dict) else {}
    decision = _dt(decision_at)
    try:
        target = datetime.fromisoformat(str(target_session_date)).date()
    except ValueError:
        target = None
    reasons = {}
    diagnostics = {'schema': 'PREMARKET_FEATURE_AVAILABILITY_V1',
                   'mode': 'SHADOW_DIAGNOSTICS_ONLY', 'decision_at': decision_at,
                   'target_session_date': str(target_session_date),
                   'provider_status': str(context.get('status') or 'UNAVAILABLE'),
                   'source_ticker': str(context.get('ticker') or 'UNSPECIFIED'),
                   'feature_reasons': reasons}
    def missing(code):
        for key in ES_KEYS:
            if key not in available:
                reasons[key] = code
    if not decision or target is None:
        missing('INVALID_DECISION_OR_TARGET_DATE')
    elif target != decision.astimezone(ET).date():
        missing('TARGET_SESSION_DATE_MISMATCH')
    elif decision.astimezone(ET).time() >= time(9, 30):
        missing('OUTSIDE_PREMARKET_DECISION_WINDOW')
    elif context.get('status') != 'ok':
        missing('ES_PROVIDER_UNAVAILABLE')
    else:
        start = datetime.combine(target - timedelta(days=1), time(18), ET).astimezone(timezone.utc)
        bars = context.get('bars')
        if not isinstance(bars, list) or not 1 <= len(bars) <= 5000:
            missing('ES_BARS_UNAVAILABLE_OR_INVALID_COUNT')
        else:
            complete = []
            for bar in bars:
                if not isinstance(bar, dict):
                    continue
                ts = _dt(bar.get('t'))
                if (ts is not None and start <= ts and
                        ts + timedelta(minutes=bar_minutes) <= decision and
                        _number(bar.get('c')) is not None):
                    complete.append((ts, bar))
            complete.sort(key=lambda pair: pair[0])
            diagnostics['completed_overnight_bars'] = len(complete)
            if not complete:
                missing('NO_COMPLETED_OVERNIGHT_BARS')
            elif complete[0][0] > start + timedelta(minutes=30):
                missing('OVERNIGHT_OPEN_COVERAGE_MISSING')
            elif complete[-1][0] < decision - timedelta(minutes=20):
                missing('LATEST_OVERNIGHT_BAR_STALE')
            else:
                for key in ('overnight_es_return', 'overnight_vwap_displacement', 'premarket_gap'):
                    if key not in available:
                        reasons[key] = 'UNVERIFIED_OR_INCOMPLETE_ES_INPUT'
                if 'overnight_vwap_displacement' not in available and any(
                        _number(b.get('v')) is None or _number(b.get('v')) <= 0 or
                        _number(b.get('h')) is None or _number(b.get('l')) is None
                        for _, b in complete):
                    reasons['overnight_vwap_displacement'] = 'INCOMPLETE_VOLUME_OR_OHLC'
                if 'premarket_gap' not in available and (
                    _number(context.get('prev_settlement')) is None or
                    _dt(context.get('prev_settlement_bar_at')) is None or
                    context.get('settlement_method') != 'previous_session_close_proxy'):
                    reasons['premarket_gap'] = 'PRIOR_ES_CLOSE_PROXY_UNAVAILABLE'
                if 'premarket_trend_strength' not in available:
                    tail = complete[-6:]
                    contiguous = len(tail) == 6 and all(
                        tail[i + 1][0] - tail[i][0] == timedelta(minutes=bar_minutes)
                        for i in range(5))
                    reasons['premarket_trend_strength'] = (
                        'INSUFFICIENT_CONSECUTIVE_COMPLETED_BARS' if not contiguous
                        else 'INVALID_OR_ZERO_TREND_OHLC_RANGE')
                prior = context.get('prior_rth_bars')
                by_day = {}
                if isinstance(prior, list):
                    for b in prior:
                        if not isinstance(b, dict):
                            continue
                        ts = _dt(b.get('t'))
                        if ts and ts < start and ts + timedelta(minutes=bar_minutes) <= decision:
                            local = ts.astimezone(ET)
                            if time(9, 30) <= local.time() < time(16):
                                by_day.setdefault(local.date(), []).append((ts, b))
                selected_day = max(by_day) if by_day else None
                rows = sorted(by_day.get(selected_day, []))
                timestamps = [ts for ts, _ in rows]
                rth = {'selected_session_date': selected_day.isoformat() if selected_day else None,
                       'bar_count': len(rows), 'unique_timestamps': len(set(timestamps)),
                       'first_bar_at': timestamps[0].isoformat() if rows else None,
                       'last_bar_at': timestamps[-1].isoformat() if rows else None,
                       'required_minimum_bars': 75,
                       'expected_open_et': '09:30', 'expected_last_bar_et': '15:55'}
                diagnostics['prior_rth_session'] = rth
                if 'prior_day_range_position' not in available:
                    if not rows:
                        reason = 'PRIOR_RTH_BARS_UNAVAILABLE'
                    elif len(set(timestamps)) != len(rows):
                        reason = 'PRIOR_RTH_DUPLICATE_TIMESTAMPS'
                    elif len(rows) < 75:
                        reason = 'PRIOR_RTH_SESSION_INCOMPLETE'
                    elif (timestamps[0].astimezone(ET).time() != time(9, 30)
                          or timestamps[-1].astimezone(ET).time() != time(15, 55)):
                        reason = 'PRIOR_RTH_OPEN_OR_CLOSE_MISSING'
                    elif any(_number(b.get('h')) is None or _number(b.get('l')) is None or
                             _number(b.get('h')) < _number(b.get('l')) for _, b in rows):
                        reason = 'PRIOR_RTH_OHLC_INVALID'
                    else:
                        reason = 'PRIOR_RTH_RANGE_NOT_VERIFIED'
                    reasons['prior_day_range_position'] = reason
    for key in ES_KEYS:
        if key in available:
            reasons[key] = 'AVAILABLE'
        elif key not in reasons:
            reasons[key] = 'ES_INPUT_NOT_VERIFIED'
    reasons['gamma_context'] = ('AVAILABLE' if 'gamma_context' in available
                                else 'NO_VERIFIED_DECISION_TIME_GAMMA_INPUT')
    return diagnostics
