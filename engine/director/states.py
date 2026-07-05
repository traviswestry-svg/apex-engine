"""engine/director/states.py — deterministic position-state machine (Part 1).

Prevents contradictory instructions (ENTER_CALL while IN_CALL, WATCHING_CALLS
while an active CALL exists, HOLD_CALL with no position). Transitions are
explicit, explainable and testable. This module holds no market data — it is a
pure graph plus a couple of guard helpers so the Director and the tests share
exactly one definition of "legal".
"""
from __future__ import annotations

from typing import Dict, Set, Tuple

from .contracts import POSITION_STATES, IN_POSITION_STATES, EXIT_STATES


# Legal transitions. Key = current state, value = set of allowed next states.
# Every state may remain itself (identity) and may drop to EXIT_IMMEDIATELY /
# COOLDOWN because a hard veto or emergency can fire from anywhere.
_TRANSITIONS: Dict[str, Set[str]] = {
    "FLAT": {"OBSERVING", "WATCHING_CALLS", "WATCHING_PUTS", "NO_TRADE", "CAUTION", "COOLDOWN"},
    "OBSERVING": {"WATCHING_CALLS", "WATCHING_PUTS", "NO_TRADE", "CAUTION", "FLAT"},
    "NO_TRADE": {"OBSERVING", "WATCHING_CALLS", "WATCHING_PUTS", "CAUTION", "FLAT"},
    "CAUTION": {"OBSERVING", "WATCHING_CALLS", "WATCHING_PUTS", "NO_TRADE", "FLAT"},

    "WATCHING_CALLS": {"SCALP_READY_CALL", "ENTER_CALL", "OBSERVING", "CAUTION",
                       "NO_TRADE", "WATCHING_PUTS", "FLAT"},
    "WATCHING_PUTS": {"SCALP_READY_PUT", "ENTER_PUT", "OBSERVING", "CAUTION",
                      "NO_TRADE", "WATCHING_CALLS", "FLAT"},

    "SCALP_READY_CALL": {"ENTER_SCALP_CALL", "ENTER_CALL", "WATCHING_CALLS", "OBSERVING", "CAUTION"},
    "SCALP_READY_PUT": {"ENTER_SCALP_PUT", "ENTER_PUT", "WATCHING_PUTS", "OBSERVING", "CAUTION"},

    "ENTER_SCALP_CALL": {"IN_CALL", "WATCHING_CALLS", "OBSERVING"},
    "ENTER_SCALP_PUT": {"IN_PUT", "WATCHING_PUTS", "OBSERVING"},
    "ENTER_CALL": {"IN_CALL", "WATCHING_CALLS", "OBSERVING"},
    "ENTER_PUT": {"IN_PUT", "WATCHING_PUTS", "OBSERVING"},

    "IN_CALL": {"HOLD_CALL", "HOLD_FOR_TARGET", "HOLD_IF_LEVEL_HOLDS", "PROTECT_PROFIT",
                "SCALE_OUT", "EXIT_FLOW_REVERSAL", "EXIT_LEVEL_FAILURE",
                "EXIT_TARGET_REACHED", "EXIT_IMMEDIATELY", "CAUTION"},
    "IN_PUT": {"HOLD_PUT", "HOLD_FOR_TARGET", "HOLD_IF_LEVEL_HOLDS", "PROTECT_PROFIT",
               "SCALE_OUT", "EXIT_FLOW_REVERSAL", "EXIT_LEVEL_FAILURE",
               "EXIT_TARGET_REACHED", "EXIT_IMMEDIATELY", "CAUTION"},

    "HOLD_CALL": {"HOLD_CALL", "HOLD_FOR_TARGET", "HOLD_IF_LEVEL_HOLDS", "PROTECT_PROFIT",
                  "SCALE_OUT", "EXIT_FLOW_REVERSAL", "EXIT_LEVEL_FAILURE",
                  "EXIT_TARGET_REACHED", "EXIT_IMMEDIATELY", "IN_CALL", "CAUTION"},
    "HOLD_PUT": {"HOLD_PUT", "HOLD_FOR_TARGET", "HOLD_IF_LEVEL_HOLDS", "PROTECT_PROFIT",
                 "SCALE_OUT", "EXIT_FLOW_REVERSAL", "EXIT_LEVEL_FAILURE",
                 "EXIT_TARGET_REACHED", "EXIT_IMMEDIATELY", "IN_PUT", "CAUTION"},

    "HOLD_FOR_TARGET": {"HOLD_CALL", "HOLD_PUT", "PROTECT_PROFIT", "SCALE_OUT",
                        "HOLD_IF_LEVEL_HOLDS", "EXIT_FLOW_REVERSAL", "EXIT_LEVEL_FAILURE",
                        "EXIT_TARGET_REACHED", "EXIT_IMMEDIATELY"},
    "HOLD_IF_LEVEL_HOLDS": {"HOLD_CALL", "HOLD_PUT", "PROTECT_PROFIT", "SCALE_OUT",
                            "HOLD_FOR_TARGET", "EXIT_FLOW_REVERSAL", "EXIT_LEVEL_FAILURE",
                            "EXIT_TARGET_REACHED", "EXIT_IMMEDIATELY"},

    "PROTECT_PROFIT": {"PROTECT_PROFIT", "SCALE_OUT", "HOLD_CALL", "HOLD_PUT",
                       "HOLD_IF_LEVEL_HOLDS", "EXIT_FLOW_REVERSAL", "EXIT_LEVEL_FAILURE",
                       "EXIT_TARGET_REACHED", "EXIT_IMMEDIATELY"},
    "SCALE_OUT": {"SCALE_OUT", "PROTECT_PROFIT", "HOLD_CALL", "HOLD_PUT",
                  "HOLD_IF_LEVEL_HOLDS", "EXIT_FLOW_REVERSAL", "EXIT_LEVEL_FAILURE",
                  "EXIT_TARGET_REACHED", "EXIT_IMMEDIATELY"},

    "EXIT_FLOW_REVERSAL": {"COOLDOWN", "FLAT"},
    "EXIT_LEVEL_FAILURE": {"COOLDOWN", "FLAT"},
    "EXIT_TARGET_REACHED": {"COOLDOWN", "FLAT", "OBSERVING"},
    "EXIT_IMMEDIATELY": {"COOLDOWN", "FLAT"},

    "COOLDOWN": {"OBSERVING", "WATCHING_CALLS", "WATCHING_PUTS", "NO_TRADE", "FLAT", "COOLDOWN"},
}

