# APEX 69.10.41 — Canonical Paper Decision Binding & Durable Ledger Activation

Candidate patch, **not production-certified**. Adds an explicit idempotent SQLite ledger initializer, a transactionally bound canonical observation method requiring a server-injected trusted persistence reader, exact contract matching, immutable evidence digests, a read-only ledger-health endpoint, and regression tests. No POST route is added for initializing or binding observations. There is **no live adapter to the real canonical decision persistence schema yet**; integration must supply `trusted_reader` strictly from the server's existing persisted canonical decision store. This build does **not** authorize dispatch or infer broker fills.

Initialize from an operator-controlled migration/startup step using `initialize_ledger()` with `APEX_TRADERSPOST_LEDGER_DB` pointing to an existing persistent disk directory (normally `/data`). Verify filesystem persistence after service restart. `GET /api/paper/traderspost/ledger-health` reads the state without creating any files.

Outstanding work: implement/test a concrete canonical decision store reader, prove decision-time provenance and authorized risk, add authenticated broker execution evidence, reconcile positions/partial fills, enforce verified daily realized losses, run full CI and check deployment restart persistence. All these remain blockers for unattended paper trades.

Rollback: remove the changed route and code additions and restore release metadata from the previous version; preserve the SQLite file for forensic audit.
