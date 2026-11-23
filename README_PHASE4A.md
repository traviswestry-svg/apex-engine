# APEX Phase 4A — Independent Render Deployment Observer (Research)

**Status:** implementation and offline tests complete. **Not deployed as an independent external collector.** `NO_GO` always. No provenance, trade, or promotion writes. This patch does not modify the Phase 3E fail-closed gate.

## Trust model

- Designed to run **outside** the APEX Render service, in a separately managed collector environment with a narrowly scoped, read-only Render API key.
- Calls only `GET https://api.render.com/v1/services/{serviceId}` and `GET https://api.render.com/v1/services/{serviceId}/deploys`. No POST/PUT/PATCH/DELETE.
- Uses TLS validation through the system's default `urllib.request` HTTPS handling.
- Captures provider-returned deploy ID, commit SHA, deployment status, trigger, and timestamp. Produces canonical SHA-256 digest for the normalized JSON evidence (digest **does not authenticate** it).
- Makes no claim to observe boot ID, PID, which executable ran for a specific decision, whether any trade was executed, or whether a receipt was produced. No signing, no checkpoint authority, no `VERIFIED`, no GO.
- For staging simulations, fixture output is marked `OFFLINE_FIXTURE_NOT_OBSERVED`. A fixture can never be used for authentication. A live response is marked `RENDER_API_READ_ONLY_RESPONSE`, and its external collector identity remains `NOT_ATTESTED` until a separately operated collector is attested.
- Incomplete pagination, duplicate deploy IDs, malformed deploy data, non-HTTPS/unapproved paths, missing credentials, API errors, ambiguous live deploy statuses, and output overwrite attempts fail safely or are explicitly labeled ambiguous. Live API errors never expose API credentials or raw HTTP bodies.
- `--out` creates a **new file only** with restrictive permissions; it will not overwrite a file or follow an existing symlink. This is not a durable append-only checkpoint store.

## Contents

- `engine/forward_provenance_render_observer.py`: restricted API reader, strict input validation, pagination, normalized report.
- `scripts/apex_forward_phase4a_observer.py`: staging fixture and live read-only command line.
- `tests/test_forward_provenance_phase4a.py`: 10 isolated tests.
- `fixtures/render_api_synthetic.json`: synthetic example; NOT Render evidence.

## Offline fixture rehearsal (safe anywhere)

```bash
PYTHONPATH=. python -m scripts.apex_forward_phase4a_observer \
  --fixture fixtures/render_api_synthetic.json \
  --service-id srv-example123

PYTHONPATH=. python -m unittest tests.test_forward_provenance_phase4a -v
```

## When an **independently operated** collector is provisioned

Provision a **read-only scoped Render API key** in the external collector's secret store; **do not** paste the key into ChatGPT, put it into command-line arguments, commit it, or put it in the APEX service. Run the observer from the independent host:

```bash
# Set RENDER_API_KEY using the external collector's secure secret injection.
PYTHONPATH=. python -m scripts.apex_forward_phase4a_observer \
  --live-render-api \
  --service-id srv-d7p3u2navr4c73d2q0jg \
  --out /external-evidence/render-observation-UNIQUE-NAME.json
```

**The output must not be treated as an externally signed attestation**. An independently authenticated collector identity, protected signer, durably retained off-host checkpoints, and process/boot observations remain unimplemented. No process identifier is available from Render's deployment listing API. The external setup requires separate operator approval and infrastructure provisioning.

## Test commands (overlay patch on complete Phase 3E checkout)

```bash
PYTHONPATH=. python -m unittest tests.test_forward_provenance_phase4a -v
PYTHONPATH=. python -m unittest \
  tests.test_forward_provenance tests.test_forward_provenance_verifier \
  tests.test_forward_provenance_phase3a tests.test_forward_provenance_phase3b \
  tests.test_forward_provenance_phase3c tests.test_forward_provenance_phase3d \
  tests.test_forward_provenance_phase3e -q
PYTHONPATH=. python -m unittest discover -s tests \
  -p 'test_apex_stage3b315_gamma_receipt_provenance_correlation.py' -q
```

## Phase 4B/4C dependencies

The next code milestone is independent identity verification and external signer design (Phase 4B), followed by durable, immutable checkpoint storage and rotation continuity (Phase 4C). Both need separately operated cloud infrastructure and scoped credentials. **Do not enable `APEX_FORWARD_PROVENANCE_ENABLED` or change production routing.** 3,569 historical decisions stay excluded from retroactive authentication. `BLOCKED_RESEARCH_ONLY` remains in force.

## Render API documentation

- https://api-docs.render.com/reference/authentication
- https://api-docs.render.com/reference/retrieve-service
- https://api-docs.render.com/reference/list-deploys
- https://api-docs.render.com/reference/pagination
