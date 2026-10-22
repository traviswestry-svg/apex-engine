# APEX 69.10.42 — Ledger Activation, Canonical Evidence Reader and Release Truth Repair

* Initializes SQLite paper ledger at Flask route registration; fails closed and surfaces initialization error. Default path `/data/apex_traderspost_paper.sqlite3`. Ensure `/data` is mounted before starting application.
* Reads exact existing decision ID, contract and source record from `engine.evidence_pipeline` persisted `decisions` table. No caller approval, no claim that learning eligibility authorizes a trade. No route for placing bound decisions.
* Read-only ledger-health includes storage and canonical-schema connectivity; broker reconciliation and unattended dispatch remain disabled.
* Repairs reported version-pinned historical CI assertions to refer to manifest's current release. Release metadata is synchronized at 69.10.42. Test helper prevents recurrence of stale current-version pins.
* No guarantees of fills, daily loss enforcement or actual trading authorization. Audit full GitHub CI before promoting.
