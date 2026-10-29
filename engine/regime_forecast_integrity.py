"""Read-only forecast-regime provenance and conditional calibration diagnostics.

Never reconstructs missing decision-time forecasts from outcome data.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from statistics import median
from .morning_forecast_shadow_calibration import extract_observation, shadow_walk_forward


def diagnose(recaps, morning_by_date=None, *, exploratory_min_train=8):
    morning_by_date = morning_by_date or {}
    records = []
    excluded = Counter()
    for recap in recaps:
        obs = extract_observation(recap)
        if obs is None:
            excluded['INELIGIBLE_OR_INCOMPLETE_RECAP'] += 1
            continue
        day = obs['session_date']
        morning = morning_by_date.get(day)
        provenance = 'MORNING_ARCHIVE_UNAVAILABLE'
        source = None
        confidence = None
        votes = {}
        spot = None
        reference_status = 'UNVERIFIABLE_WITHOUT_MORNING_ARCHIVE'
        if morning:
            structured = morning.get('structured') or {}
            canonical = morning.get('canonical_forecast_provenance') or {}
            if (canonical.get('forecast_id') == recap.get('forecast_id') and
                    canonical.get('snapshot_hash') == recap.get('forecast_snapshot_hash')):
                provenance = 'ARCHIVE_IDENTITY_MATCH'
                source = structured.get('forecast_regime_source')
                confidence = structured.get('forecast_regime_confidence')
                votes = structured.get('forecast_regime_vote_counts') or {}
                spot = structured.get('spot')
                check = next((c for c in (recap.get('comparison') or {}).get('checks', [])
                              if c.get('key') == 'expected_move_size'), {})
                try:
                    reference_status = ('MATCH' if abs(float(spot) - float(check['reference_spot'])) < 0.011
                                        else 'MISMATCH')
                except (ValueError, TypeError, KeyError):
                    reference_status = 'REFERENCE_UNAVAILABLE'
            else:
                provenance = 'ARCHIVE_IDENTITY_MISMATCH'
                reference_status = 'UNVERIFIED_ARCHIVE_IDENTITY'
        records.append({**obs, 'regime_source': source, 'regime_confidence': confidence,
                        'regime_vote_counts': votes, 'provenance_status': provenance,
                        'reference_status': reference_status, 'morning_reference_spot': spot})
    counts = Counter(r['session_date'] for r in records)
    unique = [r for r in records if counts[r['session_date']] == 1]
    excluded['AMBIGUOUS_DUPLICATE_SESSIONS'] = sum(v for v in counts.values() if v > 1)
    labels = Counter(r['projected_regime'] for r in unique)
    actuals = Counter(r['actual_regime'] for r in unique)
    sources = Counter(r['regime_source'] or r['provenance_status'] for r in unique)
    reference = Counter(r['reference_status'] for r in unique)
    by_actual = defaultdict(list)
    for r in unique:
        by_actual[r['actual_regime']].append(r)
    cohorts = {name: {'sessions': len(group),
                      'median_move_error': round(median(x['move_error'] for x in group), 4),
                      'median_center_error': round(median(x['center_error'] for x in group), 4),
                      'median_width_error': round(median(x['width_error'] for x in group), 4)}
               for name, group in sorted(by_actual.items())}
    # Exploratory diagnostics are not promotion evidence; default formal threshold stays 20.
    exploratory = shadow_walk_forward(recaps, min_train=exploratory_min_train)
    return {'ok': True, 'mode': 'READ_ONLY_REGIME_INTEGRITY_DIAGNOSTICS',
            'production_promotion': False, 'official_forecast_mutated': False,
            'official_scoring_mutated': False, 'eligible_sessions': len(unique),
            'excluded': dict(excluded), 'projected_regime_counts': dict(labels),
            'actual_regime_counts': dict(actuals), 'regime_source_counts': dict(sources),
            'reference_integrity_counts': dict(reference),
            'all_same_projected_regime': len(labels) == 1 and bool(unique),
            'exact_regime_accuracy': (round(sum(r['exact_regime'] for r in unique) / len(unique), 4)
                                      if unique else None),
            'conditional_actual_regime_diagnostics': cohorts,
            'exploratory': {'status': exploratory['status'],
                            'min_train': exploratory_min_train,
                            'evaluated_sessions': exploratory['evaluated_sessions'],
                            'baseline_center_mae': exploratory['baseline_center_mae'],
                            'shadow_center_mae': exploratory['shadow_center_mae'],
                            'baseline_move_mae': exploratory['baseline_move_mae'],
                            'shadow_move_mae': exploratory['shadow_move_mae'],
                            'baseline_containment_rate': exploratory['baseline_containment_rate'],
                            'shadow_containment_rate': exploratory['shadow_containment_rate'],
                            'production_promotion': False},
            'limitations': ['Regime cohorts use actual outcomes for retrospective diagnosis only, never as premarket features.',
                            'Missing morning archive prevents determining whether Balanced Auction was a genuine trade-map vote.',
                            'Exploratory validation is not sufficient for production promotion.']}


def archived_report(*, limit=250, exploratory_min_train=8):
    from .evening_recap import DB_PATH, _load, init_db
    from .canonical_persistence import connect
    init_db()
    with connect(DB_PATH, timeout=10) as db:
        recaps = [_load(row[0]) for row in db.execute(
            'SELECT payload_json FROM apex49_evening_recaps ORDER BY session_date DESC LIMIT ?',
            (max(1, min(int(limit), 250)),)).fetchall()]
        mornings = {}
        for date, payload in db.execute(
            'SELECT session_date,payload_json FROM apex49_morning_snapshots ORDER BY session_date DESC LIMIT ?',
            (max(1, min(int(limit), 250)),)).fetchall():
            mornings[date] = _load(payload)
    return diagnose(recaps, mornings, exploratory_min_train=exploratory_min_train)