# Emergency edges reachable from any in-position state.
_EMERGENCY_TARGETS: Set[str] = {"EXIT_IMMEDIATELY", "EXIT_FLOW_REVERSAL", "EXIT_LEVEL_FAILURE"}


def is_valid_transition(current: str, target: str) -> bool:
    """True if moving current->target is legal. Identity is always legal."""
    if current not in POSITION_STATES or target not in POSITION_STATES:
        return False
    if current == target:
        return True
    if current in IN_POSITION_STATES and target in _EMERGENCY_TARGETS:
        return True
    return target in _TRANSITIONS.get(current, set())


def coerce_transition(current: str, target: str) -> Tuple[str, bool]:
    """Return (safe_target, was_coerced).

    If target is illegal from current, fall back to the safest legal state so the
    Director never emits a contradictory instruction. In-position -> illegal
    downgrades to a HOLD of the correct side; flat -> illegal downgrades to
    OBSERVING.
    """
    if is_valid_transition(current, target):
        return target, False
    if current == "IN_CALL" or current == "HOLD_CALL":
        return "HOLD_CALL", True
    if current == "IN_PUT" or current == "HOLD_PUT":
        return "HOLD_PUT", True
    if current in IN_POSITION_STATES:
        # Preserve side if the state name encodes it, else keep holding.
        return current, True
    return "OBSERVING", True


def contradicts_position(state: str, has_call: bool, has_put: bool) -> bool:
    """Detect states that contradict the actual position (Part 1 guard).

    e.g. WATCHING_CALLS or ENTER_CALL while a CALL is already held, or
    HOLD_CALL while flat.
    """
    holding = has_call or has_put
    entry_like = state in {
        "WATCHING_CALLS", "WATCHING_PUTS", "SCALP_READY_CALL", "SCALP_READY_PUT",
        "ENTER_SCALP_CALL", "ENTER_SCALP_PUT", "ENTER_CALL", "ENTER_PUT",
    }
    if holding and entry_like:
        return True
    if not holding and state in IN_POSITION_STATES:
        return True
    if has_put and state in {"HOLD_CALL", "IN_CALL"}:
        return True
    if has_call and state in {"HOLD_PUT", "IN_PUT"}:
        return True
    return False


def is_exit(state: str) -> bool:
    return state in EXIT_STATES
