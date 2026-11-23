"""Phase 4C isolated research: durable, transactional replay and checkpoint ledger.

This is a local SQLite *simulation* of a separately administered off-host store.
It is NOT real off-host storage, WORM retention, independent key custody,
production authentication, or authority to promote historical records.

One database transaction enforces a monotonically growing checkpoint chain.
The reservation register is intentionally irreversible: interrupted signing may
leave an orphan reservation and MUST NOT silently reuse its nonce.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Mapping

DOMAIN = 'APEX_PHASE4C_CHECKPOINT_V1'
HEX = re.compile(r'^[0-9a-f]{64}$')
SCHEMA = '''
CREATE TABLE IF NOT EXISTS nonce_reservations (
    nonce TEXT PRIMARY KEY,
    reserved_at_utc TEXT NOT NULL,
    purpose TEXT NOT NULL CHECK (purpose='DEPLOYMENT_OBSERVATION_ONLY')
);
CREATE TABLE IF NOT EXISTS checkpoints (
    seq INTEGER PRIMARY KEY CHECK (seq > 0),
    checkpoint_id TEXT NOT NULL UNIQUE,
    nonce TEXT NOT NULL UNIQUE REFERENCES nonce_reservations(nonce),
    predecessor_sha256 TEXT NOT NULL,
    attestation_sha256 TEXT NOT NULL,
    checkpoint_sha256 TEXT NOT NULL UNIQUE,
    created_at_utc TEXT NOT NULL,
    record_json TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS nonce_no_update BEFORE UPDATE ON nonce_reservations
BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY'); END;
CREATE TRIGGER IF NOT EXISTS nonce_no_delete BEFORE DELETE ON nonce_reservations
BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY'); END;
CREATE TRIGGER IF NOT EXISTS checkpoint_no_update BEFORE UPDATE ON checkpoints
BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY'); END;
CREATE TRIGGER IF NOT EXISTS checkpoint_no_delete BEFORE DELETE ON checkpoints
BEGIN SELECT RAISE(ABORT, 'APPEND_ONLY'); END;
'''

class CheckpointRefusal(ValueError):
    pass


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def sha(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def _time(stamp: str) -> str:
    if not isinstance(stamp, str):
        raise CheckpointRefusal('INVALID_TIMESTAMP')
    try:
        v = dt.datetime.fromisoformat(stamp.replace('Z', '+00:00'))
        if v.tzinfo is None or v.utcoffset() is None:
            raise ValueError()
        return v.astimezone(dt.timezone.utc).isoformat()
    except ValueError as exc:
        raise CheckpointRefusal('INVALID_TIMESTAMP') from exc


class StagingCheckpointStore:
    """Single-writer transactional repository; intentionally isolated staging only.

    Pass a test-directory db path. Do not use /data production paths, filesystem
    shares, symlinks or external NFS, and never run inside the APEX application.
    """
    def __init__(self, path: str | Path, *, environment: str = 'ISOLATED_STAGING'):
        if environment != 'ISOLATED_STAGING':
            raise CheckpointRefusal('PRODUCTION_STORAGE_NOT_SUPPORTED')
        self.path = Path(path).absolute()
        if self.path.is_symlink() or not self.path.parent.is_dir() or not self.path.parent.exists():
            raise CheckpointRefusal('UNSAFE_DATABASE_PATH')
        if str(self.path).startswith('/data/') or str(self.path).startswith('/audit-copy/'):
            raise CheckpointRefusal('PRODUCTION_DATABASE_PATH_REFUSED')
        self._initialize()

    def _connect(self, readonly: bool = False):
        if self.path.is_symlink():
            raise CheckpointRefusal('SYMLINK_REJECTED')
        if readonly:
            conn = sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True, timeout=10, isolation_level=None)
            conn.execute('PRAGMA query_only=ON')
        else:
            conn = sqlite3.connect(str(self.path), timeout=10, isolation_level=None)
        conn.execute('PRAGMA busy_timeout=10000')
        conn.execute('PRAGMA foreign_keys=ON')
        return conn

    def _initialize(self):
        con = self._connect()
        try:
            con.executescript('PRAGMA journal_mode=WAL;' + SCHEMA)
        finally:
            con.close()

    def reserve_nonce(self, nonce: str, *, at: str) -> bool:
        """Atomic replay barrier; a reservation persists even if signing fails."""
        if not isinstance(nonce, str) or not HEX.fullmatch(nonce):
            raise CheckpointRefusal('INVALID_NONCE')
        stamp = _time(at)
        con = self._connect()
        try:
            con.execute('BEGIN IMMEDIATE')
            con.execute('INSERT INTO nonce_reservations VALUES (?,?,?)',
                        (nonce, stamp, 'DEPLOYMENT_OBSERVATION_ONLY'))
            con.commit()
            return True
        except sqlite3.IntegrityError:
            con.rollback()
            return False
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def publish(self, *, nonce: str, attestation: Mapping[str, Any], at: str,
                expected_predecessor: str, envelope: Mapping[str, Any],
                policy: Mapping[str, Any]) -> dict:
        """Append iff Phase 4B staging attestation verifies and head is exact.

        An invalid or missing source is never backfilled. A checkpoint commit is
        atomic, but a previously committed nonce is never released.
        """
        from .forward_provenance_signer import verify_staging_attestation
        stamp = _time(at)
        if not isinstance(nonce, str) or not HEX.fullmatch(nonce):
            raise CheckpointRefusal('INVALID_NONCE')
        if not isinstance(expected_predecessor, str) or not HEX.fullmatch(expected_predecessor):
            raise CheckpointRefusal('INVALID_PREDECESSOR')
        verification = verify_staging_attestation(envelope=envelope, attestation=attestation,
                                                   policy=policy, as_of=stamp)
        if not verification.get('ok'):
            raise CheckpointRefusal('ATTESTATION_UNVERIFIED_' + verification.get('reason', 'UNKNOWN'))
        body = attestation.get('body', {})
        if (body.get('nonce') != nonce or body.get('environment') != 'ISOLATED_STAGING'
            or body.get('kind') != 'DEPLOYMENT_OBSERVATION_ONLY'
            or body.get('process_identity') != 'NOT_OBSERVED'
            or body.get('production_activation_authorized') is not False):
            raise CheckpointRefusal('UNAUTHORIZED_ATTESTATION')
        digest = sha(attestation)
        con = self._connect()
        try:
            con.execute('BEGIN IMMEDIATE')
            reserved = con.execute('SELECT nonce FROM nonce_reservations WHERE nonce=?', (nonce,)).fetchone()
            if not reserved:
                raise CheckpointRefusal('NONCE_NOT_RESERVED')
            latest = con.execute('SELECT seq, checkpoint_sha256 FROM checkpoints ORDER BY seq DESC LIMIT 1').fetchone()
            previous = latest[1] if latest else '0'*64
            if previous != expected_predecessor:
                raise CheckpointRefusal('CHECKPOINT_HEAD_CONFLICT')
            seq = latest[0] + 1 if latest else 1
            record = {'domain': DOMAIN, 'schema': '4C.1', 'environment': 'ISOLATED_STAGING',
                      'seq': seq, 'nonce': nonce, 'predecessor_sha256': previous,
                      'attestation_sha256': digest, 'created_at_utc': stamp,
                      'runtime_authentication': 'NOT_ESTABLISHED',
                      'production_activation_authorized': False, 'promotion_authority': 'NONE'}
            head = sha(record)
            con.execute('INSERT INTO checkpoints VALUES (?,?,?,?,?,?,?,?)',
                        (seq, f'checkpoint-{seq:012d}', nonce, previous, digest, head, stamp,
                         canonical(record).decode('utf-8')))
            con.commit()
            return {'ok': True, 'seq': seq, 'checkpoint_sha256': head,
                    'status': 'STAGING_CHECKPOINT_COMMITTED', 'verdict': 'NO_GO'}
        except sqlite3.IntegrityError as exc:
            con.rollback()
            raise CheckpointRefusal('REPLAY_OR_DUPLICATE_CHECKPOINT') from exc
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def audit(self, *, expected_anchor: str | None = None) -> dict:
        """Read-only chain audit. External anchor supplied by independent caller.

        A local anchor alone is NOT independently authenticated. The return value
        can never be VERIFIED, even when the expected anchor matches.
        """
        con = self._connect(readonly=True)
        try:
            rows = con.execute('SELECT seq,checkpoint_id,nonce,predecessor_sha256,attestation_sha256,'
                               'checkpoint_sha256,created_at_utc,record_json FROM checkpoints ORDER BY seq').fetchall()
            reservations = {r[0] for r in con.execute('SELECT nonce FROM nonce_reservations')}
        finally:
            con.close()
        previous = '0'*64
        seen = set()
        for n, (seq, cid, nonce, prev, att_sha, head, stamp, raw) in enumerate(rows, 1):
            try:
                record = json.loads(raw)
                if (seq != n or cid != f'checkpoint-{seq:012d}' or nonce in seen or nonce not in reservations
                    or prev != previous or record.get('domain') != DOMAIN or record.get('seq') != seq
                    or record.get('predecessor_sha256') != prev or record.get('attestation_sha256') != att_sha
                    or record.get('nonce') != nonce or record.get('created_at_utc') != stamp
                    or record.get('environment') != 'ISOLATED_STAGING'
                    or record.get('production_activation_authorized') is not False
                    or record.get('promotion_authority') != 'NONE'
                    or sha(record) != head or not HEX.fullmatch(att_sha)):
                    raise ValueError('chain mismatch')
            except (ValueError, TypeError, AttributeError):
                return {'ok': False, 'status': 'CHAIN_INTEGRITY_FAILURE', 'verdict': 'NO_GO', 'seq': seq}
            previous = head
            seen.add(nonce)
        if expected_anchor is not None and (not isinstance(expected_anchor, str) or expected_anchor != previous):
            return {'ok': False, 'status': 'EXTERNAL_ANCHOR_MISMATCH', 'verdict': 'NO_GO'}
        return {'ok': True, 'status': 'STAGING_CHAIN_CONSISTENT_NOT_AUTHENTICATED',
                'checkpoint_count': len(rows), 'reservation_count': len(reservations),
                'uncheckpointed_reservations': len(reservations - seen), 'head_sha256': previous,
                'external_anchor_provided': expected_anchor is not None,
                'production_activation_authorized': False, 'promotion_authority': 'NONE',
                'verdict': 'NO_GO'}
