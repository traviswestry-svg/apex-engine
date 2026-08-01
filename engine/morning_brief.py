"""
APEX — On-demand pre-market Institutional Morning Brief.

Location: engine/morning_brief.py

Generates the full brief the dashboard shows before the open:
  * deterministic sections (key levels / trade map / expected move) come straight
    from the Daily Key Levels engine — REAL numbers, never invented
  * macro + narrative + regime classification come from ONE Anthropic API call
    with web_search enabled, fed the deterministic data as context so the story
    is consistent with the actual levels

Design rules carried over from the rest of APEX:
  * The model NARRATES; the engine supplies NUMBERS. The prompt forbids the model
    from inventing numeric levels — the authoritative level sections are appended
    from the engine, not from the model.
  * Anything unavailable renders [FEED REQUIRED], never a fabricated value.
  * On-demand + cached by ET session date (an LLM+web_search call costs money and
    ~30-60s; don't regenerate on every dashboard poll). force=True bypasses cache.
  * Degrades gracefully: no ANTHROPIC_API_KEY -> returns the deterministic brief
    with a clear "narrative unavailable" note instead of failing.
"""

from __future__ import annotations

import os
import datetime as dt
import threading
import time
from typing import Any, Optional

try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover
    _ET = dt.timezone(dt.timedelta(hours=-5))

try:
    from .daily_key_levels import render_brief_sections, FEED_REQUIRED, present
    from .daily_key_levels_adapters import build_daily_key_levels, intraday_time_to_close_frac
except ImportError:
    from daily_key_levels import render_brief_sections, FEED_REQUIRED, present
    from daily_key_levels_adapters import build_daily_key_levels, intraday_time_to_close_frac

try:
    import requests
except Exception:  # pragma: no cover
    requests = None

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = os.getenv("APEX_BRIEF_MODEL", "claude-sonnet-5")
DEFAULT_AI_TIMEOUT = max(5, min(int(os.getenv("APEX_BRIEF_AI_TIMEOUT_SECONDS", "10")), 45))
ANTHROPIC_MAX_ATTEMPTS = 2  # initial request + one controlled retry
ANTHROPIC_RETRY_BACKOFF_SECONDS = max(0.0, min(float(os.getenv("APEX_BRIEF_AI_RETRY_BACKOFF_SECONDS", "0.75")), 5.0))
ANTHROPIC_CIRCUIT_FAILURE_THRESHOLD = max(1, int(os.getenv("APEX_BRIEF_AI_CIRCUIT_FAILURE_THRESHOLD", "3")))
ANTHROPIC_CIRCUIT_COOLDOWN_SECONDS = max(10.0, min(float(os.getenv("APEX_BRIEF_AI_CIRCUIT_COOLDOWN_SECONDS", "120")), 1800.0))

_CIRCUIT_LOCK = threading.RLock()
_CIRCUIT = {
    "state": "CLOSED",
    "consecutive_failures": 0,
    "opened_at_monotonic": None,
    "last_error": None,
    "last_success_at": None,
}


def _now_et() -> dt.datetime:
    return dt.datetime.now(_ET)


def session_date(now: Optional[dt.datetime] = None) -> str:
    return (now or _now_et()).date().isoformat()


def _v(x: Any) -> Any:
    return x if present(x) else str(FEED_REQUIRED)


# --------------------------------------------------------------------------- #
# 1) Deterministic layer — real levels from the engine
# --------------------------------------------------------------------------- #

