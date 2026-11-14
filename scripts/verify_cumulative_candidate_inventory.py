#!/usr/bin/env python3
"""Read-only, stdlib verification of APEX cumulative candidate file inventory."""
import argparse, csv, hashlib, io, json, pathlib, sys, zipfile

def digest(data):return hashlib.sha256(data).hexdigest()
def entries(z):
    out={}
    for name in z.namelist():
        if name.endswith('/'):continue
        parts=pathlib.PurePosixPath(name).parts
        if not parts or parts[0]!='apex-engine-main':continue
        rel='/'.join(parts[1:])
        if not rel or any(x in {'__pycache__','.pytest_cache','.git'} for x in parts):continue
        out[rel]=digest(z.read(name))
    return out

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--baseline',required=True,type=pathlib.Path)
    p.add_argument('--candidate',required=True,type=pathlib.Path)
    p.add_argument('--inventory',required=True,type=pathlib.Path)
    p.add_argument('--reconciliation',required=True,type=pathlib.Path)
    args=p.parse_args(); data=json.loads(args.reconciliation.read_text())
    for name,path,key in [('baseline',args.baseline,'baseline_archive_sha256'),('candidate',args.candidate,'candidate_archive_sha256')]:
        actual=digest(path.read_bytes())
        if actual!=data[key]:raise SystemExit(f'FAIL: {name} archive checksum mismatch')
    with zipfile.ZipFile(args.baseline) as za,zipfile.ZipFile(args.candidate) as zb:
        a,b=entries(za),entries(zb)
    changes=[]
    for path in sorted(a.keys()|b.keys()):
        if a.get(path)==b.get(path):continue
        state='NEW' if path not in a else 'REMOVED' if path not in b else 'MODIFIED'
        changes.append((path,state,a.get(path,''),b.get(path,'')))
    with args.inventory.open(newline='') as fh: rows=list(csv.DictReader(fh))
    expected=[(x['path'],x['status'],x['baseline_sha256'],x['candidate_sha256']) for x in rows]
    if changes!=expected:raise SystemExit('FAIL: file inventory differs from archive diff')
    if any(p=='config/apex_release_manifest.json' for p,*_ in changes):raise SystemExit('FAIL: version manifest unexpectedly modified')
    with zipfile.ZipFile(args.candidate) as z:
        manifest=json.loads(z.read('apex-engine-main/config/apex_release_manifest.json'))
        code=z.read('apex-engine-main/engine/execution/traderspost_paper.py').decode()
        if manifest.get('apex_version')!='69.10.47':raise SystemExit('FAIL: canonical release mismatch')
        idx=code.index('def dispatch(')
        stop=code.index("raise ValueError('PAPER_EXECUTION_AUTHORITY_NOT_VERIFIED_69_10_40')",idx)
        send=code.index('payload = make_signal(',idx)
        if stop>=send:raise SystemExit('FAIL: unconditional dispatch hard stop moved after signal creation')
    print(f'PASS: {len(changes)} checked file changes; release unchanged; dispatch hard stop present. NOT a production promotion certificate.')
if __name__=='__main__':main()
