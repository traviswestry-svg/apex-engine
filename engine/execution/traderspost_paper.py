"""APEX 69.10.39: isolated, fail-closed TradersPost paper-signal gateway.

Webhook HTTP acceptance is NOT evidence of a broker fill. Independent grading
requires separately supplied, timestamped option bid/ask observations.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import hashlib
import json
import os
import sqlite3
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

VERSION = '69.10.39'
ET = ZoneInfo('America/New_York')


def now_utc():
    return datetime.now(timezone.utc)


def database_path():
    return os.getenv('APEX_TRADERSPOST_LEDGER_DB', '/data/apex_traderspost_paper.sqlite3')


def connect(path=None):
    db = sqlite3.connect(str(path or database_path()), timeout=10)
    db.execute('PRAGMA busy_timeout=10000')
    db.execute('''CREATE TABLE IF NOT EXISTS paper_signals (
        signal_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, status TEXT NOT NULL,
        payload_json TEXT NOT NULL, decision_id TEXT NOT NULL, response_code INTEGER,
        response_hash TEXT, error_code TEXT)''')
    db.execute('''CREATE TABLE IF NOT EXISTS paper_quotes (
        signal_id TEXT NOT NULL, role TEXT NOT NULL, observed_at TEXT NOT NULL,
        bid TEXT NOT NULL, ask TEXT NOT NULL, qty INTEGER NOT NULL,
        source TEXT NOT NULL, PRIMARY KEY(signal_id,role))''')
    db.commit()
    return db


def _positive_decimal(value, name):
    try:
        n = Decimal(str(value))
        if not n.is_finite() or n <= 0:
            raise ValueError(name + ' must be positive and finite')
        return n
    except (InvalidOperation, TypeError):
        raise ValueError(name + ' must be a number') from None


def make_signal(request_data, clock=None):
    """Create exact-contract SPX long option opening/exit signal only."""
    d = dict(request_data)
    when = clock or now_utc()
    local = when.astimezone(ET)
    # Exit instructions remain available until 11:55 ET for protective flattening.
    minutes = local.hour * 60 + local.minute
    cutoff = 11 * 60 + (55 if d.get('action') == 'exit' else 30)
    if local.weekday() >= 5 or not 9 * 60 + 35 <= minutes <= cutoff:
        raise ValueError('outside weekday paper signal window')
    if d.get('ticker') != 'SPX':
        raise ValueError('SPX index options only')
    side = d.get('option_type')
    if side not in ('call', 'put'):
        raise ValueError('option_type must be call or put')
    action = d.get('action')
    if action not in ('open', 'exit'):
        raise ValueError('action must be open or exit')
    if not isinstance(d.get('decision_id'), str) or not (1 <= len(d['decision_id']) <= 120):
        raise ValueError('canonical decision_id required')
    if d.get('governance_approved') is not True or d.get('human_approved') is not True:
        raise ValueError('canonical governance and human approval required')
    if not isinstance(d.get('expiration'), str) or len(d['expiration']) != 10:
        raise ValueError('explicit ISO expiration required')
    try:
        exp = datetime.strptime(d['expiration'], '%Y-%m-%d').date()
    except ValueError:
        raise ValueError('invalid expiration') from None
    if exp < local.date():
        raise ValueError('expired contract')
    strike = _positive_decimal(d.get('strike'), 'strike')
    premium = _positive_decimal(d.get('ask'), 'ask')
    bid = _positive_decimal(d.get('bid'), 'bid')
    if bid > premium:
        raise ValueError('crossed option market')
    qty = d.get('quantity')
    if type(qty) is not int or not 1 <= qty <= 3:
        raise ValueError('quantity must be 1–3 contracts')
    if action == 'open' and premium * qty * 100 > 2000:
        raise ValueError('initial debit exceeds $2,000')
    identifier = d.get('signal_id')
    if not isinstance(identifier, str) or not (8 <= len(identifier) <= 120) or not all(c.isalnum() or c in '-_.' for c in identifier):
        raise ValueError('stable unique signal_id required')
    # action=exit applies to this strategy's SPX position; avoid opening another direction.
    payload = {'ticker': 'SPX', 'action': 'exit' if action == 'exit' else ('buy' if side == 'call' else 'sell'),
               'expiration': d['expiration'], 'optionType': side,
               'strikePrice': float(strike), 'quantity': qty, 'time': when.isoformat(),
               'signalPrice': float(premium), 'extras': {'apex_signal_id': identifier, 'apex_decision_id': d['decision_id'], 'paper_only': True}}
    return payload


def dispatch(d, *, db_path=None, sender=None, clock=None):
    """No sending unless explicitly armed. Never accept a live-mode override."""
    if os.getenv('APEX_LIVE_ORDER_ROUTING_ENABLED', 'false').lower() == 'true':
        raise ValueError('paper-only mode forbids live E*TRADE order routing')
    if os.getenv('APEX_TRADERSPOST_MODE', 'disabled') != 'paper':
        raise ValueError('paper gateway disabled')
    if os.getenv('APEX_TRADERSPOST_PAPER_CONFIRMED', 'false').lower() != 'true':
        raise ValueError('paper-only subscription not confirmed')
    if os.getenv('APEX_TRADERSPOST_SEND_ENABLED', 'false').lower() != 'true':
        raise ValueError('webhook sends disabled')
    url = os.getenv('APEX_TRADERSPOST_WEBHOOK_URL', '')
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname != 'webhooks.traderspost.io' or not parsed.path.startswith('/trading/webhook/') or len(parsed.path.split('/')) != 5:
        raise ValueError('invalid TradersPost webhook URL')
    payload = make_signal(d, clock=clock)
    signal_id = d['signal_id']
    with connect(db_path) as db:
        # Limit new entries to three per ET calendar day; count delivery-unknown entries.
        if d['action'] == 'open':
            existing = db.execute('SELECT created_at,payload_json FROM paper_signals').fetchall()
            et_day = (clock or now_utc()).astimezone(ET).date()
            if sum(datetime.fromisoformat(r[0]).astimezone(ET).date() == et_day and
                   json.loads(r[1]).get('action') in ('buy', 'sell') for r in existing) >= 3:
                raise ValueError('daily maximum of 3 paper entries reached')
        try:
            db.execute('INSERT INTO paper_signals(signal_id,created_at,status,payload_json,decision_id) VALUES(?,?,?,?,?)',
                       (signal_id, (clock or now_utc()).isoformat(), 'PENDING', json.dumps(payload, sort_keys=True), d['decision_id']))
            db.commit()
        except sqlite3.IntegrityError:
            return {'signal_id': signal_id, 'status': 'DUPLICATE_SUPPRESSED', 'fill_confirmed': False}
        try:
            req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'}, method='POST')
            if sender is None:
                with urllib.request.urlopen(req, timeout=5) as response:
                    status_code = response.status
                    body = response.read(8192)
            else:
                status_code, body = sender(req)
            status_code = int(status_code)
            status = 'WEBHOOK_ACCEPTED_UNCONFIRMED' if 200 <= status_code < 300 else 'WEBHOOK_REJECTED'
            db.execute('UPDATE paper_signals SET status=?,response_code=?,response_hash=? WHERE signal_id=?',
                       (status, status_code, hashlib.sha256(body if isinstance(body, bytes) else str(body).encode()).hexdigest(), signal_id))
        except Exception:
            # Network failures can mean the remote request was processed: do not retry automatically.
            status = 'DELIVERY_UNKNOWN'
            db.execute('UPDATE paper_signals SET status=?,error_code=? WHERE signal_id=?', (status, 'DELIVERY_EXCEPTION', signal_id))
        db.commit()
    return {'signal_id': signal_id, 'status': status, 'fill_confirmed': False}


def record_quote(signal_id, role, *, observed_at, bid, ask, quantity, source, db_path=None):
    """Strict external quote evidence; never infer it from TradersPost paper fills."""
    if role not in ('entry', 'exit') or not source or source.lower() in ('traderspost_paper', 'synthetic'):
        raise ValueError('independent external quote source required')
    b, a = _positive_decimal(bid, 'bid'), _positive_decimal(ask, 'ask')
    if b > a or type(quantity) is not int or not 1 <= quantity <= 3:
        raise ValueError('invalid spread or size')
    parsed = datetime.fromisoformat(observed_at.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('timestamp must be timezone aware')
    if parsed > now_utc():
        raise ValueError('future quote')
    with connect(db_path) as db:
        if not db.execute('SELECT 1 FROM paper_signals WHERE signal_id=?', (signal_id,)).fetchone():
            raise ValueError('unknown signal')
        db.execute('INSERT INTO paper_quotes VALUES(?,?,?,?,?,?,?)', (signal_id, role, observed_at, str(b), str(a), quantity, source))
        db.commit()


def grade(signal_id, *, db_path=None, fee_per_contract=Decimal('0.00')):
    with connect(db_path) as db:
        rows = db.execute('SELECT role, observed_at,bid,ask,qty,source FROM paper_quotes WHERE signal_id=?', (signal_id,)).fetchall()
    quotes = {r[0]: r for r in rows}
    if len(quotes) != 2:
        return {'signal_id': signal_id, 'status': 'PENDING_INDEPENDENT_QUOTES', 'missing': [r for r in ('entry','exit') if r not in quotes]}
    entry, exit_ = quotes['entry'], quotes['exit']
    if datetime.fromisoformat(exit_[1].replace('Z','+00:00')) <= datetime.fromisoformat(entry[1].replace('Z','+00:00')):
        raise ValueError('exit precedes entry')
    if entry[4] != exit_[4]:
        raise ValueError('quantity mismatch; partial fills must be reconciled separately')
    # Conservative long-option gross P&L: pay ask, liquidate at bid.
    debit = Decimal(entry[3]) * entry[4] * 100
    credit = Decimal(exit_[2]) * exit_[4] * 100
    fees = _positive_decimal(fee_per_contract, 'fee') * 2 * entry[4] if fee_per_contract else Decimal(0)
    return {'signal_id': signal_id, 'status': 'INDEPENDENT_QUOTE_MODEL', 'actual_fill_verified': False,
            'model': 'long_option_entry_ask_exit_bid', 'entry_debit': float(debit),
            'exit_credit': float(credit), 'estimated_net_pnl': float(credit - debit - fees),
            'fees': float(fees), 'quote_sources': [entry[5], exit_[5]]}
