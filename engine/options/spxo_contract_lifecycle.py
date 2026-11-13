"""APEX SPXO lifecycle compatibility: conservative, read-only contract classification.

Cboe November 2026 launch: SPXO AM-settled, SET opening settlement,
expiring contracts cease trading at 17:00 ET preceding business day.
Only the announced Nov 18 and Dec 16 expiries have explicit cutoff dates
here; future listings require verified exchange calendars. No trading authority.
"""
from __future__ import annotations
from datetime import date, datetime
from typing import Mapping, Any
from zoneinfo import ZoneInfo
import re

ET = ZoneInfo("America/New_York")
KNOWN_SPXO_EXPIRATIONS = {"2026-11-18": "2026-11-17T17:00:00-05:00", "2026-12-16": "2026-12-15T17:00:00-05:00"}
ROOT_PATTERN = re.compile(r"^(?:O:)?(SPXW|SPXO|SPX)(?=\s|\d|$)", re.IGNORECASE)


def option_root(value: Any) -> str | None:
    """Exact leading contract root only; never infer from the index ticker."""
    m = ROOT_PATTERN.match(str(value or "").strip().upper())
    return m.group(1) if m else None


def classify_contract(raw: Mapping[str, Any]) -> dict:
    """Return separate underlying and option-class identity without guessing unknowns."""
    symbols = [raw.get(k) for k in ("osi_key", "osiKey", "option_symbol", "contract_symbol", "contract_ticker")]
    # Source 'symbol' is a contract only if it matches an exact option-root prefix;
    # bare SPX as the underlying is not sufficient for a settlement classification.
    candidate_symbol = str(raw.get("symbol") or "").strip()
    if candidate_symbol.upper().startswith("O:") or len(candidate_symbol) > 6:
        symbols.append(candidate_symbol)
    roots = {v for v in (option_root(x) for x in symbols if x) if v}
    declared = str(raw.get("contract_class") or raw.get("option_root") or "").strip().upper()
    if declared:
        roots.add(declared)
    root = next(iter(roots)) if len(roots) == 1 else None
    exp = str(raw.get("expiration") or raw.get("expiry") or raw.get("expiration_date") or "")
    supplied_settlement = str(raw.get("settlement_type") or "").strip().upper()
    required = {"SPXO": "AM", "SPXW": "PM", "SPX": "AM"}
    verified_class = root in required and len(roots) == 1
    settlement_type = required.get(root) if verified_class else "UNKNOWN"
    contradictions = bool(supplied_settlement and (not verified_class or supplied_settlement != settlement_type))
    supplied_ref = str(raw.get("settlement_reference") or "").strip().upper()
    reference = "SET" if root in ("SPXO", "SPX") else "CLOSING_INDEX" if root == "SPXW" else "UNKNOWN"
    if supplied_ref and supplied_ref != reference:
        contradictions = True
    cutoff = KNOWN_SPXO_EXPIRATIONS.get(exp) if root == "SPXO" else None
    if root == "SPXO" and raw.get("last_trading_timestamp") and raw.get("last_trading_timestamp") != cutoff:
        contradictions = True
    # A verified root is not sufficient for broker authorization.
    status = "BLOCKED_CONFLICT" if contradictions or len(roots) > 1 else ("RECOGNIZED_NO_EXECUTION_AUTHORITY" if verified_class else "UNKNOWN_BLOCKED")
    return {"contract_class": root if verified_class else "UNKNOWN", "settlement_type": settlement_type,
            "settlement_reference": reference, "last_trading_timestamp": cutoff,
            "lifecycle_status": status, "execution_eligible": False,
            "is_spxo": root == "SPXO", "identity_conflict": contradictions or len(roots) > 1,
            "provenance": "EXACT_CONTRACT_ROOT_AND_CBOE_2026_11_09"}


def execution_blockers(raw: Mapping[str, Any]) -> list[str]:
    """Conservative gating of unknown/AM contracts. No allow verdict returned."""
    info = classify_contract(raw)
    blockers = []
    if info["identity_conflict"]:
        blockers.append("CONTRACT_SETTLEMENT_IDENTITY_CONFLICT")
    if info["contract_class"] == "SPXO":
        blockers.append("SPXO_AM_SETTLEMENT_UNSUPPORTED_FOR_0DTE_EXECUTION")
    elif info["settlement_type"] == "AM":
        blockers.append("AM_SETTLEMENT_UNSUPPORTED_FOR_0DTE_EXECUTION")
    elif info["contract_class"] == "UNKNOWN":
        blockers.append("CONTRACT_CLASS_UNVERIFIED")
    return blockers
