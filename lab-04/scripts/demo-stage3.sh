#!/usr/bin/env bash
# Stage 3 demo: AI inventory + MCP gateway tools + Qdrant.
# Usage: asciinema rec -c ./demo-stage3.sh stage3.cast
set -e

echo "=== Stage 3.1 — AI Inventory ==="
sleep 1
echo "$ kubectl logs -n inventory job/inventory | head -30"
kubectl logs -n inventory job/inventory 2>/dev/null | head -40
sleep 3

echo
echo "=== Stage 3.2 — MCPG (agentgateway + kagent-tools) ==="
echo "$ kubectl -n kagent port-forward svc/kagent-tools 8084:8084 &"
kubectl -n kagent port-forward svc/kagent-tools 8084:8084 > /tmp/mcp-pf.log 2>&1 &
PF=$!
trap "kill $PF 2>/dev/null" EXIT
until nc -z 127.0.0.1 8084 2>/dev/null; do sleep 1; done

SESSION=$(curl -s -i -X POST http://localhost:8084/mcp \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":"1","method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"demo","version":"0.1"}}}' \
  | grep -i 'mcp-session-id:' | awk '{print $2}' | tr -d '\r')
curl -s -X POST http://localhost:8084/mcp \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -H "mcp-session-id: $SESSION" \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized"}' > /dev/null
echo "$ tools/list (count)"
curl -s -X POST http://localhost:8084/mcp \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -H "mcp-session-id: $SESSION" \
  -d '{"jsonrpc":"2.0","id":"2","method":"tools/list"}' \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('total MCP tools:', len(d['result']['tools'])); print('first 5:', [t['name'] for t in d['result']['tools'][:5]])"
sleep 2

echo
echo "=== Stage 3.3 — Qdrant ==="
kubectl -n qdrant port-forward svc/qdrant 6333:6333 > /tmp/qd-pf.log 2>&1 &
QPF=$!
trap "kill $PF $QPF 2>/dev/null" EXIT
until nc -z 127.0.0.1 6333 2>/dev/null; do sleep 1; done

echo "$ curl localhost:6333/"
curl -s http://localhost:6333/ | python3 -m json.tool
echo "$ curl localhost:6333/collections"
curl -s http://localhost:6333/collections | python3 -m json.tool
echo "=== done ==="