def build_deterministic(**kwargs) -> tuple[Any, str, dict]:
    """Run the Daily Key Levels engine. Returns (dkl, rendered_sections_text,
    compact_context) where compact_context is a small dict handed to the model."""
    suppress_opening = bool(kwargs.pop("_suppress_opening_levels", False))
    dkl = build_daily_key_levels(**kwargs)
    if suppress_opening:
        # Next-session/pre-market briefs must never present the prior session's
        # OR/IB as if it belonged to the target session. Preserve the level rows
        # but make their future-session unavailability explicit and remove them
        # from ranking.
        opening_kinds = {"or5_high", "or5_low", "or15_high", "or15_low",
                         "ib_high", "ib_low", "ib_extension"}
        for lv in dkl.levels:
            if getattr(getattr(lv, "kind", None), "value", None) in opening_kinds:
                lv.price = FEED_REQUIRED
                lv.strength_score = FEED_REQUIRED
                lv.prior_reactions = FEED_REQUIRED
                lv.reaction_prob = FEED_REQUIRED
                lv.break_prob = FEED_REQUIRED
                lv.reversal_prob = FEED_REQUIRED
                lv.magnet_score = FEED_REQUIRED
        dkl.ranked = [r for r in dkl.ranked
                      if getattr(getattr(r.level, "kind", None), "value", None) not in opening_kinds]
    sections = render_brief_sections(
        dkl.spot, dkl.levels, dkl.gamma, dkl.expected_move, dkl.trade_map, dkl.ranked
    )
    em = dkl.expected_move
    context = {
        "spot": _v(dkl.spot),
        "gamma_regime": dkl.gamma.regime.value,
        "gamma_flip": _v(dkl.gamma.flip),
        "call_wall": _v(dkl.gamma.call_wall),
        "put_wall": _v(dkl.gamma.put_wall),
        "expected_move": {"one_sigma": _v(em.em_1sigma), "upper": _v(em.upper), "lower": _v(em.lower)},
        "top_levels": [
            {"kind": r.level.kind.value, "price": _v(r.level.price),
             "instrument": r.level.instrument, "importance": r.importance}
            for r in dkl.ranked[:10]
        ],
        "trade_map": [
            {"condition": t.condition, "implication": t.implication, "regime": t.regime_hint}
            for t in dkl.trade_map
        ],
    }
    return dkl, sections, context


# --------------------------------------------------------------------------- #
# 2) Prompt — the model gets the real data + strict guardrails
# --------------------------------------------------------------------------- #

_BRIEF_SYSTEM = (
    "You are the Institutional Research Director for APEX, an SPX 0DTE options "
    "decision-support system. You are writing the PRE-MARKET morning brief so a "
    "trader can plan before the open. Objective: improve decision quality, NOT "
    "produce trade calls. Never output buy/sell/entry recommendations."
)


def build_prompt(context: dict, sdate: str, session_context: Optional[dict] = None) -> str:
    import json
    sc = session_context or {"state": "PREMARKET", "brief_mode": "PREMARKET", "label": "Pre-market"}
    mode = str(sc.get("brief_mode") or "PREMARKET").upper()
    framing = {
        "PREMARKET": "Write a forward-looking pre-market planning brief. Treat today's scheduled events as upcoming only when their ET time has not passed.",
        "LIVE_SESSION": "Write a live-session institutional update. Use completed-event language for releases that already occurred and focus on the active auction, not pre-market framing.",
        "AFTER_CLOSE": "Write an after-close session recap and next-session preparation brief. Do not use pre-market, ahead-of-open, or upcoming-today language for completed events.",
        "NEXT_SESSION_PREP": "Write a next-session preparation brief. Separate completed prior-session developments from genuinely upcoming catalysts.",
    }.get(mode, "Write a session-aware institutional brief.")
    return f"""{_BRIEF_SYSTEM}

Today is {sdate} (US Eastern). Current APEX session state is
{sc.get('state')} ({sc.get('label')}). {framing}

Use web_search to gather the most current information for the macro sections:
equity/futures behavior, Treasury yields, the dollar, VIX, the economic calendar,
Fed speakers, and earnings capable of moving SPX. Prioritize the last 24 hours.
Never describe an already-completed event as upcoming.

APEX has already computed deterministic market structure. Use these REAL values
as the factual backbone. DO NOT invent or alter any price level. Anything you
cannot source must be [FEED REQUIRED].

APEX SESSION CONTEXT:
{json.dumps(sc, indent=2)}

APEX DATA (authoritative):
{json.dumps(context, indent=2)}

Write concise institutional Markdown:

## SECTION 1 — EXECUTIVE SUMMARY
Describe the market in language appropriate to the current session state. Then
classify the expected/current regime — Trend, Balanced Auction, Expansion,
Compression, Mean Reversion, High Volatility, Low Volatility, or Event Driven —
and explain why in 2-4 sentences.

## SECTION 2 — TODAY'S EVENTS
For PREMARKET, list upcoming ET events. For LIVE_SESSION, distinguish completed
from upcoming events. For AFTER_CLOSE/NEXT_SESSION_PREP, summarize completed
catalysts and identify only genuinely upcoming next-session events.

## SECTION 12 — RISK WATCH
Largest unknowns and what would invalidate the base/current regime.

Do not write key-level, trade-map, or expected-move sections. APEX appends those.
Keep the response under ~700 words.
"""


