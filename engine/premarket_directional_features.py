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



def magnitude_conflict_diagnostics(snapshot):
    """Descriptive, frozen-only ES magnitude and conflict typology; no signal changes.

    Values have heterogeneous units; their absolute magnitudes must never be
    added or interpreted as independent weights or calibrated confidence.
    """
    agreement = explain_shadow_agreement(snapshot)
    rows = agreement['features']
    required = REQUIRED_DIRECTIONAL_INPUTS
    values = {key: rows[key]['value'] for key in required}
    positive = agreement['positive_votes']
    negative = agreement['negative_votes']
    if agreement['unavailable_required_inputs']:
        typology = 'INCOMPLETE_REQUIRED_EVIDENCE'
    elif agreement['neutral_required_inputs']:
        typology = 'ZERO_REQUIRED_INPUT'
    elif positive == 3:
        typology = 'UNANIMOUS_POSITIVE_ES'
    elif negative == 3:
        typology = 'UNANIMOUS_NEGATIVE_ES'
    elif values['overnight_es_return'] is not None and values['premarket_gap'] is not None and (
        values['overnight_es_return'] * values['premarket_gap'] > 0 and
        values['overnight_vwap_displacement'] * values['overnight_es_return'] < 0
    ):
        typology = ('VWAP_RECOVERY_AGAINST_NEGATIVE_OVERNIGHT' if
                    values['overnight_es_return'] < 0 else
                    'VWAP_PULLBACK_AGAINST_POSITIVE_OVERNIGHT')
    else:
        typology = 'OTHER_REQUIRED_SIGN_CONFLICT'
    features = {}
    for key in FEATURES:
        row = rows[key]
        value = row['value']
        features[key] = {
            'status': row['status'], 'signed_value': value,
            'absolute_magnitude': abs(value) if value is not None else None,
            'unit': ('ES_POINTS' if key == 'overnight_vwap_displacement' else
                     'PERCENT' if key in ('overnight_es_return', 'premarket_gap') else
                     'PROVIDER_FEATURE_UNITS'),
            'direction': row['direction'],
            'required_for_unanimity': row['required_for_unanimity'],
        }
    return {
        'schema': 'PREMARKET_MAGNITUDE_CONFLICT_V1',
        'mode': 'READ_ONLY_FROZEN_EVIDENCE',
        'decision_at': (snapshot or {}).get('decision_at'),
        'conflict_type': typology,
        'agreement_reason': agreement['reason'],
        'features': features,
        'confidence_calibrated': False,
        'independence_verified': False,
        'production_promotion': False,
        'note': 'No magnitude weighting or vote changes; units differ and ES inputs may be correlated.',
    }


