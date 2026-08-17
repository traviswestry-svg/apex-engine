"""Remove historical executable-source artifact directories from the live repo."""
from __future__ import annotations
import shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
TARGETS=["_check","_ds_seg","_loi_seg","APEX_66_4_1_Decision_Coherence_Fix_Changed_Files"]
def main():
    removed=[]
    for name in TARGETS:
        p=ROOT/name
        if p.exists():
            shutil.rmtree(p)
            removed.append(name)
    print({"removed":removed,"root":str(ROOT)})
if __name__=="__main__":
    main()
