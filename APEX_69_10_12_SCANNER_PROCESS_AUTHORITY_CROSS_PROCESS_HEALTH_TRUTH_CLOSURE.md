# APEX 69.10.12 — Scanner Process Authority & Cross-Process Health Truth Closure

## Source-verified problem
Production scanning is owned by `scanner_worker.py`, while `/health` is normally served by a separate Flask/Gunicorn process. The 69.10.7 completion counters are process-local. 69.10.11 production evidence showed scanner-process activity while web-process-local completion telemetry could remain `NOT_RUN`.

The prior resolver selected `SCANNER_PROCESS_HEARTBEAT` only after a fresh heartbeat also reported `scanner_started=true`. During a fresh STARTING/not-yet-started transition it fell back to web-local state, creating an avoidable authority ambiguity.

## Closure
69.10.12 makes heartbeat freshness—not a positive started flag—the cross-process authority criterion. A fresh scanner heartbeat is authoritative for both positive and negative scanner lifecycle facts. Web-local state is used only when the scanner heartbeat is stale or unavailable.

`/health` now consumes scanner-process completion, scan-in-progress, and scan-started-at state when process authority is available, and exposes explicit authority, process phase, and process PID diagnostics.

## Preserved boundaries
No scanner cadence, scan logic, market/session rules, flow learning, decision logic, calibration, risk, broker, or execution authority changes. Stale/missing heartbeats do not prove scanner health. Closed/scheduled-idle semantics remain unchanged.
