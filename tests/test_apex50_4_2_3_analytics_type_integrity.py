from engine.daily_key_levels import (
    DailyKeyLevels, FEED_REQUIRED, KeyLevel, LevelKind, LevelSource, _fmt
)
from engine.level_analytics import enrich_level_analytics


def test_enrichment_restores_numeric_analytics():
    levels = [KeyLevel(LevelKind.PDH, 7450.0, LevelSource.POLYGON, label="PDH")]
    enriched = enrich_level_analytics(7437.5, levels)
    payload = enriched[0].to_dict(7437.5)
    for key in ("strength", "reaction_prob", "break_prob", "reversal_prob", "magnet"):
        assert isinstance(payload[key], float), (key, payload[key])


def test_missing_analytics_serialize_as_null_not_display_text():
    level = KeyLevel(LevelKind.PREV_POC, FEED_REQUIRED, LevelSource.VOLUME_PROFILE)
    payload = level.to_dict(7437.5)
    assert payload["strength"] is None
    assert payload["reaction_prob"] is None
    assert payload["break_prob"] is None
    assert payload["reversal_prob"] is None
    assert payload["magnet"] is None
    assert payload["distance"] is None


def test_display_formatter_keeps_categorical_values_safe():
    assert _fmt("HIGH") == "HIGH"
    assert _fmt(7437.53) == "7,437.53"


def test_build_calls_level_analytics():
    source = __import__("inspect").getsource(DailyKeyLevels.build)
    assert "enrich_level_analytics" in source
