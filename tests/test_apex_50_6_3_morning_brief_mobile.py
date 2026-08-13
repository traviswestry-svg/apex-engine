from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "templates" / "execution_os.html"
BRIEF = ROOT / "engine" / "morning_brief.py"


def test_5063_uses_structured_mobile_brief_renderer():
    html = TEMPLATE.read_text(encoding="utf-8")
    assert "Next Institutional Levels" in html
    assert "Monday Live Levels — Awaiting Session Data" in html
    assert "renderPath(path)" in html
    assert "/api/level-calibration/transitions/path?direction=UP&max_steps=6" in html
    assert 'id="briefBody" class="brief-content"' in html


def test_5063_narrative_failure_is_sanitized_and_collapsible():
    html = TEMPLATE.read_text(encoding="utf-8")
    assert "sanitizeNarrativeError" in html
    assert "AI narrative unavailable." in html
    assert "Full report & diagnostics" in html
    assert "Technical timeout details" not in html


def test_5063_restores_mobile_sources_and_gamma_presentation():
    html = TEMPLATE.read_text(encoding="utf-8")
    assert 'id="briefSources"' in html
    assert "renderBriefSources" in html
    assert ".gamma-long" in html
    assert ".gamma-neutral" in html
    assert ".gamma-short" in html
    assert "Long Gamma" in html


def test_5063_default_narrative_timeout_is_reduced_but_configurable():
    text = BRIEF.read_text(encoding="utf-8")
    assert 'APEX_BRIEF_AI_TIMEOUT_SECONDS", "10"' in text
    assert "narrative_error" in text
    assert "Technical failure details are available in diagnostics" in text
