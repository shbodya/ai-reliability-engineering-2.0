#!/usr/bin/env bash
# Stage 4 demo: A2A task comms between own-agent and peer.
# Usage: asciinema rec -c ./demo-stage4.sh stage4.cast
set -e
cd "$(dirname "$0")/.."

VENV=agent-own/.venv/bin/python

echo "=== Stage 4 — A2A 2-agent comms ==="
echo "$ agent-peer  (port 9001)"
$VENV agent-peer/main.py > /tmp/peer.log 2>&1 &
P1=$!
echo "$ own-agent   (port 9000, delegates to peer)"
$VENV agent-own/main.py > /tmp/own.log 2>&1 &
P2=$!
trap "kill $P1 $P2 2>/dev/null" EXIT
until nc -z 127.0.0.1 9000 && nc -z 127.0.0.1 9001; do sleep 1; done

echo
echo "$ peer card (discoverable via well-known URI):"
curl -s http://localhost:9001/.well-known/agent-card.json | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['name'], '->', d['supportedInterfaces'][0]['url'])"

echo
echo "$ own card:"
curl -s http://localhost:9000/.well-known/agent-card.json | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['name'], '->', d['supportedInterfaces'][0]['url'])"
sleep 2

echo
echo "$ SendMessage to own-agent (it auto-delegates to peer via A2A):"
curl -s -X POST http://localhost:9000/a2a/jsonrpc/ \
  -H 'Content-Type: application/json' -H 'A2A-Version: 1.0' \
  -d '{"jsonrpc":"2.0","id":"1","method":"SendMessage","params":{"message":{"messageId":"u","role":"ROLE_USER","parts":[{"text":"The quick brown fox jumps over the lazy dog. It was sunny."}]}}}' \
  | python3 -m json.tool

echo
echo "=== done — note 2 artifacts: summary (own) + peer-enrichment (via A2A) ==="
