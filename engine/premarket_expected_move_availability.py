"""Decision-time options source availability and counterfactual fallback inventory.

Only frozen upstream evidence is inspected. Research-only: does not change
expected-move selection, treat prior-session prices as fresh, or fetch data.
"""
from __future__ import annotations

from datetime import datetime, time, timezone
from math import isfinite, sqrt
from zoneinfo import ZoneInfo

SCHEMA = 'PREMARKET_EXPECTED_MOVE_AVAILABILITY_V1'
ET = ZoneInfo('America/New_York')


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _dt(value):
    if not isinstance(value, str):
        return None
    try:
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return value.astimezone(timezone.utc) if value.tzinfo else None
    except ValueError:
        return None


def capture(expected_move_source, frozen_source_audit, *, decision_at, reference_spot):
    """Freeze additive research context beside the quote audit BEFORE archival.

    Provider entitlements, actual market-wide availability and GTH trading
    eligibility cannot be determined from a failed/missing options quote.
    """
    source = expected_move_source if isinstance(expected_move_source, dict) else {}
    audit = frozen_source_audit if isinstance(frozen_source_audit, dict) else {}
    decision = _dt(decision_at)
    et = decision.astimezone(ET) if decision else None
    weekday = et.weekday() if et else None
    regular = bool(et and weekday < 5 and time(9, 30) <= et.time() < time(16, 0))
    hours = ('WITHIN_US_REGULAR_SESSION_CLOCK' if regular else
             'OUTSIDE_US_REGULAR_SESSION_CLOCK' if et else 'DECISION_TIME_UNVERIFIABLE')
    legs = audit.get('quote_legs') or {}
    snapshots = {}
    fresh = True
    prior_day = True
    for side in ('call', 'put'):
        leg = legs.get(side) if isinstance(legs, dict) else None
        leg = leg if isinstance(leg, dict) else {}
        quote = _dt(leg.get('provider_quote_timestamp'))
        quote_et = quote.astimezone(ET) if quote else None
        age = _number(leg.get('quote_age_at_decision_seconds'))
        bid, ask = _number(leg.get('bid')), _number(leg.get('ask'))
        valid_mid = (leg.get('method') == 'mid' and bid is not None and ask is not None
                     and bid > 0 and ask >= bid and _number(leg.get('mid')) is not None
                     and _number(leg.get('mid')) > 0)
        computed_age = (decision - quote).total_seconds() if decision and quote else None
        fresh = fresh and bool(valid_mid and age is not None and computed_age is not None and
                               0 <= age <= 120 and 0 <= computed_age <= 120 and
                               abs(age - computed_age) <= 2.0)
        is_prior = bool(et and quote_et and quote_et.date() < et.date())
        prior_day = prior_day and is_prior
        snapshots[side] = {
            'provider_event_at': leg.get('provider_quote_timestamp'),
            'provider_event_et_date': quote_et.date().isoformat() if quote_et else None,
            'age_seconds_at_decision': age,
            'price_method': leg.get('method'),
            'two_sided_positive_market': valid_mid,
            'prior_calendar_day_event': is_prior,
        }
    issues = audit.get('issues') or []
    audit_status = audit.get('status')
    if audit_status == 'SOURCE_VERIFIED' and fresh and not issues and decision:
        availability = 'FRESH_TWO_SIDED_SOURCE_AUDITED'
    elif prior_day and all(snapshots[s]['price_method'] == 'last_trade' for s in ('call', 'put')):
        availability = 'PRIOR_DAY_LAST_TRADE_FALLBACK_ONLY'
    elif audit_status in ('DEGRADED_SOURCE_EVIDENCE', 'REJECTED_INTEGRITY'):
        availability = 'CURRENT_QUOTE_UNVERIFIED_OR_DEGRADED'
    else:
        availability = 'SOURCE_AVAILABILITY_UNDETERMINED'
    premium = _number(audit.get('source_atm_straddle_premium'))
    iv = _number(audit.get('source_atm_iv'))
    t = _number(audit.get('time_to_expiry_year_fraction'))
    spot = _number(reference_spot)
    iv_possible = bool(iv is not None and iv > 0 and t is not None and t > 0 and
                       spot is not None and spot > 0)
    iv_sigma = spot * iv * sqrt(t) if iv_possible else None
    # The original quote audit does not contain a separately attested IV event
    # timestamp; even numerically complete IV is NOT deemed source verified.
    provider_status = source.get('provider_status') if isinstance(source.get('provider_status'), str) else None
    return {
        'schema': SCHEMA, 'mode': 'READ_ONLY_FROZEN_PRE_OUTCOME_AVAILABILITY',
        'decision_at': decision.isoformat() if decision else None,
        'decision_et': et.isoformat() if et else None,
        'regular_session_clock_context': hours,
        'option_market_wide_availability_verified': False,
        'provider_entitlement_verified': False,
        'provider_status_as_reported': provider_status,
        'availability': availability,
        'frozen_source_audit_status': audit_status,
        'quote_legs': snapshots,
        'candidate_evidence': {
            'original_selected': {
                'method': audit.get('selected_path'), 'one_sigma': _number(audit.get('selected_one_sigma')),
                'is_fresh_source_verified': availability == 'FRESH_TWO_SIDED_SOURCE_AUDITED',
            },
            'prior_session_straddle': {
                'status': 'PRIOR_DAY_LAST_TRADE_UNVERIFIED' if prior_day and premium is not None and premium > 0 else 'NOT_AVAILABLE',
                'premium': premium if prior_day else None,
                'illustrative_one_sigma': round(.85 * premium, 6) if prior_day and premium is not None and premium > 0 else None,
                'allowed_as_fresh_quote': False,
            },
            'iv_fallback': {
                'status': 'NUMERIC_IV_AVAILABLE_SOURCE_UNVERIFIED' if iv_possible else 'NO_COMPLETE_DECISION_TIME_IV_INPUT',
                'illustrative_one_sigma': round(iv_sigma, 6) if iv_sigma is not None else None,
                'independent_provider_timestamp_verified': False,
            },
        },
        'cause_assessment': {
            'regular_session_clock_outside': hours == 'OUTSIDE_US_REGULAR_SESSION_CLOCK',
            'options_trading_closed_confirmed': False,
            'provider_failure_confirmed': False,
            'entitlement_failure_confirmed': False,
            'reason': 'MARKET_OR_PROVIDER_CAUSE_NOT_INFERABLE_FROM_ARCHIVED_QUOTE_EVIDENCE',
        },
        'production_promotion': False, 'official_forecast_mutated': False,
        'official_scoring_mutated': False,
        'note': ('US regular-session clock is not proof that global options trading was closed. '
                 'Provider availability/entitlements require independently frozen provider evidence. '
                 'Counterfactual values are descriptive only; do not replace official forecast.'),
    }


def visibility(morning):
    """Retrieve the archived decision-time assessment verbatim, never backfill it."""
    structured = morning.get('structured') if isinstance(morning, dict) else None
    source = ((structured or {}).get('forecast_provenance_diagnostics') or {}).get('expected_move') or {}
    row = source.get('premarket_source_availability')
    if not isinstance(row, dict) or row.get('schema') != SCHEMA:
        return {
            'schema': 'PREMARKET_EXPECTED_MOVE_AVAILABILITY_VISIBILITY_V1',
            'mode': 'READ_ONLY_FROZEN_CANONICAL_SOURCE',
            'status': 'LEGACY_AVAILABILITY_NOT_ARCHIVED',
            'frozen_availability': None,
            'production_promotion': False,
            'note': 'No retrospective quote collection, time substitution or inferred prior-session archive.',
        }
    return {
        'schema': 'PREMARKET_EXPECTED_MOVE_AVAILABILITY_VISIBILITY_V1',
        'mode': 'READ_ONLY_FROZEN_CANONICAL_SOURCE',
        'status': 'FROZEN_AVAILABILITY_AVAILABLE',
        'frozen_availability': row,
        'production_promotion': False,
    }
