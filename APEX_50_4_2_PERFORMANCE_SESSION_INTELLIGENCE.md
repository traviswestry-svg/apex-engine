# APEX 50.4.2 — Performance & Session Intelligence

## Purpose
Reduce Morning Brief blocking latency, prevent stale pre-market language after the open, and make uncertain gamma data explicitly non-directional.

## Changed files
- `app.py`
- `engine/morning_brief.py`
- `engine/morning_brief_validation.py`
- `engine/session_intelligence.py`
- `engine/version.py`
- `templates/execution_os.html`
- regression tests

## Main changes

### Session-aware brief modes
Central Eastern-time classification now identifies PREMARKET, OPENING_DRIVE, MID_MORNING, LUNCH, AFTERNOON, POWER_HOUR, AFTER_HOURS, OVERNIGHT, and WEEKEND. Brief generation routes these states into PREMARKET, LIVE_SESSION, AFTER_CLOSE, or NEXT_SESSION_PREP narrative modes.

### Narrative caching
A normal `?refresh=1` rebuilds deterministic market structure without automatically paying the full AI latency again. Use `?refresh=1&refresh_narrative=1` only when a new narrative is required.

### Bounded AI latency
`APEX_BRIEF_AI_TIMEOUT_SECONDS` defaults to 18 seconds and is bounded between 5 and 45 seconds. On timeout/error, deterministic Sections 15–17 remain available.

### Detailed performance timing
The response and validation snapshot now distinguish deterministic generation, prompt construction, AI call, assembly, providers, Expected Move, profile history, and total duration.

### Gamma semantics
When dealer gamma regime is unknown:
- confidence is 0.0
- status is UNCONFIRMED
- directional logic is disabled
- gamma flip is labeled as a reported zero-gamma reference rather than confirmed directional evidence

### Dashboard operations banner
The Morning Brief card displays session, brief mode, provider health, data quality, latency, and narrative source/status.

## Recommended Render environment variable
`APEX_BRIEF_AI_TIMEOUT_SECONDS=18`

## Deployment checks
1. `/api/morning-brief?refresh=1`
2. `/api/morning-brief/validation`
3. To deliberately refresh narrative: `/api/morning-brief?refresh=1&refresh_narrative=1`

Expected normal refresh after the first narrative is cached: deterministic refresh in a few seconds, with `narrative_source: cache`.
