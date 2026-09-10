# APEX 69.10.3 — Morning Forecast & Evening Validation Integrity Closure

## Purpose
Close forecast identity, leakage, regime-validation, and expected-move metric mismatches before any forecast calibration work.

## Changes
- Official morning forecast identity now uses `target_session_date`, not source/history date.
- Only genuinely pre-outcome PREMARKET/NEXT_SESSION_PREP briefs can become official; live and after-close briefs remain revisions only.
- Morning payload freezes a structured deterministic regime projection from active trade-map evidence; ambiguous ties fail closed.
- Evening regime grading uses only the structured field. Markdown extraction remains legacy diagnostic code and has no grading authority.
- Expected-move size is compared with maximum absolute completed-session excursion from the frozen morning spot, not half the high-low range.
- New weighted continuous score supports meaningful A/B/C/D/F bands. The former binary score is retained as a non-authoritative diagnostic.
- No historical snapshots are rewritten and no historical recaps are automatically rescored.

## Guardrails
No trade-decision changes. No execution-authority changes. No fabricated prices or regimes. No post-outcome forecast promotion. No retrospective evidence mutation.
