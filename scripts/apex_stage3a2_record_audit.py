#!/usr/bin/env python3
"""APEX Stage 3A.2: bounded, read-only SQLite record/payload/dependency review.

Diagnostic only. Never writes SQLite, exports payload content, counts whole tables,
creates snapshots, opens databases immutable, checkpoints, or approves retention.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sqlite3
import stat
import time
from pathlib import Path

SCHEMA = 'apex.stage3a2_record_payload_retention_audit.v1'
MAX_TARGETS = 5
MAX_ROWS = 32
MAX_COLUMNS = 8
MAX_OBJECTS = 16
MAX_SQL_STEPS = 20000
MAX_PER_TABLE_MS = 750
MAX_TOTAL_MS = 9000
MAX_SCAN_FILES = 256
MAX_SOURCE_FILE_BYTES = 65536
MAX_CODE_REFERENCES = 6

# These are *review priorities*, not conclusions about deletion eligibility.
TARGETS = {
    'apex_evidence_pipeline.db': ['decisions', 'decision_effectiveness_attribution'],
    'apex_trigger_observatory.db': ['observed_trade_triggers'],
    'apex_tracking.db': ['flow_features', 'gamma_observational_snapshots'],
    'apex_calibration.db': ['level_transition_observations'],
}
REVIEW_DOMAINS = {
    'decisions': 'CANONICAL_DECISION_EVIDENCE',
    'decision_effectiveness_attribution': 'DECISION_OUTCOME_ATTRIBUTION',
    'observed_trade_triggers': 'TRIGGER_OBSERVATION_EVIDENCE',
    'flow_features': 'FEATURE_SAMPLE_PROVENANCE',
    'gamma_observational_snapshots': 'GAMMA_SNAPSHOT_IDENTITY',
    'level_transition_observations': 'CALIBRATION_TRANSITION_HISTORY',
}
PAYLOAD_TOKENS = ('json', 'payload', 'blob', 'snapshot', 'features', 'context',
                  'raw', 'metadata', 'detail', 'data', 'body', 'evidence',
                  'observations', 'state', 'response', 'input', 'output', 'reason')
TIME_TOKENS = ('timestamp', 'created_at', 'observed_at', 'event_time', 'session_date',
               'decision_time', 'updated_at', 'asof', 'recorded_at')
VALID_IDENTIFIER = re.compile(r'^[A-Za-z_][A-Za-z_0-9]*$')


def _quote(name: str) -> str:
    if not VALID_IDENTIFIER.fullmatch(name):
        raise ValueError('Unexpected SQLite object identifier')
    return '"' + name + '"'


def _target_stat(path: Path) -> int:
    s = path.lstat()
    if not stat.S_ISREG(s.st_mode) or s.st_nlink < 1 or path.is_symlink():
        raise ValueError('Target must be a regular non-symlink file')
    return s.st_size


def _source_hints(root: Path | None, table: str) -> dict:
    """Bounded source reference hints only; never asserts actual retention dependency."""
    if root is None:
        return {'status': 'NOT_REQUESTED', 'references': [], 'dependency_confirmed': False}
    if not root.exists() or not root.is_dir() or root.is_symlink():
        return {'status': 'INVALID_REPOSITORY_ROOT', 'references': [], 'dependency_confirmed': False}
    hits = []
    checked = 0
    truncated = False
    try:
        # Bounded traversal; avoids followlinks and oversized files.
        for directory, dirs, files in os.walk(root, followlinks=False):
            dirs[:] = sorted(d for d in dirs if d not in {'.git', '.venv', 'venv', '__pycache__', 'node_modules'} and not (Path(directory) / d).is_symlink())
            for name in sorted(files):
                if not name.endswith('.py'):
                    continue
                if checked >= MAX_SCAN_FILES:
                    truncated = True
                    break
                p = Path(directory) / name
                try:
                    st = p.lstat()
                    if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_SOURCE_FILE_BYTES:
                        continue
                    checked += 1
                    if table.encode() in p.read_bytes() and len(hits) < MAX_CODE_REFERENCES:
                        hits.append(str(p.relative_to(root)))
                except (OSError, ValueError):
                    continue
            if truncated:
                break
    except OSError:
        return {'status': 'SOURCE_SCAN_UNAVAILABLE', 'references': hits, 'dependency_confirmed': False}
    return {'status': 'PARTIAL_BOUND_EXHAUSTED' if truncated else 'REFERENCE_HINTS_ONLY',
            'references': hits, 'checked_files': checked,
            'max_files': MAX_SCAN_FILES, 'dependency_confirmed': False,
            'interpretation': 'Text occurrence is not proof of active code use or retention requirement'}


def _indexed_columns(conn: sqlite3.Connection, table: str) -> list[dict]:
    indexes = []
    for record in conn.execute('PRAGMA index_list(' + _quote(table) + ')').fetchall()[:MAX_OBJECTS]:
        name = record[1]
        if not isinstance(name, str):
            continue
        entries = conn.execute('PRAGMA index_info(' + _quote(name) + ')').fetchall()[:MAX_COLUMNS]
        if entries and isinstance(entries[0][2], str) and VALID_IDENTIFIER.fullmatch(entries[0][2]):
            indexes.append({'index': name, 'leading_column': entries[0][2],
                            'unique': bool(record[2])})
    return indexes


def _column_inventory(conn: sqlite3.Connection, table: str) -> list[dict]:
    rows = conn.execute('PRAGMA table_xinfo(' + _quote(table) + ')').fetchall()
    result = []
    for row in rows[:128]:
        name = row[1]
        if not isinstance(name, str) or not VALID_IDENTIFIER.fullmatch(name):
            continue
        result.append({'name': name, 'type': str(row[2])[:48], 'pk': bool(row[5]),
                       'hidden': bool(row[6])})
    return result


def _sample_path(conn: sqlite3.Connection, table: str, schema_sql: str, cols: list[dict], indexes: list[dict]):
    if 'WITHOUT ROWID' not in schema_sql.upper():
        # B-tree order, no ORDER BY sort or scan. The first row is newest by rowid,
        # which need not be newest by time.
        return ('ROWID_DESC', 'rowid DESC')
    # For WITHOUT ROWID only indexed leading columns can be sampled safely.
    pks = [c['name'] for c in cols if c['pk']]
    leading = next((i['leading_column'] for i in indexes if i['leading_column'] in pks), None)
    if leading:
        return ('PRIMARY_KEY_DESC', _quote(leading) + ' DESC')
    return ('SKIPPED_NO_VERIFIED_BOUNDED_ACCESS_PATH', None)


def _inspect_table(conn: sqlite3.Connection, table: str, schema_sql: str,
                   row_limit: int, column_limit: int, budget_ms: int,
                   repo_root: Path | None, deadline: float) -> dict:
    columns = _column_inventory(conn, table)
    indexes = _indexed_columns(conn, table)
    result = {'table': table, 'status': 'NOT_SAMPLED', 'read_only': True,
              'sample_scope': 'BOUNDED_ACCESS_PATH_NOT_STATISTICAL_REPRESENTATION',
              'full_table_count_performed': False, 'payload_values_exported': False,
              'columns_available': len(columns), 'index_count_inspected': len(indexes),
              'dependency_review': {
                  'domain': REVIEW_DOMAINS.get(table, 'UNCLASSIFIED_REVIEW_REQUIRED'),
                  'retention_eligibility': 'NOT_ESTABLISHED', 'deletion_authorized': False,
                  'canonical_evidence_requirements_verified': False,
                  'cross_database_references_verified': False,
                  'backup_and_restore_verified': False,
                  'code_reference_hints': _source_hints(repo_root, table),
              }}
    try:
        fk = conn.execute('PRAGMA foreign_key_list(' + _quote(table) + ')').fetchall()[:MAX_OBJECTS]
        result['dependency_review']['declared_local_foreign_keys'] = [
            {'referenced_table': str(r[2]), 'from_column': str(r[3]), 'to_column': str(r[4])}
            for r in fk if str(r[2]).isascii()]
        result['dependency_review']['foreign_keys_exhaustive'] = len(fk) < MAX_OBJECTS
        path_type, order = _sample_path(conn, table, schema_sql, columns, indexes)
        result['access_path'] = path_type
        if not order:
            result['status'] = 'SKIPPED_UNSAFE_ACCESS_PATH'
            return result
        # Columns are identified from schema only; no SQL payload expressions returned.
        candidates = [c for c in columns if not c['hidden'] and
                      (any(t in c['name'].lower() for t in PAYLOAD_TOKENS)
                       or any(t in c['type'].upper() for t in ('TEXT','BLOB','JSON')))]
        selected = candidates[:column_limit]
        result['columns_selected'] = [c['name'] for c in selected]
        result['columns_omitted'] = max(0, len(candidates)-len(selected))
        if not selected:
            result['status'] = 'NO_CANDIDATE_PAYLOAD_COLUMNS'
            return result
        exprs = [f'length({_quote(c["name"])})' for c in selected]
        statement = (f'SELECT {", ".join(exprs)} FROM {_quote(table)} '
                     f'ORDER BY {order} LIMIT ?')
        until = min(time.monotonic() + min(budget_ms, MAX_PER_TABLE_MS) / 1000, deadline)
        visits = [0]
        def progress():
            visits[0] += 1
            return 1 if visits[0] >= MAX_SQL_STEPS or time.monotonic() > until else 0
        conn.set_progress_handler(progress, 100)
        try:
            rows = conn.execute(statement, (row_limit,)).fetchall()
        finally:
            conn.set_progress_handler(None, 0)
        measurements = []
        for col, n in zip(selected, range(len(selected))):
            vals = [max(0, int(r[n])) for r in rows if r[n] is not None and isinstance(r[n], int)]
            measurements.append({'column': col['name'], 'declared_type': col['type'],
                                 'non_null_sampled': len(vals), 'null_sampled': len(rows)-len(vals),
                                 'min_length': min(vals) if vals else None,
                                 'max_length': max(vals) if vals else None,
                                 'mean_length': round(sum(vals)/len(vals), 2) if vals else None,
                                 'total_sampled_length': sum(vals),
                                 'length_units': 'SQLITE_LENGTH_TEXT_CHARACTERS_OR_BLOB_BYTES',
                                 'not_exact_row_storage_bytes': True})
        # Indexed boundary probe: never scan by timestamp if no leading-column index.
        indexed_time = next((i['leading_column'] for i in indexes
                            if any(i['leading_column'].lower() == t or i['leading_column'].lower().endswith('_'+t)
                                   for t in TIME_TOKENS)), None)
        result['indexed_time_boundary'] = {'status': 'SKIPPED_NO_INDEXED_TIME_COLUMN'}
        if indexed_time and time.monotonic() < deadline:
            bounds = []
            for direction in ('ASC','DESC'):
                limit_time = min(time.monotonic() + min(budget_ms, MAX_PER_TABLE_MS)/1000, deadline)
                steps = [0]
                def stop():
                    steps[0] += 1
                    return int(steps[0] > MAX_SQL_STEPS or time.monotonic() >= limit_time)
                conn.set_progress_handler(stop, 100)
                try:
                    valrow = conn.execute(
                        f'SELECT {_quote(indexed_time)} FROM {_quote(table)} '
                        f'WHERE {_quote(indexed_time)} IS NOT NULL '
                        f'ORDER BY {_quote(indexed_time)} {direction} LIMIT 1').fetchone()
                    val = valrow[0] if valrow else None
                    # Only expose standardized calendar date; no raw timestamp values.
                    textval = str(val or '')[:10]
                    bounds.append(textval if re.fullmatch(r'\d{4}-\d{2}-\d{2}',textval) else None)
                except (sqlite3.Error, ValueError):
                    bounds.append(None)
                finally:
                    conn.set_progress_handler(None, 0)
            result['indexed_time_boundary'] = {
                'status':'INDEXED_ENDPOINTS_ONLY_NOT_DISTRIBUTION' if all(bounds) else 'UNAVAILABLE_OR_NOT_ISO_DATE',
                'column':indexed_time, 'earliest_date':bounds[0], 'latest_date':bounds[1],
                'retention_age_eligibility_inferred': False}
        result['sampled_rows'] = len(rows)
        result['sample_row_limit'] = row_limit
        result['column_lengths'] = measurements
        result['status'] = 'SAMPLED_BOUNDED_NONREPRESENTATIVE' if rows else 'EMPTY_SAMPLE'
        return result
    except sqlite3.Error as exc:
        result['status'] = 'BUDGET_EXCEEDED_OR_SQLITE_UNAVAILABLE'
        result['sqlite_error_class'] = type(exc).__name__
        return result
    finally:
        conn.set_progress_handler(None, 0)


def audit(root: str | Path, *, repo_root: str | Path | None = None,
          rows: int = 16, columns: int = 6, budget_ms: int = 500,
          total_budget_ms: int = 8000, targets: dict | None = None) -> dict:
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('root must be an existing non-symlink directory')
    root = root.resolve()
    repo = Path(repo_root) if repo_root else None
    rows = min(MAX_ROWS, max(1, int(rows)))
    columns = min(MAX_COLUMNS, max(1, int(columns)))
    budget_ms = min(MAX_PER_TABLE_MS, max(25, int(budget_ms)))
    total_budget_ms = min(MAX_TOTAL_MS, max(100, int(total_budget_ms)))
    deadline = time.monotonic() + total_budget_ms / 1000
    dbtargets = targets if targets is not None else TARGETS
    if len(dbtargets) > MAX_TARGETS:
        raise ValueError('Too many database targets')
    results = []
    for dbname, tables in dbtargets.items():
        if not isinstance(dbname,str) or not dbname.endswith('.db') or not VALID_IDENTIFIER.fullmatch(dbname[:-3]):
            raise ValueError('Unsafe database target')
        if len(tables) > MAX_OBJECTS or any(not isinstance(t,str) or not VALID_IDENTIFIER.fullmatch(t) for t in tables):
            raise ValueError('Unsafe table target')
        dbresult = {'database': dbname, 'tables': [], 'read_only': True}
        results.append(dbresult)
        path = root / dbname
        try:
            dbresult['file_bytes_at_start'] = _target_stat(path)
            if time.monotonic() >= deadline:
                dbresult['status'] = 'TOTAL_BUDGET_EXCEEDED'
                continue
            conn = sqlite3.connect(f'{path.as_uri()}?mode=ro', uri=True, timeout=0.2)
            try:
                conn.execute('PRAGMA query_only=ON')
                # No PRAGMA temp_store, PRAGMA journal_mode assignments, sqlite backups,
                # implicit DB initialization, or SQLite writes.
                for table in tables:
                    if time.monotonic() >= deadline:
                        dbresult['tables'].append({'table':table,'status':'TOTAL_BUDGET_EXCEEDED'})
                        continue
                    schema = conn.execute("SELECT sql FROM sqlite_schema WHERE type='table' AND name=?",(table,)).fetchone()
                    if not schema:
                        dbresult['tables'].append({'table': table,'status':'TABLE_NOT_FOUND'})
                        continue
                    dbresult['tables'].append(_inspect_table(conn,table,str(schema[0] or ''),rows,columns,budget_ms,repo,deadline))
                dbresult['status'] = 'INSPECTED'
            finally:
                conn.close()
        except (OSError, sqlite3.Error, ValueError) as exc:
            dbresult['status'] = 'DATABASE_UNAVAILABLE'
            dbresult['error_class'] = type(exc).__name__
    return {'schema': SCHEMA, 'observed_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
            'root':str(root),'mode':'READ_ONLY','databases':results,
            'limits':{'rows_per_table':rows,'columns_per_table':columns,
                      'per_table_query_budget_ms':budget_ms,'total_query_budget_ms':total_budget_ms,
                      'max_sqlite_progress_calls':MAX_SQL_STEPS, 'database_max':MAX_TARGETS,
                      'max_tables_per_database':MAX_OBJECTS},
            'sampling_limitations':['Samples are last rowid or descending primary-key records, NOT random or representative',
                'SQLite length() is Unicode characters for TEXT and bytes for BLOB, NOT on-disk row size',
                'Large TEXT length calculations may cause reads or allocations',
                'Not all columns are sampled; indexes and overflow-page allocation are excluded',
                'No row counts, age distribution, duplication rates or compression savings are established',
                'A SQLite query timeout does not bound I/O waiting outside the progress-handler callback',
                'Source code reference hints and declared FKs cannot establish cross-database retention eligibility'],
            'retention_guardrails':{'all_rows_preserved':True,'no_sqlite_mutation':True,
                'no_delete':True,'no_vacuum':True,'no_wal_checkpoint':True,
                'no_payload_content_exported':True,'no_execution_authority':True,
                'retention_eligibility_not_established':True,'manual_owner_review_required':True,
                'backup_and_restore_unverified':True,
                'canonical_evidence_and_gamma_identity_must_be_preserved':True}}


def main(argv=None):
    p = argparse.ArgumentParser(description='APEX Stage 3A.2 bounded read-only SQLite payload and retention diagnostic')
    p.add_argument('--root', default='/data')
    p.add_argument('--repo-root', help='Optional bounded Python-source reference hints (not dependency certification)')
    p.add_argument('--sample-rows',type=int,default=16)
    p.add_argument('--sample-columns',type=int,default=6)
    p.add_argument('--query-budget-ms',type=int,default=500)
    p.add_argument('--total-budget-ms',type=int,default=8000)
    p.add_argument('--output',help='Write JSON outside the live database root only')
    args = p.parse_args(argv)
    report = audit(args.root,repo_root=args.repo_root,rows=args.sample_rows,
                   columns=args.sample_columns,budget_ms=args.query_budget_ms,
                   total_budget_ms=args.total_budget_ms)
    payload = json.dumps(report,indent=2,sort_keys=True)+'\n'
    if args.output:
        target = Path(args.output).resolve()
        root = Path(args.root).resolve()
        if target == root or root in target.parents:
            p.error('Refusing to write a report into the database volume')
        target.write_text(payload,encoding='utf-8')
    else:
        print(payload,end='')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
