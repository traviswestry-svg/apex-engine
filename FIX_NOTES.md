# APEX 66.5.0 — Upload/Deploy Fix

## Symptom
CI failed on push (and therefore blocked the Render deploy) with:

    FAILED tests/test_apex_48_2_version.py::test_release_version_literals_agree_in_source_tree
    AssertionError: apex_capability_registry.yaml apex_version does not match the release manifest
    assert '66.4.0' == '66.5.0'

## Root cause
The 66.5.0 Breadth Regime addition bumped `config/apex_release_manifest.json`
to 66.5.0 but did not include `config/apex_capability_registry.yaml`, which
remained at 66.4.0. The repo's drift-guard test requires the two version
literals to agree, so the split-brain version failed CI before deploy.

## Fix (only file added to the changed set)
`config/apex_capability_registry.yaml`:
- `apex_version:` 66.4.0 -> 66.5.0 (satisfies the drift guard)
- `release_manifest` capability `version:` 66.4.0 -> 66.5.0 (kept in lockstep,
  matching prior-release convention)
- Registered the new `breadth_regime` capability (advisory-only,
  decision_authority: none) with its two routes, so the registry honestly
  reflects the endpoints the release ships.

No other file in the addition was changed.

## Verified
- `import app` boots: 882 routes, both /api/breadth-regime/* endpoints present,
  BREADTH_REGIME_AVAILABLE = True.
- Full pytest suite: 1832 passed, 0 failed (was 1831 passed / 1 failed).
- New tests/test_breadth_regime.py: 5 passed.
- Engine states verified: no-data/out-of-range -> DATA_LIMITED (fail-closed),
  14<-18 -> CAPITULATION, 19<-14 -> EARLY_RECOVERY, 32<-27 -> CONFIRMED_RECOVERY.