def forecast_center_integrity(morning, recap, observation):
    """Audit recorded SPX range arithmetic without modifying official scoring.

    Morning structured values are the frozen source; recap comparison bounds are
    rounded for display. Outcome actual high/low must originate in the completed
    recap. Never substitute later prices for absent source fields.
    """
    from .morning_forecast_shadow_calibration import _number
    structured = (morning.get('structured') or {}) if isinstance(morning, dict) else {}
    move = structured.get('expected_move') or {}
    cmp = recap.get('comparison') or {}
    actual = cmp.get('actual') or {}
    checks = [c for c in (cmp.get('checks') or [])
              if isinstance(c, dict) and c.get('key') == 'expected_move_containment']
    issues = []
    fl, fh = _number(move.get('lower')), _number(move.get('upper'))
    al, ah = _number(actual.get('low')), _number(actual.get('high'))
    if None in (fl, fh) or fl >= fh:
        issues.append('FROZEN_EXPECTED_RANGE_INVALID_OR_ABSENT')
    if None in (al, ah) or al > ah or not actual.get('available'):
        issues.append('COMPLETED_ACTUAL_RANGE_INVALID_OR_ABSENT')
    if len(checks) != 1:
        issues.append('CONTAINMENT_CHECK_MISSING_OR_DUPLICATE')
    if not issues:
        # Original extractor derives its forecast bounds from this display string,
        # whose two-decimal formatting introduces at most half-cent rounding.
        rounded_bounds = (round(fl, 2), round(fh, 2))
        displayed = (round(observation['forecast_center'] - observation['forecast_width']/2, 2),
                     round(observation['forecast_center'] + observation['forecast_width']/2, 2))
        if any(abs(a-b) > 0.011 for a,b in zip(rounded_bounds, displayed)):
            issues.append('RECAP_PROJECTED_BOUNDS_DO_NOT_MATCH_FROZEN_FORECAST')
        if (abs(al - (observation['actual_center']-observation['actual_width']/2)) > 0.0001 or
            abs(ah - (observation['actual_center']+observation['actual_width']/2)) > 0.0001):
            issues.append('RECAP_ACTUAL_BOUNDS_INCONSISTENT')
        expected_contained = al >= fl and ah <= fh
        # Official containment is calculated from unrounded frozen bounds;
        # do not change this definition or its historical result.
        if checks[0].get('correct') is not expected_contained:
            issues.append('OFFICIAL_CONTAINMENT_BOOLEAN_MISMATCH')
        extra = cmp.get('forecast_error_diagnostics') or {}
        range_diag = extra.get('range') or {}
        if range_diag.get('available') is True:
            if _number(range_diag.get('center_error_points')) is not None and abs(
                range_diag['center_error_points'] - ((al+ah-fl-fh)/2)) > 0.011:
                issues.append('OFFICIAL_CENTER_ERROR_DIAGNOSTIC_MISMATCH')
            if isinstance(range_diag.get('contained'), bool) and range_diag['contained'] != expected_contained:
                issues.append('OFFICIAL_RANGE_DIAGNOSTIC_CONTAINMENT_MISMATCH')
        return {
            'schema': 'FORECAST_CENTER_RESIDUAL_INTEGRITY_V1',
            'mode': 'READ_ONLY_EXACT_CANONICAL_AUDIT',
            'status': 'VERIFIED' if not issues else 'INCONSISTENT',
            'issues': issues, 'unit': 'SPX_INDEX_POINTS',
            'forecast_low': fl, 'forecast_high': fh,
            'forecast_center': round((fl+fh)/2, 4),
            'forecast_width': round(fh-fl, 4),
            'actual_low': al, 'actual_high': ah,
            'actual_midrange': round((al+ah)/2, 4),
            'actual_width': round(ah-al, 4),
            'center_residual_points': round((al+ah-fl-fh)/2, 4),
            'high_error_points': round(ah-fh, 4),
            'low_error_points': round(al-fl, 4),
            'width_error_points': round((ah-al)-(fh-fl), 4),
            'high_excess_points': round(max(0.,ah-fh), 4),
            'low_excess_points': round(max(0.,fl-al), 4),
            'contained_from_frozen_bounds': expected_contained,
            'official_containment_check': checks[0].get('correct'),
            'frozen_reference_spot': _number(structured.get('spot')),
            'expected_move_metric': 'MAX_ABS_EXCURSION_FROM_FROZEN_MORNING_SPOT',
            'note': 'Midrange displacement is not open-to-close return. Recap display bounds may be rounded by 0.005 index points.',
        }
    return {'schema': 'FORECAST_CENTER_RESIDUAL_INTEGRITY_V1',
            'mode': 'READ_ONLY_EXACT_CANONICAL_AUDIT',
            'status': 'UNVERIFIABLE', 'issues': issues, 'unit': 'SPX_INDEX_POINTS'}


