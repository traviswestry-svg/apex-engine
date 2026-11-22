#!/usr/bin/env python3
"""Phase 3B process-restart and interrupted-write rehearsal.

ALL rows, paths, process identities and failure conditions are SYNTHETIC.
Workers execute in fresh Python interpreters, never importing app.py and never
reading production SQLite or modifying historical APEX decisions. This is a
validation harness, not a recovery daemon or evidence promotion mechanism.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile

from engine import forward_provenance as fp


def source_connect(path: Path) -> sqlite3.Connection:
    c = sqlite3.connect(path, timeout=5)
    c.execute('PRAGMA journal_mode=WAL')
    c.execute('CREATE TABLE IF NOT EXISTS synthetic_source (kind TEXT NOT NULL, entity_id TEXT NOT NULL, PRIMARY KEY(kind, entity_id))')
    c.commit()
    return c


def source_insert(path: Path, kind: str, entity: str) -> bool:
    with source_connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        cur = db.execute('INSERT OR IGNORE INTO synthetic_source(kind,entity_id) VALUES (?,?)', (kind, entity))
        db.commit()
        return bool(cur.rowcount)


def source_count(path: Path, kind: str, entity: str) -> int:
    if not path.is_file():
        return 0
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as db:
        return int(db.execute('SELECT COUNT(*) FROM synthetic_source WHERE kind=? AND entity_id=?', (kind, entity)).fetchone()[0])


def rows(path: Path):
    if not path.is_file():
        return []
    with sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        return db.execute('SELECT * FROM forward_provenance_events ORDER BY sequence').fetchall()


def worker(mode: str, src: Path, ledger: Path):
    """Subprocess-only fault injector. Exit code 73 means intentional hard crash."""
    os.environ['APEX_FORWARD_PROVENANCE_ENABLED'] = '1'
    fp.DEFAULT_DB = str(ledger)
    e, g, d = 'execution-3b', 'gamma-3b', 'decision-3b'
    if mode == 'full_chain':
        assert fp.record_calculation(e, ticker='SPX-SYNTHETIC', path_version='fixture')['status'] == 'RECORDED'
        assert source_insert(src, 'gamma', g)
        assert fp.record_gamma(g, e, inserted=True, source_timestamp_provenance='APEX_DERIVED_PARSE_TIME')['status'] == 'RECORDED'
        assert source_insert(src, 'decision', d)
        assert fp.record_decision(d, g, inserted=True, observed_at=fp.utc_now())['status'] == 'RECORDED'
        return 0
    if mode == 'restart_calc_gamma':
        assert fp.record_calculation(e, ticker='SPX-SYNTHETIC', path_version='fixture')['status'] == 'RECORDED'
        assert source_insert(src, 'gamma', g)
        assert fp.record_gamma(g, e, inserted=True, source_timestamp_provenance='APEX_DERIVED_PARSE_TIME')['status'] == 'RECORDED'
        os._exit(73)
    if mode == 'after_gamma_source_before_receipt':
        assert fp.record_calculation(e, ticker='SPX-SYNTHETIC', path_version='fixture')['status'] == 'RECORDED'
        assert source_insert(src, 'gamma', g)
        os._exit(73)
    if mode == 'after_gamma_receipt_before_decision':
        assert fp.record_calculation(e, ticker='SPX-SYNTHETIC', path_version='fixture')['status'] == 'RECORDED'
        assert source_insert(src, 'gamma', g)
        assert fp.record_gamma(g, e, inserted=True, source_timestamp_provenance='APEX_DERIVED_PARSE_TIME')['status'] == 'RECORDED'
        os._exit(73)
    if mode == 'after_decision_source_before_receipt':
        assert fp.record_calculation(e, ticker='SPX-SYNTHETIC', path_version='fixture')['status'] == 'RECORDED'
        assert source_insert(src, 'gamma', g)
        assert fp.record_gamma(g, e, inserted=True, source_timestamp_provenance='APEX_DERIVED_PARSE_TIME')['status'] == 'RECORDED'
        assert source_insert(src, 'decision', d)
        os._exit(73)
    if mode == 'retry_existing':
        assert not source_insert(src, 'gamma', g)
        assert fp.record_gamma(g, e, inserted=False, source_timestamp_provenance=None)['status'] == 'NOT_ELIGIBLE'
        assert not source_insert(src, 'decision', d)
        assert fp.record_decision(d, g, inserted=False, observed_at=fp.utc_now())['status'] == 'NOT_ELIGIBLE'
        return 0
    if mode == 'new_boot_decision':
        assert source_insert(src, 'decision', d)
        assert fp.record_decision(d, g, inserted=True, observed_at=fp.utc_now())['status'] == 'RECORDED'
        return 0
    if mode == 'fork_self_check':
        if not hasattr(os, 'fork'):
            return 0
        r, w = os.pipe()
        pid = os.fork()
        if pid == 0:
            os.close(r)
            os.write(w, str(fp.runtime_identity()['boot_id']).encode())
            os.close(w)
            os._exit(0)
        os.close(w)
        inherited_boot = os.read(r, 200).decode()
        os.close(r)
        os.waitpid(pid, 0)
        assert inherited_boot == 'None', inherited_boot
        return 0
    if mode == 'transaction_crash':
        # An unfinished SQLite transaction must never leave a committed event.
        with sqlite3.connect(ledger, isolation_level=None, timeout=5) as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT INTO forward_provenance_events(event_id,kind,entity_id,execution_id,event_time,inserted_at,payload_json,previous_hash,event_hash) VALUES(?,?,?,?,?,?,?,?,?)',
                ('UNCOMMITTED', 'GAMMA_CALCULATED', 'UNCOMMITTED', None, fp.utc_now(), fp.utc_now(), '{}', 'WRONG', 'WRONG'))
            os._exit(73)
    if mode == 'receipt_write_failure':
        # Ledger parent path is a regular file, so SQLite cannot create ledger.
        assert source_insert(src, 'gamma', g)
        result = fp.record_gamma(g, e, inserted=True, source_timestamp_provenance=None)
        assert result['status'] == 'RECEIPT_WRITE_FAILED', result
        return 0
    raise ValueError('Unknown synthetic worker scenario: ' + mode)


def audit(ledger: Path, source: Path):
    """Report synthetically missing receipts; do not infer or reconstruct them."""
    events = rows(ledger)
    gamma = {r['entity_id'] for r in events if r['kind'] == 'GAMMA_PERSISTED'}
    decisions = {r['entity_id'] for r in events if r['kind'] == 'DECISION_PERSISTED'}
    with sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True) as db:
        src_gamma = {r[0] for r in db.execute("SELECT entity_id FROM synthetic_source WHERE kind='gamma'")}
        src_decisions = {r[0] for r in db.execute("SELECT entity_id FROM synthetic_source WHERE kind='decision'")}
    return {'gamma_source_without_receipt': sorted(src_gamma - gamma),
            'decision_source_without_receipt': sorted(src_decisions - decisions),
            'gamma_receipt_without_decision_receipt': sorted(gamma) if not decisions else [],
            'ledger_events': len(events), 'authentication': 'UNVERIFIED'}


def run_phase3b() -> dict:
    cases: dict[str, str] = {}
    with tempfile.TemporaryDirectory(prefix='apex-phase3b-SYNTHETIC-') as temp:
        root = Path(temp)
        script = 'scripts.apex_forward_phase3b_staging'
        env = dict(os.environ, APEX_FORWARD_PROVENANCE_ENABLED='1')

        def invoke(mode, scenario, expected=0):
            folder = root / scenario
            folder.mkdir(exist_ok=True)
            src, ledger = folder / 'synthetic_source.sqlite', folder / 'provenance.sqlite'
            proc = subprocess.run([sys.executable, '-m', script, '--worker', mode,
                                   '--source', str(src), '--ledger', str(ledger)],
                                  env=env, capture_output=True, text=True, timeout=15)
            if proc.returncode != expected:
                raise AssertionError(f'{scenario}/{mode} exit={proc.returncode}, expected={expected}, stderr={proc.stderr[:1200]}')
            return src, ledger

        src, led = invoke('full_chain', 'clean')
        assert fp.verify_chain(path=led)['rows'] == 3
        cases['fresh_process_three_stage_chain'] = 'PASS'
        before = [(r['event_id'], r['event_hash']) for r in rows(led)]
        invoke('retry_existing', 'clean')
        assert [(r['event_id'], r['event_hash']) for r in rows(led)] == before
        cases['idempotent_retry_preserves_original_receipts'] = 'PASS'

        src, led = invoke('after_gamma_source_before_receipt', 'gamma_gap', 73)
        assert audit(led, src)['gamma_source_without_receipt'] == ['gamma-3b']
        assert fp.verify_chain(path=led)['rows'] == 1
        cases['committed_gamma_missing_receipt_is_detected'] = 'PASS'
        # A post-crash retry sees existing gamma source row. It must NOT invent a receipt.
        assert not source_insert(src, 'gamma', 'gamma-3b')
        cases['postcrash_gamma_retry_does_not_backfill'] = 'PASS'

        src, led = invoke('after_gamma_receipt_before_decision', 'orphan_gamma', 73)
        report = audit(led, src)
        assert report['gamma_receipt_without_decision_receipt'] == ['gamma-3b']
        assert fp.verify_chain(path=led)['rows'] == 2
        cases['orphan_gamma_receipt_detected_without_promotion'] = 'PASS'

        src, led = invoke('after_decision_source_before_receipt', 'decision_gap', 73)
        assert audit(led, src)['decision_source_without_receipt'] == ['decision-3b']
        assert fp.verify_chain(path=led)['rows'] == 2
        cases['committed_decision_missing_receipt_is_detected'] = 'PASS'
        assert not source_insert(src, 'decision', 'decision-3b')
        cases['postcrash_decision_retry_does_not_backfill'] = 'PASS'

        src, led = invoke('restart_calc_gamma', 'boot_change', 73)
        origin_pid = json.loads(rows(led)[0]['payload_json'])['runtime']['pid']
        invoke('new_boot_decision', 'boot_change')
        d = [r for r in rows(led) if r['kind'] == 'DECISION_PERSISTED'][0]
        assert json.loads(d['payload_json'])['runtime']['pid'] != origin_pid
        assert json.loads(d['payload_json'])['evidence']['linkage_class'] == 'UNVERIFIED'
        assert d['execution_id'] is None
        cases['restart_fails_closed_on_cross_boot_linkage'] = 'PASS'

        src, led = invoke('full_chain', 'interrupted_txn')
        before = fp.verify_chain(path=led)
        invoke('transaction_crash', 'interrupted_txn', 73)
        after = fp.verify_chain(path=led)
        assert before == after and len(rows(led)) == 3
        cases['hard_crash_rolls_back_uncommitted_receipt'] = 'PASS'

        scenario = root / 'failed_write'
        scenario.mkdir()
        blocker = scenario / 'not_a_directory'
        blocker.write_text('SYNTHETIC PATH BLOCKER')
        proc = subprocess.run([sys.executable, '-m', script, '--worker', 'receipt_write_failure',
                               '--source', str(scenario / 'synthetic_source.sqlite'),
                               '--ledger', str(blocker / 'ledger.sqlite')],
                              env=env, capture_output=True, text=True, timeout=15)
        assert proc.returncode == 0, proc.stderr
        assert source_count(scenario / 'synthetic_source.sqlite', 'gamma', 'gamma-3b') == 1
        assert not (blocker / 'ledger.sqlite').exists()
        cases['receipt_storage_failure_preserves_source_and_unverified_status'] = 'PASS'

        # Fork test runs inside a fresh worker, avoiding fork in a threaded test runner.
        invoke('fork_self_check', 'fork_test')
        cases['forked_process_cannot_reuse_parent_boot'] = 'PASS'

    return {'ok': True, 'phase': '3B', 'environment': 'DISPOSABLE_SYNTHETIC_ONLY',
            'authentication': 'NOT_REAL_WORLD_AUTHENTICATION', 'promotion_authority': 'NONE',
            'production_data_accessed': False, 'historical_rows_modified': 0,
            'cases': cases, 'total_passed': len(cases)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--json', action='store_true')
    p.add_argument('--worker', choices=('full_chain', 'restart_calc_gamma',
        'after_gamma_source_before_receipt', 'after_gamma_receipt_before_decision',
        'after_decision_source_before_receipt', 'retry_existing', 'new_boot_decision',
        'transaction_crash', 'receipt_write_failure', 'fork_self_check'), help=argparse.SUPPRESS)
    p.add_argument('--source', type=Path, help=argparse.SUPPRESS)
    p.add_argument('--ledger', type=Path, help=argparse.SUPPRESS)
    args = p.parse_args()
    if args.worker:
        if not args.source or not args.ledger:
            return 2
        # Prevent accidental use of the fault injector against live production paths.
        # The parent harness always creates directories with this marker.
        marker = 'apex-phase3b-SYNTHETIC-'
        source_path = args.source.resolve()
        ledger_path = args.ledger.resolve()
        if not any(marker in part for part in source_path.parts) or not any(
            marker in part for part in ledger_path.parts
        ):
            print('REFUSED_NON_SYNTHETIC_PATH', file=sys.stderr)
            return 2
        return worker(args.worker, args.source, args.ledger)
    try:
        result = run_phase3b()
    except Exception as exc:
        result = {'ok': False, 'phase': '3B', 'status': 'FAILED',
                  'reason': type(exc).__name__ + ': ' + str(exc)}
    print(json.dumps(result, indent=2, sort_keys=True) if args.json else result)
    return 0 if result['ok'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
