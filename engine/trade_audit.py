"""engine/execution/trade_audit.py — append-only JSONL audit trail.

Logs every trade-command event to data/trade_audit/YYYY-MM-DD_spx_trade_command.jsonl.
Never logs API secrets. Non-fatal: a logging failure must never break a trade flow.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import threading
from typing import Any, Dict, List, Optional

_AUDIT_DIR = os.getenv("TRADE_AUDIT_DIR", os.path.join("data", "trade_audit"))
_AUDIT_LOCK = threading.Lock()

# Keys that must never be written to disk, at any nesting depth.
_SECRET_KEYS = frozenset({
    "consumer_key", "consumer_secret", "oauth_token", "oauth_token_secret",
    "authorization", "signature", "password", "secret", "api_key", "apikey",
    "etrade_consumer_key", "etrade_consumer_secret", "etrade_oauth_token",
    "etrade_oauth_token_secret",
})


def _redact(obj: Any) -> Any:
    """Recursively strip anything that looks like a secret."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if str(k).lower() in _SECRET_KEYS:
                out[k] = "***REDACTED***"
            else:
                out[k] = _redact(v)
        return out
    if isinstance(obj, (list, tuple)):
        return [_redact(v) for v in obj]
    return obj


def _today_path() -> str:
    day = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    return os.path.join(_AUDIT_DIR, f"{day}_spx_trade_command.jsonl")


def audit(event: str, payload: Optional[Dict[str, Any]] = None, *,
          actor: str = "apex", session_id: Optional[str] = None) -> bool:
    """Append one audit record. Returns True on success, False if it had to swallow
    an error (never raises). event examples: CONTRACT_SELECTED, PREVIEW_REQUEST,
    PREVIEW_RESPONSE, ORDER_PLACED, BROKER_RESPONSE, DRAG_EVENT, DRAG_REJECTED,
    CHANGE_ORDER, CANCEL_ORDER, FLATTEN_REQUEST, RISK_REJECTION, QUOTE_SNAPSHOT,
    APEX_SCORE_SNAPSHOT."""
    try:
        rec = {
            "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
            "event": event,
            "actor": actor,
            "session_id": session_id,
            "payload": _redact(payload or {}),
        }
        with _AUDIT_LOCK:
            os.makedirs(_AUDIT_DIR, exist_ok=True)
            with open(_today_path(), "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, default=str) + "\n")
        return True
    except Exception as e:  # never let auditing break a trade flow
        print(f"trade_audit error (non-fatal): {e}", flush=True)
        return False


def read_audit(day: Optional[str] = None, limit: int = 500) -> List[Dict[str, Any]]:
    """Return recent audit records for a day (default today), newest last."""
    try:
        day = day or dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
        path = os.path.join(_AUDIT_DIR, f"{day}_spx_trade_command.jsonl")
        if not os.path.exists(path):
            return []
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.readlines()[-limit:]
        out = []
        for ln in lines:
            try:
                out.append(json.loads(ln))
            except Exception:
                continue
        return out
    except Exception as e:
        print(f"read_audit error (non-fatal): {e}", flush=True)
        return []
