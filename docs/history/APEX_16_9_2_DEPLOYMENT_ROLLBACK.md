# APEX 16.9.2 Deployment and Rollback

## Deploy
1. Upload the complete repository to GitHub or apply the changed-files package to 16.9.1.
2. Keep `ETRADE_ENABLE_TRADING=false` during validation.
3. Deploy the latest commit in Render.
4. Hard-refresh the Trade Command Center.
5. Select an expiration, load the chain, then click **Diagnostics**.
6. Confirm OAuth and Accounts are PASS. With a loaded expiration, confirm Option Chain and Quotes are PASS.
7. Greeks may be NOT_TESTED or FAIL when the selected source does not provide them; this no longer blocks bid/ask-based structure pricing by itself.

## Rollback
Redeploy the last known-good 16.9.1 commit or restore `APEX_16_9_1_complete_repository.zip`. No destructive schema migration is introduced by this sprint.
