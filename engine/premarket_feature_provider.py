"""Bounded, offline adapter for already-fetched ES Globex aggregates.

No network, no historical outcome lookup, no guessed source timestamps. Only
completed bars from the target overnight window before the decision instant.
"""
from __future__ import annotations
from datetime import datetime, timedelta, time, timezone
from zoneinfo import ZoneInfo
from math import isfinite

ET = ZoneInfo('America/New_York')


def _dt(value):
    try:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return datetime.fromtimestamp(float(value) / 1000, timezone.utc)
        if isinstance(value, str):
            d = datetime.fromisoformat(value.replace('Z', '+00:00'))
            return d.astimezone(timezone.utc) if d.tzinfo else None
    except (ValueError, OverflowError, OSError):
        pass
    return None


def _number(v):
    if isinstance(v, bool):
        return None
    try:
        n = float(v)
        return n if isfinite(n) else None
    except (ValueError, TypeError):
        return None


def derive_es_features(futures_context, *, decision_at, target_session_date,
                       ingested_at=None, bar_minutes=5):
    """Derive research inputs from pre-fetched ES bars, never fetch or infer.

    The last bar must be fully completed at decision time. Price-only signals
    use the last completed bar and the first completed overnight bar. VWAP needs
    positive volume in *every* included bar. Prior close is a proxy, not CME
    settlement. Gamma, true cash gap and other unsupported features abstain.
    """
    decision = _dt(decision_at)
    ingestion = _dt(ingested_at or decision_at)
    if not decision or not ingestion or ingestion > decision:
        return {}
    try:
        target = datetime.fromisoformat(target_session_date).date()
    except (TypeError, ValueError):
        return {}
    # A next-session preparation brief cannot use the *next* overnight session.
    if target != decision.astimezone(ET).date() or decision.astimezone(ET).time() >= time(9, 30):
        return {}
    if not isinstance(futures_context, dict) or futures_context.get('status') != 'ok':
        return {}
    bars = futures_context.get('bars') or []
    if not isinstance(bars, list) or not 1 <= len(bars) <= 5000:
        return {}
    window_start = datetime.combine(target - timedelta(days=1), time(18), ET).astimezone(timezone.utc)
    # For Monday, futures session begins Sunday 18:00 ET.
    if target.weekday() == 0:
        window_start = datetime.combine(target - timedelta(days=1), time(18), ET).astimezone(timezone.utc)
    selected = []
    for b in bars:
        if not isinstance(b, dict):
            continue
        ts = _dt(b.get('t'))
        close = _number(b.get('c'))
        vol = _number(b.get('v'))
        if ts and window_start <= ts and ts + timedelta(minutes=bar_minutes) <= decision and close is not None:
            selected.append((ts, close, vol, b))
    selected.sort(key=lambda x: x[0])
    if not selected or selected[-1][0] < decision - timedelta(minutes=20):
        return {}
    # Do not invent a complete overnight return when the initial window is missing.
    if selected[0][0] > window_start + timedelta(minutes=30):
        return {}
    source = 'MASSIVE_POLYGON_ES_AGGREGATES:' + str(futures_context.get('ticker') or 'ES')
    observed_at = selected[-1][0].isoformat()
    # The source bar is observed at its closing time, not its opening time.
    observed_at = (selected[-1][0] + timedelta(minutes=bar_minutes)).isoformat()
    def row(value):
        return {'value': value, 'source': source, 'observed_at': observed_at,
                'ingested_at': ingestion.isoformat(), 'decision_time_verified': True}
    result = {}
    initial = selected[0][1]
    last = selected[-1][1]
    if initial > 0:
        result['overnight_es_return'] = row((last / initial - 1) * 100)
    if all(v is not None and v > 0 for _, _, v, _ in selected):
        den = sum(v for _, _, v, _ in selected)
        typical = [((_number(b.get('h')) + _number(b.get('l')) + c) / 3, v)
                   for _, c, v, b in selected if _number(b.get('h')) is not None and _number(b.get('l')) is not None]
        if len(typical) == len(selected) and den > 0:
            vwap = sum(p * v for p, v in typical) / den
            result['overnight_vwap_displacement'] = row(last - vwap)
    previous = _number(futures_context.get('prev_settlement'))
    prior_bar_at = _dt(futures_context.get('prev_settlement_bar_at'))
    if (previous is not None and previous > 0 and prior_bar_at is not None
            and prior_bar_at < window_start and
            futures_context.get('settlement_method') == 'previous_session_close_proxy'):
        # Explicitly labelled ES proxy; not a SPX cash opening gap.
        result['premarket_gap'] = {'value': (last / previous - 1) * 100,
            'source': source + ':PREVIOUS_ES_CLOSE_PROXY', 'observed_at': observed_at,
            'ingested_at': ingestion.isoformat(), 'decision_time_verified': True}
    return result
