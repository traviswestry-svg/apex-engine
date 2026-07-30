from engine.daily_key_levels import KeyLevel, LevelKind, LevelSource
from engine.level_analytics import enrich_level_analytics
from engine.profile_history import save_profile, load_profile_context


def test_level_analytics_fill_internal_fields():
    level = KeyLevel(LevelKind.PDH, 7420.0, LevelSource.POLYGON, label="PDH")
    enrich_level_analytics(7410.0, [level])
    assert 0 < level.strength_score <= 1
    assert 0 < level.reaction_prob <= 1
    assert 0 < level.break_prob <= 1
    assert 0 < level.reversal_prob <= 1
    assert 0 < level.magnet_score <= 1


def test_profile_context_empty_is_safe(monkeypatch, tmp_path):
    import engine.profile_history as ph
    monkeypatch.setattr(ph, "DB_PATH", str(tmp_path / "profile.db"))
    assert load_profile_context("SPX", "2026-07-30") == {}
    save_profile("2026-07-29", "SPX", {"levels": {"poc": 7400, "vah": 7420, "val": 7380}})
    ctx = load_profile_context("SPX", "2026-07-30")
    assert ctx["prev_poc"] == 7400
    assert ctx["comp_poc"] == 7400
