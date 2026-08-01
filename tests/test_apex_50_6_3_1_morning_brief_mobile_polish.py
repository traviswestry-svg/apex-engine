from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "templates" / "execution_os.html"


def test_50631_morning_brief_actions_are_compact_and_grouped():
    html = TEMPLATE.read_text(encoding="utf-8")
    assert 'class="brief-actions"' in html
    assert 'class="brief-generate"' in html
    assert 'class="brief-refresh"' in html
    assert 'aria-label="Refresh Morning Brief"' in html


def test_50631_machine_brief_mode_is_humanized():
    html = TEMPLATE.read_text(encoding="utf-8")
    assert "friendlyBriefMode" in html
    assert "NEXT_SESSION_PREP:'Next-Session Prep'" in html
    assert "briefSessionShort" in html
    assert "Weekend Prep" in html


def test_50631_archive_state_is_rendered_as_badge():
    html = TEMPLATE.read_text(encoding="utf-8")
    assert "renderArchiveBadge" in html
    assert "Official archived" in html
    assert ".brief-archive-badge.official" in html
    assert "OFFICIAL FORECAST ARCHIVED" not in html


def test_50631_mobile_status_and_narrative_are_compact():
    html = TEMPLATE.read_text(encoding="utf-8")
    assert 'class="brief-opsbar"' in html
    assert ".brief-status{padding:8px 10px" in html
    assert ".brief-meta-row{font-size:11px" in html
