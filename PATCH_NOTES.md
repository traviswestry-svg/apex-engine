# APEX October 19 scanner runtime integration candidate

Base: apex-engine-main(20261019-185049).zip. Preserve canonical release 69.10.37.

Changes: latest persisted COMPLETED journal event independently of latest ATTEMPT; completion-only fallback when heartbeat stale; reserve next full-scan duration and 120s estimated optional flow learning; cap scheduler sleep by completion deadline. No new threads or database writers.

Validation: 37 focused tests passed; Python compilation passed. Full CI and live validation not run. Advisory/observation only.
