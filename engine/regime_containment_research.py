"""Read-only archived vote evidence, recap eligibility and containment research."""
from __future__ import annotations
from collections import Counter
from statistics import median
from .morning_forecast_shadow_calibration import extract_observation


def audit_archive(recaps, mornings):
    exclusions = []
    evidence = []
    for recap in recaps:
        day = str(recap.get('session_date') or '')
        obs = extract_observation(recap)
        if obs is None:
            reasons = []
            if not recap.get('forecast_id') or not recap.get('forecast_snapshot_hash'):
                reasons.append('MISSING_CANONICAL_FORECAST_IDENTITY')
            cmp = recap.get('comparison') or {}
            if not (cmp.get('actual') or {}).get('available'):
                reasons.append('ACTUAL_SESSION_UNAVAILABLE')
            checks = {c.get('key'): c for c in cmp.get('checks') or [] if isinstance(c, dict)}
            if 'expected_move_containment' not in checks or 'expected_move_size' not in checks:
                reasons.append('REQUIRED_FORECAST_CHECK_MISSING')
            if (checks.get('expected_move_size') or {}).get('actual_metric') != 'MAX_ABS_EXCURSION_FROM_FROZEN_MORNING_SPOT':
                reasons.append('EXPECTED_MOVE_METRIC_INCOMPATIBLE')
            exclusions.append({'session_date': day, 'reasons': reasons or ['INVALID_OR_INCOMPLETE_NUMERIC_FIELDS']})
            continue
        morning = mornings.get(day)
        if not morning:
            status = 'MORNING_ARCHIVE_MISSING'
            vote = None
        else:
            canonical = morning.get('canonical_forecast_provenance') or {}
            if canonical.get('forecast_id') != recap.get('forecast_id') or canonical.get('snapshot_hash') != recap.get('forecast_snapshot_hash'):
                status = 'MORNING_ARCHIVE_IDENTITY_MISMATCH'
                vote = None
            else:
                structured = morning.get('structured') or {}
                provenance = structured.get('forecast_provenance_diagnostics') or {}
                vote = provenance.get('regime')
                if not isinstance(vote, dict) or 'evidence_rows' not in vote:
                    status = 'VOTE_EVIDENCE_NOT_ARCHIVED'
                    vote = None
                else:
                    status = 'VOTE_EVIDENCE_ARCHIVED'
        evidence.append({'session_date': day, 'forecast_id': obs['forecast_id'],
                         'projected_regime': obs['projected_regime'], 'status': status,
                         'vote_evidence': vote})
    counts = Counter(r['session_date'] for r in evidence)
    duplicates = sorted(k for k, v in counts.items() if v > 1)
    return {'eligible_sessions': sum(v == 1 for v in counts.values()),
            'excluded_sessions': len(exclusions), 'excluded_details': exclusions,
            'ambiguous_duplicate_dates': duplicates,
            'vote_evidence_status_counts': dict(Counter(x['status'] for x in evidence)),
            'vote_evidence': evidence,
            'limitations': ['Missing archived vote rows cannot be reconstructed from recap outcomes.',
                            'Existing immutable morning records are never overwritten.']}


def containment_research(recaps, *, min_train=8, window=120):
    """Past-only grid comparison with width penalty; never changes official bounds."""
    if not 2 <= min_train <= window <= 250:
        raise ValueError('invalid training window')
    observations = [o for r in recaps if (o := extract_observation(r)) is not None]
    counts = Counter(o['session_date'] for o in observations)
    obs = sorted((o for o in observations if counts[o['session_date']] == 1), key=lambda o: o['session_date'])
    candidates = {'baseline': (0, 0), 'center_only': (1, 0),
                  'center_and_width': (1, 1), 'conservative_half_width': (1, .5)}
    evaluations = []
    for i, current in enumerate(obs):
        prior = obs[max(0, i-window):i]
        if len(prior) < min_train:
            continue
        center_bias = median(x['center_error'] for x in prior)
        width_bias = median(x['width_error'] for x in prior)
        methods = {}
        for name, (center_weight, width_weight) in candidates.items():
            center = current['forecast_center'] + center_weight * center_bias
            width = max(.01, current['forecast_width'] + width_weight * width_bias)
            actual_low = current['actual_center'] - current['actual_width']/2
            actual_high = current['actual_center'] + current['actual_width']/2
            contained = center-width/2 <= actual_low and center+width/2 >= actual_high
            # Width penalty discourages trivial containment by inflation.
            width_ratio = width / current['actual_width'] if current['actual_width'] > 0 else None
            methods[name] = {'contained': contained, 'width': round(width, 4),
                             'width_to_realized': round(width_ratio, 4) if width_ratio is not None else None,
                             'center_abs_error': round(abs(current['actual_center'] - center), 4),
                             'excess_width_points': round(max(0, width-current['actual_width']), 4)}
        evaluations.append({'session_date': current['session_date'],
                            'training_through': prior[-1]['session_date'],
                            'training_count': len(prior), 'methods': methods})
    summaries = {}
    for name in candidates:
        rows = [e['methods'][name] for e in evaluations]
        n = len(rows)
        summaries[name] = {'sessions': n,
            'containment_rate': round(sum(r['contained'] for r in rows)/n, 4) if n else None,
            'center_mae': round(sum(r['center_abs_error'] for r in rows)/n, 4) if n else None,
            'mean_width_to_realized': round(sum(r['width_to_realized'] for r in rows if r['width_to_realized'] is not None)/sum(r['width_to_realized'] is not None for r in rows), 4) if any(r['width_to_realized'] is not None for r in rows) else None,
            'mean_excess_width_points': round(sum(r['excess_width_points'] for r in rows)/n, 4) if n else None}
    return {'status': 'EVALUATED' if evaluations else 'INSUFFICIENT_CHRONOLOGICAL_HISTORY',
            'evaluated_sessions': len(evaluations), 'min_train': min_train,
            'methods': summaries, 'evaluation_details': evaluations,
            'production_promotion': False,
            'note': 'Candidates are fixed in advance; retrospective actual widths are used for scoring only.'}


def archived_report(*, limit=250, min_train=8):
    from .evening_recap import DB_PATH, _load, init_db
    from .canonical_persistence import connect
    init_db()
    with connect(DB_PATH, timeout=10) as db:
        recaps = [_load(row[0]) for row in db.execute(
            'SELECT payload_json FROM apex49_evening_recaps ORDER BY session_date DESC LIMIT ?',
            (max(1, min(int(limit), 250)),)).fetchall()]
        mornings = {date: _load(payload) for date, payload in db.execute(
            'SELECT session_date,payload_json FROM apex49_morning_snapshots ORDER BY session_date DESC LIMIT ?',
            (max(1, min(int(limit), 250)),)).fetchall()}
    return {'ok': True, 'mode': 'READ_ONLY_PROVENANCE_AND_CONTAINMENT_RESEARCH',
            'production_promotion': False, 'official_forecast_mutated': False,
            'official_scoring_mutated': False,
            'archive': audit_archive(recaps, mornings),
            'containment': containment_research(recaps, min_train=min_train)}
