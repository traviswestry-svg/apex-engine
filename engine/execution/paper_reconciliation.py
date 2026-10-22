"""69.10.43: broker-evidence validation in a non-authorizing quarantine journal.

No TradersPost order/fill read API is configured. Only trusted server-owned
readers may supply evidence; this module never claims a webhook is a fill.
Evidence remains quarantined and cannot change paper_lifecycle state or P&L.
"""
from __future__ import annotations
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import hashlib
import json
import sqlite3
from engine.execution.paper_execution_foundation import _db_path, initialize_ledger


def _utc(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except (ValueError, TypeError) as exc:
        raise ValueError('INVALID_EVIDENCE_TIME') from exc
    if parsed.tzinfo is None or parsed > datetime.now(timezone.utc):
        raise ValueError('INVALID_EVIDENCE_TIME')
    return parsed.astimezone(timezone.utc).isoformat()


def _positive(value):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError) as exc:
        raise ValueError('INVALID_EVIDENCE_NUMBER') from exc
    if not number.is_finite() or number <= 0:
        raise ValueError('INVALID_EVIDENCE_NUMBER')
    return str(number)


def initialize_reconciliation(*, db_path=None):
    initialize_ledger(db_path=db_path)
    with sqlite3.connect(_db_path(db_path), timeout=10) as db:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('''CREATE TABLE IF NOT EXISTS paper_reconciliation_evidence (
          evidence_id TEXT PRIMARY KEY, lifecycle_id TEXT NOT NULL,
          broker_order_id TEXT NOT NULL, broker_event_id TEXT NOT NULL UNIQUE,
          event_type TEXT NOT NULL, contract_json TEXT NOT NULL,
          quantity INTEGER NOT NULL, price TEXT NOT NULL, observed_at TEXT NOT NULL,
          source TEXT NOT NULL, payload_digest TEXT NOT NULL, verdict TEXT NOT NULL,
          FOREIGN KEY(lifecycle_id) REFERENCES paper_lifecycle(id))''')
        db.commit()
    return {'ok': True, 'reconciliation_journal': 'AVAILABLE',
            'broker_reconciliation_operational': False, 'execution_authorized': False}


def validate_trusted_event(lifecycle_id, broker_event_id, *, trusted_reader, db_path=None):
    """Quarantine exact trusted-reader data; never promote fills or realized P&L.

    A reader is injected only by server code, never via a request body. Its
    `authenticated` marker is insufficient for promotion without a verified
    broker adapter and account/position snapshot reconciliation.
    """
    if not callable(trusted_reader) or not lifecycle_id or not broker_event_id:
        raise ValueError('TRUSTED_BROKER_READER_REQUIRED')
    event = trusted_reader(broker_event_id)
    if not isinstance(event, dict) or event.get('event_id') != broker_event_id:
        raise ValueError('BROKER_EVENT_NOT_FOUND')
    if event.get('source') != 'authenticated_broker_order_feed' or event.get('authenticated') is not True:
        raise ValueError('UNTRUSTED_BROKER_EVIDENCE')
    if event.get('event_type') not in ('ENTRY_FILL', 'EXIT_FILL', 'ORDER_REJECTED', 'ORDER_CANCELLED'):
        raise ValueError('INVALID_BROKER_EVENT_TYPE')
    if not isinstance(event.get('order_id'), str) or not event['order_id'].strip():
        raise ValueError('BROKER_ORDER_ID_REQUIRED')
    if type(event.get('quantity')) is not int or event['quantity'] < 1:
        raise ValueError('INVALID_QUANTITY')
    price = _positive(event.get('price'))
    at = _utc(event.get('observed_at'))
    initialize_reconciliation(db_path=db_path)
    with sqlite3.connect(_db_path(db_path), timeout=10) as db:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('''SELECT l.decision_id,l.contract_json,b.canonical_decision_id
          FROM paper_lifecycle l JOIN paper_decision_bindings b ON b.lifecycle_id=l.id
          WHERE l.id=?''', (lifecycle_id,)).fetchone()
        if not row or row[0] != row[2] or event.get('decision_id') != row[0]:
            raise ValueError('CANONICAL_BINDING_MISMATCH')
        contract = json.loads(row[1])
        if event.get('contract') != contract:
            raise ValueError('CONTRACT_MISMATCH')
        payload = {k:event[k] for k in ('event_id','order_id','event_type','quantity','price','observed_at','decision_id','contract','source')}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
        try:
            db.execute('''INSERT INTO paper_reconciliation_evidence
              (evidence_id,lifecycle_id,broker_order_id,broker_event_id,event_type,contract_json,
               quantity,price,observed_at,source,payload_digest,verdict)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
               (broker_event_id,lifecycle_id,event['order_id'],broker_event_id,
                event['event_type'],row[1],event['quantity'],price,at,event['source'],digest,'QUARANTINED_UNRECONCILED'))
        except sqlite3.IntegrityError as exc:
            raise ValueError('DUPLICATE_OR_CONFLICTING_BROKER_EVIDENCE') from exc
    return {'evidence_id': broker_event_id, 'verdict': 'QUARANTINED_UNRECONCILED',
            'fill_verified': False, 'position_reconciled': False,
            'realized_pnl_verified': False, 'dispatch_authorized': False}


def reconciliation_health(*, db_path=None):
    path = Path(_db_path(db_path))
    if not path.is_file():
        return {'journal_state':'NOT_INITIALIZED','quarantined_events':0,
                'broker_reconciliation_operational':False,'ready_for_unattended_orders':False}
    try:
        with sqlite3.connect(f'file:{path}?mode=ro',uri=True,timeout=3) as db:
            present = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='paper_reconciliation_evidence'").fetchone()
            count = db.execute('SELECT count(*) FROM paper_reconciliation_evidence').fetchone()[0] if present else 0
        return {'journal_state':'AVAILABLE' if present else 'NOT_INITIALIZED',
                'quarantined_events':count,'broker_reconciliation_operational':False,
                'ready_for_unattended_orders':False}
    except sqlite3.Error:
        return {'journal_state':'UNAVAILABLE','quarantined_events':0,
                'broker_reconciliation_operational':False,'ready_for_unattended_orders':False}
