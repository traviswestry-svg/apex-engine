# APEX Scanner Scheduler Continuity & Full-Scan Freshness Closure

Baseline: October 16 2026 repository, canonical release 69.10.37. Changed files only.

## Root cause
Default SCAN_INTERVAL_SECONDS=300 while HEALTH_STALE_AFTER_S=180; additionally post-scan work occurs before the interval sleep. This guarantees a stale period for otherwise successful cycles.

## Fix
Calculate next sleep as min(configured interval, max(0, stale threshold - age since last completion - 20-second margin)). Record scheduler iteration, post-cycle time, planned sleep and freshness budget exhaustion. Preserve exclusive scan lock, advisory-only status, and unchanged health stale threshold. No synthetic scan completion and no concurrent scans.

## Caveat
This cannot guarantee a new scan finishes within the freshness window if scans themselves or post-scan work take too long. Monitor `last_post_scan_duration_seconds`, `last_scheduler_sleep_seconds`, `freshness_budget_exhausted_cycles`, and completed-scan age. Increased scan frequency may increase API and compute usage. Production validation is required.

## Validation
Focused tests and syntax checks; full CI must run in GitHub Actions. No release bump.
