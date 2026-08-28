# APEX 69.6.1 — Futures Trade Diagnostic Freshness & Non-Ingesting Entitlement Probe Closure

Adds `GET /api/tick-momentum/probe`, an explicit bounded provider-access probe that may run outside RTH solely to refresh secret-safe HTTP and entitlement diagnostics.

The probe never normalizes provider trades, never calls the tick-momentum transaction processor, never advances cursors, never persists tick-momentum state, and never writes snapshots. It has no trade-decision or execution authority and reports `evidence_ingestion_permitted=false` and `production_effect=NONE`.

The existing scanner-owned RTH-only evidence-ingestion path is unchanged.