def forecast_center_construction_provenance(morning):
    """Read immutable morning inputs; do not reconstruct absent provider metadata.

    Structural arithmetic verification is not a raw quote provenance guarantee.
    """
    from .morning_forecast_shadow_calibration import _number
    structured = (morning.get('structured') or {}) if isinstance(morning, dict) else {}
    move = structured.get('expected_move') or {}
    diagnostic = (structured.get('forecast_provenance_diagnostics') or {}).get('expected_move') or {}
    spot, low, high = (_number(structured.get('spot')), _number(move.get('lower')),
                       _number(move.get('upper')))
    sigma = _number(move.get('one_sigma'))
    path = diagnostic.get('selected_path')
    issues = []
    if None in (spot, low, high, sigma) or sigma <= 0 or low >= high:
        issues.append('FROZEN_CENTER_INPUTS_MISSING_OR_INVALID')
    if not diagnostic:
        issues.append('DECISION_TIME_EXPECTED_MOVE_PROVENANCE_ABSENT')
    if not issues:
        if abs((spot + sigma) - high) > .011 or abs((spot - sigma) - low) > .011:
            issues.append('FROZEN_SPOT_SIGMA_BOUNDS_MISMATCH')
        if (_number(diagnostic.get('reference_spot')) is None or
            abs(diagnostic['reference_spot'] - spot) > .011 or
            _number(diagnostic.get('selected_one_sigma')) is None or
            abs(diagnostic['selected_one_sigma'] - sigma) > .011 or
            _number(diagnostic.get('upper')) is None or
            abs(diagnostic['upper'] - high) > .011 or
            _number(diagnostic.get('lower')) is None or
            abs(diagnostic['lower'] - low) > .011):
            issues.append('FROZEN_PROVENANCE_VALUES_MISMATCH')
        straddle = _number(diagnostic.get('straddle_implied_one_sigma'))
        iv = _number(diagnostic.get('iv_implied_one_sigma'))
        if (path == 'STRADDLE_FIRST' and (straddle is None or abs(straddle-sigma) > .011) or
            path == 'IV_FALLBACK' and (straddle is not None or iv is None or abs(iv-sigma) > .011) or
            path not in ('STRADDLE_FIRST', 'IV_FALLBACK')):
            issues.append('SELECTED_EXPECTED_MOVE_PATH_MISMATCH')
    return {
        'schema': 'FORECAST_CENTER_CONSTRUCTION_PROVENANCE_V1',
        'mode': 'READ_ONLY_FROZEN_CONSTRUCTION',
        'status': 'UNVERIFIABLE' if 'FROZEN_CENTER_INPUTS_MISSING_OR_INVALID' in issues or
                  'DECISION_TIME_EXPECTED_MOVE_PROVENANCE_ABSENT' in issues else
                  'INCONSISTENT' if issues else 'ARITHMETIC_VERIFIED_SOURCE_UNVERIFIED',
        'issues': issues, 'reference_spot': spot, 'selected_one_sigma': sigma,
        'forecast_low': low, 'forecast_high': high,
        'forecast_center': round((low+high)/2, 4) if low is not None and high is not None else None,
        'formula': 'LOWER=SPOT-SIGMA;UPPER=SPOT+SIGMA',
        'selected_path': path,
        'straddle_implied_one_sigma': _number(diagnostic.get('straddle_implied_one_sigma')),
        'iv_implied_one_sigma': _number(diagnostic.get('iv_implied_one_sigma')),
        'source_quote_timestamp': diagnostic.get('quote_timestamp'),
        'source_option_expiration': diagnostic.get('option_expiration'),
        'missing_source_metadata': list(diagnostic.get('missing_source_metadata') or []),
        'provider_source_verified': False,
        'note': 'Arithmetic only; unarchived raw option quote, expiry and timing cannot be inferred.',
    }


