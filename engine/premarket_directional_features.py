"""APEX decision-time directional feature foundation. Research only; fail closed.

A feature is accepted only when an upstream provider supplies its numeric value,
observation time, source and an explicit decision-time provenance marker.
No post-session actuals, reconstructed gaps or inferred timestamps are accepted.
"""
from __future__ import annotations
from collections import Counter
from datetime import datetime, timezone, time
from zoneinfo import ZoneInfo
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
    diagnostics = source.get('_availability_diagnostics') if isinstance(source, dict) else None
    if isinstance(diagnostics, dict) and diagnostics.get('schema') == 'PREMARKET_FEATURE_AVAILABILITY_V1':
        # Capture at generation time, not at archive-read time. Never invent prior data.
        result['availability_diagnostics'] = diagnostics
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

# The directional rule below is the existing three-input unanimity rule.
# ES-derived inputs may be correlated: vote counts are NOT independent evidence,
# calibrated probabilities, or weights in production forecasts.
REQUIRED_DIRECTIONAL_INPUTS = (
    'overnight_es_return', 'overnight_vwap_displacement', 'premarket_gap'
)


def explain_shadow_agreement(snapshot):
    """Read-only explanation of the current shadow_direction rule.

    Uses *only* frozen canonical feature rows. Never rereads providers, fills
    absent values, or derives observations from subsequent market outcomes.
    The original signal remains authoritative and its behavior is unchanged.
    """
    features = (snapshot or {}).get('features') or {}
    evidence = {}
    positive = negative = 0
    unavailable = []
    neutral = []
    for key in FEATURES:
        row = features.get(key) or {}
        status = row.get('status', 'MISSING')
        value = row.get('value')
        valid = (status == 'AVAILABLE' and isinstance(value, (int, float))
                 and not isinstance(value, bool) and isfinite(value))
        direction = ('POSITIVE' if value > 0 else 'NEGATIVE' if value < 0 else 'NEUTRAL') if valid else 'NOT_EVALUATED'
        participates = key in REQUIRED_DIRECTIONAL_INPUTS
        if participates:
            if not valid:
                unavailable.append(key)
            elif value == 0:
                neutral.append(key)
            elif value > 0:
                positive += 1
            else:
                negative += 1
        evidence[key] = {
            'status': status,
            'value': float(value) if valid else None,
            'direction': direction,
            'required_for_unanimity': participates,
            'vote': (1 if value > 0 else -1 if value < 0 else 0) if valid and participates else None,
            'source': row.get('source') if valid else None,
            'observed_at': row.get('observed_at') if valid else None,
            'ingested_at': row.get('ingested_at') if valid else None,
            'age_seconds': row.get('age_seconds') if valid else None,
        }
    if unavailable:
        reason = 'REQUIRED_DIRECTIONAL_INPUT_UNAVAILABLE'
    elif neutral:
        reason = 'REQUIRED_DIRECTIONAL_INPUT_ZERO'
    elif positive and negative:
        reason = 'REQUIRED_DIRECTIONAL_INPUTS_CONFLICT'
    elif positive == 3 or negative == 3:
        reason = 'THREE_REQUIRED_INPUTS_UNANIMOUS'
    else:
        reason = 'REQUIRED_DIRECTIONAL_INPUT_INVALID'
    return {
        'schema': 'PREMARKET_SHADOW_AGREEMENT_EXPLAINABILITY_V1',
        'mode': 'READ_ONLY_FROZEN_EVIDENCE',
        'decision_at': (snapshot or {}).get('decision_at'),
        'rule': 'THREE_REQUIRED_NONZERO_ES_INPUTS_UNANIMOUS',
        'required_inputs': list(REQUIRED_DIRECTIONAL_INPUTS),
        'positive_votes': positive, 'negative_votes': negative,
        'unavailable_required_inputs': unavailable,
        'neutral_required_inputs': neutral,
        'reason': reason,
        'features': evidence,
        'independence_verified': False,
        'confidence_calibrated': False,
        'note': 'Three ES-derived inputs are potentially correlated; two additional ES features and gamma do not vote in this legacy rule.',
    }


