# APEX 23.1 Deployment and Rollback

Deploy the complete repository using the existing Render build/start configuration. No new environment variables or database migration are required.

Validate `/health`, `/api/regime-intelligence/status`, `/api/trading-brain/status`, and `/api/mission-control-v2/status` after deployment.

Rollback by redeploying the prior APEX 23.0 repository. APEX 23.1 introduces no persistent schema changes, so rollback is code-only.
