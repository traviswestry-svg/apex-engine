# APEX 69.10.47 — Governance candidate

This ZIP is an **additive governance patch**, not a full repository replacement and not a production release.

Apply `docs/release_governance/` and `scripts/verify_cumulative_candidate_inventory.py` to your review branch. Do not modify `config/apex_release_manifest.json` or execution authority.

Offline verification:

```bash
python scripts/verify_cumulative_candidate_inventory.py --baseline "apex-engine-main(20261030-113020).zip" --candidate "apex-engine-main(20261114-103859).zip" --inventory docs/release_governance/CHANGED_FILES_69_10_47_CANDIDATE.csv --reconciliation docs/release_governance/CANDIDATE_RECONCILIATION.json
```

The source audit provided by the user references a different October 31 baseline and reports 2,801 passed/3 environment failures. The exact inventory in this package compares the available October 30 and November 14 archives.
