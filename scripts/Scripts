"""Dry-run-first utility to consolidate historical root release reports."""
from __future__ import annotations
import argparse
from pathlib import Path
import shutil

def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument('--apply',action='store_true'); args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]; target=root/'docs'/'releases'
    reports=sorted(p for p in root.glob('APEX_*.md') if p.is_file())
    print(f'{len(reports)} release reports identified; destination={target}')
    if args.apply:
        target.mkdir(parents=True,exist_ok=True)
        for report in reports: shutil.move(str(report),str(target/report.name))
        print(f'moved={len(reports)}')
    else: print('dry-run only; use --apply after deployment review')
    return 0
if __name__=='__main__': raise SystemExit(main())
