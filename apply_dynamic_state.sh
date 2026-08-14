#!/usr/bin/env bash
# APEX 66.7.0 — Dynamic State surface + independent-evidence damping. Copies 7
# files in one step, verifies each landed + is wired + prior features preserved.
# Usage: ./apply_dynamic_state.sh /path/to/apex-engine
set -euo pipefail
DEST="${1:?Usage: ./apply_dynamic_state.sh /path/to/apex-engine}"
SRC="$(cd "$(dirname "$0")/files" && pwd)"
FILES=(
  "app.py"
  "engine/dynamic_state.py"
  "engine/dynamic_state_routes.py"
  "engine/institutional_intelligence_mesh.py"
  "templates/apex_os.html"
  "tests/test_dynamic_state.py"
  "tests/test_mesh_independence.py"
)
for f in "${FILES[@]}"; do mkdir -p "$DEST/$(dirname "$f")"; cp "$SRC/$f" "$DEST/$f"; echo "  copied  $f"; done
miss=0; for f in "${FILES[@]}"; do [ -f "$DEST/$f" ] || { echo "  MISSING $f"; miss=1; }; done
[ "$miss" -eq 0 ] || { echo "ERROR: files missing after copy."; exit 1; }
echo "Verifying wiring..."
grep -q "register_dynamic_state_routes" "$DEST/app.py"                    || { echo "ERROR: app.py not wired (dynamic state)."; exit 1; }
grep -q "independent_evidence_factor" "$DEST/engine/institutional_intelligence_mesh.py" || { echo "ERROR: mesh not fed independence factor."; exit 1; }
grep -q "independence" "$DEST/engine/institutional_intelligence_mesh.py"  || { echo "ERROR: mesh independence field missing."; exit 1; }
grep -q 'id="dsBand"' "$DEST/templates/apex_os.html"                      || { echo "ERROR: Dynamic State panel missing from template."; exit 1; }
# guard against full-file app.py reverting prior merged features:
for feat in carry_forward_ladder build_flow_tape breadth_regime flow_excitation register_range_routes; do
  grep -q "$feat" "$DEST/app.py" || echo "NOTE: '$feat' not found in app.py — confirm it is merged before pushing."
done
python -c "import ast; [ast.parse(open(f).read()) for f in ['app.py','engine/dynamic_state.py','engine/dynamic_state_routes.py','engine/institutional_intelligence_mesh.py']]" && echo "PY SYNTAX OK"
echo ""
echo "OK — all 7 files present and wired."
echo "Run:  python -m pytest -q tests/test_dynamic_state.py tests/test_mesh_independence.py tests/test_apex43_intelligence_mesh.py tests/test_consolidation_guard.py"
