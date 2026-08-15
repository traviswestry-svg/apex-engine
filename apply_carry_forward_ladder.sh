#!/usr/bin/env bash
# APEX 66.6.0 — Carry-Forward Levels Ladder. Copies all 6 files into your repo
# in one step and verifies each landed + is wired. A partial merge (the failure
# mode that broke earlier releases) is impossible: if anything is missing it
# exits non-zero and names it.
# Usage: ./apply_carry_forward_ladder.sh /path/to/apex-engine
set -euo pipefail
DEST="${1:?Usage: ./apply_carry_forward_ladder.sh /path/to/apex-engine}"
SRC="$(cd "$(dirname "$0")/files" && pwd)"
FILES=(
  "engine/carry_forward_ladder.py"
  "engine/carry_forward_ladder_routes.py"
  "app.py"
  "templates/apex_os.html"
  "static/js/apex_os.js"
  "tests/test_carry_forward_ladder.py"
)
for f in "${FILES[@]}"; do mkdir -p "$DEST/$(dirname "$f")"; cp "$SRC/$f" "$DEST/$f"; echo "  copied  $f"; done
miss=0; for f in "${FILES[@]}"; do [ -f "$DEST/$f" ] || { echo "  MISSING $f"; miss=1; }; done
[ "$miss" -eq 0 ] || { echo "ERROR: files missing after copy."; exit 1; }
echo "Verifying wiring..."
grep -q "register_carry_forward_ladder_routes" "$DEST/app.py"           || { echo "ERROR: app.py not wired (import/registration)."; exit 1; }
grep -q "APEX 66.6.0 Carry-Forward Ladder routes registered" "$DEST/app.py" || { echo "ERROR: app.py registration block missing."; exit 1; }
grep -q 'data-tab="levels"' "$DEST/templates/apex_os.html"              || { echo "ERROR: Levels tab button missing from template."; exit 1; }
grep -q 'id="tab-levels"' "$DEST/templates/apex_os.html"                || { echo "ERROR: Levels pane missing from template."; exit 1; }
grep -q "loadCarryForwardLadder" "$DEST/static/js/apex_os.js"           || { echo "ERROR: JS loader missing."; exit 1; }
echo ""
echo "OK — all 6 files present and wired."
echo "Bump the apex_os asset cache-buster if you want browsers to reload the JS/CSS immediately."
echo "Then run:  python -m pytest -q tests/test_carry_forward_ladder.py tests/test_consolidation_guard.py"
