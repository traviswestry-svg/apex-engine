# APEX 47.0.6 — Evidence Pipeline Trace & Canonical Version Enforcement

## Added
- End-to-end read-only evidence pipeline trace.
- Operations Center Evidence Pipeline tab and lifecycle cards.
- First-blocker identification and per-stage counts.
- Canonical release-version enforcement across `/api/version`, `/api/release-manifest`, `/api/system/version`, and `/api/system/release`.
- Legacy version fields preserved under explicit `legacy_*` names.
- New endpoint: `GET /api/evidence-pipeline/trace`.

## Guardrails
- Read-only diagnostics.
- No trade-decision changes.
- No inferred or fabricated outcomes.
- No execution authority.
