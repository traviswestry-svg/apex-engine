"""Canonical-vs-directional status reconciliation; immutable, read-only behavior."""
import json
import sqlite3

import engine.evening_recap as er
from engine.premarket_directional_features import archived_diagnostics


def brief(mode, generated, target='2026-11-02', snapshot=None):
    return {'target_session_date': target, 'session_date': target,
            'generated_at': generated, 'session_context': {'brief_mode': mode},
            'forecast_identity': {'brief_mode': mode},
            'structured': {**({'premarket_directional_feature_snapshot': snapshot} if snapshot is not None else {}),
                           'spot': 6800, 'expected_move': {'one_sigma': 30}}}


def setup(monkeypatch, tmp_path):
    monkeypatch.setattr(er, 'DB_PATH', str(tmp_path / 'audit.db'))


def report_for(day):
    return next(x for x in archived_diagnostics(limit=30)['details'] if x['session_date'] == day)


def test_preparation_does_not_claim_slot_and_same_day_becomes_canonical(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    prep = er.save_morning_snapshot(brief('NEXT_SESSION_PREP', '2026-10-31T08:09:00-04:00'))
    assert prep['is_official'] is False
    assert prep['eligibility_reason'] == 'NEXT_SESSION_PREPARATION_NOT_OFFICIAL'
    frozen = er.save_morning_snapshot(brief('PREMARKET', '2026-11-02T08:12:00-05:00'))
    assert frozen['is_official'] is True
    later = er.save_morning_snapshot(brief('PREMARKET', '2026-11-02T08:40:00-05:00'))
    assert later['is_official'] is False
    assert er.get_morning_snapshot('2026-11-02')['generated_at'] == '2026-11-02T08:12:00-05:00'
    item = report_for('2026-11-02')
    assert item['status'] == 'CANONICAL_DIRECTIONAL_SNAPSHOT_NOT_ARCHIVED'
    assert item['lifecycle']['canonical_same_day_premarket'] is True
    assert item['lifecycle']['same_day_eligible_revisions'] == 2
    assert item['lifecycle']['revision_count'] == 3
    assert item['canonical_presence'] == 'PRESENT'
    assert item['directional_snapshot_presence'] == 'ABSENT'


def test_preparation_only_never_claims_canonical(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    er.save_morning_snapshot(brief('NEXT_SESSION_PREP', '2026-10-31T08:09:00-04:00'))
    item = report_for('2026-11-02')
    assert item['status'] == 'PREPARATION_OR_NONELIGIBLE_ONLY'
    assert item['canonical_presence'] == 'ABSENT'
    assert er.get_morning_snapshot('2026-11-02') is None


def test_same_day_revision_without_canonical_is_distinct(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    er.init_db()
    payload = brief('PREMARKET', '2026-11-02T08:00:00-05:00')
    with sqlite3.connect(er.DB_PATH) as db:
        db.execute('INSERT INTO apex49_morning_revisions(session_date, generated_at, ticker, payload_json,version,is_official) VALUES(?,?,?,?,?,?)',
                   ('2026-11-02',payload['generated_at'],'SPX',json.dumps(payload),er.VERSION,0))
    item = report_for('2026-11-02')
    assert item['status'] == 'SAME_DAY_REVISION_WITHOUT_CANONICAL'
    assert item['canonical_presence'] == 'ABSENT'


def test_historical_preparation_occupied_canonical_is_flagged_not_rewritten(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    er.init_db()
    prep = brief('NEXT_SESSION_PREP', '2026-10-31T08:09:00-04:00')
    with sqlite3.connect(er.DB_PATH) as db:
        db.execute('INSERT INTO apex49_morning_snapshots(session_date,generated_at,ticker,payload_json,version) VALUES(?,?,?,?,?)',
                   ('2026-11-02',prep['generated_at'],'SPX',json.dumps(prep),er.VERSION))
        db.execute('INSERT INTO apex49_morning_revisions(session_date, generated_at,ticker,payload_json,version,is_official) VALUES(?,?,?,?,?,?)',
                   ('2026-11-02',prep['generated_at'],'SPX',json.dumps(prep),er.VERSION,1))
    before=er.get_morning_snapshot('2026-11-02')
    item=report_for('2026-11-02')
    assert item['status'] == 'CANONICAL_ORIGIN_REQUIRES_REVIEW'
    assert item['lifecycle']['canonical_brief_mode'] == 'NEXT_SESSION_PREP'
    assert item['canonical_presence'] == 'PRESENT'
    assert er.get_morning_snapshot('2026-11-02') == before


def test_canonical_feature_snapshot_is_authoritative_not_revisions(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    snapshot={'schema':'PREMARKET_DIRECTIONAL_FEATURES_V1', 'usable_count':3,
              'features':{k:{'status':'AVAILABLE','value':-1.0} for k in
                  ('overnight_es_return','overnight_vwap_displacement','premarket_gap')}}
    er.save_morning_snapshot(brief('PREMARKET', '2026-11-02T08:12:00-05:00', snapshot=snapshot))
    er.save_morning_snapshot(brief('PREMARKET', '2026-11-02T08:20:00-05:00'))
    item=report_for('2026-11-02')
    assert item['status']=='SHADOW_DIRECTIONAL_CONTEXT'
    assert item['direction']=='BEARISH'
    assert item['directional_snapshot_presence']=='PRESENT'


def test_future_dated_premarket_not_eligible():
    eligible, reason, _ = er._official_forecast_eligibility(brief('PREMARKET','2026-10-31T08:00:00-04:00'))
    assert not eligible and reason=='NOT_SAME_DAY_PREMARKET'
