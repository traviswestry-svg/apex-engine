# APEX 50.4.2.3 — Analytics Type Integrity Hotfix

Restores the APEX 50.2 deterministic level-analytics enrichment that was accidentally removed when `daily_key_levels.py` was replaced during the formatting hotfix.

## Corrections

- Restores numeric `strength`, `reaction_prob`, `break_prob`, `reversal_prob`, and `magnet` values before ranking.
- Keeps structured analytics numeric or `null`; `[FEED REQUIRED]` is now presentation-only for those fields.
- Makes ranking resistant to categorical strings and other nonnumeric values.
- Preserves safe formatting for categorical values such as `HIGH` and `neutral_gamma`.
- Updates the Morning Brief version to `50.4.2.3_ANALYTICS_TYPE_INTEGRITY_HOTFIX`.

Do not upload `__pycache__` or `.pyc` files.
