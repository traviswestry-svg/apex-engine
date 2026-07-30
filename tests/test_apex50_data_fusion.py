from engine.data_registry import DataRegistry
from engine.data_quality import build_morning_registry


def test_registry_reports_provider_completeness_without_fabrication():
    r = DataRegistry()
    r.put("overnight_high", 7500.0, source="massive_futures")
    r.missing("gamma_flip", source="quantdata", reason="no local crossing")
    report = r.report()
    assert report["score"] == 50.0
    assert report["providers"]["massive_futures"]["score"] == 100.0
    assert report["missing"][0]["value"] is None


def test_morning_registry_explains_missing_fields():
    structured = {
        "gamma_regime": "short_gamma",
        "expected_move": {"one_sigma": "[FEED REQUIRED]", "upper": "[FEED REQUIRED]", "lower": "[FEED REQUIRED]", "confidence": "[FEED REQUIRED]"},
        "levels": [{"kind": "overnight_high", "price": 7520.0}, {"kind": "call_wall", "price": 7600.0}],
    }
    report = build_morning_registry(
        structured=structured,
        options_feed={"error": "ATM quote missing", "call_contracts": 2, "put_contracts": 2},
        flow={}, overnight_meta={}, provider_flags={"massive": True},
    ).report()
    assert report["points"]["overnight_high"]["value"] == 7520.0
    assert report["points"]["expected_move_one_sigma"]["reason"] == "ATM quote missing"
    assert report["points"]["provider_massive_configured"]["value"] is True
