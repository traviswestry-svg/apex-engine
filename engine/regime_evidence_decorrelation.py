"""APEX regime de-correlation and directional range research (read-only).

Only decision-time archived vote rows are features. Completed actuals are labels
used for retrospective scoring, never for predicting the same session.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from statistics import median
from .regime_containment_research import audit_archive
from .morning_forecast_shadow_calibration import extract_observation

FAMILY = {'Below PDH': 'prior_range', 'Above PDL': 'prior_range',
          'Inside value': 'value', 'Outside value': 'value',
          'Dealer gamma regime:': 'dealer_gamma',
          'Inside expected move': 'expected_move',
          'Outside expected move': 'expected_move',
          'Above reported zero-gamma': 'gamma_reference',
          'Below reported zero-gamma': 'gamma_reference'}
REGIME = {'balance': 'Balanced Auction', 'mean_reversion': 'Mean Reversion',
          'expansion': 'Expansion', 'momentum': 'Trend', 'trend': 'Trend',
          'compression': 'Compression'}


def _family(condition):
    return next((family for prefix, family in FAMILY.items()
                 if str(condition).startswith(prefix)), 'unclassified')


def classify_families(vote):
    """One vote maximum per evidence family; conflict in a family abstains.

    Never interpret absent evidence as a Balanced Auction vote.
    """
    if not isinstance(vote, dict) or not isinstance(vote.get('evidence_rows'), list):
        return {'status': 'MISSING_DECISION_TIME_EVIDENCE', 'selected': None}
    families = defaultdict(set)
    for row in vote['evidence_rows']:
        if not isinstance(row, dict):
            continue
        family = _family(row.get('condition'))
        regime = REGIME.get(str(row.get('regime_hint') or '').lower())
        if family != 'unclassified' and regime:
            families[family].add(regime)
    resolved = {k: next(iter(v)) for k,v in families.items() if len(v)==1}
    conflicts = sorted(k for k,v in families.items() if len(v)>1)
    counts = Counter(resolved.values())
    if not counts:
        return {'status': 'ABSTAIN_NO_INDEPENDENT_EVIDENCE', 'selected': None,
                'family_votes': resolved, 'conflicts': conflicts}
    leaders = counts.most_common()
    if len(leaders)>1 and leaders[0][1]==leaders[1][1]:
        status, selected = 'ABSTAIN_FAMILY_TIE', None
    else:
        status, selected = 'SHADOW_CLASSIFIED', leaders[0][0]
    return {'status': status, 'selected': selected,
            'family_votes': resolved, 'conflicts': conflicts,
            'vote_counts': dict(counts),
            'independent_family_count': len(resolved),
            'vote_share_not_calibrated_confidence': (round(leaders[0][1]/len(resolved),4)
                                                      if resolved else None)}


def directional_signal(vote):
    """Only explicit directional premarket signals; no inference from realized session."""
    if not isinstance(vote, dict):
        return {'status':'NO_DIRECTIONAL_PREMARKET_EVIDENCE','direction':None}
    signs=[]
    for row in vote.get('evidence_rows') or []:
        if not isinstance(row,dict):
            continue
        # Existing generic PDH/PDL and gamma rows are non-directional by design.
        # Do not infer bullish/bearish direction from proximity alone.
        if row.get('directional_evidence_verified') is True and row.get('as_of_morning') is True:
            signal=str(row.get('direction') or '').upper()
            if signal in ('BULLISH','BEARISH'):
                signs.append(1 if signal=='BULLISH' else -1)
    if not signs or sum(signs)==0:
        return {'status':'NO_DIRECTIONAL_PREMARKET_EVIDENCE','direction':None}
    return {'status':'DIRECTIONAL_EVIDENCE_AVAILABLE',
            'direction':'BULLISH' if sum(signs)>0 else 'BEARISH',
            'verified_rows':len(signs)}


def evaluate(recaps, mornings, *, min_train=8, window=120):
    """Compare frozen baseline, family-aware classification, and conservative
    direction-gated center correction; strict past-only training.
    """
    if not 2<=min_train<=window<=250:
        raise ValueError('invalid training window')
    audit=audit_archive(recaps,mornings)
    records=[]
    counts=Counter()
    for recap in recaps:
        o=extract_observation(recap)
        if o: counts[o['session_date']]+=1
    for recap in recaps:
        o=extract_observation(recap)
        if not o or counts[o['session_date']]!=1: continue
        morning=mornings.get(o['session_date']) or {}
        canonical=morning.get('canonical_forecast_provenance') or {}
        if canonical.get('forecast_id')!=recap.get('forecast_id') or canonical.get('snapshot_hash')!=recap.get('forecast_snapshot_hash'):
            vote=None
        else:
            vote=((morning.get('structured') or {}).get('forecast_provenance_diagnostics') or {}).get('regime')
        family=classify_families(vote)
        direction=directional_signal(vote)
        actual=str((recap.get('comparison') or {}).get('actual_regime') or '')
        records.append({'date':o['session_date'],'observation':o,'actual_regime':actual,
                        'family':family,'direction':direction})
    records.sort(key=lambda r:r['date'])
    evaluated=[]
    for i,r in enumerate(records):
        prior=records[max(0,i-window):i]
        if len(prior)<min_train: continue
        o=r['observation']; signal=r['direction']['direction']
        # Median signed center displacement is learned only from prior completed sessions.
        # Do not apply it unless a verified decision-time direction agrees with its sign.
        historical=median(p['observation']['center_error'] for p in prior)
        shift=(max(0,historical) if signal=='BULLISH' else min(0,historical)
               if signal=='BEARISH' else 0.0)
        actual_low=o['actual_center']-o['actual_width']/2
        actual_high=o['actual_center']+o['actual_width']/2
        def metrics(center):
            half=o['forecast_width']/2
            return {'contained': center-half<=actual_low and center+half>=actual_high,
                    'center_abs_error':round(abs(o['actual_center']-center),4),
                    'width':round(o['forecast_width'],4),
                    'width_to_realized':round(o['forecast_width']/o['actual_width'],4) if o['actual_width']>0 else None}
        evaluated.append({'session_date':r['date'],'training_through':prior[-1]['date'],
                          'family_prediction':r['family']['selected'],
                          'actual_regime':r['actual_regime'],
                          'direction_status':r['direction']['status'],
                          'center_shift':round(shift,4),
                          'baseline':metrics(o['forecast_center']),
                          'direction_gated':metrics(o['forecast_center']+shift)})
    eligible=[r for r in records if r['family']['status']=='SHADOW_CLASSIFIED' and r['actual_regime']]
    def aggregate(name):
        rows=[r[name] for r in evaluated]
        return {'sessions':len(rows),
                'containment_rate':round(sum(x['contained'] for x in rows)/len(rows),4) if rows else None,
                'center_mae':round(sum(x['center_abs_error'] for x in rows)/len(rows),4) if rows else None,
                'mean_width_to_realized':round(sum(x['width_to_realized'] for x in rows if x['width_to_realized'] is not None)/sum(x['width_to_realized'] is not None for x in rows),4) if any(x['width_to_realized'] is not None for x in rows) else None}
    return {'ok':True,'mode':'SHADOW_RESEARCH_ONLY','production_promotion':False,
            'official_forecast_mutated':False,'official_scoring_mutated':False,
            'archive_summary':{'eligible_sessions':audit['eligible_sessions'],
                               'excluded_sessions':audit['excluded_sessions'],
                               'vote_evidence_status_counts':audit['vote_evidence_status_counts']},
            'family_classification':{'classified_sessions':len(eligible),
                'exact_accuracy':round(sum(r['family']['selected']==r['actual_regime'] for r in eligible)/len(eligible),4) if eligible else None,
                'abstentions':dict(Counter(r['family']['status'] for r in records if r['family']['selected'] is None)),
                'predicted_counts':dict(Counter(r['family']['selected'] for r in eligible))},
            'directional_evidence_status':dict(Counter(r['direction']['status'] for r in records)),
            'walk_forward':{'evaluated_sessions':len(evaluated),'min_train':min_train,
                            'baseline':aggregate('baseline'),'direction_gated':aggregate('direction_gated'),
                            'details':evaluated},
            'limitations':['No actual-session regime or prices used as decision-time features.',
                           'Archived generic vote rows do not establish directional signal.',
                           'Vote share is not calibrated probability.',
                           'Small exploratory sample cannot authorize promotion.']}


def archived_report(*, limit=250, min_train=8):
    from .evening_recap import DB_PATH, _load, init_db
    from .canonical_persistence import connect
    init_db()
    with connect(DB_PATH,timeout=10) as db:
        recaps=[_load(row[0]) for row in db.execute('SELECT payload_json FROM apex49_evening_recaps ORDER BY session_date DESC LIMIT ?', (max(1,min(int(limit),250)),)).fetchall()]
        mornings={day:_load(payload) for day,payload in db.execute('SELECT session_date,payload_json FROM apex49_morning_snapshots ORDER BY session_date DESC LIMIT ?', (max(1,min(int(limit),250)),)).fetchall()}
    return evaluate(recaps,mornings,min_train=min_train)
