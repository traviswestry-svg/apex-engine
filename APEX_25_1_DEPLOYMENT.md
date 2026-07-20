# APEX 25.1 Delta Deployment

1. Extract this ZIP at the repository root.
2. Allow the included paths to overwrite matching files.
3. Commit and push to GitHub.
4. Deploy through the existing Render service.
5. Verify:
   - `GET /api/institutional-reasoning/status`
   - `GET /api/institutional-reasoning/current`
   - Mission Control includes `INSTITUTIONAL_REASONING`.

No database migration or new environment variable is required.
