# APEX 18.0 — Deployment and Rollback

## Deployment
1. Back up the current Render deployment and database.
2. Deploy the complete repository or apply the changed-files package.
3. Allow the application to create the new adaptive tables on first status/API access.
4. Verify `/api/adaptive-intelligence/status` returns `READY`.
5. Verify the Trading Desk displays the Adaptive Intelligence Center.
6. Keep all broker execution environment flags unchanged and disabled unless manually used through existing confirmation gates.

## Initial operating state
The system will correctly show `COLLECTING` until validated sessions and outcomes are recorded. Confidence calibration requires at least 30 validated binary outcomes. Playbooks require at least 10 graded trades to become eligible for adaptive ranking.

## Rollback
Restore the APEX 17.1 repository. The new adaptive database tables are additive and may remain without affecting 17.1. Do not delete production history unless a separate reviewed migration is approved.
