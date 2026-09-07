# APEX 67.0.0 — Canonical Persistence Layer

Introduces `engine/canonical_persistence.py` as the standard SQLite connection
policy for APEX-owned databases.

## Standardized behavior
- configurable connect timeout
- configurable SQLite busy timeout
- WAL journaling for writable file-backed databases
- configurable synchronous mode (default NORMAL)
- foreign-key enforcement
- `sqlite3.Row` access by default
- explicit connection lifecycle
- atomic transaction helper with rollback
- non-mutating diagnostics
- integration with existing corruption quarantine (`db_resilience.py`)

## Initial migrations
- governed evidence pipeline
- institutional governance
- Trade Director learning
- Historical Level Calibration Engine (read/write paths)

This is intentionally a staged migration. Legacy stores continue to function
unchanged until individually moved behind the canonical layer and regression-tested.

## Authority
Persistence standardization has no decision or execution authority.
