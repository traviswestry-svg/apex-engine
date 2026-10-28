"""Read-only, strictly chronological morning forecast calibration research.

Uses only completed, canonically bound recaps. Never updates official forecasts,
scorecards, execution decisions, or persisted rows. Shadow predictions are
trained on earlier sessions only, with explicit abstention on sparse evidence.
"""
from __future__ import annotations

from statistics import median
from typing import Iterable

MIN_TRAIN = 20
MAX_TRAIN = 120


def _number(value):
    try:
        n = float(value)
        return n if n == n and abs(n) != float('inf') else None
    except (ValueError, TypeError):
        return None


def extract_observation(recap: dict) -> dict | None:
    """Read recorded frozen morning projection and completed-session result.

    Rejects absent canonical identity; does not reconstruct missing authority
    from later market prices or model-generated narratives.
    """
    if not isinstance(recap, dict) or not recap.get('forecast_id') or not recap.get('forecast_snapshot_hash'):
        return None
    cmp = recap.get('comparison') or {}
    actual = cmp.get('actual') or {}
    if not actual.get('available'):
        return None
    checks = {c.get('key'): c for c in cmp.get('checks') or [] if isinstance(c, dict)}
    containment = checks.get('expected_move_containment') or {}
    move = checks.get('expected_move_size') or {}
    try:
        bounds = str(containment['projected']).split(' to ')
        low, high = (_number(x) for x in bounds)
    except (KeyError, ValueError):
        return None
    actual_low, actual_high = _number(actual.get('low')), _number(actual.get('high'))
    expected, realized = _number(move.get('projected')), _number(move.get('actual'))
    spot = _number(move.get('reference_spot'))
    if None in (low, high, actual_low, actual_high, expected, realized, spot) or high <= low or expected <= 0:
        return None
    if move.get('actual_metric') != 'MAX_ABS_EXCURSION_FROM_FROZEN_MORNING_SPOT':
        return None
    date = str(recap.get('session_date') or actual.get('session_date') or '')
    if len(date) != 10:
        return None
    return {
        'session_date': date, 'forecast_id': recap['forecast_id'],
        'center_error': ((actual_low + actual_high) - (low + high)) / 2,
        'width_error': (actual_high - actual_low) - (high - low),
        'move_error': realized - expected,
        'forecast_center': (low + high) / 2, 'forecast_width': high - low,
        'forecast_move': expected, 'actual_center': (actual_low + actual_high) / 2,
        'actual_width': actual_high - actual_low, 'actual_move': realized,
        'projected_regime': str(cmp.get('projected_regime') or ''),
        'actual_regime': str(cmp.get('actual_regime') or ''),
        'exact_regime': str(cmp.get('projected_regime', '')).upper() == str(cmp.get('actual_regime', '')).upper(),
    }


def shadow_walk_forward(recaps: Iterable[dict], *, min_train: int = MIN_TRAIN, window: int = MAX_TRAIN) -> dict:
    """Median-bias correction evaluated strictly out of sample by session date.

    Each candidate correction uses earlier completed sessions, never the target
    session. This is a research-only diagnostic, not a deployable forecast.
    """
    if min_train < 2 or window < min_train:
        raise ValueError('invalid calibration window')
    observations = [o for r in recaps if (o := extract_observation(r)) is not None]
    observations.sort(key=lambda o: o['session_date'])
    # One frozen official forecast per session. Ambiguous duplicates abstain.
    counts = {}
    for o in observations:
        counts[o['session_date']] = counts.get(o['session_date'], 0) + 1
    observations = [o for o in observations if counts[o['session_date']] == 1]
    evaluated = []
    for idx, current in enumerate(observations):
        prior = observations[max(0, idx - window):idx]
        if len(prior) < min_train:
            continue
        corrections = {k: median(o[k] for o in prior) for k in ('center_error', 'width_error', 'move_error')}
        predicted_center = current['forecast_center'] + corrections['center_error']
        predicted_width = max(0.01, current['forecast_width'] + corrections['width_error'])
        predicted_move = max(0.01, current['forecast_move'] + corrections['move_error'])
        baseline_bounds = (current['forecast_center'] - current['forecast_width']/2, current['forecast_center'] + current['forecast_width']/2)
        shadow_bounds = (predicted_center - predicted_width/2, predicted_center + predicted_width/2)
        actual_bounds = (current['actual_center'] - current['actual_width']/2, current['actual_center'] + current['actual_width']/2)
        evaluated.append({
            'session_date': current['session_date'], 'forecast_id': current['forecast_id'],
            'training_count': len(prior), 'training_through': prior[-1]['session_date'],
            'corrections': {k: round(v, 4) for k, v in corrections.items()},
            'baseline_center_abs_error': abs(current['center_error']),
            'shadow_center_abs_error': abs(current['actual_center'] - predicted_center),
            'baseline_move_abs_error': abs(current['move_error']),
            'shadow_move_abs_error': abs(current['actual_move'] - predicted_move),
            'baseline_width': current['forecast_width'], 'shadow_width': predicted_width,
            'actual_width': current['actual_width'],
            'baseline_contained': baseline_bounds[0] <= actual_bounds[0] and baseline_bounds[1] >= actual_bounds[1],
            'shadow_contained': shadow_bounds[0] <= actual_bounds[0] and shadow_bounds[1] >= actual_bounds[1],
        })
    def mean(field):
        return round(sum(row[field] for row in evaluated) / len(evaluated), 4) if evaluated else None
    return {
        'mode': 'SHADOW_RESEARCH_ONLY', 'production_promotion': False,
        'official_forecast_mutated': False, 'official_scoring_mutated': False,
        'status': 'EVALUATED' if evaluated else 'INSUFFICIENT_CHRONOLOGICAL_HISTORY',
        'eligible_sessions': len(observations), 'evaluated_sessions': len(evaluated),
        'min_train': min_train, 'window': window,
        'baseline_center_mae': mean('baseline_center_abs_error'),
        'shadow_center_mae': mean('shadow_center_abs_error'),
        'baseline_move_mae': mean('baseline_move_abs_error'),
        'shadow_move_mae': mean('shadow_move_abs_error'),
        'baseline_containment_rate': mean('baseline_contained'),
        'shadow_containment_rate': mean('shadow_contained'),
        'evaluations': evaluated,
    }


