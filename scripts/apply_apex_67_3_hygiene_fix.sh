#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT"

TARGETS=(
  "_check"
  "_ds_seg"
  "_loi_seg"
  "APEX_66_4_1_Decision_Coherence_Fix_Changed_Files"
)

echo "APEX 67.3 hygiene fix: removing historical executable source mirrors..."
git rm -r --ignore-unmatch -- "${TARGETS[@]}"

# If any target is untracked rather than tracked, remove it from the working tree too.
for target in "${TARGETS[@]}"; do
  if [ -e "$target" ]; then
    rm -rf -- "$target"
  fi
done

echo "Verifying forbidden source mirrors are gone..."
python - <<'PY'
from pathlib import Path
root = Path.cwd()
targets = ["_check","_ds_seg","_loi_seg","APEX_66_4_1_Decision_Coherence_Fix_Changed_Files"]
violations = []
for name in targets:
    p = root / name
    if p.exists():
        violations.extend(str(x.relative_to(root)) for x in p.rglob("*.py"))
if violations:
    raise SystemExit("Cleanup failed; remaining historical Python files: " + repr(violations[:20]))
print("APEX source-tree hygiene: CLEAN")
PY

echo "Running the two previously failing tests..."
python -m pytest -q   tests/test_apex_67_2_source_tree_hygiene.py   tests/test_apex_67_2_architecture_integrity.py

echo
echo "Fix applied. Commit the staged deletions and this script with your 67.3 changes."
