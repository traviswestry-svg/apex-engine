import engine.morning_brief as mb
import engine.level_transition_probability as ltpe


def setup_function(_fn):
    mb._reset_anthropic_circuit_for_tests()


def test_embedded_brief_path_uses_inline_payload_even_when_store_init_fails(monkeypatch):
    monkeypatch.setattr(ltpe, "initialize_transition_store", lambda _path=None: (_ for _ in ()).throw(RuntimeError("db unavailable")))
    monkeypatch.setattr(ltpe, "_load_latest_morning_brief", lambda _symbol: None)
    monkeypatch.setattr(ltpe, "_load_durable_canonical_context", lambda _symbol: None)
    brief = {
        "ticker": "SPX",
        "source_session_date": "2026-07-31",
        "target_session_date": "2026-08-03",
        "session_context": {"state": "WEEKEND", "brief_mode": "NEXT_SESSION_PREP"},
        "structured": {
            "spot": 7489.52,
            "expected_move": {"one_sigma": 39.48, "lower": 7450.04, "upper": 7529.00},
            "levels": [
                {"kind":"vah", "price":7495.0, "source":"volume_profile_engine"},
                {"kind":"prev_day_high", "price":7512.04, "source":"polygon"},
                {"kind":"em_upper", "price":7529.0, "source":"computed"},
            ],
        },
    }
    monkeypatch.setattr(ltpe, "_zone_probability", lambda *a, **k: {"ok":True,"probability":None,"sample_count":0,"source":"INSUFFICIENT_HISTORY"})
    out = ltpe.current_transition_path(brief, direction="UP", max_steps=6)
    assert out["ok"] is True
    assert out["steps"]
    assert out["spot"] == 7489.52
    assert out["source_session_date"] == "2026-07-31"
    assert any(w.get("stage") == "STORE_INIT" for w in out["resolution_warnings"])


def test_failure_type_distinguishes_read_timeout(monkeypatch):
    class R:
        class exceptions:
            class Timeout(Exception): pass
            class ConnectionError(Exception): pass
            class ReadTimeout(Timeout): pass
        @staticmethod
        def post(*a, **k):
            raise R.exceptions.ReadTimeout("slow read")
    monkeypatch.setattr(mb, "requests", R)
    monkeypatch.setattr(mb, "ANTHROPIC_RETRY_BACKOFF_SECONDS", 0.0)
    monkeypatch.setattr(mb, "ANTHROPIC_ENRICHED_TIMEOUT_SECONDS", 0.1)
    monkeypatch.setattr(mb, "ANTHROPIC_DEGRADED_TIMEOUT_SECONDS", 0.1)
    monkeypatch.setattr(mb, "ANTHROPIC_TOTAL_BUDGET_SECONDS", 1.0)
    text, err, telem = mb.call_anthropic("x", api_key="k", timeout=1)
    assert text == ""
    assert err
    assert telem["final_failure_type"] == "READ_TIMEOUT"
    assert len(telem["attempts"]) == 2
    assert telem["attempts"][1]["web_search_enabled"] is False
