# APEX 69.7.1 — Universal Trade Trigger Observation & Manual E*TRADE Handoff

APEX now records every genuine trade trigger it receives, including confirmed,
blocked, abstained, and ignored triggers. Observation is independent of whether
the operator chooses to trade.

## Captured trigger sources

- TradingView/Pine CALL, PUT, and EXIT signals
- Canonical APEX entry decisions
- Failed Breakdown `ENTRY_ELIGIBLE` lifecycle events

Each source event receives a stable, duplicate-safe trigger identity and a
durable chronology record. Directional triggers with an underlying entry price
are observed for five minutes. APEX stores price samples, maximum favorable
excursion, maximum adverse excursion, terminal status, and outcome label.

## Power E*TRADE workflow

Each entry trigger includes a manual handoff contract for SPXW 0DTE trading:

- CALL or PUT direction
- underlying entry, stop, and target references when supplied
- live option-chain selection required
- 1–3 contract sizing guidance
- five-minute maximum hold
- configured per-trade, daily-loss, and daily-trade limits

APEX does not select a live option contract, submit an order, mutate a broker
account, or claim execution authority. Power E*TRADE order preview and explicit
human confirmation remain required.

## API

- `GET /api/triggers/capability`
- `GET /api/triggers/history`

The existing signal and canonical-decision paths populate the observatory
automatically. Observation failures are fail-soft and do not change the trade
decision or execution boundary.

