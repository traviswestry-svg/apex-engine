# APEX 19.0 Implementation Report

## Release
- Name: APEX 19.0 — Institutional Intelligence Engine
- Runtime: `12.0.0_INSTITUTIONAL_INTELLIGENCE_ENGINE`
- Baseline: APEX 18.0.5 complete repository

## Delivered
- Added a deterministic, read-only institutional intelligence synthesis engine.
- Added volume-transition classification with `GREEN` active levels, `RED` stalled levels, and neutral balance levels.
- Added expected-move bands and move-consumption context using existing chain/state inputs.
- Added overnight range location using ONH/ONL and prior-day references.
- Added weighted synthesis of auction, volume profile, dealer positioning, flow, overnight structure, and legacy consensus.
- Added fail-closed intelligence eligibility when data is stale or evidence coverage is insufficient.
- Added four read-only APIs and a compact Mission Control panel.
- Preserved all existing trading, broker mutation, global kill-switch, and human-confirmation safeguards.

## Architecture
The engine performs no provider requests and no database writes. It consumes fields already produced by APEX and publishes `institutional_intelligence_engine` into the normal scan result. Existing intelligence objects and API fields remain intact.
