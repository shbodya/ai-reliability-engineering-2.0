#!/usr/bin/env bash
# Stage 5 demo: A2A team — orchestrator fans out to kagent k8s-agent + observability-agent.
# Slow (~9 min) since kagent runs on Ollama qwen3:4b on CPU.
# Usage: asciinema rec -c ./demo-stage5.sh stage5.cast
set -e
cd "$(dirname "$0")/.."

VENV=agent-own/.venv/bin/python

echo "=== Stage 5 — A2A team (orchestrator → kagent k8s + observability) ==="

echo "$ kubectl -n kagent port-forward svc/k8s-agent 18080:8080 &"
kubectl -n kagent port-forward svc/k8s-agent 18080:8080 > /tmp/pf-k8s.log 2>&1 &
PF1=$!
echo "$ kubectl -n kagent port-forward svc/observability-agent 18081:8080 &"
kubectl -n kagent port-forward svc/observability-agent 18081:8080 > /tmp/pf-obs.log 2>&1 &
PF2=$!
until nc -z 127.0.0.1 18080 && nc -z 127.0.0.1 18081; do sleep 1; done

echo "$ kagent k8s-agent card:"
curl -s http://127.0.0.1:18080/.well-known/agent-card.json | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['name'])"
echo "$ kagent observability-agent card:"
curl -s http://127.0.0.1:18081/.well-known/agent-card.json | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['name'])"

echo
echo "$ start agent-team orchestrator (port 9002)"
PEER_TIMEOUT_S=900 KAGENT_PEERS="http://127.0.0.1:18080,http://127.0.0.1:18081" \
  $VENV agent-team/main.py > /tmp/agent-team.log 2>&1 &
TEAM=$!
trap "kill $TEAM $PF1 $PF2 2>/dev/null" EXIT
until nc -z 127.0.0.1 9002; do sleep 1; done

echo "$ orchestrate (wait ~9 min CPU inference)"
curl -s -X POST http://127.0.0.1:9002/a2a/jsonrpc/ \
  -H 'Content-Type: application/json' -H 'A2A-Version: 1.0' \
  --max-time 1800 \
  -d '{"jsonrpc":"2.0","id":"1","method":"SendMessage","params":{"message":{"messageId":"u","role":"ROLE_USER","parts":[{"text":"One short sentence: describe what you do."}]}}}' \
  | python3 -m json.tool

echo "=== done ==="
