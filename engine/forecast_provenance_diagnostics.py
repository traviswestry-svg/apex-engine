"""APEX 69.10.37: additive, decision-time forecast provenance; advisory only.

This module reads only the deterministic morning inputs. It never inspects realized
session outcomes, changes a forecast, or synthesizes unavailable quote metadata.
"""
from __future__ import annotations
import math

SCHEMA_VERSION = '69.10.37'


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def capture(dkl, regime):
    em = getattr(dkl, 'expected_move', None)
    spot = _number(getattr(dkl, 'spot', None))
    straddle_em = _number(getattr(em, 'straddle_implied', None))
    iv_em = _number(getattr(em, 'iv_implied', None))
    selected = _number(getattr(em, 'em_1sigma', None))
    selected_path = ('STRADDLE_FIRST' if straddle_em is not None else
                     'IV_FALLBACK' if iv_em is not None else 'UNAVAILABLE')
    rows = []
    for index, line in enumerate(getattr(dkl, 'trade_map', None) or []):
        rows.append({
            'index': index,
            'condition': str(getattr(line, 'condition', '') or ''),
            'implication': str(getattr(line, 'implication', '') or ''),
            'regime_hint': str(getattr(line, 'regime_hint', '') or ''),
            'weight': 1,
        })
    atr = _number(getattr(em, 'atr', None))
    adr = _number(getattr(em, 'avg_daily_range', None))
    agreement = (abs(straddle_em - iv_em) / straddle_em
                 if straddle_em is not None and iv_em is not None and straddle_em > 0
                 else None)
    return {
        'schema_version': SCHEMA_VERSION,
        'capture_stage': 'MORNING_DETERMINISTIC_PRE_OUTCOME',
        'authority': 'DIAGNOSTIC_ONLY_NO_FORECAST_OR_EXECUTION_CHANGE',
        'regime': {
            'selected': regime.get('regime'),
            'source': regime.get('source'),
            'votes': dict(regime.get('vote_counts') or {}),
            'confidence': regime.get('confidence'),
            'vote_rule': 'UNWEIGHTED_TRADE_MAP_PLURALITY_TIES_ABSTAIN',
            'evidence_rows': rows,
        },
        'expected_move': {
            'selected_path': selected_path,
            'selected_one_sigma': selected,
            'reference_spot': spot,
            'upper': _number(getattr(em, 'upper', None)),
            'lower': _number(getattr(em, 'lower', None)),
            'straddle_implied_one_sigma': straddle_em,
            'implied_atm_straddle_premium': (straddle_em / 0.85 if straddle_em is not None else None),
            'iv_implied_one_sigma': iv_em,
            'straddle_iv_relative_divergence': agreement,
            'atr': atr,
            'average_daily_range': adr,
            'atr_to_selected_ratio': (atr / selected if atr is not None and selected and selected > 0 else None),
            'adr_to_full_expected_range_ratio': (adr / (2 * selected) if adr is not None and selected and selected > 0 else None),
            'confidence_heuristic': _number(getattr(em, 'confidence', None)),
            'source_atm_straddle_quote': None,
            'source_atm_iv': None,
            'source_time_to_close_year_fraction': None,
            'option_expiration': None,
            'quote_timestamp': None,
            'quote_age_seconds': None,
            'quote_bid_ask': None,
            'missing_source_metadata': [
                'source_atm_straddle_quote', 'source_atm_iv',
                'source_time_to_close_year_fraction', 'option_expiration',
                'quote_timestamp', 'quote_age_seconds', 'quote_bid_ask',
            ],
            'metadata_note': 'Underlying provider exposes derived values but not raw quote provenance here; null means unverified, not zero.',
        },
    }