# --------------------------------------------------------------------------- #
# 3) The single Anthropic call (macro + narrative, with web_search)
# --------------------------------------------------------------------------- #

def _circuit_snapshot(now_mono: Optional[float] = None) -> dict:
    now_mono = time.monotonic() if now_mono is None else now_mono
    with _CIRCUIT_LOCK:
        state = str(_CIRCUIT["state"])
        opened = _CIRCUIT.get("opened_at_monotonic")
        remaining = 0.0
        if state == "OPEN" and opened is not None:
            elapsed = max(0.0, now_mono - float(opened))
            remaining = max(0.0, ANTHROPIC_CIRCUIT_COOLDOWN_SECONDS - elapsed)
            if remaining <= 0.0:
                state = "HALF_OPEN"
        return {
            "state": state,
            "consecutive_failures": int(_CIRCUIT["consecutive_failures"]),
            "failure_threshold": ANTHROPIC_CIRCUIT_FAILURE_THRESHOLD,
            "cooldown_seconds": ANTHROPIC_CIRCUIT_COOLDOWN_SECONDS,
            "cooldown_remaining_seconds": round(remaining, 3),
            "last_error": _CIRCUIT.get("last_error"),
            "last_success_at": _CIRCUIT.get("last_success_at"),
        }


def _circuit_before_call() -> tuple[bool, dict]:
    now_mono = time.monotonic()
    with _CIRCUIT_LOCK:
        state = str(_CIRCUIT["state"])
        opened = _CIRCUIT.get("opened_at_monotonic")
        if state == "OPEN" and opened is not None:
            elapsed = max(0.0, now_mono - float(opened))
            if elapsed < ANTHROPIC_CIRCUIT_COOLDOWN_SECONDS:
                return False, _circuit_snapshot(now_mono)
            _CIRCUIT["state"] = "HALF_OPEN"
    return True, _circuit_snapshot(now_mono)


