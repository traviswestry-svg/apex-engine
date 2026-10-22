"""APEX 69.10.41: durable, fail-closed paper execution authority foundation.

This is an evidence/authority boundary, NOT a TradersPost broker fill adapter.
No callable in this module sends orders or infers fills from HTTP receipts.
"""
from __future__ import annotations
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from zoneinfo import ZoneInfo
import hashlib
import json
import os
import sqlite3

ET = ZoneInfo("America/New_York")
VERSION = "69.10.42"
REQUIRED_STATES = ("DECISION_OBSERVED", "APPROVED", "SUBMITTED_UNCONFIRMED", "DELIVERY_UNKNOWN",
                   "BROKER_ACKNOWLEDGED", "FILL_VERIFIED", "EXIT_VERIFIED", "RECONCILED_CLOSED", "REJECTED")

def _db_path(path=None):
    return str(path or os.environ.get("APEX_TRADERSPOST_LEDGER_DB", "/data/apex_traderspost_paper.sqlite3"))

def _connect(path=None):
    db = sqlite3.connect(_db_path(path), timeout=10)
    db.execute("PRAGMA busy_timeout=10000")
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""CREATE TABLE IF NOT EXISTS paper_lifecycle (
      id TEXT PRIMARY KEY, decision_id TEXT NOT NULL, state TEXT NOT NULL,
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL, contract_json TEXT NOT NULL,
      decision_origin TEXT NOT NULL, execution_source TEXT,
      entry_fill_id TEXT, exit_fill_id TEXT, realized_pnl TEXT,
      UNIQUE(decision_id, id))""")
    db.execute("""CREATE TABLE IF NOT EXISTS paper_lifecycle_events (
      sequence INTEGER PRIMARY KEY AUTOINCREMENT, lifecycle_id TEXT NOT NULL,
      at TEXT NOT NULL, from_state TEXT, to_state TEXT NOT NULL,
      evidence_origin TEXT NOT NULL, evidence_digest TEXT NOT NULL,
      FOREIGN KEY(lifecycle_id) REFERENCES paper_lifecycle(id))""")
    db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS unique_paper_fill_evidence
       ON paper_lifecycle(execution_source,entry_fill_id) WHERE entry_fill_id IS NOT NULL""")
    db.commit()
    return db

def initialize_ledger(*, db_path=None):
    """Explicitly create the ledger on persistent storage; NEVER authorize trading.

    No HTTP mutation route exposes this initializer. Invoke from controlled service
    startup/migration after ensuring /data is a mounted persistent disk.
    """
    path = Path(_db_path(db_path))
    if not path.parent.is_dir():
        raise RuntimeError("PAPER_LEDGER_PARENT_MISSING")
    with _connect(str(path)) as db:
        check = db.execute("PRAGMA integrity_check").fetchone()[0]
        if check != "ok":
            raise RuntimeError("PAPER_LEDGER_INTEGRITY_FAILURE")
        db.execute("CREATE TABLE IF NOT EXISTS paper_decision_bindings (lifecycle_id TEXT PRIMARY KEY, canonical_decision_id TEXT NOT NULL, source_record_id TEXT NOT NULL, source_digest TEXT NOT NULL, bound_at TEXT NOT NULL, FOREIGN KEY(lifecycle_id) REFERENCES paper_lifecycle(id))")
        db.commit()
    return {"ok": True, "ledger_state": "AVAILABLE", "db_exists": path.is_file(), "dispatch_authorized": False}


def persisted_canonical_reader(decision_id, *, evidence_db=None):
    """Read an existing scanner-persisted decision, never an HTTP supplied object.

    The evidence pipeline stores decision IDs and bounded snapshots. This reader
    intentionally does NOT infer execution approval from learning eligibility.
    """
    from engine.evidence_pipeline import DEFAULT_DB
    path = Path(evidence_db or DEFAULT_DB)
    if not path.is_file() or not decision_id:
        return None
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=3) as db:
            row = db.execute(
                "SELECT decision_id, observed_at, ticker, snapshot_json FROM decisions WHERE decision_id=?",
                (decision_id,),
            ).fetchone()
    except (sqlite3.Error, ValueError):
        return None
    if not row or row[2] != "SPX":
        return None
    try:
        snapshot_json = json.loads(row[3]); institutional = snapshot_json.get("institutional_decision_object") or {}
        contract = institutional.get("authoritative_contract") or snapshot_json.get("authoritative_contract")
    except (TypeError, ValueError, AttributeError):
        return None
    if not isinstance(contract, dict) or contract.get("ticker") != "SPX":
        return None
    return {"decision_id": row[0], "record_id": row[0],
            "origin": "canonical_scanner_persistence", "contract": contract,
            "persisted": True, "observed_at": row[1]}


