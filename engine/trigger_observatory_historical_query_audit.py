"""Bounded, read-only audit of Trigger Observatory predictive-validation query shape.

Operator callable only. No application route, scanner invocation, schema change, or mutations.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

SCHEMA = 'apex.trigger_observatory_historical_query_audit.v1'
MAX_SECONDS_PER_QUERY = 3.0
QUERIES = {
    'trigger_rows': ("SELECT count(*), coalesce(sum(length(blocker_codes_json)),0) FROM observed_trade_triggers WHERE symbol=?", True),
    'distinct_linked_decisions': ("SELECT count(DISTINCT decision_id) FROM observed_trade_triggers WHERE symbol=? AND decision_id IS NOT NULL AND decision_id!=''", True),
    'linked_price_observations': ("SELECT count(*), coalesce(sum(length(o.observation_id)+length(o.trigger_id)+length(o.observed_at)),0) FROM trade_trigger_price_observations o JOIN observed_trade_triggers t ON t.trigger_id=o.trigger_id WHERE t.symbol=?", True),
    'largest_observation_cohorts': ("SELECT t.trigger_id, count(*) AS observation_count FROM observed_trade_triggers t JOIN trade_trigger_price_observations o ON o.trigger_id=t.trigger_id WHERE t.symbol=? GROUP BY t.trigger_id ORDER BY observation_count DESC,t.trigger_id LIMIT 5", True),
}

def _run_bounded(conn: sqlite3.Connection, sql: str, params: tuple, *, limit_seconds: float) -> list[tuple]:
    deadline = time.monotonic() + limit_seconds
    def progress() -> int:
        return int(time.monotonic() >= deadline)
    conn.set_progress_handler(progress, 1000)
    cursor = None
    try:
        cursor = conn.execute(sql, params)
        return [tuple(row) for row in cursor]  # aggregate or LIMIT 5 only
    finally:
        if cursor is not None:
            cursor.close()
        conn.set_progress_handler(None, 0)

def audit_database(path: str, symbol: str = 'SPX', *, query_budget_seconds: float = MAX_SECONDS_PER_QUERY) -> dict[str, Any]:
    """Read schema, query plans, cardinalities without loading historical rows."""
    result: dict[str, Any] = {
        'schema': SCHEMA, 'read_only': True, 'db_reads': True,
        'writes_data': False, 'execution_authority': False, 'changes_trade_decisions': False,
        'database': str(path), 'symbol': symbol.upper(), 'results': {},
        'risks': [
            'predictive_validation currently materializes all matching trigger rows with fetchall',
            '_attach_window_metrics retains linked observation dictionaries and in-window arrays',
            'predictive_validation calls initialize_store (default reconcile=True), potentially writing historical reconciliation rows',
            'EXPLAIN describes plans, not actual runtime memory or IO cost',
        ],
        'limitations': [
            'No table content or canonical sample IDs are returned (only aggregate totals and up to five trigger IDs for top observation cohorts)',
            'Aggregate queries can read substantial database pages; each query has a 3-second default progress-handler budget',
            'SQLite length() reports textual/identifier lengths, not Python object heap or full SQLite disk footprint',
            'No behavior changes are recommended without output parity tests over full historical cohorts',
        ],
    }
    if not Path(path).is_file():
        return {**result, 'status': 'DATABASE_NOT_FOUND'}
    # sqlite3 URI mode=ro stops any schema creation or reconciliation, including WAL writes by this connection.
    uri = Path(path).resolve().as_uri() + '?mode=ro'
    connection = sqlite3.connect(uri, uri=True, timeout=2)
    try:
        connection.execute('PRAGMA query_only=ON')
        available = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('observed_trade_triggers','trade_trigger_price_observations')")}
        result['tables_present'] = sorted(available)
        if len(available) < 2:
            return {**result, 'status': 'REQUIRED_TABLES_MISSING'}
        result['indexes'] = {
            t: [row[1] for row in connection.execute(f'PRAGMA index_list({t})')]
            for t in sorted(available)
        }
        for name, (query, _) in QUERIES.items():
            entry: dict[str, Any] = {'bounded_seconds': query_budget_seconds}
            try:
                # small, bounded EXPLAIN plan; no real query execution.
                entry['plan'] = [str(row[3]) for row in connection.execute('EXPLAIN QUERY PLAN '+query, (symbol.upper(),))][:12]
                started = time.monotonic()
                rows = _run_bounded(connection, query, (symbol.upper(),), limit_seconds=query_budget_seconds)
                entry['elapsed_ms'] = round((time.monotonic()-started)*1000, 2)
                entry['result'] = rows
                entry['status'] = 'OK'
            except sqlite3.OperationalError as exc:
                entry['status'] = 'QUERY_BUDGET_EXCEEDED' if 'interrupted' in str(exc).lower() else 'QUERY_ERROR'
                entry['error_type'] = type(exc).__name__
            result['results'][name] = entry
        statuses = [r['status'] for r in result['results'].values()]
        result['status'] = 'COMPLETE' if all(s == 'OK' for s in statuses) else 'PARTIAL_BOUNDED'
        return result
    finally:
        connection.close()

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True, help='Existing apex_trigger_observatory.db path')
    parser.add_argument('--symbol', default='SPX')
    parser.add_argument('--output', help='Optional JSON report output path')
    args = parser.parse_args()
    report = audit_database(args.db, args.symbol)
    encoded = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(encoded + '\n', encoding='utf-8')
    else:
        print(encoded)

if __name__ == '__main__':
    main()
