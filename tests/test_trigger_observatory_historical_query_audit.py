import sqlite3
from engine import trigger_observatory_historical_query_audit as module

def seed(path):
    with sqlite3.connect(path) as conn:
        conn.executescript('''CREATE TABLE observed_trade_triggers(trigger_id TEXT PRIMARY KEY,symbol TEXT,decision_id TEXT,blocker_codes_json TEXT);
          CREATE TABLE trade_trigger_price_observations(observation_id TEXT PRIMARY KEY,trigger_id TEXT,observed_at TEXT);
          CREATE INDEX ix_link ON trade_trigger_price_observations(trigger_id,observed_at);''')
        conn.executemany('INSERT INTO observed_trade_triggers VALUES(?,?,?,?)', [('a','SPX','d1','[]'),('b','SPX','d1','[]'),('c','ES','d2','[]')])
        conn.executemany('INSERT INTO trade_trigger_price_observations VALUES(?,?,?)', [('1','a','x'),('2','a','y'),('3','b','z'),('4','c','z')])

def test_exact_symbol_and_aggregation(tmp_path):
    db = tmp_path/'test.db'; seed(db)
    report = module.audit_database(str(db))
    assert report['status'] == 'COMPLETE'
    assert report['results']['trigger_rows']['result'][0][0] == 2
    assert report['results']['distinct_linked_decisions']['result'][0][0] == 1
    assert report['results']['linked_price_observations']['result'][0][0] == 3
    assert report['results']['largest_observation_cohorts']['result'][0] == ('a',2)
    assert report['read_only'] and not report['writes_data']

def test_missing_database_does_not_create(tmp_path):
    db = tmp_path/'missing.db'
    assert module.audit_database(str(db))['status'] == 'DATABASE_NOT_FOUND'
    assert not db.exists()

def test_missing_tables_returns_diagnostic(tmp_path):
    db=tmp_path/'empty.db'; sqlite3.connect(db).close()
    assert module.audit_database(str(db))['status'] == 'REQUIRED_TABLES_MISSING'

def test_still_read_only_after_run(tmp_path):
    db=tmp_path/'sample.db';seed(db)
    before=db.read_bytes()
    module.audit_database(str(db))
    assert db.read_bytes()==before

def test_query_timeout_is_bounded(tmp_path):
    db=tmp_path/'large.db';seed(db)
    result=module.audit_database(str(db),query_budget_seconds=0.000001)
    assert result['status'] in {'COMPLETE','PARTIAL_BOUNDED'}