def shadow_directional_center_sensitivity(morning, *, actual_low=None, actual_high=None):
    """Predeclared what-if offsets from frozen ES return; never used as official predictions.

    The ES return is in percentage points; converting to SPX points using frozen
    SPX spot is an unvalidated cross-instrument proxy. Two fixed sensitivities
    are descriptive, not fitted or selected using the realized outcome.
    """
    from .morning_forecast_shadow_calibration import _number
    provenance = forecast_center_construction_provenance(morning)
    snapshot = ((morning.get('structured') or {}).get('premarket_directional_feature_snapshot') or {})
    row = (snapshot.get('features') or {}).get('overnight_es_return') or {}
    value = _number(row.get('value')) if row.get('status') == 'AVAILABLE' else None
    issues = []
    if provenance['status'] != 'ARITHMETIC_VERIFIED_SOURCE_UNVERIFIED':
        issues.append('CENTER_CONSTRUCTION_NOT_VERIFIED')
    if value is None or not row.get('source') or not _time(row.get('observed_at')) or not _time(row.get('ingested_at')):
        issues.append('VERIFIED_OVERNIGHT_ES_RETURN_UNAVAILABLE')
    decision = _time(snapshot.get('decision_at'))
    if (not decision or (row.get('observed_at') and _time(row.get('observed_at')) > decision) or
        (row.get('ingested_at') and _time(row.get('ingested_at')) > decision)):
        issues.append('FEATURE_TIME_NOT_VERIFIED')
    if issues:
        return {'schema': 'FORECAST_CENTER_SHADOW_DISPLACEMENT_V1',
                'mode': 'READ_ONLY_PREDECLARED_SENSITIVITY', 'status': 'ABSTAIN',
                'issues': issues, 'candidates': [], 'production_promotion': False}
    spot, sigma = provenance['reference_spot'], provenance['selected_one_sigma']
    proxy = spot * value / 100.0
    candidates = []
    for fraction in (0.5, 1.0):
        offset = max(-sigma, min(sigma, proxy*fraction))
        center = spot + offset
        low, high = center-sigma, center+sigma
        candidate = {'sensitivity_fraction': fraction, 'offset_points': round(offset, 4),
                     'shadow_center': round(center, 4), 'shadow_low': round(low, 4),
                     'shadow_high': round(high, 4), 'width_unchanged': True}
        if None not in (actual_low, actual_high):
            candidate['retrospective_abs_center_error'] = round(abs((actual_low+actual_high)/2-center), 4)
            candidate['retrospective_contained'] = actual_low >= low and actual_high <= high
        candidates.append(candidate)
    return {'schema': 'FORECAST_CENTER_SHADOW_DISPLACEMENT_V1',
            'mode': 'READ_ONLY_PREDECLARED_SENSITIVITY', 'status': 'DESCRIPTIVE_ONLY',
            'issues': [], 'input_feature': 'overnight_es_return',
            'frozen_feature_value_percent': value,
            'frozen_feature_observed_at': row.get('observed_at'),
            'frozen_feature_source': row.get('source'),
            'raw_proxy_offset_points': round(proxy, 4),
            'offset_cap_points': sigma, 'candidates': candidates,
            'sample_size_sufficient': False, 'confidence_calibrated': False,
            'production_promotion': False,
            'limitations': ['ES percent return mapped to SPX points is an unvalidated proxy.',
                            'ES, SPX and reference spot can differ in level and timing.',
                            'Sensitivity factors are fixed, not fitted on session outcomes.',
                            'Realized prices are used only for retrospective comparison.']}


