# APEX 50.7.1.1 — Dashboard Loading Hardening

## Production symptom
`/apex_os` returned HTTP 200 and all primary institutional APIs completed, but the mobile browser continued to show the page as loading.

## Root cause
The homepage started two heavyweight supporting requests during initial render even though their UI lived inside a collapsed `<details>` panel:

- `GET /api/mission-control-v2/status`
- `GET /api/market-memory/status`

The Render request log showed successful completion of `/api/institutional-workspace/status` and the other homepage APIs, but no completed response for these two requests. The Institutional Workspace renderer also coupled Mission Control to the workspace request through `Promise.all`, allowing the heavyweight request to hold the supporting UI in its warming/loading state.

## Repair
- Initial Institutional Workspace rendering now depends only on `/api/institutional-workspace/status`.
- Mission Control and Market Memory are lazy-loaded only when `Supporting intelligence and system context` is expanded.
- Mission Control receives a 4.5-second AbortController timeout.
- Market Memory receives a 3.5-second AbortController timeout.
- Lazy requests use `Promise.allSettled`, so one component cannot block the other.
- Timeout/error states render explicitly as `TIMEOUT` or `UNAVAILABLE`.
- Until expanded, Mission Control displays `ON DEMAND` and uses the already-loaded execution plan for its lightweight execution summary.

## Safety
No trading, risk, broker, signal, LTPE, Morning Brief, archive, or market-data calculations were changed.

## Validation
- Target inline JavaScript syntax: PASS (`node --check`)
- Repository Python compilation: PASS (`python -m py_compile app.py engine/*.py`)
- Static frontend hardening assertions: PASS
- Python pytest suite could not be executed in the artifact environment because Flask is not installed in that local interpreter (`ModuleNotFoundError: flask`). No Python application code was modified by this build.
