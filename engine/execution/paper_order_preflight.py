"""69.10.45 supervised paper-order preflight: read-only and fail-closed.

This module never sends network requests, approves orders, or trusts caller
provided approval bits. Its result is diagnostic, NOT execution authority.
"""
from __future__ import annotations
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo
import os

ET = ZoneInfo('America/New_York')


def _amount(value):
    try:
        number = Decimal(str(value))
        return number if number.is_finite() and number > 0 else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def inspect(candidate=None, *, clock=None, decision_reader=None):
    """Check whether a submitted *candidate* contains credible binding inputs.

    The static blocking reasons are deliberately non-overridable: downstream
    execution must never consume this diagnostic as a dispatch permission.
    """
    data = candidate if isinstance(candidate, dict) else {}
    local = (clock or datetime.now(timezone.utc)).astimezone(ET)
    minute = local.hour * 60 + local.minute
    blockers = []
    flags = {
        'paper_mode': os.getenv('APEX_TRADERSPOST_MODE') == 'paper',
        'paper_account_attested': os.getenv('APEX_TRADERSPOST_PAPER_CONFIRMED', '').lower() == 'true',
        'live_routing_disabled': os.getenv('APEX_LIVE_ORDER_ROUTING_ENABLED', 'false').lower() != 'true',
        'within_entry_window': local.weekday() < 5 and 575 <= minute <= 690,
        'broker_reconciliation_operational': False,
        'verified_daily_loss_enforcement': False,
        'verified_position_exit': False,
        'trusted_execution_authority': False,
    }
    blockers.extend(k.upper() for k, ok in flags.items() if not ok)
    if candidate is not None:
        decision_id = data.get('decision_id')
        if not isinstance(decision_id, str) or not decision_id.strip():
            blockers.append('CANONICAL_DECISION_ID_REQUIRED')
        ticker = data.get('ticker')
        if ticker != 'SPX':
            blockers.append('SPX_ONLY')
        contract = data.get('contract')
        if not isinstance(contract, dict) or contract.get('ticker') != 'SPX':
            blockers.append('EXACT_SPX_OPTION_CONTRACT_REQUIRED')
        else:
            if contract.get('side') not in ('CALL', 'PUT'):
                blockers.append('OPTION_SIDE_REQUIRED')
            if _amount(contract.get('strike')) is None:
                blockers.append('VALID_STRIKE_REQUIRED')
            try:
                expiration = datetime.strptime(contract.get('expiry', ''), '%Y-%m-%d').date()
                if expiration < local.date():
                    blockers.append('EXPIRED_CONTRACT')
            except (TypeError, ValueError):
                blockers.append('VALID_EXPIRY_REQUIRED')
        qty = data.get('quantity')
        ask = _amount(data.get('ask'))
        bid = _amount(data.get('bid'))
        if type(qty) is not int or qty < 1 or qty > 3:
            blockers.append('QUANTITY_OUT_OF_RANGE')
        if ask is None or bid is None or (ask is not None and bid is not None and bid > ask):
            blockers.append('VALID_MARKET_QUOTE_REQUIRED')
        if ask is not None and type(qty) is int and ask * qty * 100 > 2000:
            blockers.append('ENTRY_DEBIT_EXCEEDS_2000')
        source = None
        if isinstance(decision_id, str) and decision_id.strip():
            if decision_reader is None:
                from engine.execution.paper_execution_foundation import persisted_canonical_reader
                decision_reader = persisted_canonical_reader
            try:
                source = decision_reader(decision_id)
            except (OSError, ValueError, RuntimeError):
                source = None
        if not isinstance(source, dict) or not source.get('persisted') or source.get('decision_id') != decision_id:
            blockers.append('PERSISTED_CANONICAL_DECISION_NOT_FOUND')
        elif source.get('contract') != contract:
            blockers.append('CANONICAL_CONTRACT_MISMATCH')
    return {
        'ok': True, 'mode': 'READ_ONLY_PREFLIGHT', 'test_signal_creates_orders': False,
        'candidate_checked': candidate is not None, 'checks': flags,
        'blockers': sorted(set(blockers)), 'may_send_order': False,
        'ready_for_unattended_orders': False, 'paper_fill_verified': False,
        'warning': 'This diagnostic cannot authorize a paper order; webhook test=true never executes a trade.'
    }
