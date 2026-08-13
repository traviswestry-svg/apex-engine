# APEX Trade Director Phase 25 — Institutional Shadow Validation & Promotion Pipeline

Phase 25 evaluates Phase 24 policy proposals against archived Phase 22 outcomes. It computes baseline-versus-shadow expectancy, win-rate change, bounded tail risk, evidence sufficiency, and promotion gates.

## Safety
- No automatic promotion
- No live policy mutation
- No broker or provider access
- Human approval and rollback remain mandatory
- Phase 20 authorization and Phase 21 management remain authoritative

## API
- `GET /api/position/shadow-validation`
- `POST /api/position/shadow-validation` with `action=EVALUATE_TRIAL`
