import engine.morning_brief as mb


class _Resp:
    status_code = 200
    headers = {"request-id": "req_123"}
    def json(self):
        return {"stop_reason": "end_turn", "content": [{"type": "text", "text": "narrative ok"}]}


def setup_function():
    mb._reset_anthropic_circuit_for_tests()


def test_background_transport_uses_realistic_separate_read_budget(monkeypatch):
    seen = []
    def post(*args, **kwargs):
        seen.append(kwargs)
        return _Resp()
    monkeypatch.setattr(mb.requests, "post", post)
    text, err, tel = mb.call_anthropic("small prompt", api_key="secret")
    assert text == "narrative ok" and err is None
    assert tel["enriched_timeout_seconds"] >= 20
    assert tel["total_budget_seconds"] >= 50
    assert isinstance(seen[0]["timeout"], tuple)
    assert seen[0]["timeout"][0] == mb.ANTHROPIC_CONNECT_TIMEOUT_SECONDS
    assert seen[0]["timeout"][1] > seen[0]["timeout"][0]


def test_transport_telemetry_reports_payload_and_request_id(monkeypatch):
    monkeypatch.setattr(mb.requests, "post", lambda *a, **k: _Resp())
    text, err, tel = mb.call_anthropic("abc" * 100, api_key="secret")
    assert err is None
    req = tel["attempts"][0]["requests"][0]
    assert req["payload_bytes"] > 0
    assert req["prompt_chars"] >= 300
    assert req["approx_input_tokens"] > 0
    assert req["request_id"] == "req_123"
    assert tel["endpoint"]["host"] == "api.anthropic.com"
    assert tel["prompt_utf8_bytes"] >= 300


def test_timeout_records_exact_transport_failure(monkeypatch):
    def post(*args, **kwargs):
        raise mb.requests.exceptions.ReadTimeout("slow body")
    monkeypatch.setattr(mb.requests, "post", post)
    monkeypatch.setattr(mb.time, "sleep", lambda _s: None)
    text, err, tel = mb.call_anthropic("prompt", api_key="secret")
    assert text == ""
    assert tel["final_failure_type"] == "READ_TIMEOUT"
    assert tel["attempts"][0]["requests"][0]["failure_type"] == "READ_TIMEOUT"
    assert tel["attempts"][1]["degraded_retry_without_web_search"] is True
    assert tel["attempts"][1]["requests"][0]["max_tokens"] == mb.ANTHROPIC_DEGRADED_MAX_TOKENS


def test_degraded_prompt_removes_web_search_instruction_and_is_shorter():
    prompt = "Use web_search to gather the most current information for the macro sections:\n" \
             "equity/futures behavior, Treasury yields, the dollar, VIX, the economic calendar,\n" \
             "Fed speakers, and earnings capable of moving SPX. Prioritize the last 24 hours.\n" \
             "Never describe an already-completed event as upcoming.\nKeep the response under ~700 words."
    degraded = mb._degraded_prompt(prompt)
    assert "Use web_search" not in degraded
    assert "~350 words" in degraded
