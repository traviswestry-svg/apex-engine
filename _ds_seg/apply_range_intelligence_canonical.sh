#!/usr/bin/env bash
# APEX — Range Intelligence canonical-context correction. Copies 6 files in one
# step and verifies each landed + is wired + prior features preserved. Fails
# loudly on any partial merge.
# Usage: ./apply_range_intelligence_canonical.sh /path/to/apex-engine
set -euo pipefail
DEST="${1:?Usage: ./apply_range_intelligence_canonical.sh /path/to/apex-engine}"
SRC="$(cd "$(dirname "$0")/files" && pwd)"
FILES=(
  "app.py"
  "engine/range_intelligence.py"
  "engine/range_routes.py"
  "templates/apex_os.html"
  "tests/test_range_intelligence.py"
  "tests/test_range_intelligence_canonical.py"
)
for f in "${FILES[@]}"; do mkdir -p "$DEST/$(dirname "$f")"; cp "$SRC/$f" "$DEST/$f"; echo "  copied  $f"; done
miss=0; for f in "${FILES[@]}"; do [ -f "$DEST/$f" ] || { echo "  MISSING $f"; miss=1; }; done
[ "$miss" -eq 0 ] || { echo "ERROR: files missing after copy."; exit 1; }
echo "Verifying wiring..."
grep -q "canonical_provider" "$DEST/engine/range_routes.py"                 || { echo "ERROR: route not updated (canonical_provider)."; exit 1; }
grep -q "canonical_provider=_ri_canonical" "$DEST/app.py"                   || { echo "ERROR: app.py not wired to canonical/runtime providers."; exit 1; }
grep -q "expected_session_range" "$DEST/engine/range_intelligence.py"       || { echo "ERROR: engine missing the four-section output."; exit 1; }
grep -q "riEsr" "$DEST/templates/apex_os.html"                             || { echo "ERROR: template not updated to four sections."; exit 1; }
# guard against full-file app.py reverting prior merged features:
grep -q "carry_forward_ladder" "$DEST/app.py"  || { echo "REVERT RISK: carry_forward_ladder missing from app.py — STOP"; exit 1; }
grep -q "build_flow_tape" "$DEST/app.py"       || { echo "REVERT RISK: flow_tape/large-order missing from app.py — STOP"; exit 1; }
grep -q "breadth_regime" "$DEST/app.py"        || { echo "REVERT RISK: breadth_regime missing from app.py — STOP"; exit 1; }
grep -q "flow_excitation" "$DEST/app.py" || grep -q "residual_pressure" "$DEST/app.py" || echo "NOTE: dynamic-state refs not found in app.py — confirm 66.4 is merged."
python -c "import ast; [ast.parse(open(f).read()) for f in ['app.py','engine/range_intelligence.py','engine/range_routes.py']]" && echo "PY SYNTAX OK"
echo ""
echo "OK — all 6 files present and wired."
echo "Then run:  python -m pytest -q tests/test_range_intelligence_canonical.py tests/test_range_intelligence.py tests/test_consolidation_guard.py"
