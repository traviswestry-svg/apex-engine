"""69.10.44: offline TradersPost CSV evidence staging (never execution authority).

TradersPost does not expose a developer order/position read API. The product
announced CSV exports, but the exact export schema varies. Operators must map
CSV headings explicitly; never mistake an exported trade for a verified fill.
No web route, external HTTP request, or automatic reconciliation occurs here.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from engine.execution.paper_execution_foundation import _db_path, initialize_ledger

MAX_BYTES = 5 * 1024 * 1024
ALLOWED_TYPES = frozenset({'ENTRY_FILL', 'EXIT_FILL', 'ORDER_REJECTED', 'ORDER_CANCELLED'})
REQUIRED = ('event_id', 'order_id', 'event_type', 'decision_id', 'observed_at', 'contract_json', 'quantity', 'price')


def _timestamp(value):
    value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if value.tzinfo is None or value > datetime.now(timezone.utc):
        raise ValueError('INVALID_EXPORT_TIMESTAMP')
    return value.astimezone(timezone.utc).isoformat()


def initialize_export_inbox(*, db_path=None):
    initialize_ledger(db_path=db_path)
    with sqlite3.connect(_db_path(db_path), timeout=10) as db:
        db.execute('''CREATE TABLE IF NOT EXISTS paper_export_inbox (
          evidence_id TEXT PRIMARY KEY, lifecycle_id TEXT NOT NULL,
          decision_id TEXT NOT NULL, order_id TEXT NOT NULL,
          event_type TEXT NOT NULL, quantity INTEGER NOT NULL,
          observed_at TEXT NOT NULL, contract_json TEXT NOT NULL,
          payload_digest TEXT NOT NULL, csv_digest TEXT NOT NULL,
          verdict TEXT NOT NULL,
          FOREIGN KEY(lifecycle_id) REFERENCES paper_lifecycle(id))''')
        db.commit()
    return {'state': 'AVAILABLE', 'broker_reconciliation_operational': False}


def stage_csv(csv_bytes, *, column_map, lifecycle_by_decision, db_path=None):
    """Server-side/offline only. Mapping and identities must come from trusted operator.

    Atomic all-or-nothing batch. All staged rows remain QUARANTINED_MANUAL_EXPORT.
    In particular, an export CSV cannot certify its own authenticity, and no
    account snapshots, fill promotion, position or P&L writes occur.
    """
    if not isinstance(csv_bytes, bytes) or not csv_bytes or len(csv_bytes) > MAX_BYTES:
        raise ValueError('INVALID_EXPORT_SIZE')
    if not isinstance(column_map, dict) or set(column_map) != set(REQUIRED):
        raise ValueError('EXPLICIT_COLUMN_MAPPING_REQUIRED')
    if not isinstance(lifecycle_by_decision, dict):
        raise ValueError('EXPLICIT_DECISION_BINDINGS_REQUIRED')
    raw = csv_bytes.decode('utf-8-sig')
    rows = list(csv.DictReader(io.StringIO(raw, newline='')))
    if not rows or len(rows) > 10000:
        raise ValueError('INVALID_EXPORT_ROWS')
    if any(not isinstance(name, str) or name not in (rows[0].keys()) for name in column_map.values()):
        raise ValueError('MISSING_EXPORT_COLUMN')
    parsed = []
    for row in rows:
        e = {key: row[col] for key, col in column_map.items()}
        if any(not isinstance(v, str) or not v.strip() for v in e.values()):
            raise ValueError('MISSING_EXPORT_VALUE')
        if e['event_type'] not in ALLOWED_TYPES:
            raise ValueError('UNRECOGNIZED_EXPORT_EVENT')
        try:
            qty = int(e['quantity'])
            if qty <= 0 or str(qty) != e['quantity'].strip():
                raise ValueError
            contract = json.loads(e['contract_json'])
            if not isinstance(contract, dict):
                raise ValueError
            from decimal import Decimal
            price = Decimal(e['price'])
            if not price.is_finite() or price < 0:
                raise ValueError
            at = _timestamp(e['observed_at'])
        except (ValueError, TypeError, KeyError, json.JSONDecodeError, ArithmeticError) as exc:
            raise ValueError('INVALID_EXPORT_ROW') from exc
        lifecycle = lifecycle_by_decision.get(e['decision_id'])
        if not isinstance(lifecycle, str) or not lifecycle:
            raise ValueError('UNMATCHED_CANONICAL_DECISION')
        digest = hashlib.sha256(json.dumps(e, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        parsed.append((e['event_id'], lifecycle, e['decision_id'], e['order_id'],
                       e['event_type'], qty, at, json.dumps(contract, sort_keys=True), digest))
    initialize_export_inbox(db_path=db_path)
    csv_digest = hashlib.sha256(csv_bytes).hexdigest()
    with sqlite3.connect(_db_path(db_path), timeout=10) as db:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('BEGIN IMMEDIATE')
        for entry in parsed:
            row = db.execute('''SELECT l.decision_id, l.contract_json, b.canonical_decision_id
                FROM paper_lifecycle l JOIN paper_decision_bindings b ON b.lifecycle_id=l.id
                WHERE l.id=?''', (entry[1],)).fetchone()
            if not row or row[0] != entry[2] or row[2] != entry[2] or json.loads(row[1]) != json.loads(entry[7]):
                raise ValueError('CANONICAL_CONTRACT_OR_DECISION_MISMATCH')
            try:
                db.execute('''INSERT INTO paper_export_inbox VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
                           (*entry, csv_digest, 'QUARANTINED_MANUAL_EXPORT'))
            except sqlite3.IntegrityError as exc:
                raise ValueError('DUPLICATE_EXPORT_EVENT') from exc
    return {'staged': len(parsed), 'csv_sha256': csv_digest,
            'verdict': 'QUARANTINED_MANUAL_EXPORT', 'fill_verified': False,
            'broker_reconciliation_operational': False, 'ready_for_unattended_orders': False}


def export_inbox_health(*, db_path=None):
    path = Path(_db_path(db_path))
    if not path.is_file():
        return {'state':'NOT_INITIALIZED', 'quarantined_csv_events':0}
    try:
        with sqlite3.connect(f'file:{path}?mode=ro', uri=True, timeout=3) as db:
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='paper_export_inbox'").fetchone()
            n = db.execute('SELECT COUNT(*) FROM paper_export_inbox').fetchone()[0] if exists else 0
        return {'state':'AVAILABLE' if exists else 'NOT_INITIALIZED','quarantined_csv_events':n}
    except sqlite3.Error:
        return {'state':'UNAVAILABLE','quarantined_csv_events':0}
