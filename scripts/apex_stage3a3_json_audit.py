#!/usr/bin/env python3
"""APEX Stage 3A.3: bounded read-only JSON shape and compression feasibility.

Operator-run only. Does not modify DB, return raw content, emit hashes, or establish
retention/compression eligibility. SQLite progress limits are cooperative.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sqlite3
import stat
import time
import zlib
from pathlib import Path

SCHEMA = 'apex.stage3a3_json_structure_compression_audit.v1'
TARGETS = {
    'apex_evidence_pipeline.db': {'decisions': ('snapshot_json',)},
    'apex_trigger_observatory.db': {'observed_trade_triggers': ('blocker_codes_json', 'evidence_json', 'etrade_handoff_json', 'canonical_grade_json')},
    'apex_tracking.db': {'flow_features': ('features_json', 'availability_json'), 'gamma_observational_snapshots': ('snapshot_json', 'lineage_json')},
    'apex_calibration.db': {'level_transition_observations': ('target_cluster_json',)},
}
IDENT = re.compile(r'^[A-Za-z_][A-Za-z_0-9]*$')
MAX_ROWS = 16
MAX_CHARS_PER_VALUE = 65536
MAX_TOTAL_RAW_BYTES = 2 * 1024 * 1024
MAX_TABLE_MS = 1200
MAX_TOTAL_MS = 12000
MAX_PROGRESS_CALLS = 20000
MAX_JSON_NODES = 4096
MAX_JSON_DEPTH = 32
MAX_DB = 4
MAX_TABLES = 2
MAX_COLUMNS = 4


def _ident(s: str) -> str:
    if not isinstance(s, str) or not IDENT.fullmatch(s):
        raise ValueError('Unsafe SQL identifier')
    return '"' + s + '"'


def _validate_target(path: Path) -> int:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or path.is_symlink():
        raise ValueError('Database path not a regular file')
    return info.st_size


def _shape(value, *, max_nodes=MAX_JSON_NODES, max_depth=MAX_JSON_DEPTH):
    """Return non-sensitive aggregate node counts and private shape identity.

    Never return key strings, values, hashes, IDs, or schema signatures.
    """
    stack = [(value, 0)]
    nodes = 0
    depth_max = 0
    dictionaries = lists = scalars = keys = 0
    # Key names remain local; signature represents only JSON key/type topology.
    # Use private key-name-bearing representation only to compare samples in memory.
    signatures = []
    while stack:
        v, depth = stack.pop()
        nodes += 1
        if nodes > max_nodes or depth > max_depth:
            raise ValueError('JSON structural traversal cap')
        depth_max = max(depth_max, depth)
        if isinstance(v, dict):
            dictionaries += 1
            keys += len(v)
            if keys > max_nodes:
                raise ValueError('JSON key count cap')
            # Including key names internally distinguishes structural changes,
            # but no names/signatures are returned from this function.
            signatures.append(('object', depth, tuple(sorted(str(k) for k in v.keys()))))
            stack.extend((item, depth + 1) for item in v.values())
        elif isinstance(v, list):
            lists += 1
            signatures.append(('array', depth, len(v)))
            stack.extend((item, depth + 1) for item in v)
        else:
            scalars += 1
            signatures.append(('scalar', depth, type(v).__name__))
    return {'nodes':nodes,'max_depth':depth_max,'objects':dictionaries,
            'arrays':lists,'scalar_nodes':scalars,'keys':keys}, tuple(signatures)


def _stats(values: list[int]) -> dict:
    return {'n':len(values), 'min':min(values) if values else None,
            'mean':round(sum(values)/len(values), 2) if values else None,
            'max':max(values) if values else None}


def _inspect_column(con: sqlite3.Connection, table: str, column: str, *, rows: int,
                    max_chars: int, remaining_bytes: list[int], mode: str,
                    table_deadline: float, global_deadline: float) -> dict:
    result = {'column':column,'status':'NOT_STARTED','sample_scope':'LAST_ROWID_NONREPRESENTATIVE',
              'raw_values_exported':False,'hashes_exported':False,
              'lossless_compression_only_in_memory':True,
              'sampled_rows':0,'null_rows':0,'oversize_or_truncated_rows':0,
              'invalid_json_rows':0,'shape_limit_rows':0}
    progress_calls = [0]
    def progress():
        progress_calls[0] += 1
        return int(progress_calls[0] >= MAX_PROGRESS_CALLS or
                   time.monotonic() >= min(table_deadline, global_deadline))
    con.set_progress_handler(progress,100)
    lengths, packed, node_counts, depths, key_counts = [], [], [], [], []
    private_shapes: dict[tuple, int] = {}
    try:
        # Every returned SQLite cell is substr-bounded. +1 sentinel distinguishes
        # potential truncation; no unbounded value SELECT and no full-table count.
        sql = (f'SELECT substr({_ident(column)}, 1, ?) FROM {_ident(table)} '
               'ORDER BY rowid DESC LIMIT ?')
        for (raw,) in con.execute(sql, (max_chars + 1, rows)):
            if time.monotonic() >= min(table_deadline, global_deadline):
                result['status'] = 'BUDGET_EXCEEDED_PARTIAL'; break
            result['sampled_rows'] += 1
            if raw is None:
                result['null_rows'] += 1; continue
            if not isinstance(raw, (str, bytes)):
                result['invalid_json_rows'] += 1; continue
            if len(raw) > max_chars:
                result['oversize_or_truncated_rows'] += 1; continue
            if not isinstance(raw,str):
                try: raw = raw.decode('utf-8')
                except UnicodeError:
                    result['invalid_json_rows'] += 1; continue
            data = raw.encode('utf-8')
            if len(data) > max_chars * 4 or len(data) > remaining_bytes[0]:
                result['oversize_or_truncated_rows'] += 1
                if remaining_bytes[0] < len(data):
                    result['status'] = 'GLOBAL_RAW_BYTE_BUDGET_EXHAUSTED'; break
                continue
            remaining_bytes[0] -= len(data)
            lengths.append(len(data))
            try:
                obj = json.loads(raw)
            except (ValueError, RecursionError):
                result['invalid_json_rows'] += 1; continue
            if mode in ('structure','both'):
                try:
                    m, sig = _shape(obj)
                    node_counts.append(m['nodes']); depths.append(m['max_depth']); key_counts.append(m['keys'])
                    private_shapes[sig] = private_shapes.get(sig, 0) + 1
                except (ValueError, RecursionError):
                    result['shape_limit_rows'] += 1
            if mode in ('compression','both'):
                packed.append((len(data),len(zlib.compress(data,level=6))))
        else:
            result['status'] = 'SAMPLED_BOUNDED_NONREPRESENTATIVE'
    except sqlite3.Error as exc:
        result['status'] = 'SQLITE_UNAVAILABLE_OR_BUDGET_EXCEEDED'
        result['error_class'] = type(exc).__name__
    finally:
        con.set_progress_handler(None,0)
    result['utf8_payload_bytes'] = _stats(lengths)
    if mode in ('structure','both'):
        result['shape'] = {'valid_traversals':len(node_counts),'node_count':_stats(node_counts),
                           'nesting_depth':_stats(depths),'key_occurrences':_stats(key_counts),
                           'distinct_shapes_in_sample':len(private_shapes),
                           'largest_repeated_shape_count':max(private_shapes.values(),default=0),
                           'shape_equality_is_not_payload_equality':True}
    if mode in ('compression','both'):
        raw_total = sum(a for a,b in packed)
        compressed_total = sum(b for a,b in packed)
        result['zlib_level6'] = {'valid_samples':len(packed),
            'aggregate_original_bytes':raw_total,
            'aggregate_compressed_bytes':compressed_total,
            'aggregate_ratio':round(compressed_total/raw_total,4) if raw_total else None,
            'sample_only_not_disk_savings':True,
            'not_validated_against_existing_readers':True}
    return result


def audit(root: str | Path, *, mode: str='both', rows: int=16,
          max_chars: int=65536, total_bytes: int=2*1024*1024,
          table_budget_ms: int=900, total_budget_ms: int=10000,
          targets: dict | None=None) -> dict:
    if mode not in ('structure','compression','both'):
        raise ValueError('Invalid audit mode')
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError('Database root unavailable')
    root = root.resolve()
    rows = min(MAX_ROWS,max(1,int(rows)))
    max_chars = min(MAX_CHARS_PER_VALUE,max(1024,int(max_chars)))
    total_bytes = min(MAX_TOTAL_RAW_BYTES,max(1024,int(total_bytes)))
    table_budget_ms = min(MAX_TABLE_MS,max(50,int(table_budget_ms)))
    total_budget_ms = min(MAX_TOTAL_MS,max(100,int(total_budget_ms)))
    start = time.monotonic(); deadline = start + total_budget_ms/1000
    remaining = [total_bytes]
    targets = TARGETS if targets is None else targets
    if len(targets) > MAX_DB:
        raise ValueError('Too many target databases')
    for db,tables in targets.items():
        if not isinstance(db,str) or not db.endswith('.db'):
            raise ValueError('Invalid database name')
        _ident(db[:-3])
        if len(tables)>MAX_TABLES:
            raise ValueError('Too many tables')
        for table,cols in tables.items():
            _ident(table)
            if not cols or len(cols)>MAX_COLUMNS:
                raise ValueError('Invalid columns')
            for col in cols: _ident(col)
    records=[]
    for db,tables in targets.items():
        entry={'database':db,'status':'NOT_STARTED','tables':[],'read_only':True}
        records.append(entry)
        path=root/db
        try:
            entry['file_bytes_at_start'] = _validate_target(path)
            if time.monotonic()>=deadline:
                entry['status']='TOTAL_BUDGET_EXCEEDED';continue
            con=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=0.2)
            try:
                con.execute('PRAGMA query_only=ON')
                for table,columns in tables.items():
                    data={'table':table,'columns':[],'status':'NOT_STARTED'}
                    entry['tables'].append(data)
                    row=con.execute('SELECT sql FROM sqlite_schema WHERE type=? AND name=?',('table',table)).fetchone()
                    if not row:
                        data['status']='TABLE_NOT_FOUND';continue
                    if 'WITHOUT ROWID' in str(row[0]).upper():
                        data['status']='SKIPPED_WITHOUT_ROWID_UNVERIFIED_ACCESS_PATH';continue
                    valid_columns={r[1] for r in con.execute('PRAGMA table_info('+_ident(table)+')')}
                    table_deadline=min(time.monotonic()+table_budget_ms/1000,deadline)
                    for column in columns:
                        if time.monotonic()>=table_deadline:
                            data['columns'].append({'column':column,'status':'TABLE_BUDGET_EXCEEDED'});continue
                        if column not in valid_columns:
                            data['columns'].append({'column':column,'status':'COLUMN_NOT_FOUND'});continue
                        data['columns'].append(_inspect_column(con,table,column,rows=rows,max_chars=max_chars,
                                                remaining_bytes=remaining,mode=mode,
                                                table_deadline=table_deadline,global_deadline=deadline))
                    data['status']='INSPECTED_BOUNDED'
                entry['status']='INSPECTED_BOUNDED'
            finally:
                con.close()
        except (OSError, sqlite3.Error, ValueError) as exc:
            entry['status']='DATABASE_UNAVAILABLE';entry['error_class']=type(exc).__name__
    return {'schema':SCHEMA,'observed_at_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
            'root':str(root),'mode':'READ_ONLY','analysis_mode':mode,'databases':records,
            'limits':{'rows_per_column':rows,'max_chars_per_value':max_chars,
                      'raw_byte_budget_total':total_bytes,'raw_byte_budget_remaining':remaining[0],
                      'query_budget_per_table_ms':table_budget_ms,
                      'total_budget_ms':total_budget_ms,'sqlite_progress_calls_max':MAX_PROGRESS_CALLS},
            'interpretation':{'sample_not_representative':True,'payload_content_exported':False,
              'column_names_are_preapproved':True,'shape_repetition_is_not_duplicate_content':True,
              'compression_result_is_not_production_savings':True,
              'sqlite_page_reclamation_not_estimated':True,'backup_restore_verified':False,
              'cross_database_retention_dependencies_verified':False,
              'schema_and_reader_compatibility_verified':False},
            'guardrails':{'no_writes_to_sqlite':True,'no_delete':True,'no_vacuum':True,
              'no_checkpoint':True,'no_schema_mutation':True,'no_retention_authorization':True,
              'no_execution_authority':True,'no_payload_or_hash_export':True,
              'no_compressed_payload_persisted':True},
            'limitations':['SQLite progress callbacks are cooperative; I/O waits are not hard-timed',
              'substr() can require SQLite to read large source pages despite bounded returned values',
              'Samples are descending rowid, not representative or randomized',
              'Compression is in-memory zlib level 6; no compatibility or recoverable filesystem bytes inferred',
              'No payload values, hashes, key names, structural signatures, or row identifiers are exported']}


def main(argv=None):
    p=argparse.ArgumentParser(description='APEX Stage 3A.3 bounded read-only JSON shape/compression feasibility')
    p.add_argument('--root',default='/data')
    p.add_argument('--mode',choices=('structure','compression','both'),default='both')
    p.add_argument('--sample-rows',type=int,default=16)
    p.add_argument('--max-chars',type=int,default=65536)
    p.add_argument('--raw-byte-budget',type=int,default=2*1024*1024)
    p.add_argument('--table-budget-ms',type=int,default=900)
    p.add_argument('--total-budget-ms',type=int,default=10000)
    p.add_argument('--output',help='Write report outside persistent database root; stdout if omitted')
    args=p.parse_args(argv)
    report=audit(args.root,mode=args.mode,rows=args.sample_rows,max_chars=args.max_chars,
                 total_bytes=args.raw_byte_budget,table_budget_ms=args.table_budget_ms,
                 total_budget_ms=args.total_budget_ms)
    payload=json.dumps(report,indent=2,sort_keys=True)+'\n'
    if args.output:
        root=Path(args.root).resolve()
        dest=Path(args.output).resolve()
        if root==dest or root in dest.parents or Path(args.output).is_symlink():
            p.error('Refusing output inside persistent volume or a symlink')
        dest.write_text(payload,encoding='utf-8')
    else:
        print(payload,end='')
    return 0

if __name__=='__main__':
    raise SystemExit(main())
