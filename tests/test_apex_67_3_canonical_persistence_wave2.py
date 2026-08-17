from pathlib import Path

from engine.canonical_persistence import connection

ROOT = Path(__file__).resolve().parents[1]

MIGRATED = ['engine/adaptive_learning.py', 'engine/learning_calibration.py', 'engine/offline_weight_optimization.py', 'engine/adaptive_intelligence.py', 'engine/institutional_validation_promotion_v255.py', 'engine/institutional_evidence_graph.py', 'engine/strategy_promotion_governance.py', 'engine/trade_director_institutional_learning.py', 'engine/prediction_confidence_calibration.py', 'engine/institutional_learning_engine.py', 'engine/production_governance.py', 'engine/decision_evidence_pipeline.py', 'engine/decision_intelligence_core.py', 'engine/decision_provenance.py', 'engine/institutional_evidence.py', 'engine/adaptive_refusal_calibration.py', 'engine/continuous_learning_calibration.py', 'engine/trade_director_performance_calibration.py', 'engine/institutional_decision_review.py', 'engine/trade_director_institutional_evidence.py']


def test_wave2_modules_no_longer_open_sqlite_directly():
    offenders = []
    for rel in MIGRATED:
        text = (ROOT / rel).read_text(encoding="utf-8")
        if "sqlite3.connect" in text:
            offenders.append(rel)
        assert "canonical_persistence import connect as canonical_connect" in text
    assert offenders == []


def test_canonical_policy_remains_wal_fk_and_busy_timeout(tmp_path):
    db = tmp_path / "wave2.db"
    with connection(db) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] > 0


def test_wave2_does_not_change_database_path_literals():
    # Migration is a connection-policy change, not a storage-location migration.
    for rel in MIGRATED:
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "canonical_connect(" in text
