"""Pure session gating and unresolved-attempt classification (diagnostic only)."""
from __future__ import annotations
import datetime as dt


def full_scan_allowed(session: str) -> bool:
    """Honor the existing canonical session classifier; never run in CLOSED."""
    return str(session).upper() in {'MARKET_OPEN', 'PREMARKET', 'AFTER_HOURS', 'OVERNIGHT'}


def classify_unresolved(attempts: int, completed: int, failed: int, lock_skips: int,
                        last_event: str | None, last_event_age_seconds: float | None,
                        grace_seconds: float = 600.0) -> dict:
    """Unpaired counts are not necessarily failures; journal v1 lacks attempt IDs."""
    outstanding = max(0, int(attempts) - int(completed) - int(failed) - int(lock_skips))
    if outstanding == 0:
        state = 'NONE'
    elif last_event == 'ATTEMPT' and last_event_age_seconds is not None and last_event_age_seconds < grace_seconds:
        state = 'RECENT_UNRESOLVED'
    else:
        state = 'STALE_UNRESOLVED_UNCONFIRMED'
    return {'count': outstanding, 'state': state,
            'note': 'Journal v1 has no per-attempt correlation IDs; unresolved does not prove failure.',
            'grace_seconds': grace_seconds}
