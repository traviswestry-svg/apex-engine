#!/usr/bin/env bash
set -euo pipefail

export RUN_SCANNER_ON_IMPORT=false
# Tell wsgi.py that this launcher already owns scanner_worker.py. This prevents
# the WSGI fallback from spawning a second scanner while preserving direct-
# Gunicorn resilience when Render has an overriding Start Command.
export APEX_SCANNER_MANAGED_EXTERNALLY=true

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

# Both processes are required. If either process exits, fail the service so
# Render restarts the pair instead of leaving a web-only zombie deployment.
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
