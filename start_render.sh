#!/usr/bin/env bash
set -euo pipefail

export RUN_SCANNER_ON_IMPORT=false

python scanner_worker.py &
SCANNER_PID=$!
gunicorn wsgi:app --bind "0.0.0.0:${PORT}" --workers 1 --threads 4 --timeout 120 &
WEB_PID=$!

cleanup() {
  kill -TERM "$SCANNER_PID" "$WEB_PID" 2>/dev/null || true
  wait "$SCANNER_PID" 2>/dev/null || true
  wait "$WEB_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# APEX 65.7.2: both processes are required. Previously scanner_worker.py ran in
# the background and could die while Gunicorn stayed healthy indefinitely.
# Treat loss of either process as a service failure so Render restarts the pair.
while true; do
  if ! kill -0 "$SCANNER_PID" 2>/dev/null; then
    wait "$SCANNER_PID" || rc=$?
    echo "APEX scanner process exited (rc=${rc:-0}); terminating web process for supervised restart." >&2
    exit "${rc:-1}"
  fi
  if ! kill -0 "$WEB_PID" 2>/dev/null; then
    wait "$WEB_PID" || rc=$?
    echo "APEX web process exited (rc=${rc:-0}); terminating scanner process." >&2
    exit "${rc:-1}"
  fi
  sleep 5
done
