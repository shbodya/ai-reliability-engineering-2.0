# Lab-04 — A2A Protocol

End-to-end A2A demo on abox (KinD + Flux + agentgateway + kagent + Ollama + Qdrant).

## Layout

```
lab-04/
├── task.md                          # original assignment
├── tasks.md                         # step-by-step plan
├── notes/a2a-spec.md                # Stage 1 — A2A v1.0 spec digest
├── agent-own/                       # Stage 2 + 4 — orchestrator (summarize + delegate)
├── agent-peer/                      # Stage 4 — peer (enrich)
├── agent-team/                      # Stage 5 — A2A team orchestrator (kagent fan-out)
├── scripts/                         # asciinema-friendly demos per stage
│   ├── demo-stage2.sh
│   ├── demo-stage3.sh
│   ├── demo-stage4.sh
│   ├── demo-stage5.sh
│   └── record-all.sh                # rec + upload all stages
├── manifests/                       # Stage 3 + 5 infra
│   ├── inventory.yaml
│   ├── qdrant.yaml
│   ├── ollama.yaml
│   └── kagent-modelconfig-ollama.yaml
└── artifacts/                       # captured evidence
```

## Stage map

| Stage | Track | Artifact |
|------|------|---------|
| 1. Research A2A spec | Beginner | `notes/a2a-spec.md` |
| 2. Own agent + Agent Card | Beginner | `agent-own/`, `artifacts/own-agent-card.json`, `artifacts/own-agent-send-message.json` |
| 3.1. Inventory | Beginner | `manifests/inventory.yaml`, `artifacts/inventory.txt` |
| 3.2. MCPG (agentgateway) | Beginner | `artifacts/mcp-tools-list.json`, `artifacts/mcp-tools-summary.txt` |
| 3.3. Qdrant | Beginner | `manifests/qdrant.yaml`, `artifacts/qdrant-verify.txt` |
| 4. A2A 2-agent comms | Experienced | `agent-own/`, `agent-peer/`, `artifacts/a2a-2agent-trace.json` |
| 5. A2A team w/ kagent | Max | `agent-team/`, `manifests/{ollama,kagent-modelconfig-ollama}.yaml`, `artifacts/a2a-team-trace.json` |

## Key findings

- A2A v1.0 well-known URI = `/.well-known/agent-card.json` (not `agent.json`).
- a2a-sdk v1.x uses protobuf types + Starlette route factories; v1.0 RPC method names are CamelCase (`SendMessage`), v0.3 dotted (`message/send`). kagent serves v0.3.
- AgentExecutor must enqueue a `Task` event FIRST, then `TaskStatusUpdateEvent` and `TaskArtifactUpdateEvent`. Helper: `a2a.helpers.new_task_from_user_message`.
- Card advertises in-cluster URL — orchestrators reaching agents via port-forward must reuse base URL, not card's `url` field.
- Ollama `qwen3.6:27b` needs ~20.7 GiB RAM; demo downgraded to `qwen3:4b` (~3 GiB) so kagent agents on 3-node KinD could load model on CPU.

## Public recordings (asciinema)

| Stage | URL |
|---|---|
| 2 — Own A2A agent + Agent Card | https://asciinema.org/a/wULifQItOnAuVlHP |
| 3 — Inventory + MCPG + Qdrant | https://asciinema.org/a/Uze0zbNI5nFf4Crc |
| 4 — A2A 2-agent comms | https://asciinema.org/a/U2S0povC2Xob05Ju |
| 5 — A2A team w/ kagent | https://asciinema.org/a/Dilx6V6A3To2xW55 |

> Uploaded anonymously — auto-deleted after 7 days unless linked via `asciinema auth`.

## How to record + upload

```bash
brew install asciinema
asciinema auth          # optional, for upload to asciinema.org

# Record per-stage:
asciinema rec -c ./scripts/demo-stage2.sh casts/stage2.cast
asciinema rec -c ./scripts/demo-stage3.sh casts/stage3.cast
asciinema rec -c ./scripts/demo-stage4.sh casts/stage4.cast
asciinema rec -c ./scripts/demo-stage5.sh casts/stage5.cast

# Upload all:
for c in casts/*.cast; do asciinema upload "$c"; done

# Or do everything at once:
./scripts/record-all.sh
```

The submission requires a **public URL** (not the raw `.cast` file). After `asciinema upload`, the command prints the public link.

## Reproduce

```bash
# 0. cluster
cd ~/Documents/homelab/abox && make run
kind export kubeconfig --name abox

# 1. own + peer agents (local)
cd lab-04/agent-own && python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
python main.py &
cd ../agent-peer && ../agent-own/.venv/bin/python main.py &
curl -s -X POST http://127.0.0.1:9000/a2a/jsonrpc/ \
  -H 'Content-Type: application/json' -H 'A2A-Version: 1.0' \
  -d '{"jsonrpc":"2.0","id":"1","method":"SendMessage","params":{"message":{"messageId":"u","role":"ROLE_USER","parts":[{"text":"hello world"}]}}}'

# 2. infra
kubectl apply -f manifests/inventory.yaml
kubectl apply -f manifests/qdrant.yaml
kubectl apply -f manifests/ollama.yaml
kubectl apply -f manifests/kagent-modelconfig-ollama.yaml
for a in k8s-agent observability-agent; do
  kubectl patch agent -n kagent $a --type=merge -p '{"spec":{"declarative":{"modelConfig":"ollama-qwen3"}}}'
done

# 3. team demo
kubectl -n kagent port-forward svc/k8s-agent 18080:8080 &
cd ../agent-team
PEER_TIMEOUT_S=900 KAGENT_PEERS=http://127.0.0.1:18080 \
  ../agent-own/.venv/bin/python main.py &
curl -s -X POST http://127.0.0.1:9002/a2a/jsonrpc/ \
  -H 'Content-Type: application/json' -H 'A2A-Version: 1.0' \
  -d '{"jsonrpc":"2.0","id":"1","method":"SendMessage","params":{"message":{"messageId":"u","role":"ROLE_USER","parts":[{"text":"what is your role?"}]}}}'
```
