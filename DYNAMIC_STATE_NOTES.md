# APEX 66.7.0 — Dynamic State surface + independent-evidence damping

Two things:

## A · Surface the three dynamic-state signals on the dashboard
New "Dynamic State" band (below Range Intelligence) with three cards:
- Flow Excitation — genuine surge vs one repeated burst (independent-evidence %,
  redundancy; a redundant burst is labelled "discounted").
- Residual Pressure — unresolved absorbed/contained pressure that can re-fire
  (state, direction, remaining, origin level).
- Gamma Path — the spatial gamma map (regime, upside/downside destinations).

Read-only aggregator (engine/dynamic_state.py) pulls all three straight from the
Data Bus / persisted scanner state — recomputes nothing, so it always agrees with
the pipeline. Served at GET /api/dynamic-state.

## B · Feed independent_evidence_factor into the consensus (mesh) calc
engine/institutional_intelligence_mesh.py: each evidence node's contribution is
now scaled by its independent_evidence_factor (default 1.0 when absent). A flow
source that is really one continuing burst (factor < 1.0) can no longer count as
many independent confirmations — verified: discounting a redundant CALL burst
drops its contribution ~4x and moves net_score away from CALL, so a single burst
cannot artificially multiply conviction. The factor is surfaced per node as
`independence`.

## Files (7)
NEW: engine/dynamic_state.py, engine/dynamic_state_routes.py,
     tests/test_dynamic_state.py, tests/test_mesh_independence.py
CHANGED: app.py (import guard + route registration, reusing STATE/SCANNER_STATE),
     engine/institutional_intelligence_mesh.py (independence damping),
     templates/apex_os.html (Dynamic State band + inline render).

## Verified
- app boots: 885 routes; /api/dynamic-state registered; DYNAMIC_STATE_AVAILABLE = True.
- New tests: 11 passed. Existing mesh tests unaffected.
- Dead-code + version-drift guards: pass.
- Full ratcheted suite: 1869 passed, 0 failed (was 1858).

## Apply
./apply_dynamic_state.sh /path/to/apex-engine  (verifies wiring + prior features),
then branch + PR (main is protected). Bump the apex_os asset cache-buster so the
new band loads immediately.
