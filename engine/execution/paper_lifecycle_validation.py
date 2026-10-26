"""APEX 69.10.47: pure offline paper lifecycle validation.

No database writes, webhook calls, or execution authority. Results are only
modelled scenarios, never broker fills, real positions, or realized P&L.
"""
from __future__ import annotations
from datetime import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

_ET = ZoneInfo('America/New_York')
_ENTRY_STATES = {'ENTRY_FILL', 'ENTRY_PARTIAL_FILL'}
_EXIT_STATES = {'EXIT_FILL', 'EXIT_PARTIAL_FILL'}
_EVENTS = _ENTRY_STATES | _EXIT_STATES | {'ENTRY_REJECTED', 'ENTRY_CANCELLED', 'EXIT_REJECTED', 'EXIT_CANCELLED'}


def _number(value, *, positive=False, allow_zero=True):
    try:
        n = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError('INVALID_NUMBER') from None
    if not n.is_finite() or (positive and n <= 0) or (not allow_zero and n == 0):
        raise ValueError('INVALID_NUMBER')
    return n


def _time(value):
    try:
        t = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except (ValueError, TypeError):
        raise ValueError('INVALID_EVENT_TIME') from None
    if t.tzinfo is None:
        raise ValueError('TIMEZONE_REQUIRED')
    return t


def validate_scenario(candidate: dict, events: list[dict], *, daily_loss_limit='1000', prior_verified_daily_pnl=None):
    """Replay a synthetic scenario deterministically and fail closed.

    candidate must be the server-assembled canonical ID and exact contract;
    these are validated for consistency, not independently authenticated here.
    Never use this function as authorization to submit an order.
    """
    if not isinstance(candidate, dict) or not isinstance(events, list):
        raise ValueError('INVALID_SCENARIO')
    decision_id = candidate.get('decision_id')
    contract = candidate.get('contract')
    if not isinstance(decision_id, str) or not decision_id.strip() or not isinstance(contract, dict):
        raise ValueError('MISSING_CANONICAL_IDENTITY')
    if contract.get('ticker') != 'SPX' or contract.get('right') not in ('CALL', 'PUT'):
        raise ValueError('INVALID_SPX_CONTRACT')
    for field in ('expiration', 'strike'):
        if not contract.get(field):
            raise ValueError('INCOMPLETE_SPX_CONTRACT')
    _number(contract['strike'], positive=True)
    qty = candidate.get('quantity')
    if type(qty) is not int or not 1 <= qty <= 3:
        raise ValueError('INVALID_SIZE')
    premium = _number(candidate.get('entry_limit'), positive=True)
    multiplier = _number(candidate.get('multiplier', 100), positive=True)
    if multiplier != 100:
        raise ValueError('INVALID_MULTIPLIER')
    max_risk = _number(candidate.get('max_entry_risk', '2000'), positive=True)
    if premium * qty * multiplier > max_risk or max_risk > 2000:
        raise ValueError('ENTRY_RISK_EXCEEDED')
    limit = _number(daily_loss_limit, positive=True)
    # Unknown verified daily P&L is a hard blocker, not an assumed zero.
    prior_known = prior_verified_daily_pnl is not None
    prior = _number(prior_verified_daily_pnl) if prior_known else None
    reasons = []
    if not prior_known:
        reasons.append('VERIFIED_DAILY_PNL_UNAVAILABLE')
    elif prior <= -limit:
        reasons.append('DAILY_LOSS_LIMIT_REACHED')
    if not candidate.get('canonical_persisted', False):
        reasons.append('CANONICAL_DECISION_NOT_VERIFIED')
    if not candidate.get('server_approved', False):
        reasons.append('SERVER_EXECUTION_APPROVAL_MISSING')
    if len(events) > 1000:
        raise ValueError('TOO_MANY_EVENTS')
    opened = exited = 0
    entry_cost = exit_proceeds = Decimal(0)
    seen = set()
    previous_time = None
    terminal_entry = False
    last_action = None
    rejects = cancels = 0
    for i, item in enumerate(events):
        if not isinstance(item, dict):
            raise ValueError('INVALID_EVENT')
        eid = item.get('event_id')
        if not isinstance(eid, str) or not eid.strip() or eid in seen:
            raise ValueError('DUPLICATE_OR_MISSING_EVENT_ID')
        seen.add(eid)
        if item.get('decision_id') != decision_id or item.get('contract') != contract:
            raise ValueError('CANONICAL_OR_CONTRACT_MISMATCH')
        kind = item.get('type')
        if kind not in _EVENTS:
            raise ValueError('INVALID_EVENT_TYPE')
        at = _time(item.get('at'))
        if previous_time is not None and at < previous_time:
            raise ValueError('OUT_OF_ORDER_EVENT')
        previous_time = at
        size = item.get('quantity', 0)
        if type(size) is not int or (kind in _ENTRY_STATES | _EXIT_STATES and size < 1):
            raise ValueError('INVALID_EVENT_QUANTITY')
        if kind in _ENTRY_STATES:
            if terminal_entry or opened + size > qty:
                raise ValueError('OVERFILL_OR_TERMINAL_ENTRY')
            opened += size
            entry_cost += _number(item.get('price'), positive=True) * size * multiplier
            last_action = kind
        elif kind in _EXIT_STATES:
            if exited + size > opened:
                raise ValueError('ORPHAN_EXIT_OR_OVEREXIT')
            exited += size
            exit_proceeds += _number(item.get('price'), positive=True) * size * multiplier
            last_action = kind
        elif kind.startswith('ENTRY_'):
            if opened > 0 and kind == 'ENTRY_REJECTED':
                raise ValueError('REJECTED_AFTER_FILL')
            terminal_entry = True
            rejects += kind.endswith('REJECTED')
            cancels += kind.endswith('CANCELLED')
        else:
            if opened <= exited:
                raise ValueError('ORPHAN_EXIT_STATUS')
            rejects += kind.endswith('REJECTED')
            cancels += kind.endswith('CANCELLED')
    open_qty = opened - exited
    if open_qty:
        reasons.append('POSITION_EXIT_UNVERIFIED')
    if opened == 0:
        reasons.append('NO_ENTRY_FILL')
    if opened and exited == opened and not terminal_entry and opened < qty:
        reasons.append('ENTRY_REMAINDER_UNRESOLVED')
    if rejects:
        reasons.append('REJECTED_EVENT_PRESENT')
    pnl_model = None
    if opened and opened == exited and (opened == qty or terminal_entry):
        pnl_model = str(exit_proceeds - entry_cost)
        if prior_known and prior + Decimal(pnl_model) <= -limit:
            reasons.append('MODEL_DAILY_LOSS_LIMIT_BREACH')
    return {
        'ok': True, 'mode': 'OFFLINE_SIMULATION_ONLY', 'scenario_events': len(events),
        'entry_filled_quantity': opened, 'exit_filled_quantity': exited,
        'open_quantity': open_qty, 'rejected_events': rejects, 'cancelled_events': cancels,
        'modeled_pnl_not_broker_verified': pnl_model,
        'blockers': sorted(set(reasons + ['BROKER_RECONCILIATION_UNAVAILABLE',
            'VERIFIED_EXIT_UNAVAILABLE', 'UNATTENDED_AUTHORITY_DISABLED'])),
        'broker_fill_verified': False, 'verified_realized_pnl': None,
        'daily_loss_enforced': False, 'may_send_order': False,
        'ready_for_unattended_orders': False,
    }
