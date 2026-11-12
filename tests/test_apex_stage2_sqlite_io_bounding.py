"""Stage 2 SQLite read-side bound/closure regression tests."""
import sqlite3
from pathlib import Path
from engine.trigger_observatory import _linked_rows
from engine.canonical_persistence import connection


def _fixture(tmp_path, count=600):
    path = tmp_path / 'read_side.db'
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE decisions (decision_id TEXT PRIMARY KEY, session TEXT, action TEXT, snapshot_json TEXT)')
        conn.execute('CREATE TABLE grading_results (decision_id TEXT, horizon_seconds INT)')
        conn.executemany('INSERT INTO decisions VALUES (?,?,?,?)', [(f'd{i}', 'RTH','NO_TRADE','{}') for i in range(count)])
        conn.executemany('INSERT INTO grading_results VALUES (?,?)', [(f'd{i}', 300) for i in range(count)])
    return path


def test_exact_linked_ids_across_multiple_bounded_batches(tmp_path):
    path = _fixture(tmp_path)
    with connection(path, read_only=True, heal=False) as conn:
        ids = {f'd{i}' for i in range(512)} | {'missing', '', ' d2 '}
        rows = list(_linked_rows(conn, table='decisions', columns='decision_id,session,action,snapshot_json', decision_ids=ids))
    found = [r['decision_id'] for r in rows]
    assert len(found) == 512 and len(set(found)) == 512
    assert 'd599' not in found
    assert 'missing' not in found


def test_empty_id_set_does_not_read_all_decisions(tmp_path):
    path = _fixture(tmp_path)
    with connection(path, read_only=True, heal=False) as conn:
        sql = []
        conn.set_trace_callback(sql.append)
        assert list(_linked_rows(conn, table='decisions', columns='decision_id,session,action,snapshot_json', decision_ids=set())) == []
    assert not any('FROM decisions' in entry for entry in sql)


def test_readonly_connection_guaranteed_closed_even_on_exception(tmp_path):
    path = _fixture(tmp_path)
    conn = None
    try:
        with connection(path, read_only=True, heal=False) as opened:
            conn = opened
            assert opened.execute('SELECT COUNT(*) FROM decisions').fetchone()[0] == 600
            raise RuntimeError('application parse exception')
    except RuntimeError:
        pass
    try:
        conn.execute('SELECT 1')
    except sqlite3.ProgrammingError as exc:
        assert 'closed' in str(exc)
    else:
        raise AssertionError('Connection must close')


def test_tables_are_fixed_not_dynamic_sql(tmp_path):
    path = _fixture(tmp_path)
    with connection(path, read_only=True, heal=False) as conn:
        try:
            list(_linked_rows(conn, table='decisions; DROP TABLE decisions', columns='decision_id,session,action,snapshot_json', decision_ids={'d1'}))
        except ValueError:
            pass
        else:
            raise AssertionError('Unsupported query source must be rejected')
        assert [r['horizon_seconds'] for r in _linked_rows(conn, table='grading_results', columns='decision_id,horizon_seconds', decision_ids={'d1'})] == [300]


def test_query_plan_uses_exact_identity_index(tmp_path):
    path = _fixture(tmp_path)
    with connection(path, read_only=True, heal=False) as conn:
        plan = conn.execute('EXPLAIN QUERY PLAN SELECT decision_id,session,action,snapshot_json FROM decisions WHERE decision_id IN (?,?)', ('d1','d2')).fetchall()
        assert any('INDEX' in str(row[3]).upper() for row in plan)


def test_observation_query_restricts_exact_trigger_owners(tmp_path):
    from engine.trigger_observatory import _linked_trigger_observations
    path = tmp_path / 'observations.db'
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE trade_trigger_price_observations (trigger_id TEXT, observed_at TEXT, price REAL)')
        conn.execute('CREATE INDEX idx_test_trigger_obs ON trade_trigger_price_observations(trigger_id, observed_at)')
        conn.executemany('INSERT INTO trade_trigger_price_observations VALUES(?,?,?)',
                         [(f't{i}', '2026-01-01T12:00:00Z', float(i)) for i in range(600)])
    with connection(path, read_only=True, heal=False) as conn:
        rows = list(_linked_trigger_observations(conn, {f't{i}' for i in range(257)} | {'nonexistent'}))
    assert len(rows) == 257
    assert {r['trigger_id'] for r in rows} == {f't{i}' for i in range(257)}


def test_empty_linked_trigger_list_skips_all_observation_queries(tmp_path):
    from engine.trigger_observatory import _linked_trigger_observations
    path = tmp_path / 'observations.db'
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE trade_trigger_price_observations (trigger_id TEXT, observed_at TEXT, price REAL)')
    with connection(path, read_only=True, heal=False) as conn:
        sql = []
        conn.set_trace_callback(sql.append)
        assert list(_linked_trigger_observations(conn, set())) == []
    assert not any('FROM trade_trigger_price_observations' in q for q in sql)
