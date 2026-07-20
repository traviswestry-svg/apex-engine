#!/usr/bin/env bash
set -euo pipefail

export RUN_SCANNER_ON_IMPORT=false
python scanner_worker.py &
SCANNER_PID=$!

cleanup() {
  kill -TERM "$SCANNER_PID" 2>/dev/null || true
  wait "$SCANNER_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

gunicorn app:app --bind "0.0.0.0:${PORT}" --workers 1 --threads 4 --timeout 120
