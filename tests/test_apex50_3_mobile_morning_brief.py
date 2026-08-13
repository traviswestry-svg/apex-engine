from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "execution_os.html"


def test_mobile_brief_has_responsive_components():
    html = TEMPLATE.read_text(encoding="utf-8")
    assert "APEX 50.3 — mobile-first Morning Brief presentation" in html
    assert 'id="briefSources"' in html
    assert 'class="brief-content"' in html
    assert "renderBriefSources" in html


def test_raw_anthropic_error_is_sanitized_for_display():
    html = TEMPLATE.read_text(encoding="utf-8")
    assert "sanitizeNarrativeError" in html
    assert "AI narrative unavailable." in html
    assert "APEX is showing deterministic institutional levels" in html


def test_gamma_labels_are_human_readable_and_color_coded():
    html = TEMPLATE.read_text(encoding="utf-8")
    assert ".gamma-long" in html
    assert ".gamma-neutral" in html
    assert ".gamma-short" in html
    assert "replace(/neutral_gamma/g,'Neutral Gamma')" in html


def test_morning_brief_preserves_line_breaks_on_mobile():
    html = TEMPLATE.read_text(encoding="utf-8")
    assert ".brief-content p{white-space:pre-line" in html
    assert ".brief-content table{display:block;overflow-x:auto" in html