def canonical_binding_health(*, evidence_db=None):
    """Reports whether the real evidence-store reader is connected and readable.

    Not a claim that any particular contract/decision is tradable.
    """
    from engine.evidence_pipeline import DEFAULT_DB
    path = Path(evidence_db or DEFAULT_DB)
    if not path.is_file():
        return {"operational": False, "reason": "EVIDENCE_DB_MISSING"}
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=3) as db:
            cols = {row[1] for row in db.execute("PRAGMA table_info(decisions)")}
            valid = {"decision_id", "snapshot_json", "observed_at", "ticker"} <= cols
        return {"operational": valid, "reason": "READY" if valid else "CANONICAL_SCHEMA_MISSING"}
    except sqlite3.Error:
        return {"operational": False, "reason": "EVIDENCE_DB_UNREADABLE"}


def bind_persisted_canonical_observation(identifier, decision_id, contract, *, observed_at, db_path=None, evidence_db=None):
    return bind_canonical_observation(identifier, decision_id, contract,
        trusted_reader=lambda did: persisted_canonical_reader(did, evidence_db=evidence_db),
        observed_at=observed_at, db_path=db_path)


def bind_canonical_observation(identifier, decision_id, contract, *, trusted_reader, observed_at, db_path=None):
    """Read exact, persisted server-owned evidence using a server-injected reader.

    No request route accepts a reader, origin, or approval assertion. This binds
    identity ONLY; it is deliberately not authorization to place an order.
    `trusted_reader` must return the persisted record with exact decision ID,
    contract, source record ID, and an origin from the canonical evidence store.
    """
    if not callable(trusted_reader):
        raise ValueError("TRUSTED_READER_REQUIRED")
    source = trusted_reader(decision_id)
    if not isinstance(source, dict) or source.get("decision_id") != decision_id:
        raise ValueError("CANONICAL_DECISION_NOT_FOUND")
    if not source.get("record_id") or source.get("origin") not in ("canonical_decision_store", "canonical_scanner_persistence"):
        raise ValueError("INVALID_CANONICAL_ORIGIN")
    if not isinstance(source.get("contract"), dict) or source["contract"] != contract:
        raise ValueError("CANONICAL_CONTRACT_MISMATCH")
    if not source.get("persisted", False):
        raise ValueError("UNPERSISTED_DECISION")
    at = _timestamp(observed_at)
    source_payload = {"decision_id":decision_id,"record_id":source["record_id"],"origin":source["origin"],"contract":contract}
    digest = hashlib.sha256(json.dumps(source_payload,sort_keys=True,separators=(",", ":")).encode()).hexdigest()
    initialize_ledger(db_path=db_path)
    # Observation and provenance binding are atomic. Duplicate IDs fail closed.
    with _connect(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        payload=json.dumps(contract,sort_keys=True,separators=(",", ":"))
        try:
            db.execute("INSERT INTO paper_lifecycle(id,decision_id,state,created_at,updated_at,contract_json,decision_origin) VALUES(?,?,?,?,?,?,?)",
                (identifier,decision_id,"DECISION_OBSERVED",at,at,payload,source["origin"]))
            db.execute("INSERT INTO paper_decision_bindings(lifecycle_id,canonical_decision_id,source_record_id,source_digest,bound_at) VALUES(?,?,?,?,?)",
                (identifier,decision_id,str(source["record_id"]),digest,at))
            db.execute("INSERT INTO paper_lifecycle_events(lifecycle_id,at,from_state,to_state,evidence_origin,evidence_digest) VALUES(?,?,?,?,?,?)",
                (identifier,at,None,"DECISION_OBSERVED",source["origin"],digest))
        except sqlite3.IntegrityError:
            raise ValueError("duplicate lifecycle identity") from None
    return {"id":identifier,"state":"DECISION_OBSERVED","canonical_bound":True,"dispatch_authorized":False}

def _timestamp(value):
    at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if at.tzinfo is None:
        raise ValueError("evidence timestamp must include timezone")
    if at > datetime.now(timezone.utc):
        raise ValueError("future evidence timestamp")
    return at.astimezone(timezone.utc).isoformat()

def _money(value):
    try:
        n = Decimal(str(value))
    except (InvalidOperation, TypeError):
        raise ValueError("invalid P&L") from None
    if not n.is_finite():
        raise ValueError("nonfinite P&L")
    return n

def observe_decision(identifier, decision_id, contract, *, origin, observed_at, db_path=None):
    """Record a genuine observation; never authorize or dispatch from this operation."""
    if not identifier or not decision_id or not origin or origin in ("operator_assertion", "webhook"):
        raise ValueError("canonical observation identity and origin required")
    if not isinstance(contract, dict) or contract.get("ticker") != "SPX":
        raise ValueError("SPX option contract required")
    at = _timestamp(observed_at)
    payload = json.dumps(contract, sort_keys=True, separators=(",", ":"))
    with _connect(db_path) as db:
        try:
            db.execute("INSERT INTO paper_lifecycle(id,decision_id,state,created_at,updated_at,contract_json,decision_origin) VALUES(?,?,?,?,?,?,?)",
                       (identifier, decision_id, "DECISION_OBSERVED", at, at, payload, origin))
            db.execute("INSERT INTO paper_lifecycle_events(lifecycle_id,at,from_state,to_state,evidence_origin,evidence_digest) VALUES(?,?,?,?,?,?)",
                       (identifier,at,None,"DECISION_OBSERVED",origin,hashlib.sha256(payload.encode()).hexdigest()))
        except sqlite3.IntegrityError:
            raise ValueError("duplicate lifecycle identity") from None
    return {"id": identifier, "state": "DECISION_OBSERVED", "dispatch_authorized": False}

def note_evidence(identifier, state, *, origin, observed_at, evidence, db_path=None):
    """Persist evidence but NEVER promote to verified fills absent trusted adapter.

    Even a caller supplying 'FILL_VERIFIED' is rejected until a broker adapter
    independently authenticates and correlates a fill (not implemented here).
    """
    if state not in ("REJECTED", "DELIVERY_UNKNOWN", "SUBMITTED_UNCONFIRMED", "BROKER_ACKNOWLEDGED"):
        raise ValueError("state requires trusted server-owned verification adapter")
    if not origin or not isinstance(evidence, dict):
        raise ValueError("evidence origin and data required")
    if state == "BROKER_ACKNOWLEDGED":
        raise ValueError("broker acknowledgement requires independently authenticated adapter")
    at = _timestamp(observed_at)
    digest = hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()
    with _connect(db_path) as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT state FROM paper_lifecycle WHERE id=?", (identifier,)).fetchone()
        if row is None:
            raise ValueError("unknown lifecycle")
        old = row[0]
        if old not in ("DECISION_OBSERVED", "SUBMITTED_UNCONFIRMED", "DELIVERY_UNKNOWN"):
            raise ValueError("terminal or unsupported transition")
        if state == "SUBMITTED_UNCONFIRMED" and old != "DECISION_OBSERVED":
            raise ValueError("unsupported transition")
        if state == "DELIVERY_UNKNOWN" and old not in ("DECISION_OBSERVED", "SUBMITTED_UNCONFIRMED"):
            raise ValueError("unsupported transition")
        db.execute("UPDATE paper_lifecycle SET state=?,updated_at=? WHERE id=?", (state,at,identifier))
        db.execute("INSERT INTO paper_lifecycle_events(lifecycle_id,at,from_state,to_state,evidence_origin,evidence_digest) VALUES(?,?,?,?,?,?)",
                   (identifier,at,old,state,origin,digest))
    return {"id":identifier, "state":state, "fill_verified":False}

def snapshot(*, db_path=None, daily_limit=Decimal("1000")):
    """Read-only, fail-closed reconciliation and risk snapshot.

    Never equates observed price movement with actual realized P&L. Unknown fills
    or any unverified position means no deployable daily-loss authority.
    """
    path = Path(_db_path(db_path))
    if not path.is_file():
        return {"ok": True, "ledger_state": "NOT_INITIALIZED", "ready_for_unattended_orders":False,
                "realized_loss_enforced": False, "risk_state":"BLOCKED_UNVERIFIED_EVIDENCE",
                "reconciliation_state":"NOT_INITIALIZED", "records":0, "verified_closed":0,
                "unresolved":0, "realized_pnl":None, "daily_loss_limit":str(daily_limit)}
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
            rows = db.execute("SELECT state,created_at,realized_pnl FROM paper_lifecycle").fetchall()
    except sqlite3.Error:
        return {"ok":False,"ledger_state":"UNAVAILABLE","ready_for_unattended_orders":False,
                "realized_loss_enforced":False,"risk_state":"BLOCKED_LEDGER_UNAVAILABLE",
                "reconciliation_state":"UNAVAILABLE"}
    today = datetime.now(ET).date()
    daily = Decimal(0)
    verified = 0
    for state,created,pnl in rows:
        if state == "RECONCILED_CLOSED" and pnl is not None:
            verified += 1
            if datetime.fromisoformat(created).astimezone(ET).date() == today:
                daily += _money(pnl)
    unresolved = sum(state != "RECONCILED_CLOSED" and state != "REJECTED" for state,_,_ in rows)
    return {"ok":True,"ledger_state":"AVAILABLE","ready_for_unattended_orders":False,
            "realized_loss_enforced":False,"risk_state":"BLOCKED_UNVERIFIED_EVIDENCE",
            "reconciliation_state":"UNVERIFIED" if unresolved else "NO_BROKER_RECONCILIATION",
            "records":len(rows),"verified_closed":verified,"unresolved":unresolved,
            "realized_pnl":str(daily) if verified else None,"daily_loss_limit":str(daily_limit)}
