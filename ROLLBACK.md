# APEX 26.6-26.10 — ROLLBACK

Additive and advisory-only; low-risk.

## Full rollback
1. Delete the new engine files (trade_story_v266, broker_intelligence_v267,
   execution_review_v268, command_center_v269, execution_suite_v26x_part2_routes)
   and tests/test_execution_suite_v26x_part2.py.
2. Revert `app.py` to its 26.1-26.5 revision.
3. Restart the app.

## Note on fail-loud registration
`app.py` registers part 2 as required and fail-loud. Remove the engine files and
the app.py block together, or boot will raise a clear RuntimeError.

## Data
No database or schema changes; nothing to clean up. No broker credentials or
execution behavior are affected by removing these advisory engines.
