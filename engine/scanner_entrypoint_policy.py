"""APEX 69.10.37 advisory-only scan entry-point and provider bounds policy."""


def scan_session_allowed(session: str) -> bool:
    """Conservatively reject unknown and CLOSED states; retain overnight policy."""
    return str(session).upper() in {"MARKET_OPEN", "PREMARKET", "AFTER_HOURS", "OVERNIGHT"}


def quantdata_consolidated_size(value: object) -> int:
    """QuantData consolidated order-flow contract: inclusive 1..100."""
    try:
        count = int(value)
    except (ValueError, TypeError, OverflowError):
        count = 50
    return max(1, min(100, count))
