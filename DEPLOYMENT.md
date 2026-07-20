# APEX 25.3 — DEPLOYMENT

## Prerequisites
- APEX 25.0, 25.1, and 25.2 already deployed. The 25.3 app.py is cumulative
  through 25.3 and expects the 25.2 blocks already present.

## Steps
1. Extract `APEX_25_3_DELTA.zip` into the repository root (paths preserved).
2. Leave `APEX_CALIBRATION_PRODUCTION_ENABLED` and
   `APEX_CALIBRATION_PROMOTION_APPROVED` unset/false. Calibration stays shadow.
3. Restart the app / Gunicorn. Expect on boot:
   `APEX 25.3 Adaptive Confidence Calibration routes registered (6 canonical
   routes verified, shadow-mode).`
4. Verify `GET /api/confidence-calibration/status` -> `shadow_mode: true`,
   `production_effect: "NONE"`.

## Post-deploy checks
- `/api/confidence-calibration/current` returns the six confidence layers with
  `final_calibrated_confidence <= integrity_ceiling`.
- `/api/confidence-calibration/drift` and `/curve` respond 200.
- No new scanner process; existing endpoints unaffected.

## Promotion (later, deliberate)
Do NOT enable calibrated production confidence until the promotion panel reports
READY on live data AND you set both flags. Nothing self-promotes.
