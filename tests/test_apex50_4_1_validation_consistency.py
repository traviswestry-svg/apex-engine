from engine.morning_brief_validation import derive_status, validate_payload


def _payload(markdown: str, regime: str = "neutral_gamma"):
    return {
        "section_profile": "EXECUTIVE_5",
        "markdown": markdown,
        "structured": {
            "spot": 7437.5,
            "gamma_regime": regime,
            "levels": [
                {"kind": "gamma_flip", "price": 7440.0},
                {"kind": "zero_gamma", "price": 7438.0},
                {"kind": "volatility_trigger", "price": 7450.0},
            ],
            "trade_map": [],
        },
        "profile_history": {"saved": True, "prior_sessions_loaded": 0},
        "settlement_normalization": {
            "raw_es_settlement": 7335.25,
            "normalized_spx_settlement": 7358.53,
            "basis_adjustment": 23.28,
        },
    }


def test_executive_profile_does_not_require_sections_3_through_14():
    report = validate_payload(_payload("SECTION 1\nSECTION 2\nSECTION 15\nSECTION 16\nSECTION 17"), duration_ms=1200)
    assert report["section_profile"] == "EXECUTIVE_5"
    assert report["missing_required_sections"] == []
    assert not any("3" in warning and "Missing required" in warning for warning in report["warnings"])


def test_missing_required_executive_section_degrades():
    report = validate_payload(_payload("SECTION 1\nSECTION 2\nSECTION 15\nSECTION 16"), duration_ms=1200)
    assert "17" in report["missing_required_sections"]
    assert derive_status(report["errors"], report["warnings"]) == "DEGRADED"


def test_unknown_gamma_and_slow_generation_are_explicit_warnings():
    payload = _payload("SECTION 1\nSECTION 2\nSECTION 15\nSECTION 16\nSECTION 17", regime="unknown")
    payload["structured"]["levels"] = [
        {"kind": "gamma_flip", "price": 7697.5},
        {"kind": "zero_gamma", "price": 7697.5},
        {"kind": "volatility_trigger", "price": 7697.5},
    ]
    report = validate_payload(payload, duration_ms=58585.9)
    joined = " | ".join(report["warnings"])
    assert "Dealer gamma regime unavailable" in joined
    assert "identical" in joined
    assert "exceeded 30 seconds" in joined
    assert derive_status(report["errors"], report["warnings"]) == "DEGRADED"


def test_first_profile_session_is_initializing_not_error():
    report = validate_payload(_payload("SECTION 1\nSECTION 2\nSECTION 15\nSECTION 16\nSECTION 17"))
    assert report["profile_history_state"] == "INITIALIZING"
