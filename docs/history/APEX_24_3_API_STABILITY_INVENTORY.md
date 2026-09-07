# APEX 24.3 — /api/research/* API Stability Inventory

Produced per the API Stability Policy before changing any existing endpoint.

## 1. Pre-change route inventory (research)

Existing `/api/research/*` routes served by `institutional_roadmap_routes.py`:
`/status`, `/clusters`, `/findings`, `/findings/<id>`, `/generate`,
`/comparisons`, `/runs`, `/similarity`, `/similarity/<id>`, `/vector` (and vector
variants). These implement the research-findings / similarity capability, a
different concern from the Strategy Research Laboratory.

## 2. Consumers identified

- `/api/research/status` was a combined status of governed research +
  similarity + research findings.
- Frontend/templates/JavaScript: no `/api/research/*` consumers found under
  `static/` or `templates/`.

## 3. Changes and compatibility

- `/api/research/status` is now owned by the canonical APEX 24.3 registrar. It
  merges the pre-existing payload (`gov.research_status()`,
  `institutional_similarity.status()`, `institutional_research.status()`) via an
  injected `legacy_status_provider`, then overlays the research-lab status. All
  previously returned fields are preserved (verified: `institutional_research`
  and `institutional_similarity` keys still present).
- New routes `/strategies`, `/performance`, `/experiments` (+ supporting POSTs)
  are additive.
- All other research routes are unchanged.

## 4. Breaking changes

None. The `/status` payload is a superset of the previous one. The only
structural change is that the status route moved from the roadmap registrar to
the canonical 24.3 registrar, with its legacy content preserved via the provider.