def shadow_outcome_attribution(mornings, recaps, *, min_samples=20):
    """Exact-canonical, read-only session-outcome join; never trains on current outcomes.

    Outcomes are descriptive realized *forecast-center residuals*, not market
    open-to-close directional returns. Rejects duplicate recaps and invalid
    canonical origins; never reconstructs unarchived premarket features.
    """
    from .morning_forecast_shadow_calibration import extract_observation
    if min_samples < 2:
        raise ValueError('min_samples must be >= 2')
    recap_counts = Counter(str(x.get('session_date')) for x in recaps if isinstance(x, dict))
    recap_by_day = {str(x.get('session_date')): x for x in recaps if isinstance(x, dict)}
    rows = []
    integrity_exclusions = []
    exclusions = Counter()
    for day, morning in sorted(mornings.items()):
        if not isinstance(morning, dict) or not morning:
            exclusions['NO_CANONICAL_MORNING'] += 1
            continue
        identity = morning.get('canonical_forecast_provenance') or {}
        mode = str((morning.get('session_context') or {}).get('brief_mode') or
                   (morning.get('forecast_identity') or {}).get('brief_mode') or
                   morning.get('brief_mode') or '').upper()
        generated = _time(morning.get('generated_at'))
        generated_day = generated.astimezone(ZoneInfo('America/New_York')).date().isoformat() if generated else None
        if mode != 'PREMARKET' or generated_day != day:
            exclusions['INVALID_CANONICAL_ORIGIN'] += 1
            continue
        snapshot = (morning.get('structured') or {}).get('premarket_directional_feature_snapshot')
        if not isinstance(snapshot, dict) or snapshot.get('schema') != 'PREMARKET_DIRECTIONAL_FEATURES_V1':
            exclusions['DIRECTIONAL_SNAPSHOT_ABSENT'] += 1
            continue
        if recap_counts[day] > 1:
            exclusions['AMBIGUOUS_DUPLICATE_RECAP'] += 1
            continue
        recap = recap_by_day.get(day)
        if recap is None:
            exclusions['NO_COMPLETED_RECAP'] += 1
            continue
        if not identity.get('forecast_id') or not identity.get('snapshot_hash') or (
            recap.get('forecast_id') != identity['forecast_id'] or
            recap.get('forecast_snapshot_hash') != identity['snapshot_hash']
        ):
            exclusions['EXACT_CANONICAL_IDENTITY_MISMATCH'] += 1
            continue
        obs = extract_observation(recap)
        if obs is None:
            exclusions['OUTCOME_INCOMPLETE_OR_INCOMPATIBLE'] += 1
            continue
        integrity = forecast_center_integrity(morning, recap, obs)
        if integrity['status'] != 'VERIFIED':
            exclusions['FORECAST_CENTER_INTEGRITY_' + integrity['status']] += 1
            integrity_exclusions.append({'session_date': day,
                'canonical_forecast_id': identity['forecast_id'],
                'status': integrity['status'], 'issues': integrity['issues']})
            continue
        diagnostic = magnitude_conflict_diagnostics(snapshot)
        construction = forecast_center_construction_provenance(morning)
        sensitivity = shadow_directional_center_sensitivity(morning,
            actual_low=integrity['actual_low'], actual_high=integrity['actual_high'])
        residual = integrity['center_residual_points']
        rows.append({
            'session_date': day,
            'canonical_forecast_id': identity['forecast_id'],
            'decision_at': snapshot.get('decision_at'),
            'conflict_type': diagnostic['conflict_type'],
            'shadow_direction': shadow_direction(snapshot)['direction'],
            'forecast_center_residual_points': round(residual, 4),
            'residual_direction': ('ABOVE_FORECAST_CENTER' if residual > 0 else
                                   'BELOW_FORECAST_CENTER' if residual < 0 else 'AT_FORECAST_CENTER'),
            'forecast_center_integrity': integrity,
            'forecast_center_construction_provenance': construction,
            'shadow_directional_center_sensitivity': sensitivity,
            'actual_session_range_points': round(obs['actual_width'], 4),
            'forecast_contained_actual_range': (
                obs['actual_center']-obs['actual_width']/2 >= obs['forecast_center']-obs['forecast_width']/2 and
                obs['actual_center']+obs['actual_width']/2 <= obs['forecast_center']+obs['forecast_width']/2
            ),
            'outcome_metric': 'REALIZED_SESSION_MIDRANGE_MINUS_FROZEN_FORECAST_CENTER',
        })
    counts = Counter(row['conflict_type'] for row in rows)
    return {'schema': 'PREMARKET_SHADOW_OUTCOME_ATTRIBUTION_V1',
            'mode': 'READ_ONLY_EXACT_CANONICAL_OUTCOMES',
            'status': 'DESCRIPTIVE_SAMPLE_AVAILABLE' if rows else 'NO_ELIGIBLE_MATCHED_OUTCOMES',
            'eligible_sessions': len(rows), 'minimum_for_research_comparison': min_samples,
            'comparison_ready': len(rows) >= min_samples,
            'conflict_type_counts': dict(counts), 'excluded_reasons': dict(exclusions),
            'rows': rows, 'integrity_exclusions': integrity_exclusions,
            'production_promotion': False,
            'official_forecast_mutated': False, 'official_scoring_mutated': False,
            'accuracy_claim': False,
            'limitations': [
                'Outcome direction is relative to frozen forecast center, not SPX open-to-close direction.',
                'No trained model, calibrated confidence, or walk-forward improvement claim.',
                'Actuals are used for retrospective scoring only; never feature construction.',
                'Missing historical feature snapshots cannot be backfilled from outcomes.',
            ]}

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
        item['magnitude_conflict_diagnostics'] = magnitude_conflict_diagnostics(snapshot)
        item['forecast_center_construction_provenance'] = forecast_center_construction_provenance(morning)
        item['shadow_directional_center_sensitivity'] = shadow_directional_center_sensitivity(morning)
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
        recaps = [_load(row[0]) for row in db.execute(
            'SELECT payload_json FROM apex49_evening_recaps WHERE session_date IN ('
            + ','.join('?' for _ in days) + ')', days).fetchall()] if days else []
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
    report['shadow_outcome_attribution'] = shadow_outcome_attribution(mornings, recaps)
    return report
