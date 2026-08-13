# APEX 10.0.2 Deployment Checklist

## Before deployment

1. Ensure the working tree is clean: `git status`.
2. Check the patch: `git apply --check apex-10.0.2-release-manager.patch`.
3. Apply it: `git apply apex-10.0.2-release-manager.patch`.
4. Run tests: `pytest -q`.
5. Commit and push to the Render-connected branch.

## After deployment

Verify:

```text
/health
/api/system/readiness
/api/system/release
/api/system/version
/api/system/build
/api/system/features
/api/system/migrations
```

Expected application version:

```text
10.0.2_RELEASE_MANAGER
```

## Rollback

Preferred rollback:

```bash
git revert <release-commit-sha>
git push origin main
```

Before committing, a locally applied patch can be reversed with:

```bash
git apply -R apex-10.0.2-release-manager.patch
```
