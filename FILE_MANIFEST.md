# APEX 25.3 — FILE MANIFEST

Extract directly into the repository root (repo-relative paths preserved).
Apply on top of a repository that already contains the 25.2 delta.

## NEW
- engine/adaptive_confidence_calibration_v253.py
- engine/adaptive_confidence_calibration_v253_routes.py
- tests/test_adaptive_confidence_calibration_v253.py
- tests/test_adaptive_confidence_calibration_v253_routes.py

## MODIFIED
- app.py                                  (adds 25.3 import + registration; cumulative through 25.3)
- engine/configuration_governance.py      (registers 2 calibration feature flags; cumulative)

## REMOVED
- (none) — see REMOVED.txt