def archive_diagnostics(mornings):
    counts=Counter(); decisions=[]
    for day, morning in sorted(mornings.items()):
        # Archive keys are TARGET session dates, not proof of a same-day
        # premarket forecast. Preserve NEXT_SESSION_PREP without scoring it.
        identity = morning.get('forecast_identity') or {}
        generated = _time(morning.get('generated_at'))
        generated_et = generated.astimezone(ZoneInfo('America/New_York')) if generated else None
        mode = identity.get('brief_mode') or morning.get('brief_mode')
        if mode == 'NEXT_SESSION_PREP' or (generated_et and generated_et.date().isoformat() < day):
            counts['NEXT_SESSION_PREPARATION_NOT_PREMARKET'] += 1
            decisions.append({'session_date': day, 'status': 'NEXT_SESSION_PREPARATION_NOT_PREMARKET',
                'brief_mode': mode, 'generated_at': morning.get('generated_at'),
                'canonical_forecast_id': morning.get('canonical_forecast_id'),
                'note': 'Archived preparation record; not a same-day premarket prediction'})
            continue
        if generated_et and generated_et.date().isoformat() > day:
            counts['ARCHIVE_DATE_INTEGRITY_REVIEW'] += 1
            decisions.append({'session_date': day, 'status': 'ARCHIVE_DATE_INTEGRITY_REVIEW',
                'generated_at': morning.get('generated_at'), 'brief_mode': mode})
            continue
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
        item = {'session_date': day, 'status': signal['status'],
                'direction': signal['direction'],
                'usable_count': snapshot.get('usable_count',0),
                'feature_status': {k:v.get('status') for k,v in
                    (snapshot.get('features') or {}).items()}}
        item['agreement_explainability'] = explain_shadow_agreement(snapshot)
        diagnostics = snapshot.get('availability_diagnostics')
        if isinstance(diagnostics, dict) and diagnostics.get('schema') == 'PREMARKET_FEATURE_AVAILABILITY_V1':
            item['availability_diagnostics'] = diagnostics
        decisions.append(item)
    return {'ok': True, 'mode': 'SHADOW_RESEARCH_ONLY',
            'production_promotion': False, 'official_forecast_mutated': False,
            'sessions': len(mornings), 'status_counts': dict(counts),
            'details': decisions,
            'limitations': ['Historical absent features cannot be reconstructed from session outcomes.',
                            'Directional context is not an exact-regime classifier.',
                            'No trained model or out-of-sample accuracy claim.']}

