# APEX 69.10.12 Build Report

Build: **Scanner Process Authority & Cross-Process Health Truth Closure**

Authoritative baseline was reconstructed as 69.10.11 from the latest full 69.10.4 repository plus the canonical 69.10.5 through 69.10.11 changed-file overlays, including the 69.10.9 configuration-governance CI fix.

The implementation is narrowly observational. It makes fresh durable scanner-process heartbeat state authoritative across the web/scanner process boundary and removes the prior requirement that `scanner_started` already be true before the heartbeat can own truth.

Validation results are recorded at delivery after tests, compile, and architecture checks.

## Validation
- Focused scanner authority/lifecycle set: 17 passed.
- Complete APEX 69.10.x + consolidation regression set: 83 passed.
- Architecture Integrity tests: 3 passed.
- Python compile: 732 files, 0 errors.
- Architecture Integrity snapshot: HEALTHY; apex_version 69.10.12; registry_version 69.10.12; identity_aligned true; capability_count 62.
- No new environment variables were introduced.
- Runtime production closure is not claimed until a MARKET_OPEN deployment proves `/health` consumes scanner-process completion truth consistently.
