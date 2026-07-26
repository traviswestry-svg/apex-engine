# APEX 40 — Institutional Workspace System

## Purpose
Unify APEX's independent dashboards into one navigation and workflow shell without rewriting or coupling their analytical internals.

## Delivered
- Persistent collapsible left sidebar across dashboard HTML responses.
- Grouped navigation: Command, Trading, Intelligence, Learning, Operations.
- Workflow shortcuts: Find Trade, Execute, Manage, Review.
- Global command palette opened with Ctrl/Cmd+K.
- Search across dashboard pages and tools.
- Browser-persisted favorites using localStorage.
- Breadcrumb context and active-page highlighting.
- Responsive mobile drawer behavior.
- Print-safe shell suppression.
- API, health, webhook, and static responses excluded from HTML decoration.

## Architecture
The shell is injected through a Flask `after_request` hook for HTML dashboard routes. This preserves every existing template and route implementation while making the navigation available across current and future dashboards.

## Changed files
- `app.py`
- `static/css/apex_workspace.css`
- `static/js/apex_workspace.js`
- `tests/test_apex40_workspace_static.py`

## Validation
- Python compilation: PASS
- JavaScript syntax (`node --check`): PASS
- APEX 40 static integration tests: 3 PASS
- Navigation registry route coverage: PASS

## Deployment
Upload the files while preserving paths, commit to GitHub, then deploy through Render. No new environment variables or database migrations are required.
