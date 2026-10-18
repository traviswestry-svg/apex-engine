# APEX Scanner Entry-Point Gate & QuantData Request Validation Closure

Based on apex-engine-main(20261018-130229).zip. Apply only the included files on top of that baseline. Version 69.10.37 unchanged. No broker execution changes.

- `run_scan_once` refuses CLOSED or unrecognized sessions before emitting an ATTEMPT, including forced invocations. It records source in paired diagnostic scan trace. No diagnostic override is enabled.
- `/api/run` rejects CLOSED sessions with HTTP 409 and an explicit reason. Existing authorized eligible-session calls continue.
- QuantData consolidated order-flow `size` is bounded to inclusive 1..100 in the provider adapter, not only at the HTTP route. Invalid sizes fall back to 50.
- Overnight remains eligible under existing session policy, including Sunday after 18:00 ET.

**Limitations:** The existing persistent journal v1 cannot store scan source or correlate attempts individually. The paired diagnostic trace has source; extending the journal needs a separate backwards-compatible schema migration. The scheduler may still wake during CLOSED sessions, but cannot execute full scans through this central function. No new authentication controls are introduced on `/api/run`; assess authorization separately. Full CI and production validation required.
