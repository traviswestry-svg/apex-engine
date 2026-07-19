# APEX 18.0.6 Deployment and Rollback

## Deployment checks

1. Deploy the complete APEX 18.0.6 repository.
2. Confirm `/api/system/version` reports `11.0.4_TRADE_REFUSAL_REPLAY`.
3. Confirm `GET /api/premium_discipline/replay` returns HTTP 200.
4. Confirm `POST /api/premium_discipline/replay/run` returns HTTP 200 after the bar provider is available.
5. Confirm the existing Premium Discipline endpoints remain healthy.

## Rollback

Redeploy the prior APEX 18.0.5 complete repository. The additive database
columns `counterfactual_metrics_json` and `replay_version` may remain; APEX
18.0.5 ignores them. No destructive database rollback is required.
