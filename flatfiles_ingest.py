#!/usr/bin/env python3
"""
flatfiles_ingest.py — Massive Flat Files ingestion (Layer 1: single-slice, validated).

PURPOSE
-------
Pull a bounded slice of historical market data from Massive Flat Files (S3),
parse it correctly, VALIDATE it against sanity checks, and land it locally as
parquet for later backtest/calibration use. This is deliberately small and
verifiable — it does NOT backfill years or run any backtest. It proves the
download + parse + validate path is correct on one slice before anything scales.

WHY LAYER 1 IS SEPARATE
-----------------------
Backtest data infrastructure is where silent errors (wrong timestamp units,
timezone drift, lookahead) produce confident-but-wrong results. So the first
deliverable is ONLY: "can we reliably pull and parse one slice correctly, and
prove it with checks a human can eyeball?" Everything else builds on this.

DATA CONTRACT (from Massive Flat Files docs)
--------------------------------------------
CSV columns: ticker, volume, open, close, high, low, window_start, transactions
  - window_start is a NANOSECOND epoch (e.g. 1744792500000000000). NOT ms.
Files: gzipped CSV, organized as
  {dataset}/{datatype}/{YYYY}/{MM}/{YYYY-MM-DD}.csv.gz
Endpoint: https://files.massive.com   Bucket: flatfiles
Credentials: S3 Access/Secret keys (NOT the REST API key), from env:
  MASSIVE_S3_ACCESS_KEY / MASSIVE_S3_SECRET_KEY
Data for a trading day is available ~11 AM ET the NEXT day.

USAGE
-----
  export MASSIVE_S3_ACCESS_KEY=...  MASSIVE_S3_SECRET_KEY=...
  # list what date files exist for a dataset/datatype/month:
  python3 flatfiles_ingest.py list  --dataset us_indices --datatype minute_aggs_v1 --month 2026-06
  # download+validate a single day:
  python3 flatfiles_ingest.py pull  --dataset us_indices --datatype minute_aggs_v1 --date 2026-06-10 --ticker I:SPX
  # download+validate a date range (inclusive), landing parquet per day:
  python3 flatfiles_ingest.py range --dataset us_indices --datatype minute_aggs_v1 --start 2026-06-01 --end 2026-06-05 --ticker I:SPX

Output lands under ./flatfiles_data/{dataset}/{datatype}/{date}.parquet
Requires: boto3, pandas, pyarrow
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import io
import os
import sys
from typing import Optional

ENDPOINT = "https://files.massive.com"
BUCKET = "flatfiles"
OUT_ROOT = os.environ.get("FLATFILES_OUT", "./flatfiles_data")

EXPECTED_COLS = ["ticker", "open", "close", "high", "low", "window_start"]
# volume + transactions exist in stocks/options datasets but NOT indices (an index
# has no volume — it's a calculated value). Treated as optional below.
OPTIONAL_COLS = ["volume", "transactions"]


# ── S3 ───────────────────────────────────────────────────────────────────────
def _client():
    ak = os.environ.get("MASSIVE_S3_ACCESS_KEY")
    sk = os.environ.get("MASSIVE_S3_SECRET_KEY")
    if not ak or not sk:
        sys.exit("ERROR: set MASSIVE_S3_ACCESS_KEY and MASSIVE_S3_SECRET_KEY "
                 "(Flat Files S3 credentials, NOT the REST API key).")
    import boto3
    from botocore.config import Config
    return boto3.client("s3", endpoint_url=ENDPOINT,
                        aws_access_key_id=ak, aws_secret_access_key=sk,
                        config=Config(signature_version="s3v4",
                                      retries={"max_attempts": 3}))


def _key_for(dataset: str, datatype: str, date: dt.date) -> str:
    return f"{dataset}/{datatype}/{date:%Y}/{date:%m}/{date:%Y-%m-%d}.csv.gz"


# ── parse + validate ─────────────────────────────────────────────────────────
def _parse_csv_gz(raw: bytes, ticker_filter: Optional[str]):
    import pandas as pd
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as gz:
        df = pd.read_csv(gz)

    # Contract check: columns must match what we expect, or we stop — a schema
    # drift silently mis-parsing is exactly the failure we refuse to allow.
    missing = [c for c in EXPECTED_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"Schema mismatch — missing columns {missing}. "
                         f"Got: {list(df.columns)}")

    if ticker_filter:
        df = df[df["ticker"] == ticker_filter].copy()

    # window_start is NANOSECOND epoch. Convert explicitly and label the tz as UTC,
    # then also provide an ET column (market-local) since sessions are ET.
    df["ts_utc"] = pd.to_datetime(df["window_start"], unit="ns", utc=True)
    df["ts_et"] = df["ts_utc"].dt.tz_convert("America/New_York")
    return df.reset_index(drop=True)


def _validate(df, date: dt.date, ticker_filter: Optional[str]) -> list:
    """Return a list of human-readable validation findings. Empty-ish = healthy."""
    import pandas as pd
    findings = []
    if df.empty:
        findings.append("EMPTY after filter — no rows for that ticker/date "
                        "(check ticker symbol format, e.g. 'I:SPX' for indices).")
        return findings

    # 1. All timestamps should fall on the requested ET calendar date.
    et_dates = df["ts_et"].dt.date.unique()
    if len(et_dates) != 1 or et_dates[0] != date:
        findings.append(f"Date drift: rows span ET dates {sorted(map(str, et_dates))}, "
                        f"expected only {date} — timezone/parse bug suspected.")

    # 2. OHLC sanity: high >= max(open,close) >= min(open,close) >= low, all > 0.
    bad_ohlc = df[(df["high"] < df[["open", "close"]].max(axis=1)) |
                  (df["low"] > df[["open", "close"]].min(axis=1)) |
                  (df[["open", "high", "low", "close"]] <= 0).any(axis=1)]
    if len(bad_ohlc):
        findings.append(f"{len(bad_ohlc)} rows fail OHLC sanity (high<max/lo>min/<=0).")

    # 3. Monotonic, de-duplicated timestamps.
    if df["ts_utc"].duplicated().any():
        findings.append(f"{int(df['ts_utc'].duplicated().sum())} duplicate timestamps.")
    if not df["ts_utc"].is_monotonic_increasing:
        findings.append("Timestamps not sorted ascending (will sort on write).")

    # 4. Eyeball anchors — print the session's first/last bar so a human can
    #    cross-check the close against a known value.
    first, last = df.iloc[0], df.iloc[-1]
    findings.append(
        f"EYEBALL: {len(df)} rows | first {first['ts_et']:%H:%M} O={first['open']} "
        f"| last {last['ts_et']:%H:%M} C={last['close']} "
        f"| session H={df['high'].max()} L={df['low'].min()}")
    return findings


# ── commands ─────────────────────────────────────────────────────────────────
def cmd_list(a):
    s3 = _client()
    prefix = f"{a.dataset}/{a.datatype}/{a.month.replace('-', '/')}/"
    resp = s3.list_objects_v2(Bucket=BUCKET, Prefix=prefix)
    keys = [o["Key"] for o in resp.get("Contents", [])]
    if not keys:
        print(f"No files under {prefix} (check dataset/datatype names & entitlement).")
        return
    print(f"{len(keys)} day-files under {prefix}:")
    for k in sorted(keys):
        print("   ", k.split("/")[-1])


def _pull_one(s3, a, date: dt.date):
    import pandas as pd
    key = _key_for(a.dataset, a.datatype, date)
    try:
        obj = s3.get_object(Bucket=BUCKET, Key=key)
        raw = obj["Body"].read()
    except Exception as e:
        print(f"  {date}: FETCH FAILED ({key}): {e}")
        return None
    df = _parse_csv_gz(raw, a.ticker)
    findings = _validate(df, date, a.ticker)
    print(f"  {date}:")
    for f in findings:
        print(f"      - {f}")
    # write parquet only if not empty and no hard failures (date drift / OHLC)
    hard = any(("Date drift" in f or "OHLC sanity" in f or "EMPTY" in f) for f in findings)
    if df.empty:
        return None
    if hard and not a.force:
        print(f"      ! NOT WRITTEN (validation flagged; re-run with --force to override)")
        return None
    outdir = os.path.join(OUT_ROOT, a.dataset, a.datatype)
    os.makedirs(outdir, exist_ok=True)
    outpath = os.path.join(outdir, f"{date:%Y-%m-%d}.parquet")
    df.sort_values("ts_utc").to_parquet(outpath, index=False)
    print(f"      → wrote {outpath} ({len(df)} rows)")
    return outpath


def cmd_pull(a):
    s3 = _client()
    date = dt.date.fromisoformat(a.date)
    _pull_one(s3, a, date)


def cmd_range(a):
    s3 = _client()
    start = dt.date.fromisoformat(a.start)
    end = dt.date.fromisoformat(a.end)
    if end < start:
        sys.exit("end before start")
    d = start
    wrote = 0
    while d <= end:
        # skip weekends (no market data); Massive files won't exist for them
        if d.weekday() < 5:
            if _pull_one(s3, a, d):
                wrote += 1
        d += dt.timedelta(days=1)
    print(f"\nDone. Wrote {wrote} day-file(s) under {OUT_ROOT}/{a.dataset}/{a.datatype}/")


def main():
    p = argparse.ArgumentParser(description="Massive Flat Files ingestion (Layer 1).")
    sub = p.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("list", help="list available day-files for a month")
    pl.add_argument("--dataset", required=True)
    pl.add_argument("--datatype", required=True)
    pl.add_argument("--month", required=True, help="YYYY-MM")
    pl.set_defaults(func=cmd_list)

    pp = sub.add_parser("pull", help="download+validate one day")
    for arg in ("--dataset", "--datatype", "--date"):
        pp.add_argument(arg, required=True)
    pp.add_argument("--ticker", default=None, help="filter to one ticker, e.g. I:SPX")
    pp.add_argument("--force", action="store_true")
    pp.set_defaults(func=cmd_pull)

    pr = sub.add_parser("range", help="download+validate an inclusive date range")
    for arg in ("--dataset", "--datatype", "--start", "--end"):
        pr.add_argument(arg, required=True)
    pr.add_argument("--ticker", default=None)
    pr.add_argument("--force", action="store_true")
    pr.set_defaults(func=cmd_range)

    a = p.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
