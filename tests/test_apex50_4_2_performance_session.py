import datetime as dt
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]



def test_after_hours_session_classification():
    from engine import session_intelligence as mod
    now = dt.datetime(2026, 7, 30, 19, 24, tzinfo=mod.ET)
    ctx = mod.classify_session(now).to_dict()
    assert ctx["state"] == "AFTER_HOURS"
    assert ctx["brief_mode"] == "AFTER_CLOSE"
    assert ctx["market_open"] is False


def test_premarket_session_classification():
    from engine import session_intelligence as mod
    now = dt.datetime(2026, 7, 30, 8, 0, tzinfo=mod.ET)
    ctx = mod.classify_session(now).to_dict()
    assert ctx["state"] == "PREMARKET"
    assert ctx["brief_mode"] == "PREMARKET"


def test_version_is_5042():
    from engine import version as mod
    assert mod.MORNING_BRIEF_VERSION == "50.4.2_PERFORMANCE_SESSION_INTELLIGENCE"


def test_app_contains_narrative_cache_and_gamma_guard():
    text = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "_MORNING_NARRATIVE_CACHE" in text
    assert "refresh_narrative" in text
    assert "directional_logic_enabled" in text
    assert "reported zero-gamma reference" in text


def test_brief_has_bounded_timeout_and_session_prompt():
    text = (ROOT / "engine/morning_brief.py").read_text(encoding="utf-8")
    assert "APEX_BRIEF_AI_TIMEOUT_SECONDS" in text
    assert "session_context" in text
    assert "TIMEOUT_FALLBACK" in text
    assert "Never describe an already-completed event as upcoming" in text
