#!/usr/bin/env python3
"""
flatfiles_probe.py — READ-ONLY probe for Massive Flat Files (S3) access.

Verifies your Flat Files S3 credentials work, lists the available datasets, and
shows the date depth for the ones APEX cares about (options, indices, stocks,
futures). Downloads NOTHING and writes NOTHING — it only lists.

USAGE
-----
Set two environment variables with your Flat Files S3 credentials (NOT your REST
API key), then run:

    export MASSIVE_S3_ACCESS_KEY=...      # Flat Files Access Key ID
    export MASSIVE_S3_SECRET_KEY=...      # Flat Files Secret Access Key
    python3 flatfiles_probe.py

On Render you'd set those in the Environment tab and run this from the Shell.

Requires: boto3  (pip install boto3)
"""

import os
import sys

ENDPOINT = "https://files.massive.com"
BUCKET = "flatfiles"

# Dataset prefixes APEX is most likely to use. The probe checks which of these
# actually exist under your entitlements; missing ones are simply reported, not
# errors (your plan may not include every asset class).
CANDIDATE_DATASETS = [
    "us_options_opra",   # options (chains, aggs, trades, quotes)
    "us_indices",        # SPX and other indices
    "us_stocks_sip",     # equities (scanner universe, drivers)
    "global_futures",    # futures (ES) — name may vary
    "us_futures",        # alt futures prefix
]


def _client():
    ak = os.environ.get("MASSIVE_S3_ACCESS_KEY")
    sk = os.environ.get("MASSIVE_S3_SECRET_KEY")
    if not ak or not sk:
        print("ERROR: set MASSIVE_S3_ACCESS_KEY and MASSIVE_S3_SECRET_KEY "
              "environment variables first (your Flat Files S3 credentials, "
              "NOT your REST API key).", file=sys.stderr)
        sys.exit(2)
    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        print("ERROR: boto3 not installed. Run: pip install boto3", file=sys.stderr)
        sys.exit(2)
    return boto3.client(
        "s3",
        endpoint_url=ENDPOINT,
        aws_access_key_id=ak,
        aws_secret_access_key=sk,
        config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
    )


def _list_prefixes(s3, prefix=""):
    """Return the immediate 'subfolder' prefixes under a given prefix."""
    out = []
    token = None
    while True:
        kw = {"Bucket": BUCKET, "Delimiter": "/", "Prefix": prefix}
        if token:
            kw["ContinuationToken"] = token
        resp = s3.list_objects_v2(**kw)
        out += [cp["Prefix"] for cp in resp.get("CommonPrefixes", [])]
        if resp.get("IsTruncated"):
            token = resp.get("NextContinuationToken")
        else:
            break
    return out


def _sample_keys(s3, prefix, n=3):
    """Return up to n object keys under a prefix (for showing file examples)."""
    resp = s3.list_objects_v2(Bucket=BUCKET, Prefix=prefix, MaxKeys=n)
    return [o["Key"] for o in resp.get("Contents", [])]


def main():
    s3 = _client()

    # 1. Auth check — list top-level datasets.
    print(f"Connecting to {ENDPOINT} (bucket: {BUCKET}) ...")
    try:
        top = _list_prefixes(s3)
    except Exception as e:
        print(f"\nAUTH/CONNECT FAILED: {e}", file=sys.stderr)
        print("Check: (a) credentials are the Flat Files S3 keys, not the REST "
              "API key; (b) your plan includes Flat Files.", file=sys.stderr)
        sys.exit(1)

    print(f"\n✓ Access OK. Top-level datasets ({len(top)}):")
    for p in top:
        print(f"    {p}")

    # 2. For APEX-relevant datasets that exist, show structure + date depth.
    print("\n--- APEX-relevant datasets: structure & date depth ---")
    present = [d for d in CANDIDATE_DATASETS if any(t.rstrip('/') == d for t in top)]
    if not present:
        print("  (none of the expected APEX datasets found by name — the full "
              "top-level list above shows what IS available; names may differ.)")
    for ds in present:
        print(f"\n  {ds}/")
        # data-type subfolders (e.g. day_aggs_v1, minute_aggs_v1, trades_v1, quotes_v1)
        types = _list_prefixes(s3, prefix=f"{ds}/")
        for t in types:
            # drill to year to show date depth
            years = _list_prefixes(s3, prefix=t)
            if years:
                yr_labels = sorted(y.rstrip('/').split('/')[-1] for y in years)
                span = f"{yr_labels[0]}..{yr_labels[-1]}" if len(yr_labels) > 1 else yr_labels[0]
                print(f"    {t.split('/')[-2]:22s} years: {span}")
            else:
                sample = _sample_keys(s3, t, 1)
                print(f"    {t.split('/')[-2]:22s} (files: {sample[0] if sample else 'none'})")

    print("\nDone. This was read-only — nothing was downloaded or written.")
    print("Next step (separate, deliberate): a small ingestion that pulls the "
          "specific day-files APEX needs and lands them for the scanner/backtest.")


if __name__ == "__main__":
    main()
