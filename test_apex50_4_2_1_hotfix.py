import datetime as dt

from engine.session_intelligence import ET, classify_session
from engine import morning_brief as mb


def test_next_session_date_rolls_forward():
    ctx = classify_session(dt.datetime(2026, 7, 30, 21, 0, tzinfo=ET)).to_dict()
    assert ctx["source_session_date"] == "2026-07-30"
    assert ctx["target_session_date"] == "2026-07-31"
    assert ctx["brief_mode"] == "NEXT_SESSION_PREP"


def test_timeout_fallback_is_not_cached(monkeypatch):
    monkeypatch.setattr(mb, "session_date", lambda now=None: "2026-07-30")
    monkeypatch.setattr(mb, "build_deterministic", lambda **kwargs: (type("D", (), {"to_dict": lambda self: {}})(), "SECTION 15", {}))
    cache = {}
    ctx = {"state":"OVERNIGHT","brief_mode":"NEXT_SESSION_PREP","label":"Overnight","source_session_date":"2026-07-30","target_session_date":"2026-07-31"}
    out = mb.generate_morning_brief(narrative_cache=cache, session_context=ctx, api_key="x", _llm=lambda *a, **k: ("", "ReadTimeout"))
    assert cache == {}
    assert out["narrative_status"] == "TIMEOUT_FALLBACK"
    assert out["target_session_date"] == "2026-07-31"
    assert "2026-07-31" in out["markdown"]


def test_successful_narrative_is_cached(monkeypatch):
    monkeypatch.setattr(mb, "session_date", lambda now=None: "2026-07-30")
    monkeypatch.setattr(mb, "build_deterministic", lambda **kwargs: (type("D", (), {"to_dict": lambda self: {}})(), "SECTION 15", {}))
    cache = {}
    ctx = {"state":"OVERNIGHT","brief_mode":"NEXT_SESSION_PREP","label":"Overnight","source_session_date":"2026-07-30","target_session_date":"2026-07-31"}
    mb.generate_morning_brief(narrative_cache=cache, session_context=ctx, api_key="x", _llm=lambda *a, **k: ("hello", None))
    assert "2026-07-31:NEXT_SESSION_PREP" in cache
