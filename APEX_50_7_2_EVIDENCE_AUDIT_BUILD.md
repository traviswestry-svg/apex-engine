# APEX 50.7.2 — Evidence Audit & Recap Semantics

## Scope
- Adds a read-only production evidence audit for HLCE/LTPE + Morning/Evening report archives.
- Renames Evening Recap `Tests` to `Bar Touches` to prevent confusion with historical sample size.
- Does **not** alter forecast scoring, transition probabilities, trading, risk, broker, or collection logic.

## Endpoint
`GET /api/level-calibration/evidence-audit`

The endpoint opens SQLite stores in URI `mode=ro`, performs no schema creation/migration, and returns table counts, session coverage, oldest/newest records, basic integrity checks, and explicit data semantics.

## Evidence semantics
Evening Recap `Bar Touches` = number of regular-session bars intersecting a level tolerance zone in that one session.
Historical LTPE sample size = `level_transition_statistics.sample_count`, derived from persisted `level_transition_observations` only.
