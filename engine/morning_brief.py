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
    dkl = build_daily_key_levels(**kwargs)
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


def build_prompt(context: dict, sdate: str) -> str:
    import json
    return f"""{_BRIEF_SYSTEM}

Today is {sdate} (US Eastern), pre-market. Use web_search to gather the most
current information for the macro sections: overnight developments, ES/equity
futures behavior, Treasury yields, the dollar, VIX, today's economic calendar
(releases, Fed speakers), and any earnings capable of moving SPX. Prioritize the
last 24 hours and cite what you find.

APEX has already computed today's deterministic market structure. Use these REAL
values as the factual backbone of your narrative. DO NOT invent or alter any
price level — if you reference a level, use exactly the number below. Anything you
genuinely cannot source, write as [FEED REQUIRED] rather than guessing.

APEX DATA (authoritative):
{json.dumps(context, indent=2)}

Write these sections in Markdown, concise and institutional:

## SECTION 1 — EXECUTIVE SUMMARY
Overnight developments, futures, rates, dollar, VIX, macro themes, sentiment.
Then classify today's expected regime — one of: Trend, Balanced Auction,
Expansion, Compression, Mean Reversion, High Volatility, Low Volatility,
Event Driven — and explain WHY in 2-4 sentences, referencing the APEX gamma
regime ({context.get('gamma_regime')}) and expected move where relevant.

## SECTION 2 — TODAY'S EVENTS
Scheduled releases, Fed speakers, major earnings, and why each matters to
intraday SPX. Note exact ET times where known.

## SECTION 12 — RISK WATCH
Today's largest unknowns, macro/event/volatility/liquidity risks, and what would
invalidate the base-case regime you assigned.

Do NOT write the key-levels, trade-map, or expected-move sections — APEX appends
those from its own engine after your text. Keep the whole thing under ~700 words.
"""


# --------------------------------------------------------------------------- #
# 3) The single Anthropic call (macro + narrative, with web_search)
# --------------------------------------------------------------------------- #

def call_anthropic(prompt: str, *, api_key: str, model: str = DEFAULT_MODEL,
                   max_tokens: int = 4000, timeout: int = 120) -> tuple[str, Optional[str]]:
    """Returns (narrative_markdown, error). error is None on success."""
    if requests is None:
        return "", "requests library unavailable"
    try:
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
        if resp.status_code != 200:
            return "", f"anthropic {resp.status_code}: {resp.text[:200]}"
        data = resp.json()
        text = "".join(
            b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"
        ).strip()
        return (text, None) if text else ("", "empty narrative")
    except Exception as e:  # network/timeout/parse
        return "", f"{type(e).__name__}: {e}"


# --------------------------------------------------------------------------- #
# 4) Orchestrator — assemble, cache, degrade gracefully
# --------------------------------------------------------------------------- #

def generate_morning_brief(
    *,
    cache: Optional[dict] = None,
    force: bool = False,
    api_key: Optional[str] = None,
    model: str = DEFAULT_MODEL,
    _llm=call_anthropic,           # injectable for testing
    **engine_kwargs,
) -> dict:
    """Build the full brief. `cache` is any dict you persist (e.g. a module global
    or ACTIVE_POSITION slot); results are keyed by ET session date."""
    sdate = session_date()
    if cache is not None and not force:
        hit = cache.get(sdate)
        if hit:
            return {**hit, "cached": True}

    dkl, sections, context = build_deterministic(**engine_kwargs)

    api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "").strip()
    if api_key:
        narrative, err = _llm(build_prompt(context, sdate), api_key=api_key, model=model)
    else:
        narrative, err = "", "no ANTHROPIC_API_KEY set"

    if narrative:
        head = narrative
        has_narrative = True
    else:
        head = (f"# APEX MORNING BRIEF — {sdate}\n\n"
                f"_Macro + narrative unavailable ({err}). Showing deterministic "
                f"levels only._\n")
        has_narrative = False

    markdown = f"{head}\n\n---\n\n{sections}\n"
    result = {
        "ok": True,
        "session_date": sdate,
        "generated_at": _now_et().isoformat(),
        "cached": False,
        "has_narrative": has_narrative,
        "narrative_error": err,
        "markdown": markdown,
        "structured": dkl.to_dict(),
    }
    if cache is not None:
        cache[sdate] = result
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
