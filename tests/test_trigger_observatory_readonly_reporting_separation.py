"""Regression contract: querying never performs historical reconciliation."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from engine.trigger_observatory import (
    effectiveness, history, initialize_store, observation_integrity_validation,
    predictive_validation, reconcile_historical_observation_windows,
    record_trigger, trade_visualization,
)


def test_reporting_does_not_reconcile_legacy_rows(tmp_path):
    db = str(tmp_path / 'trigger.db')
    missing_evidence = str(tmp_path / 'missing_evidence.db')
    result = record_trigger(
        source='PINE', trigger_type='CALL_ENTRY', symbol='SPX', direction='BULLISH',
        disposition='OBSERVED', triggered_at='2026-11-10T14:00:00+00:00',
        source_event_key='readonly-contract', price=6000.0, path=db,
    )
    trigger_id = result['trigger_id']
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE observed_trade_triggers SET window_integrity_status=NULL, "
            "window_integrity_checked_at=NULL, outcome_label='PRESERVED' WHERE trigger_id=?",
            (trigger_id,),
        )
        conn.execute(
            "INSERT INTO trade_trigger_price_observations "
            "(observation_id,trigger_id,observed_at,price,favorable_points,adverse_points,created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            ('raw-new', trigger_id, '2026-11-10T14:01:00+00:00', 6005.0, 5.0, 0.0,
             '2026-11-10T14:01:00+00:00'),
        )
    with sqlite3.connect(db) as conn:
        original = conn.execute(
            'SELECT window_integrity_status,window_integrity_checked_at,outcome_label,updated_at '
            'FROM observed_trade_triggers WHERE trigger_id=?', (trigger_id,),
        ).fetchone()
        initial_obs = conn.execute(
            'SELECT elapsed_seconds,window_class FROM trade_trigger_price_observations '
            'WHERE observation_id=?', ('raw-new',),
        ).fetchone()

    # Every public query here must be read-only; derivative metrics may be computed in memory.
    assert history(path=db)['triggers']
    assert trade_visualization(path=db)['trade'] is not None
    assert effectiveness(path=db)['sample_size'] == 1
    assert predictive_validation(path=db, evidence_path=missing_evidence)['sample_size'] == 1
    assert observation_integrity_validation(path=db, evidence_path=missing_evidence)['ok']

    with sqlite3.connect(db) as conn:
        after = conn.execute(
            'SELECT window_integrity_status,window_integrity_checked_at,outcome_label,updated_at '
            'FROM observed_trade_triggers WHERE trigger_id=?', (trigger_id,),
        ).fetchone()
        after_obs = conn.execute(
            'SELECT elapsed_seconds,window_class FROM trade_trigger_price_observations '
            'WHERE observation_id=?', ('raw-new',),
        ).fetchone()
    assert after == original
    assert after_obs == initial_obs
    assert not Path(missing_evidence).exists()

    # An explicit maintenance action still performs the original repair.
    repaired = reconcile_historical_observation_windows(path=db)
    assert repaired['operation'] == 'EXPLICIT_HISTORICAL_RECONCILIATION'
    assert repaired['observation_window_integrity']['reconciled'] >= 1
    with sqlite3.connect(db) as conn:
        reconciled = conn.execute(
            'SELECT window_integrity_status FROM observed_trade_triggers WHERE trigger_id=?',
            (trigger_id,),
        ).fetchone()
    assert reconciled[0] == 'IN_WINDOW'


def test_reporting_missing_store_does_not_create_database(tmp_path):
    db = tmp_path / 'not-created.db'
    assert history(path=str(db))['status'] == 'WAITING_FOR_TRIGGERS'
    assert effectiveness(path=str(db))['status'] == 'WAITING_FOR_TRIGGERS'
    assert predictive_validation(path=str(db))['status'] == 'WAITING_FOR_TRIGGERS'
    assert trade_visualization(path=str(db))['status'] == 'WAITING_FOR_TRIGGERS'
    assert not db.exists()