def _circuit_record_success() -> dict:
    with _CIRCUIT_LOCK:
        _CIRCUIT.update({
            "state": "CLOSED",
            "consecutive_failures": 0,
            "opened_at_monotonic": None,
            "last_error": None,
            "last_success_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        })
    return _circuit_snapshot()


def _circuit_record_failure(error: str) -> dict:
    with _CIRCUIT_LOCK:
        failures = int(_CIRCUIT["consecutive_failures"]) + 1
        _CIRCUIT["consecutive_failures"] = failures
        _CIRCUIT["last_error"] = str(error)[:300]
        if failures >= ANTHROPIC_CIRCUIT_FAILURE_THRESHOLD:
            _CIRCUIT["state"] = "OPEN"
            _CIRCUIT["opened_at_monotonic"] = time.monotonic()
        elif _CIRCUIT.get("state") == "HALF_OPEN":
            _CIRCUIT["state"] = "OPEN"
            _CIRCUIT["opened_at_monotonic"] = time.monotonic()
    return _circuit_snapshot()


def _reset_anthropic_circuit_for_tests() -> None:
    with _CIRCUIT_LOCK:
        _CIRCUIT.update({
            "state": "CLOSED",
            "consecutive_failures": 0,
            "opened_at_monotonic": None,
            "last_error": None,
            "last_success_at": None,
        })


def _retryable_status(status_code: int) -> bool:
    return status_code == 429 or status_code >= 500 or status_code in {408, 409}


def call_anthropic(prompt: str, *, api_key: str, model: str = DEFAULT_MODEL,
                   max_tokens: int = 4000, timeout: int = DEFAULT_AI_TIMEOUT):
    """Return ``(narrative, error, telemetry)``.

    The integration is intentionally bounded: one retry maximum, exponential
    backoff, and a local circuit breaker. No API key or response body is exposed
    through telemetry.
    """
    telemetry = {
        "provider": "anthropic",
        "model": model,
        "max_attempts": ANTHROPIC_MAX_ATTEMPTS,
        "timeout_seconds_per_attempt": timeout,
        "retry_backoff_base_seconds": ANTHROPIC_RETRY_BACKOFF_SECONDS,
        "attempts": [],
        "retry_count": 0,
        "total_duration_ms": 0.0,
        "circuit": _circuit_snapshot(),
        "network_io_performed": False,
    }
    if requests is None:
        error = "requests library unavailable"
        telemetry["final_error"] = error
        return "", error, telemetry

    allowed, circuit = _circuit_before_call()
    telemetry["circuit"] = circuit
    if not allowed:
        error = "Anthropic circuit breaker open; deterministic fallback active"
        telemetry.update({
            "final_error": error,
            "circuit_bypassed_request": True,
            "outcome": "CIRCUIT_OPEN",
        })
        return "", error, telemetry

    total_started = time.perf_counter()
    final_error = None
    for attempt_no in range(1, ANTHROPIC_MAX_ATTEMPTS + 1):
        attempt_started = time.perf_counter()
        attempt = {
            "attempt": attempt_no,
            "status": "UNKNOWN",
            "duration_ms": 0.0,
            "retryable": False,
            "http_status": None,
            "error_type": None,
            "error": None,
        }
        try:
            telemetry["network_io_performed"] = True
            resp = requests.post(
                ANTHROPIC_URL,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": model,
                    "max_tokens": max_tokens,
                    "messages": [{"role": "user", "content": prompt}],
                    "tools": [{"type": "web_search_20250305", "name": "web_search"}],
                },
                timeout=timeout,
            )
            attempt["http_status"] = int(resp.status_code)
            if resp.status_code != 200:
                retryable = _retryable_status(int(resp.status_code))
                final_error = f"anthropic {resp.status_code}: {resp.text[:200]}"
                attempt.update({
                    "status": "HTTP_ERROR",
                    "retryable": retryable,
                    "error_type": "HTTPError",
                    "error": final_error,
                })
            else:
                data = resp.json()
                text = "".join(
                    b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"
                ).strip()
                if text:
                    attempt["status"] = "SUCCESS"
                    attempt["duration_ms"] = round((time.perf_counter() - attempt_started) * 1000, 1)
                    telemetry["attempts"].append(attempt)
                    telemetry["total_duration_ms"] = round((time.perf_counter() - total_started) * 1000, 1)
                    telemetry["outcome"] = "SUCCESS"
                    telemetry["final_error"] = None
                    telemetry["circuit"] = _circuit_record_success()
                    return text, None, telemetry
                final_error = "empty narrative"
                attempt.update({
                    "status": "EMPTY_RESPONSE",
                    "retryable": True,
                    "error_type": "EmptyResponse",
                    "error": final_error,
                })
        except Exception as exc:  # network / timeout / parse
            final_error = f"{type(exc).__name__}: {exc}"
            retryable = False
            if requests is not None:
                retryable_types = tuple(
                    t for t in (
                        getattr(requests.exceptions, "Timeout", None),
                        getattr(requests.exceptions, "ConnectionError", None),
                    ) if t is not None
                )
                retryable = bool(retryable_types and isinstance(exc, retryable_types))
            attempt.update({
                "status": "EXCEPTION",
                "retryable": retryable,
                "error_type": type(exc).__name__,
                "error": final_error,
            })

        attempt["duration_ms"] = round((time.perf_counter() - attempt_started) * 1000, 1)
        telemetry["attempts"].append(attempt)
        if attempt_no >= ANTHROPIC_MAX_ATTEMPTS or not attempt["retryable"]:
            break

        delay = ANTHROPIC_RETRY_BACKOFF_SECONDS * (2 ** (attempt_no - 1))
        telemetry["retry_count"] += 1
        telemetry["attempts"][-1]["backoff_before_next_attempt_seconds"] = round(delay, 3)
        if delay > 0:
            time.sleep(delay)

    telemetry["total_duration_ms"] = round((time.perf_counter() - total_started) * 1000, 1)
    telemetry["final_error"] = final_error
    telemetry["outcome"] = "FAILED"
    breaker_eligible = bool(telemetry["attempts"] and telemetry["attempts"][-1].get("retryable"))
    telemetry["breaker_failure_counted"] = breaker_eligible
    telemetry["circuit"] = (
        _circuit_record_failure(final_error or "unknown anthropic failure")
        if breaker_eligible else _circuit_snapshot()
    )
    return "", final_error, telemetry


# --------------------------------------------------------------------------- #
# 4) Orchestrator — assemble, cache, degrade gracefully
# --------------------------------------------------------------------------- #

def generate_morning_brief(
    *,
    cache: Optional[dict] = None,
    narrative_cache: Optional[dict] = None,
    force: bool = False,
    refresh_narrative: bool = False,
    session_context: Optional[dict] = None,
    api_key: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    _llm=call_anthropic,
    **engine_kwargs,
) -> dict:
    """Rebuild deterministic data every request while reusing session narrative.

    `force` refreshes market structure. `refresh_narrative` is the explicit,
    costlier operation that bypasses the narrative cache.
    """
    import time

    started = time.perf_counter()
    timings = {}
    sdate = session_date()
    sc = session_context or {"state": "PREMARKET", "brief_mode": "PREMARKET", "label": "Pre-market"}
    mode = str(sc.get("brief_mode") or "PREMARKET").upper()
    source_date = str(sc.get("source_session_date") or sdate)
    target_date = str(sc.get("target_session_date") or source_date)
    display_date = target_date if mode == "NEXT_SESSION_PREP" else source_date
    result_key = f"{target_date}:{mode}"

    step = time.perf_counter()
    dkl, sections, context = build_deterministic(
        _suppress_opening_levels=(target_date != source_date),
        **engine_kwargs,
    )
    timings["deterministic"] = round((time.perf_counter() - step) * 1000, 1)

    narrative = ""
    err = None
    narrative_source = "none"
    narrative_status = "UNAVAILABLE"
    ai_telemetry = {"provider": "anthropic", "outcome": "NOT_ATTEMPTED", "attempts": [], "circuit": _circuit_snapshot()}
    ncache = narrative_cache if narrative_cache is not None else cache
    cached_narrative = (ncache or {}).get(result_key) if ncache is not None else None

    if cached_narrative and not refresh_narrative:
        narrative = str(cached_narrative.get("narrative") or "")
        err = cached_narrative.get("error")
        narrative_source = "cache"
        narrative_status = "CACHED_SUCCESS" if narrative else "UNAVAILABLE"
        timings["prompt_build"] = 0.0
        timings["ai_call"] = 0.0
    else:
        step = time.perf_counter()
        prompt = build_prompt(context, display_date, sc)
        timings["prompt_build"] = round((time.perf_counter() - step) * 1000, 1)
        api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "").strip()
        step = time.perf_counter()
        if api_key:
            llm_result = _llm(prompt, api_key=api_key, model=model)
            if isinstance(llm_result, tuple) and len(llm_result) >= 3:
                narrative, err, ai_telemetry = llm_result[0], llm_result[1], (llm_result[2] or ai_telemetry)
            else:
                narrative, err = llm_result
                ai_telemetry = {
                    "provider": "anthropic",
                    "outcome": "SUCCESS" if narrative else "FAILED",
                    "attempts": [],
                    "telemetry_source": "legacy_llm_adapter",
                    "circuit": _circuit_snapshot(),
                }
            narrative_source = "anthropic" if narrative else "deterministic_fallback"
            low_err = str(err or "").lower()
            if narrative:
                narrative_status = "FRESH"
            elif str(ai_telemetry.get("outcome") or "").upper() == "CIRCUIT_OPEN":
                narrative_status = "CIRCUIT_OPEN_FALLBACK"
            elif "timeout" in low_err:
                narrative_status = "TIMEOUT_FALLBACK"
            else:
                narrative_status = "ERROR_FALLBACK"
        else:
            narrative, err = "", "no ANTHROPIC_API_KEY set"
            narrative_source = "deterministic_fallback"
            narrative_status = "NO_KEY_FALLBACK"
            ai_telemetry = {
                "provider": "anthropic",
                "outcome": "NO_KEY",
                "attempts": [],
                "network_io_performed": False,
                "circuit": _circuit_snapshot(),
            }
        timings["ai_call"] = round((time.perf_counter() - step) * 1000, 1)
        # Cache successful narratives only. Timeout/error fallbacks are deterministic
        # response states, not reusable narrative content.
        if ncache is not None and narrative:
            ncache[result_key] = {
                "narrative": narrative,
                "error": None,
                "status": "FRESH",
                "generated_at": _now_et().isoformat(),
                "session_context": sc,
                "ai_call_ms": timings["ai_call"],
            }

    step = time.perf_counter()
    if narrative:
        head = narrative
        has_narrative = True
    else:
        title = {
            "AFTER_CLOSE": "APEX AFTER-CLOSE BRIEF",
            "NEXT_SESSION_PREP": "APEX NEXT-SESSION PREP",
            "LIVE_SESSION": "APEX LIVE SESSION BRIEF",
        }.get(mode, "APEX MORNING BRIEF")
        head = (f"# {title} — {display_date}\n\n"
                "_AI narrative unavailable — deterministic institutional analysis "
                "is active. Technical failure details are available in diagnostics._\n")
        has_narrative = False

    markdown = f"{head}\n\n---\n\n{sections}\n"
    timings["assembly"] = round((time.perf_counter() - step) * 1000, 1)
    timings["total"] = round((time.perf_counter() - started) * 1000, 1)

    result = {
        "ok": True,
        "session_date": source_date,
        "source_session_date": source_date,
        "target_session_date": target_date,
        "generated_at": _now_et().isoformat(),
        "cached": False,
        "has_narrative": has_narrative,
        "narrative_error": err,
        "narrative_status": narrative_status,
        "narrative_source": narrative_source,
        "session_context": sc,
        "generation_timing": timings,
        "narrative_attempt": {
            "attempted": bool(ai_telemetry.get("network_io_performed")) or narrative_source == "anthropic",
            "duration_ms": timings.get("ai_call", 0.0),
            "status": narrative_status,
            "error": err,
            "attempt_count": len(ai_telemetry.get("attempts") or []),
            "retry_count": int(ai_telemetry.get("retry_count") or 0),
            "circuit_state": (ai_telemetry.get("circuit") or {}).get("state"),
        },
        "anthropic_telemetry": ai_telemetry,
        "markdown": markdown,
        "structured": dkl.to_dict(),
    }
    if cache is not None:
        cache[result_key] = result
    return result


