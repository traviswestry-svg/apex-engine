# APEX 16.4 Implementation Report

## Release
APEX 16.4 — Explainable Intelligence Assistant, built from the completed APEX 16.3 repository.

## Purpose
Provide deterministic, evidence-grounded answers to operational questions without using unrestricted generative inference or changing live trading outputs.

## New engine
`engine/explainable_intelligence_assistant.py`

Supported intents:
- WHY_CONFIDENCE
- WHY_ACTION
- WHAT_CHANGED
- WHY_INVALIDATED
- SIMILAR_SESSIONS
- EVIDENCE_SUMMARY

## Capabilities
- Intent classification using bounded deterministic rules.
- Mission Control evidence extraction across confluence, order flow, market state, playbook, Trade Director, adaptive management, and risk.
- Traceable evidence citations with stable evidence IDs.
- Snapshot-to-snapshot change detection.
- Descriptive similar-session presentation.
- Explicit `Evidence Not Available` fallback.
- Immutable explanation interaction records.

## APIs
- `GET /api/explainable-intelligence/status`
- `POST /api/explainable-intelligence/ask`
- `POST /api/explainable-intelligence/record`
- `GET /api/explainable-intelligence/history`

## Mission Control
The Mission Control page now includes an Explainable Intelligence Assistant panel with evidence-backed answers and evidence details.

## Safety
No recommendation, confidence, position, risk, stop, target, order, or broker mutation. No future information and no automatic production effect.
