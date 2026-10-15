"""Pure, fail-closed threshold evaluation for observational APEX signal updates."""
import math


def finite_number(value):
    try:
        if value is None or isinstance(value, bool):
            return None
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError, OverflowError):
        return None


def evaluate_signal_thresholds(price, direction, stop, target1, target2):
    """Return (reason, exit_level, missing_fields); stop wins ties.

    No classification is issued when the protective stop or first target is absent.
    Target2 is optional by existing contract. The caller can still expire a signal
    under the existing session/holding-time policy.
    """
    p = finite_number(price)
    s = finite_number(stop)
    t1 = finite_number(target1)
    t2 = finite_number(target2)
    missing = tuple(name for name, value in (("price", p), ("stop", s), ("target1", t1)) if value is None)
    if missing:
        return None, None, missing
    if direction == "CALL":
        if p <= s:
            return "STOP", s, ()
        if t2 is not None and p >= t2:
            return "T2", t2, ()
        if p >= t1:
            return "T1", t1, ()
    elif direction == "PUT":
        if p >= s:
            return "STOP", s, ()
        if t2 is not None and p <= t2:
            return "T2", t2, ()
        if p <= t1:
            return "T1", t1, ()
    else:
        return None, None, ("direction",)
    return None, None, ()
