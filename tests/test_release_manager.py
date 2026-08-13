from engine.release_manager import APP_VERSION, FEATURES, migration_status, release_metadata


def test_release_metadata_is_read_only_and_complete(monkeypatch):
    monkeypatch.setenv('APEX_BUILD_ID', 'build-test-1')
    monkeypatch.setenv('APEX_GIT_COMMIT', 'abcdef1234567890')
    metadata = release_metadata()
    assert metadata['application_version'] == APP_VERSION
    assert metadata['build'] == 'build-test-1'
    assert metadata['commit'] == 'abcdef1234567890'
    assert 'Institutional State' in metadata['features']
    assert 'Release Manager' in FEATURES
    assert metadata['guardrails']['read_only'] is True
    assert metadata['guardrails']['changes_trade_decisions'] is False


def test_migration_status_reports_mismatch(monkeypatch):
    monkeypatch.setenv('APEX_DATABASE_SCHEMA_VERSION', '4')
    status = migration_status()
    assert status['ready'] is False
    assert status['pending_migrations']


def test_data_integrity_names_empty_stores(monkeypatch, tmp_path):
    import sqlite3
    from engine.release_manager import data_integrity
    db = tmp_path / "t.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE premium_recommendations (id INTEGER)")
    con.commit(); con.close()
    monkeypatch.setenv('DB_PATH', str(db))
    result = data_integrity()
    assert result['tables']['premium_recommendations']['state'] == 'EMPTY'
    assert result['tables']['apex_signals']['state'] == 'MISSING'
    assert result['statistics_supportable'] is False


def test_migration_status_unstamped_is_not_ready(monkeypatch, tmp_path):
    """No PRAGMA user_version and no operator claim -> not ready, not a silent pass."""
    from engine.release_manager import migration_status
    monkeypatch.delenv('APEX_DATABASE_SCHEMA_VERSION', raising=False)
    monkeypatch.setenv('DB_PATH', str(tmp_path / "empty.db"))
    status = migration_status()
    assert status['ready'] is False
    assert status['verified'] is False
    assert status['actual_version'] is None


def test_declared_schema_version_is_not_verified(monkeypatch, tmp_path):
    """An operator claim matching expected is ready — but flagged unverified."""
    from engine.release_manager import migration_status, DATABASE_VERSION
    monkeypatch.setenv('APEX_DATABASE_SCHEMA_VERSION', DATABASE_VERSION)
    monkeypatch.setenv('DB_PATH', str(tmp_path / "empty.db"))
    status = migration_status()
    assert status['ready'] is True
    assert status['verified'] is False   # matched, but from a claim not a measurement