def _archive_lifecycle_context(db, days):
    """Inventory exact-date revisions and canonical source independently, read-only."""
    from .evening_recap import _load, _official_forecast_eligibility
    result = {}
    for day in days:
        records = db.execute(
            'SELECT generated_at,payload_json,is_official FROM apex49_morning_revisions '
            'WHERE session_date=? ORDER BY id ASC', (day,)
        ).fetchall()
        canonical = db.execute(
            'SELECT generated_at,forecast_id,snapshot_hash,payload_json '
            'FROM apex49_morning_snapshots WHERE session_date=?', (day,)
        ).fetchone()
        modes = {}
        same_day_eligible = 0
        for generated_at, raw, official in records:
            payload = _load(raw)
            mode = str((payload.get('session_context') or {}).get('brief_mode') or
                       (payload.get('forecast_identity') or {}).get('brief_mode') or
                       payload.get('brief_mode') or 'UNKNOWN').upper()
            modes[mode] = modes.get(mode, 0) + 1
            eligible, _, target = _official_forecast_eligibility(payload)
            if eligible and target == day:
                same_day_eligible += 1
        canonical_payload = _load(canonical[3]) if canonical else {}
        context = canonical_payload.get('session_context') or {}
        identity = canonical_payload.get('forecast_identity') or {}
        canonical_mode = str(context.get('brief_mode') or identity.get('brief_mode') or
                             canonical_payload.get('brief_mode') or 'UNKNOWN').upper() if canonical else None
        generated = _time(canonical_payload.get('generated_at') or canonical[0]) if canonical else None
        et_date = generated.astimezone(ZoneInfo('America/New_York')).date().isoformat() if generated else None
        canonical_same_day = bool(canonical and canonical_mode == 'PREMARKET' and et_date == day)
        if canonical and not canonical_same_day:
            classification = 'CANONICAL_ORIGIN_REQUIRES_REVIEW'
        elif canonical:
            classification = 'CANONICAL_SAME_DAY_ARCHIVED'
        elif same_day_eligible:
            classification = 'SAME_DAY_REVISION_WITHOUT_CANONICAL'
        elif records:
            classification = 'PREPARATION_OR_NONELIGIBLE_ONLY'
        else:
            classification = 'NO_ARCHIVE_RECORD'
        result[day] = {
            'revision_count': len(records), 'brief_modes': modes,
            'same_day_eligible_revisions': same_day_eligible,
            'has_canonical_snapshot': bool(canonical),
            'canonical_forecast_id': canonical[1] if canonical else None,
            'canonical_snapshot_hash_present': bool(canonical and canonical[2]),
            'canonical_generated_at': canonical[0] if canonical else None,
            'canonical_brief_mode': canonical_mode,
            'canonical_same_day_premarket': canonical_same_day,
            'classification': classification, 'observation_only': True,
        }
    return result


def archived_diagnostics(*, limit=250):
    """Canonical-first read model; never infer directional data from revisions."""
    from .evening_recap import DB_PATH, _load, init_db
    from .canonical_persistence import connect
    init_db()
    with connect(DB_PATH, timeout=10) as db:
        cap = max(1, min(int(limit), 250))
        days = [r[0] for r in db.execute(
            'SELECT session_date FROM apex49_morning_snapshots '
            'UNION SELECT session_date FROM apex49_morning_revisions '
            'ORDER BY session_date DESC LIMIT ?', (cap,)
        ).fetchall()]
        mornings = {}
        for day in days:
            row = db.execute('SELECT payload_json FROM apex49_morning_snapshots '
                             'WHERE session_date=?', (day,)).fetchone()
            mornings[day] = _load(row[0]) if row else {}
        lifecycle = _archive_lifecycle_context(db, days)
    report = archive_diagnostics(mornings)
    for item in report['details']:
        day = item['session_date']
        context = lifecycle[day]
        item['lifecycle'] = context
        item['canonical_presence'] = ('PRESENT' if context['has_canonical_snapshot'] else 'ABSENT')
        item['directional_snapshot_presence'] = ('PRESENT' if item['status'] in (
            'SHADOW_DIRECTIONAL_CONTEXT', 'ABSTAIN_INSUFFICIENT_OR_CONFLICTING_EVIDENCE')
            else 'UNVERIFIED_SCHEMA' if item['status'] == 'UNKNOWN_SCHEMA'
            else 'ABSENT')
        # A historical preparation-occupied canonical is immutable: report for
        # review rather than borrowing a later premarket revision or rewriting it.
        if context['has_canonical_snapshot'] and not context['canonical_same_day_premarket']:
            item['status'] = 'CANONICAL_ORIGIN_REQUIRES_REVIEW'
            item['direction'] = None
            item.pop('feature_status', None)
            item.pop('usable_count', None)
        elif context['has_canonical_snapshot'] and item['status'] == 'SNAPSHOT_NOT_ARCHIVED':
            item['status'] = 'CANONICAL_DIRECTIONAL_SNAPSHOT_NOT_ARCHIVED'
        elif not context['has_canonical_snapshot']:
            item['status'] = context['classification']
            item['direction'] = None
            item['directional_snapshot_presence'] = 'ABSENT'
    report['status_counts'] = dict(Counter(x['status'] for x in report['details']))
    return report
