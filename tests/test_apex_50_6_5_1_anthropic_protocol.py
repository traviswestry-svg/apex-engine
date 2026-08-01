import engine.morning_brief as mb


class _Resp:
    def __init__(self, payload, status=200, text=''):
        self.status_code = status
        self.text = text
        self._payload = payload
    def json(self):
        return self._payload


def setup_function():
    mb._reset_anthropic_circuit_for_tests()


def test_pause_turn_is_continued_not_retried(monkeypatch):
    payloads = []
    responses = [
        _Resp({
            "stop_reason": "pause_turn",
            "content": [
                {"type": "server_tool_use", "id": "srv_1", "name": "web_search", "input": {"query": "SPX"}},
                {"type": "web_search_tool_result", "tool_use_id": "srv_1", "content": []},
            ],
        }),
        _Resp({"stop_reason": "end_turn", "content": [{"type": "text", "text": "final narrative"}]}),
    ]
    def post(*args, **kwargs):
        payloads.append(kwargs["json"])
        return responses.pop(0)
    monkeypatch.setattr(mb.requests, "post", post)

    text, err, tel = mb.call_anthropic("prompt", api_key="secret", timeout=5)

    assert text == "final narrative"
    assert err is None
    assert tel["outcome"] == "SUCCESS"
    assert tel["retry_count"] == 0
    assert tel["pause_turn_count"] == 1
    assert tel["network_call_count"] == 2
    assert len(tel["attempts"]) == 1
    assert tel["attempts"][0]["pause_continuations"] == 1
    assert payloads[0]["tools"][0]["max_uses"] == mb.ANTHROPIC_WEB_SEARCH_MAX_USES
    assert payloads[1]["messages"][1]["role"] == "assistant"
    assert "tools" in payloads[1]


def test_transient_retry_drops_web_search(monkeypatch):
    payloads = []
    def post(*args, **kwargs):
        payloads.append(kwargs["json"])
        if len(payloads) == 1:
            raise mb.requests.exceptions.Timeout("slow web search")
        return _Resp({"stop_reason": "end_turn", "content": [{"type": "text", "text": "degraded narrative"}]})
    monkeypatch.setattr(mb.requests, "post", post)
    monkeypatch.setattr(mb.time, "sleep", lambda _s: None)

    text, err, tel = mb.call_anthropic("prompt", api_key="secret", timeout=5)

    assert text == "degraded narrative"
    assert err is None
    assert tel["retry_count"] == 1
    assert tel["degraded_no_web_search"] is True
    assert "tools" in payloads[0]
    assert "tools" not in payloads[1]
    assert tel["attempts"][1]["degraded_retry_without_web_search"] is True


def test_budget_exhaustion_gets_specific_status(monkeypatch):
    class _Gamma:
        regime = type("R", (), {"value": "unknown"})()
        flip = call_wall = put_wall = None
    class _EM:
        em_1sigma = upper = lower = None
    class _DKL:
        spot = 5000.0
        gamma = _Gamma()
        expected_move = _EM()
        trade_map = []
        ranked = []
        levels = []
        def to_dict(self): return {"spot": self.spot, "levels": []}
    monkeypatch.setattr(mb, "build_deterministic", lambda **kwargs: (_DKL(), "SECTIONS", {"spot": 5000.0}))
    telemetry = {"provider":"anthropic","outcome":"BUDGET_EXHAUSTED","network_io_performed":True,"retry_count":1,"attempts":[{"attempt":1}],"circuit":{"state":"CLOSED"}}
    def fake_llm(prompt, *, api_key, model):
        return "", "Anthropic total latency budget exhausted", telemetry
    out = mb.generate_morning_brief(cache={}, api_key="secret", _llm=fake_llm, session_context={"brief_mode":"NEXT_SESSION_PREP","source_session_date":"2026-07-31","target_session_date":"2026-08-03"})
    assert out["narrative_status"] == "BUDGET_EXHAUSTED_FALLBACK"
