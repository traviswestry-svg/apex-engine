import engine.morning_brief as mb


class _Resp:
    def __init__(self, status=200, text='', payload=None):
        self.status_code = status
        self.text = text
        self._payload = payload if payload is not None else {"content": [{"type": "text", "text": "ok narrative"}]}

    def json(self):
        return self._payload


def setup_function():
    mb._reset_anthropic_circuit_for_tests()


def test_timeout_retries_once_then_succeeds(monkeypatch):
    calls = []
    sleeps = []

    def post(*args, **kwargs):
        calls.append(kwargs.get("timeout"))
        if len(calls) == 1:
            raise mb.requests.exceptions.Timeout("slow")
        return _Resp()

    monkeypatch.setattr(mb.requests, "post", post)
    monkeypatch.setattr(mb.time, "sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(mb, "ANTHROPIC_RETRY_BACKOFF_SECONDS", 0.25)

    text, err, telemetry = mb.call_anthropic("prompt", api_key="secret", timeout=5)

    assert text == "ok narrative"
    assert err is None
    assert len(calls) == 2
    assert telemetry["retry_count"] == 1
    assert telemetry["attempts"][0]["retryable"] is True
    assert telemetry["attempts"][0]["backoff_before_next_attempt_seconds"] == 0.25
    assert sleeps == [0.25]
    assert telemetry["outcome"] == "SUCCESS"
    assert telemetry["circuit"]["state"] == "CLOSED"


def test_auth_error_is_not_retried(monkeypatch):
    calls = []

    def post(*args, **kwargs):
        calls.append(1)
        return _Resp(status=401, text="bad key")

    monkeypatch.setattr(mb.requests, "post", post)
    text, err, telemetry = mb.call_anthropic("prompt", api_key="secret")

    assert text == ""
    assert "401" in err
    assert len(calls) == 1
    assert telemetry["retry_count"] == 0
    assert telemetry["attempts"][0]["retryable"] is False


def test_circuit_opens_and_bypasses_network(monkeypatch):
    calls = []

    def post(*args, **kwargs):
        calls.append(1)
        raise mb.requests.exceptions.Timeout("still slow")

    monkeypatch.setattr(mb.requests, "post", post)
    monkeypatch.setattr(mb.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(mb, "ANTHROPIC_RETRY_BACKOFF_SECONDS", 0.0)
    monkeypatch.setattr(mb, "ANTHROPIC_CIRCUIT_FAILURE_THRESHOLD", 2)

    for _ in range(2):
        text, err, telemetry = mb.call_anthropic("prompt", api_key="secret")
        assert text == ""
        assert err

    network_calls_after_open = len(calls)
    text, err, telemetry = mb.call_anthropic("prompt", api_key="secret")

    assert text == ""
    assert "circuit breaker open" in err.lower()
    assert telemetry["outcome"] == "CIRCUIT_OPEN"
    assert telemetry["network_io_performed"] is False
    assert len(calls) == network_calls_after_open


def test_generate_morning_brief_exposes_retry_and_circuit_telemetry(monkeypatch):
    # Avoid needing the full deterministic fixture here: validate normalization
    # of a resilience-aware LLM adapter through a small monkeypatched builder.
    class _Gamma:
        regime = type("R", (), {"value": "unknown"})()
        flip = None
        call_wall = None
        put_wall = None

    class _EM:
        em_1sigma = None
        upper = None
        lower = None

    class _DKL:
        spot = 5000.0
        gamma = _Gamma()
        expected_move = _EM()
        trade_map = []
        ranked = []
        levels = []
        def to_dict(self):
            return {"spot": self.spot, "levels": []}

    monkeypatch.setattr(mb, "build_deterministic", lambda **kwargs: (_DKL(), "SECTIONS", {"spot": 5000.0}))

    telemetry = {
        "provider": "anthropic",
        "outcome": "FAILED",
        "network_io_performed": True,
        "retry_count": 1,
        "attempts": [{"attempt": 1}, {"attempt": 2}],
        "circuit": {"state": "OPEN"},
    }
    def fake_llm(prompt, *, api_key, model):
        return "", "ReadTimeout: slow", telemetry

    out = mb.generate_morning_brief(
        cache={}, api_key="secret", _llm=fake_llm,
        session_context={"brief_mode": "NEXT_SESSION_PREP", "source_session_date": "2026-07-31", "target_session_date": "2026-08-03"},
    )
    assert out["narrative_status"] == "TIMEOUT_FALLBACK"
    assert out["narrative_attempt"]["attempt_count"] == 2
    assert out["narrative_attempt"]["retry_count"] == 1
    assert out["narrative_attempt"]["circuit_state"] == "OPEN"
    assert out["anthropic_telemetry"] == telemetry
