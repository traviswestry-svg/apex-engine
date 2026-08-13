"""APEX 48.2.1 — Session-aware Morning Readiness (presentation layer).

This module is a *presentation / interpretation* layer over readiness objects
that other services already compute.  It contains no trading, scanner,
recommendation, execution, risk, learning, or session-*detection* business
logic.  It takes:

  * the current session (as produced by the canonical APEX session detector —
    ``session_status`` / ``system_mode`` in ``app.py``), and
  * the boolean checks that ``build_execution_snapshot`` already produced, plus
    the system-health checks and loaded global risk limits,

and re-expresses each checklist item as a rich :class:`ReadinessState` instead
of a bare pass/fail boolean.

The single behavioural change is *interpretation*: a check that is ``False``
only because the market is closed is reported as ``CLOSED`` / ``NOT_EXPECTED``
(informational, gray) rather than ``FAIL`` (red).  ``FAIL`` is reserved for a
condition that should hold during a live session but does not.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Mapping, Optional


# ── Rich per-item state model ──────────────────────────────────────────────
class ReadinessState(str, Enum):
    READY = "READY"                 # dependency satisfied
    OPEN = "OPEN"                   # market row: live session
    WAITING = "WAITING"            # expected soon; nothing wrong
    NOT_EXPECTED = "NOT_EXPECTED"  # not applicable while the market is closed
    NOT_REQUIRED = "NOT_REQUIRED"  # intentionally dormant (e.g. broker off-hours)
    CLOSED = "CLOSED"              # market row: outside session
    DISCONNECTED = "DISCONNECTED"  # required dependency is down — actionable
    FAIL = "FAIL"                  # genuine operational failure — actionable


class OverallStatus(str, Enum):
    READY = "READY"                       # live and good to go
    STANDBY = "STANDBY"                   # market closed; nothing to do
    WAITING = "WAITING"                   # live; awaiting recommendation
    ACTION_REQUIRED = "ACTION_REQUIRED"  # a required dependency needs attention
    FAILURE = "FAILURE"                   # a critical dependency has failed


# Color mapping (spec §Color Mapping). Named colors are resolved to concrete
# hex values by the front-end so the palette stays in one place there.
STATE_COLOR: Dict[str, str] = {
    ReadinessState.READY.value: "green",
    ReadinessState.OPEN.value: "green",
    ReadinessState.WAITING.value: "blue",
    ReadinessState.NOT_EXPECTED.value: "gray",
    ReadinessState.NOT_REQUIRED.value: "gray",
    ReadinessState.CLOSED.value: "gray",
    ReadinessState.DISCONNECTED.value: "orange",
    ReadinessState.FAIL.value: "red",
}

OVERALL_COLOR: Dict[str, str] = {
    OverallStatus.READY.value: "green",
    OverallStatus.STANDBY.value: "gray",
    OverallStatus.WAITING.value: "blue",
    OverallStatus.ACTION_REQUIRED.value: "orange",
    OverallStatus.FAILURE.value: "red",
}


# ── Session phases (spec §Build Goals) ─────────────────────────────────────
PREMARKET = "PREMARKET"
REGULAR_SESSION = "REGULAR_SESSION"
AFTER_HOURS = "AFTER_HOURS"
OVERNIGHT = "OVERNIGHT"
WEEKEND = "WEEKEND"
HOLIDAY = "HOLIDAY"
UNKNOWN = "UNKNOWN"

# Only the regular cash session has live SPX options quotes / liquidity.
_LIVE_PHASES = {REGULAR_SESSION}
_CLOSED_PHASES = {PREMARKET, AFTER_HOURS, OVERNIGHT, WEEKEND, HOLIDAY}

# Human labels for the normalized phase.
_PHASE_LABEL = {
    PREMARKET: "Pre-Market",
    REGULAR_SESSION: "Regular Session",
    AFTER_HOURS: "After Hours",
    OVERNIGHT: "Overnight",
    WEEKEND: "Weekend",
    HOLIDAY: "Market Holiday",
    UNKNOWN: "Unknown",
}


def normalize_session(session: Any = None, *, market_open: Optional[bool] = None) -> Dict[str, Any]:
    """Normalize whatever the canonical detector returned into a phase.

    Accepts the raw ``session_status()`` string, a ``system_mode()`` /
    ``market_session_context()`` mapping, or ``None``.  Never *computes* the
    session — it only maps the canonical detector's output onto the phase names
    this presentation layer speaks.  ``market_open`` is a last-resort fallback
    used only when no session information is available at all.
    """
    raw = ""
    is_holiday = False
    next_open: Optional[str] = None

    if isinstance(session, Mapping):
        raw = str(
            session.get("session")
            or session.get("session_state")
            or session.get("status")
            or ""
        )
        is_holiday = bool(session.get("is_holiday"))
        next_open = session.get("next_rth") or session.get("next_open")
    elif isinstance(session, str):
        raw = session

    raw = raw.strip().upper()

    if raw == "MARKET_OPEN":
        phase = REGULAR_SESSION
    elif raw in ("PREMARKET", "PRE_MARKET", "PRE-MARKET"):
        phase = PREMARKET
    elif raw == "AFTER_HOURS":
        phase = AFTER_HOURS
    elif raw == "OVERNIGHT":
        phase = OVERNIGHT
    elif raw in ("CLOSED", "MARKET_CLOSED"):
        phase = HOLIDAY if is_holiday else WEEKEND
    else:
        # No usable session string — fall back to the coarse market_open flag.
        # When even that is unknown, assume closed so we never fabricate a red
        # FAIL from missing information.
        if market_open is True:
            phase = REGULAR_SESSION
        else:
            phase = WEEKEND

    return {
        "raw": raw or None,
        "phase": phase,
        "phase_label": _PHASE_LABEL.get(phase, phase),
        "is_live": phase in _LIVE_PHASES,
        "is_holiday": is_holiday,
        "next_open": next_open,
    }


def _row(key: str, label: str, state: ReadinessState, help_text: str,
         detail: Optional[str] = None) -> Dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "state": state.value,
        "color": STATE_COLOR[state.value],
        "detail": detail,
        "help": help_text,
        "actionable": state in (ReadinessState.FAIL, ReadinessState.DISCONNECTED),
    }


def _b(checks: Mapping[str, Any], name: str) -> bool:
    try:
        return bool(checks.get(name))
    except Exception:
        return False


def build_checklist(
    *,
    session: Mapping[str, Any],
    execution_checks: Optional[Mapping[str, Any]] = None,
    risk_config_ready: bool = False,
    broker_required: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    """Build the session-aware Institutional Checklist rows.

    ``execution_checks`` is the boolean ``checks`` dict from
    ``build_execution_snapshot`` — this function only *interprets* it.
    """
    checks = execution_checks or {}
    live = bool(session.get("is_live"))
    next_open = session.get("next_open")
    closed_hint = f" Next session: {next_open}." if (not live and next_open) else ""

    broker_ready = _b(checks, "broker_ready")
    rec_present = _b(checks, "recommendation_present")
    chain_evaluated = _b(checks, "chain_evaluated")
    quotes_expected = _b(checks, "quotes_expected") or rec_present or chain_evaluated
    if broker_required is None:
        # Execution is only *required* to be connected when there is a live
        # session and an actionable recommendation to place.
        broker_required = live and rec_present

    rows: List[Dict[str, Any]] = []

    # ── Broker ─────────────────────────────────────────────────────────────
    if broker_ready:
        rows.append(_row(
            "broker", "Broker",
            ReadinessState.READY,
            "Broker session is authenticated and reachable.",
        ))
    elif broker_required:
        rows.append(_row(
            "broker", "Broker",
            ReadinessState.DISCONNECTED,
            "A recommendation is live but the execution broker is not "
            "connected. Reconnect before placing the trade.",
        ))
    else:
        rows.append(_row(
            "broker", "Broker",
            ReadinessState.NOT_REQUIRED,
            "Execution connection is intentionally dormant. It is not required "
            "outside of an active, executable session.",
        ))

    # ── Market ─────────────────────────────────────────────────────────────
    if live:
        rows.append(_row(
            "market", "Market",
            ReadinessState.OPEN,
            "Regular cash trading session is live.",
        ))
    else:
        rows.append(_row(
            "market", "Market",
            ReadinessState.CLOSED,
            "Cash market is closed." + closed_hint,
            detail=session.get("phase_label"),
        ))

    # ── Chain Gate ─────────────────────────────────────────────────────────
    if _b(checks, "chain_gate_passed"):
        rows.append(_row(
            "chain_gate", "Chain Gate",
            ReadinessState.READY,
            "Options chain quality gate is not suppressing entries.",
        ))
    elif live and not chain_evaluated:
        rows.append(_row(
            "chain_gate", "Chain Gate",
            ReadinessState.WAITING,
            "Awaiting a candidate recommendation before evaluating the options chain.",
        ))
    elif live:
        rows.append(_row(
            "chain_gate", "Chain Gate",
            ReadinessState.FAIL,
            "Chain quality gate is suppressing entries during a live session.",
        ))
    else:
        rows.append(_row(
            "chain_gate", "Chain Gate",
            ReadinessState.NOT_EXPECTED,
            "Chain quality is evaluated once the live options chain is available.",
        ))

    # ── Quotes Present ─────────────────────────────────────────────────────
    if _b(checks, "quotes_present"):
        rows.append(_row(
            "quotes_present", "Quotes Present",
            ReadinessState.READY,
            "Live option quotes are present.",
        ))
    elif live and not quotes_expected:
        rows.append(_row(
            "quotes_present", "Quotes Present",
            ReadinessState.WAITING,
            "Option quotes are requested after a candidate recommendation is selected.",
        ))
    elif live:
        rows.append(_row(
            "quotes_present", "Quotes Present",
            ReadinessState.FAIL,
            "A candidate requires option quotes, but none are present.",
        ))
    else:
        rows.append(_row(
            "quotes_present", "Quotes Present",
            ReadinessState.NOT_EXPECTED,
            "Live market data is not expected while the market is closed.",
        ))

    # ── Quotes Fresh ───────────────────────────────────────────────────────
    if not live:
        rows.append(_row(
            "quotes_fresh", "Quotes Fresh",
            ReadinessState.NOT_EXPECTED,
            "Live market data is not expected while the market is closed.",
        ))
    elif not quotes_expected:
        rows.append(_row(
            "quotes_fresh", "Quotes Fresh",
            ReadinessState.WAITING,
            "Quote freshness will be evaluated after quotes are requested.",
        ))
    elif _b(checks, "quotes_fresh"):
        rows.append(_row(
            "quotes_fresh", "Quotes Fresh",
            ReadinessState.READY,
            "Option quotes are within the freshness threshold.",
        ))
    else:
        rows.append(_row(
            "quotes_fresh", "Quotes Fresh",
            ReadinessState.FAIL,
            "Required option quotes are missing or stale.",
        ))

    # ── Liquidity ──────────────────────────────────────────────────────────
    if _b(checks, "liquidity_acceptable"):
        rows.append(_row(
            "liquidity", "Liquidity",
            ReadinessState.READY,
            "Displayed liquidity meets the acceptability threshold.",
        ))
    elif live and not quotes_expected:
        rows.append(_row(
            "liquidity", "Liquidity",
            ReadinessState.WAITING,
            "Liquidity is evaluated after a candidate and live quotes are available.",
        ))
    elif live:
        rows.append(_row(
            "liquidity", "Liquidity",
            ReadinessState.FAIL,
            "Required displayed liquidity is unavailable or below threshold.",
        ))
    else:
        rows.append(_row(
            "liquidity", "Liquidity",
            ReadinessState.NOT_EXPECTED,
            "Liquidity is not measurable while the market is closed.",
        ))

    # ── Recommendation ─────────────────────────────────────────────────────
    if rec_present:
        rows.append(_row(
            "recommendation", "Recommendation",
            ReadinessState.READY,
            "A recommendation is available.",
        ))
    else:
        rows.append(_row(
            "recommendation", "Recommendation",
            ReadinessState.WAITING,
            "Recommendations are generated after live scanner confirmation."
            + closed_hint,
        ))

    # ── Risk (system risk configuration) ───────────────────────────────────
    # System-level risk configuration is independent of any single trade.
    # Trade-specific risk is only meaningful once a recommendation exists and is
    # surfaced via the execution snapshot's own ``risk_defined`` check.
    if risk_config_ready:
        rows.append(_row(
            "risk", "Risk",
            ReadinessState.READY,
            "Global risk parameters have been loaded.",
        ))
    elif live:
        rows.append(_row(
            "risk", "Risk",
            ReadinessState.FAIL,
            "Global risk parameters are not loaded. Configure limits before "
            "trading.",
        ))
    else:
        rows.append(_row(
            "risk", "Risk",
            ReadinessState.WAITING,
            "Global risk parameters have not been loaded yet.",
        ))

    return rows


def summarize(session: Mapping[str, Any], checklist: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Roll the checklist rows up into an intelligent overall status."""
    live = bool(session.get("is_live"))
    failing = [r for r in checklist if r["state"] == ReadinessState.FAIL.value]
    disconnected = [r for r in checklist if r["state"] == ReadinessState.DISCONNECTED.value]
    rec_waiting = any(
        r["key"] == "recommendation" and r["state"] == ReadinessState.WAITING.value
        for r in checklist
    )

    if failing:
        status = OverallStatus.FAILURE
        headline = "Operational Issue"
        detail = "Failing: " + ", ".join(r["label"] for r in failing)
    elif disconnected:
        status = OverallStatus.ACTION_REQUIRED
        headline = "Broker Disconnected"
        detail = "Reconnect execution before trading."
    elif not live:
        status = OverallStatus.STANDBY
        if session.get("phase") == HOLIDAY:
            headline = "Market Holiday"
        else:
            headline = "Market Closed"
        nxt = session.get("next_open")
        detail = f"Awaiting next trading session{f' — {nxt}' if nxt else ''}."
    elif rec_waiting:
        status = OverallStatus.WAITING
        headline = "Awaiting Recommendation"
        detail = "Session is live; scanner has not confirmed a setup yet."
    else:
        status = OverallStatus.READY
        headline = "Ready"
        detail = "Session is live and all dependencies are satisfied."

    return {
        "status": status.value,
        "color": OVERALL_COLOR[status.value],
        "headline": headline,
        "detail": detail,
    }


def build_session_readiness(
    *,
    session: Any = None,
    market_open: Optional[bool] = None,
    execution_checks: Optional[Mapping[str, Any]] = None,
    risk_config_ready: bool = False,
    broker_required: Optional[bool] = None,
) -> Dict[str, Any]:
    """Full session-aware readiness block: normalized session + checklist + rollup."""
    norm = normalize_session(session, market_open=market_open)
    checklist = build_checklist(
        session=norm,
        execution_checks=execution_checks,
        risk_config_ready=risk_config_ready,
        broker_required=broker_required,
    )
    overall = summarize(norm, checklist)
    return {
        "session": norm,
        "checklist": checklist,
        "overall": overall,
        "color_legend": STATE_COLOR,
    }
