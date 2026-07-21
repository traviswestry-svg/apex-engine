# APEX dashboard request-stagger fix

Replace:
- `app.py`
- `static/js/apex_os.js`

Why: the browser was launching roughly ten API calls simultaneously against a one-worker/four-thread Render service. Even though `/api/institutional_os` is cache-only, it was queued behind slower calls and the browser aborted it after 12 seconds.

Changes:
- Institutional OS loads first.
- Remaining panels are staggered over 11 seconds.
- Recurring polls are offset so they do not synchronize.
- Mission Control polling reduced from every 5 seconds to every 15 seconds.
- Static asset version bumped to `_ios_bg4`.

Deploy with Clear build cache & deploy, then clear site data once in the regular browser.