def archived_shadow_report(*, limit: int = 250, min_train: int = MIN_TRAIN) -> dict:
    """Load archived recaps without writing or initiating data collection."""
    from .evening_recap import DB_PATH, _load, init_db
    from .canonical_persistence import connect
    init_db()
    with connect(DB_PATH, timeout=10) as db:
        rows = db.execute('SELECT payload_json FROM apex49_evening_recaps ORDER BY session_date DESC LIMIT ?', (max(1, min(int(limit), 250)),)).fetchall()
    return shadow_walk_forward([_load(row[0]) for row in rows], min_train=min_train)


def forecast_precision_report(recaps, *, min_train=MIN_TRAIN, window=MAX_TRAIN):
    """Read-only precision report with strictly chronological shadow comparisons."""
    raw = list(recaps)
    observations = [o for r in raw if (o := extract_observation(r)) is not None]
    counts = {}
    for o in observations:
        counts[o['session_date']] = counts.get(o['session_date'], 0) + 1
    observations = sorted((o for o in observations if counts[o['session_date']] == 1),
                          key=lambda o: o['session_date'])
    def avg(values):
        return round(sum(values) / len(values), 4) if values else None
    walk = shadow_walk_forward(raw, min_train=min_train, window=window)
    rows = walk['evaluations']
    def precision(prefix):
        return {
            'sessions': len(rows),
            'containment_rate': avg([float(r[prefix + '_contained']) for r in rows]),
            'range_width_to_realized_ratio': avg([r[prefix + '_width'] / r['actual_width']
                for r in rows if r['actual_width'] > 0]),
            'center_mae': avg([r[prefix + '_center_abs_error'] for r in rows]),
            'move_mae': avg([r[prefix + '_move_abs_error'] for r in rows]),
        }
    confusion = {}
    for o in observations:
        pair = o['projected_regime'] + ' -> ' + o['actual_regime']
        confusion[pair] = confusion.get(pair, 0) + 1
    return {
        'ok': True, 'mode': 'SHADOW_RESEARCH_ONLY', 'production_promotion': False,
        'official_forecast_mutated': False, 'official_scoring_mutated': False,
        'status': walk['status'], 'eligible_sessions': len(observations),
        'evaluated_sessions': len(rows), 'min_train': min_train, 'window': window,
        'full_archive_diagnostics': {
            'range_center_signed_bias': avg([o['center_error'] for o in observations]),
            'range_center_mae': avg([abs(o['center_error']) for o in observations]),
            'range_width_signed_bias': avg([o['width_error'] for o in observations]),
            'move_signed_bias': avg([o['move_error'] for o in observations]),
            'exact_regime_accuracy': avg([float(o['exact_regime']) for o in observations]),
            'regime_confusion': confusion,
        },
        'out_of_sample': {'baseline': precision('baseline'), 'shadow': precision('shadow')},
        'evaluation_details': rows,
        'limitations': ['Canonical completed recaps only',
                        'Containment must be read alongside range-width efficiency',
                        'No automatic promotion or official forecast changes'],
    }


def archived_precision_report(*, limit=250, min_train=MIN_TRAIN, window=MAX_TRAIN):
    """Bounded, read-only access to the existing canonical recap archive."""
    from .evening_recap import DB_PATH, _load, init_db
    from .canonical_persistence import connect
    init_db()
    with connect(DB_PATH, timeout=10) as db:
        rows = db.execute('SELECT payload_json FROM apex49_evening_recaps '
                          'ORDER BY session_date DESC LIMIT ?',
                          (max(1, min(int(limit), 250)),)).fetchall()
    return forecast_precision_report([_load(row[0]) for row in rows],
                                     min_train=min_train, window=window)
