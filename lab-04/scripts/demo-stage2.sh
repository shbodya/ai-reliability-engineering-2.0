#!/usr/bin/env bash
# Stage 2 demo: own A2A agent serves card + handles task.
# Usage: asciinema rec -c ./demo-stage2.sh stage2.cast
set -e
cd "$(dirname "$0")/.."

echo "=== Stage 2 — own A2A agent ==="
sleep 1

echo "$ source agent-own/.venv/bin/activate && python agent-own/main.py &"
source agent-own/.venv/bin/activate
python agent-own/main.py > /tmp/own.log 2>&1 &
PID=$!
trap "kill $PID 2>/dev/null" EXIT
until nc -z 127.0.0.1 9000 2>/dev/null; do sleep 1; done
sleep 1

echo
echo "$ curl http://localhost:9000/.well-known/agent-card.json | jq ."
curl -s http://localhost:9000/.well-known/agent-card.json | python3 -m json.tool
sleep 2

echo
echo "$ curl -X POST http://localhost:9000/a2a/jsonrpc/  (SendMessage)"
curl -s -X POST http://localhost:9000/a2a/jsonrpc/ \
  -H 'Content-Type: application/json' \
  -H 'A2A-Version: 1.0' \
  -d '{"jsonrpc":"2.0","id":"1","method":"SendMessage","params":{"message":{"messageId":"u1","role":"ROLE_USER","parts":[{"text":"The quick brown fox. It was sunny."}]}}}' \
  | python3 -m json.tool
sleep 2
echo
echo "=== done ==="
