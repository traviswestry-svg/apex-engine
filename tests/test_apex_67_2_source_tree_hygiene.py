from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
FORBIDDEN=("_check","_ds_seg","_loi_seg","APEX_66_4_1_Decision_Coherence_Fix_Changed_Files")

def test_no_historical_executable_source_copy_directories():
    violations=[]
    for name in FORBIDDEN:
        p=ROOT/name
        if p.exists():
            violations.extend(str(x.relative_to(ROOT)) for x in p.rglob("*.py"))
    assert violations == [], f"historical executable source copies must be removed: {violations[:20]}"
