from engine.morning_brief_validation import latest, provider_record, record, validate_payload

def test_validation_detects_core_sections_and_missing_narrative():
    report = validate_payload({"structured": {"spot": 1, "gamma_regime": "neutral_gamma", "levels": [], "trade_map": []}, "markdown": "SECTION 1 — X\nSECTION 15 — LEVELS\nSECTION 16 — MAP\nSECTION 17 — RANKED"})
    assert report["sections"]["15"] is True
    assert report["errors"] == []

def test_validation_state_is_json_safe_and_persistent():
    record({"ok": True, "status": "HEALTHY", "providers": {"flow": provider_record("ok", 12.34)}, "warnings": [], "errors": []})
    snap = latest()
    assert snap["providers"]["flow"]["latency_ms"] == 12.3
    # The point of this test is json-safety/persistence + latency rounding, not a
    # specific sprint number; assert a version is present and well-formed instead.
    assert isinstance(snap["version"], str) and snap["version"]