# --------------------------------------------------------------------------- #
# Demo: deterministic assembly + merge, with a stubbed LLM (no network/key)
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    now = _now_et()
    ms_ts = lambda hh, mm, d=0: int((now.replace(hour=hh, minute=mm, second=0, microsecond=0)
                                     + dt.timedelta(days=d)).timestamp() * 1000)
    canonical_ms = {"price": 7455.0, "poc": 7448.0, "vah": 7460.0, "val": 7435.0,
                    "hvn": [7448.0], "lvn": [7475.0], "call_wall": 7500.0,
                    "put_wall": 7400.0, "zero_gamma": 7438.0, "gamma_regime": "POSITIVE"}
    flow_snapshot = {"stock_price": 7455.0, "active_gamma_flip": 7440.0}
    daily = [{"t": ms_ts(16, 0, -2), "o": 7380, "h": 7420, "l": 7360, "c": 7405, "v": 2e6},
             {"t": ms_ts(16, 0, -1), "o": 7405, "h": 7442, "l": 7398, "c": 7430, "v": 2.2e6}]

    def fake_llm(prompt, *, api_key, model=DEFAULT_MODEL):
        assert "APEX DATA" in prompt and "7455" in prompt  # engine data reached the prompt
        return ("## SECTION 1 — EXECUTIVE SUMMARY\n(stubbed narrative; real run uses "
                "web_search)\nRegime: **Event Driven** — dealers long gamma into a "
                "scheduled catalyst.\n\n## SECTION 2 — TODAY'S EVENTS\n[FEED REQUIRED]\n\n"
                "## SECTION 12 — RISK WATCH\nBase case invalidated below the put wall.", None)

    out = generate_morning_brief(
        cache={}, api_key="test", _llm=fake_llm,
        canonical_ms=canonical_ms, flow_snapshot=flow_snapshot,
        daily_bars=daily, intraday_1m_bars=[],
        straddle=58.0, iv=0.14, time_to_close_frac=intraday_time_to_close_frac(now),
        atr_val=62.0, adr_val=55.0,
    )
    print("has_narrative:", out["has_narrative"], "| session:", out["session_date"])
    print("=" * 70)
    print(out["markdown"][:1400])
