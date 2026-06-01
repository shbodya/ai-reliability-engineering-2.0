# Lab-04 Plan — A2A Protocol

Goal: study A2A spec → build own agent w/ Agent Card via Well-Known URI → deploy Inventory + MCPG + Qdrant on abox → enable A2A task comms between agents → orchestrate A2A team w/ kagent agents.

## Track map

- **Beginner (cert)**: Stage 1 (research) → Stage 2 (own agent + card) → Stage 3 (Inventory + MCPG + Qdrant on abox).
- **Experienced**: Beginner + Stage 4 (a2a task comms 2 agents).
- **Max**: Experienced + Stage 5 (a2a team: own agent + kagent agents complex task).

## Prereqs

- [ ] abox cluster from lab-02 up (KinD + Flux + agentgateway + kagent).
- [ ] LLM provider reachable: Ollama w/ `qwen3.6:27b` (17GB, 256K ctx, text+image) — in-cluster OR host w/ cluster pointed at it. Pull: `ollama pull qwen3.6:27b`.
- [ ] Python 3.11+ OR Node 20+ (agent impl).
- [ ] `kubectl`, `helm`, `flux`, `curl`, `jq`.
- [ ] ghcr.io PAT (`write:packages`) if pushing agent image.
- [ ] Free RAM ≥ 8 GB (qdrant + LLM heavy).

## Stage 1 — Research A2A spec

1. Read https://a2a-protocol.org spec end-to-end.
2. Note: Agent Card schema, Well-Known URI = `/.well-known/agent-card.json`, task lifecycle (SUBMITTED/WORKING/COMPLETED/...), JSON-RPC 2.0 + REST + gRPC transports, streaming via SSE, push notifications, auth schemes.
3. Capture key fields of Agent Card: `name`, `description`, `url`, `version`, `capabilities`, `skills[]`, `defaultInputModes`, `defaultOutputModes`, `authentication`.
4. Save short notes in `notes/a2a-spec.md` (cite section anchors).

Deliverable: `notes/a2a-spec.md` summary.

## Stage 2 — Own agent w/ Agent Card

