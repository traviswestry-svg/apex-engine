#!/usr/bin/env python3
import argparse, json
from engine.storage_retention import audit, cleanup_quarantined_backups, checkpoint_wals, prune_mature_price_samples
p=argparse.ArgumentParser(description="APEX governed storage maintenance")
p.add_argument("--apply",action="store_true",help="Apply only explicitly classified safe maintenance")
p.add_argument("--acknowledge",default="",help="Required with --apply: APEX_STORAGE_MAINTENANCE")
a=p.parse_args()
if a.apply and a.acknowledge != "APEX_STORAGE_MAINTENANCE": raise SystemExit("--apply requires --acknowledge APEX_STORAGE_MAINTENANCE")
out={"audit":audit(),"quarantine_cleanup":cleanup_quarantined_backups(apply=a.apply),"wal_checkpoint":checkpoint_wals(apply=a.apply),"price_sample_prune":prune_mature_price_samples(apply=a.apply)}
print(json.dumps(out,indent=2,default=str))
