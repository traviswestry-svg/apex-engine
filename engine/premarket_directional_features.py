"""APEX decision-time directional feature foundation. Research only; fail closed.

A feature is accepted only when an upstream provider supplies its numeric value,
observation time, source and an explicit decision-time provenance marker.
No post-session actuals, reconstructed gaps or inferred timestamps are accepted.
"""
from __future__ import annotations
from collections import Counter
from datetime import datetime, timezone
from math import isfinite

FEATURES = ('overnight_es_return', 'overnight_vwap_displacement',
            'premarket_gap', 'prior_day_range_position', 'premarket_trend_strength',
            'gamma_context')
MAX_AGE_SECONDS = {'overnight_es_return': 900, 'overnight_vwap_displacement': 900,
                   'premarket_gap': 900, 'prior_day_range_position': 900,
                   'premarket_trend_strength': 900, 'gamma_context': 1800}

def _time(value):
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return dt.astimezone(timezone.utc) if dt.tzinfo else None
    except ValueError:
        return None

def freeze_features(source, *, decision_at):
    """Produce additive snapshot. Never invent missing data or repair source timestamps."""
    decision = _time(decision_at)
    result = {'schema': 'PREMARKET_DIRECTIONAL_FEATURES_V1', 'decision_at': decision_at,
              'mode': 'SHADOW_ONLY', 'features': {}, 'usable_count': 0}
    for key in FEATURES:
        row = source.get(key) if isinstance(source, dict) else None
        status = 'MISSING'
        if isinstance(row, dict):
            value = row.get('value')
            observed = _time(row.get('observed_at'))
            ingested = _time(row.get('ingested_at'))
            origin = row.get('source')
            if (not decision or not observed or not ingested or not origin or
                row.get('decision_time_verified') is not True):
                status = 'UNVERIFIED_PROVENANCE'
            elif observed > decision or ingested > decision:
                status = 'FUTURE_EVIDENCE_REJECTED'
            elif (decision-observed).total_seconds() > MAX_AGE_SECONDS[key]:
                status = 'STALE'
            elif isinstance(value, bool) or not isinstance(value, (int,float)) or not isfinite(value):
                status = 'INVALID_VALUE'
            else:
                status = 'AVAILABLE'
                result['features'][key] = {'status': status, 'value': float(value),
                    'source': str(origin), 'observed_at': row['observed_at'],
                    'ingested_at': row['ingested_at'],
                    'age_seconds': round((decision-observed).total_seconds(), 3)}
                result['usable_count'] += 1
        if key not in result['features']:
            result['features'][key] = {'status': status, 'value': None}
    result['status'] = 'FEATURES_AVAILABLE' if result['usable_count'] else 'ABSTAIN_NO_VERIFIED_FEATURES'
    return result

def shadow_direction(snapshot):
    """Deterministic exploratory signal, not a trained regime model or calibrated probability.

    Three distinct premarket families must agree; otherwise abstain. Does not
    use gamma as a directional vote. No claim of predictive validity.
    """
    features = (snapshot or {}).get('features') or {}
    keys = ('overnight_es_return', 'overnight_vwap_displacement', 'premarket_gap')
    votes = []
    for key in keys:
        row = features.get(key) or {}
        if row.get('status') != 'AVAILABLE':
            continue
        value = row.get('value')
        if isinstance(value, (int, float)) and value != 0:
            votes.append(1 if value > 0 else -1)
    if len(votes) != 3 or abs(sum(votes)) != 3:
        return {'status': 'ABSTAIN_INSUFFICIENT_OR_CONFLICTING_EVIDENCE',
                'direction': None, 'regime': None, 'confidence': None}
    return {'status': 'SHADOW_DIRECTIONAL_CONTEXT',
            'direction': 'BULLISH' if votes[0] > 0 else 'BEARISH',
            'regime': None, 'confidence': None,
            'note': 'Unvalidated directional context, not a regime prediction'}

def archive_diagnostics(mornings):
    counts=Counter(); decisions=[]
    for day, morning in sorted(mornings.items()):
        structured = morning.get('structured') or {}
        snapshot = structured.get('premarket_directional_feature_snapshot')
        if not isinstance(snapshot, dict):
            counts['SNAPSHOT_NOT_ARCHIVED'] += 1
            decisions.append({'session_date': day, 'status': 'SNAPSHOT_NOT_ARCHIVED'})
            continue
        if snapshot.get('schema') != 'PREMARKET_DIRECTIONAL_FEATURES_V1':
            counts['UNKNOWN_SCHEMA'] += 1
            decisions.append({'session_date': day, 'status': 'UNKNOWN_SCHEMA'})
            continue
        signal=shadow_direction(snapshot)
        counts[signal['status']] += 1
        decisions.append({'session_date': day, 'status': signal['status'],
                          'direction': signal['direction'],
                          'usable_count': snapshot.get('usable_count',0),
                          'feature_status': {k:v.get('status') for k,v in
                              (snapshot.get('features') or {}).items()}})
    return {'ok': True, 'mode': 'SHADOW_RESEARCH_ONLY',
            'production_promotion': False, 'official_forecast_mutated': False,
            'sessions': len(mornings), 'status_counts': dict(counts),
            'details': decisions,
            'limitations': ['Historical absent features cannot be reconstructed from session outcomes.',
                            'Directional context is not an exact-regime classifier.',
                            'No trained model or out-of-sample accuracy claim.']}

def archived_diagnostics(*, limit=250):
    from .evening_recap import DB_PATH, _load, init_db
    from .canonical_persistence import connect
    init_db()
    with connect(DB_PATH, timeout=10) as db:
        mornings = {day: _load(payload) for day, payload in db.execute(
            'SELECT session_date,payload_json FROM apex49_morning_snapshots '
            'ORDER BY session_date DESC LIMIT ?', (max(1, min(int(limit), 250)),)
        ).fetchall()}
    return archive_diagnostics(mornings)