Pick framework: **a2a-python SDK** (https://github.com/google/A2A) OR LangGraph + custom server OR fastapi from scratch.

Recommended: a2a-python SDK (fastest path).

1. Scaffold:
   ```bash
   mkdir -p lab-04/agent-own && cd lab-04/agent-own
   python -m venv .venv && source .venv/bin/activate
   pip install a2a-sdk uvicorn fastapi
   ```
2. Define skill (e.g. `summarize-k8s-events`, `echo`, `weather-lookup` — pick one useful).
3. Implement agent handler (`agent.py`):
   - subclass `AgentExecutor` from SDK
   - return task w/ artifacts
4. Wire AgentCard:
   ```python
   AgentCard(
     name="own-agent",
     description="...",
     url="http://localhost:9000",
     version="0.1.0",
     capabilities=AgentCapabilities(streaming=True),
     skills=[AgentSkill(id="...", name="...", description="...", tags=[...])],
     defaultInputModes=["text"], defaultOutputModes=["text"],
   )
   ```
5. Mount well-known endpoint — SDK serves `/.well-known/agent.json` automatically.
6. Run: `uvicorn main:app --port 9000`.
7. Verify card:
   ```bash
   curl -s http://localhost:9000/.well-known/agent.json | jq .
   ```
8. Send test task via SDK client OR raw JSON-RPC `tasks/send`.
9. Containerize (`Dockerfile`) + push to ghcr (optional, needed for Stage 4/5 in-cluster).

Deliverable: `agent-own/` dir w/ source, Dockerfile, sample card JSON, asciinema of card fetch + task call.

## Stage 3 — Infra: Inventory + MCPG + Qdrant

### 3.1 Inventory (abox AI resource lister)

1. Clone https://github.com/den-vasyliev/abox (already done in lab-02; reuse).
2. Find Inventory manifest/chart in repo (`releases/` or `apps/`). If missing — build minimal: a job/cronjob that lists `agents.kagent.dev`, `mcpservers.kagent.dev`, `gateways.gateway.networking.k8s.io`, `httproutes`, models in cluster.
3. Apply via abox OCI flow OR `kubectl apply -f`.
4. Verify: `kubectl get pods -n inventory` + run/exec to print AI resource inventory. Save output to `artifacts/inventory.txt`.

Alt: write own list script:
```bash
kubectl get agents,mcpservers,modelconfigs,gateway,httproute -A -o wide > artifacts/inventory.txt
```

### 3.2 MCPG (MCP Gateway)

1. Identify MCPG impl: kagent's agentgateway already proxies MCP (verify) OR install dedicated MCP Gateway (e.g. https://github.com/agentgateway/agentgateway w/ MCP route type).
2. Deploy via Helm or manifest in `releases/mcpg/`.
3. Register at least one upstream MCP server (reuse lab-02 MCP server).
4. Verify: `curl http://<mcpg-ip>/mcp/tools/list` returns aggregated tools.

### 3.3 Qdrant

1. Add helm repo:
   ```bash
   helm repo add qdrant https://qdrant.github.io/qdrant-helm
   helm repo update
   ```
2. Install:
   ```bash
   kubectl create ns qdrant
   helm upgrade -i qdrant qdrant/qdrant -n qdrant \
     --set replicaCount=1 \
     --set persistence.size=5Gi
   ```
   OR add as HelmRelease in abox `releases/` (Experienced track — GitOps it).
3. Verify:
   ```bash
   kubectl -n qdrant port-forward svc/qdrant 6333:6333
   curl localhost:6333/collections | jq .
   ```
4. Create test collection + upsert vector to confirm write path.

Deliverable: `artifacts/inventory.txt`, `artifacts/mcpg-tools.json`, `artifacts/qdrant-collections.json`.

## Stage 4 — A2A task comms between 2 agents (Experienced)

1. Build second agent (`agent-peer/`) — different skill (e.g. `translate`, `enrich`).
2. Agent A calls Agent B via A2A client:
   - fetch B's card from `http://agent-b/.well-known/agent.json`
   - submit task `tasks/send` w/ delegated payload
   - poll `tasks/get` OR subscribe SSE
   - merge B's artifact into A's response
3. Deploy both agents in cluster (Deployment + Service + HTTPRoute on agentgateway).
4. End-to-end: client → A → B → response.
5. Capture trace (curl + jq output) in `artifacts/a2a-trace.txt`.

Deliverable: 2 agents source, asciinema of cross-agent task.

## Stage 5 — A2A team w/ kagent agents (Max)

1. Pick 2+ kagent built-in agents (k8s-agent, observability-agent, etc).
2. Expose kagent agents via A2A (kagent supports A2A — verify version; if not, wrap via adapter).
3. Own agent acts as **orchestrator**:
   - receives top-level task (e.g. "diagnose pod CrashLoopBackOff, propose fix, draft post-mortem")
   - splits into subtasks → dispatches via A2A to kagent agents in parallel
   - aggregates artifacts → returns combined response
4. Use a2a Team / multi-agent pattern from spec (parent task w/ child tasks).
5. Deploy orchestrator alongside kagent in cluster.
6. Demo run end-to-end. Capture asciinema.

Deliverable: orchestrator code, team topology diagram, asciinema URL.

## Submission

- Public asciinema recordings (one per stage minimum, OR single full run).
- Add links to top-level `README.md` of lab-04.
- Push all source under `lab-04/`.

## Open questions / risks

- abox Inventory: confirm exact path in repo — may need to write own minimal lister.
- MCPG vs agentgateway: clarify if separate component needed; agentgateway may already cover MCP gateway role.
- kagent A2A native support: check current kagent version compat w/ A2A spec; may need shim.
- LLM cost/latency for Max stage (multi-agent fan-out).
