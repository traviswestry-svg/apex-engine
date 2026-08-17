# APEX 67.3.0 — Source-Tree Hygiene CI Fix

The 67.2 architecture tests intentionally fail while historical executable source
mirrors remain in the Git working tree. Overlay ZIPs cannot represent deletions,
so the four directories survived the prior upload.

Run:

```bash
bash scripts/apply_apex_67_3_hygiene_fix.sh
```

This uses `git rm -r --ignore-unmatch` so tracked copies are staged as deletions,
removes any untracked leftovers, then runs the two affected tests.

Directories removed:
- `_check`
- `_ds_seg`
- `_loi_seg`
- `APEX_66_4_1_Decision_Coherence_Fix_Changed_Files`

Files currently present under those directories in the audited ZIP: 39.
