#!/bin/bash
# Opens a quick cloudflared tunnel to the site and tells the Worker (deploy/worker.js) where it is.
# Run by haluka-tunnel.service. Needs in /etc/haluka/tunnel.env (chmod 600):
#   HALUKA_FRONT_URL=https://<the worker's address>      HALUKA_REGISTER_KEY=<the Worker's secret>
set -u
LOG=$(mktemp)
cloudflared tunnel --no-autoupdate --url http://127.0.0.1:8787 >"$LOG" 2>&1 &
PID=$!
trap 'kill $PID 2>/dev/null; rm -f "$LOG"' EXIT
URL=""
for _ in $(seq 60); do
  URL=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' "$LOG" | head -1)
  [ -n "$URL" ] && break
  kill -0 $PID 2>/dev/null || exit 1
  sleep 1
done
[ -n "$URL" ] || exit 1
for _ in $(seq 10); do
  curl -fsS -X POST -H "X-Register-Key: $HALUKA_REGISTER_KEY" --data "$URL" "$HALUKA_FRONT_URL/__tunnel" >/dev/null && break
  sleep 3
done
wait $PID
