# Lab-02 Plan

Goal: deploy abox (`github.com/den-vasyliev/abox`) → add MCP tool server + Agent in kagent. Max track = own KMCP-built MCP + ship via abox's gitless OCI flow.

## What abox gives us

- **Cluster**: KinD (1 cp + 2 worker) provisioned by OpenTofu (`bootstrap/`).
- **LB**: `cloud-provider-kind` → real IPs for `Service type=LoadBalancer`.
- **GitOps**: Flux Operator + `FluxInstance` + `ResourceSetInputProvider` (RSIP) polling `oci://ghcr.io/den-vasyliev/abox/releases` (lexicographic tag sort, watch v*.*.9 → bump minor).
- **CRDs**: gateway-api, agentgateway, kagent (HelmReleases in `releases/crds/`, `wait: true`).
- **Apps**: agentgateway v2.2.1 (Gateway + GatewayClass), kagent (runtime + HTTPRoute), `dependsOn: releases-crds`.
- **No LLM provider** included — must add (Ollama in-cluster or external API).
- **No MCP** included — lab-02 work.

## Track map

- **Beginner (cert)**: Stage 0 abox up → Stage 1 UIs → Stage 2 model → Stage 3 MCP+Agent via `kubectl apply`.
- **Experienced**: Stage 0–2 → Stage 4 fork abox, add MCP+Agent manifests to `releases/`, `make push` → OCI reconcile.
- **Max**: Stage 4 + Stage 5 own MCP server built w/ KMCP, image pushed to ghcr, manifests via abox OCI flow.

## Prereqs

- [ ] Docker Desktop ≥ 7 GB RAM (KinD + 3 nodes).
- [ ] `gh` CLI auth'd (fork abox).
- [ ] `kubectl`, `helm`, `flux`, `kind` on PATH (Makefile installs `tofu` + `k9s`).
- [ ] `kmcp` CLI (Max only). Install: `brew install kagent-dev/tap/kmcp` or release binary.
- [ ] ghcr.io PAT scope `write:packages` + `read:packages` (Experienced/Max).
- [ ] Stop lab-01 minikube + tunnel to free ports 80/443/8080.

## Stage 0 — abox up

```bash
cd ~/Documents/homelab
git clone https://github.com/den-vasyliev/abox.git
cd abox
make tools   # installs OpenTofu + k9s
make run     # KinD + Flux bootstrap + reconcile releases/
```

Verify:
```bash
kubectl get gateway,httproute -A
kubectl get agents -n kagent
kubectl get svc -n agentgateway-system   # note LB IP
kubectl get fluxinstance,resourceset,resourcesetinputprovider -A
kubectl get ocirepository,kustomization,helmrelease -A
```

Expect: `releases-crds` + `releases` Kustomizations Ready=True, agentgateway HelmRelease Ready=True, kagent HelmRelease Ready=True.

## Stage 1 — UI access (Flux, Kagent, agentgateway)

1. **agentgateway data plane LB IP**: `kubectl get svc -n agentgateway-system <gw-svc> -o jsonpath='{.status.loadBalancer.ingress[0].ip}'`. Hit `http://<ip>/`.
2. **agentgateway admin UI**: `kubectl -n agentgateway-system port-forward deploy/<gw-deploy> 15000:15000` → `http://localhost:15000/ui/`.
3. **Kagent UI**:
   - Patch `svc/kagent-ui -n kagent → type=LoadBalancer` (or port-forward 8082).
   - `kubectl get svc -n kagent kagent-ui` → IP. Open `http://<ip>:80` (or PF URL).
4. **Flux UI** (not in abox — add Weave GitOps OSS):
   - `helm repo add ww https://helm.gitops.weave.works && helm repo update`
   - `helm upgrade -i ww-gitops ww/weave-gitops -n flux-system --set adminUser.create=true --set adminUser.username=admin --set adminUser.passwordHash="$(gitops get bcrypt-hash <<<admin)"`
   - Expose: patch svc → LoadBalancer port 9001.
   - Login admin/admin → confirm sources `releases`, `releases-crds` Ready.

Verify: 3 UIs reachable, kagent UI lists no agents yet (or just `k8s-agent`).

## Stage 2 — Model (ModelConfig)

abox has no LLM. Pick one:

**Option A — in-cluster Ollama** (re-use lab-01 pattern):
```bash
kubectl apply -f ../ai-reliability-engineering-2.0/lab-01/manifests/ollama.yaml
kubectl -n ollama exec deploy/ollama -- ollama pull llama3.2:1b
```
Then declare `AgentgatewayBackend` + `HTTPRoute` to route `/v1/...` to ollama, and `ModelConfig` pointing kagent at `http://<gw-svc>.<gw-ns>.svc/v1`.

**Option B — external API** (OpenAI/Anthropic): create Secret w/ key, `ModelConfig` w/ `openAI.apiKey` ref + `baseUrl=https://api.openai.com/v1`.

Default = A (matches lab-01).

Verify:
```bash
kubectl -n kagent get modelconfig
curl -s http://<gw-ip>/v1/chat/completions -H 'Content-Type: application/json' \
  -d '{"model":"llama3.2:1b","messages":[{"role":"user","content":"ping"}],"max_tokens":5}'
```

## Stage 3 — Declarative MCP + Agent (Beginner cert exit)

Use stock MCP image (`mcp/everything` or kagent's filesystem MCP) — zero code.

1. `lab-02/manifests/mcp-everything.yaml`:
   - `MCPServer` (kagent CRD) `name: mcp-everything`, image, transport=stdio/sse.
   - Confirm CRD shape: `kubectl explain mcpserver.spec`.
2. `lab-02/manifests/agent-mcp.yaml`:
   - `Agent name: mcp-demo`, `spec.declarative.modelConfig: <Stage 2 name>`, `spec.declarative.tools: [{type: McpServer, mcpServer: {ref: mcp-everything}}]`.
3. Apply:
   ```bash
   kubectl apply -f lab-02/manifests/
   kubectl -n kagent get mcpserver,agent
   ```
4. Kagent UI → chat `mcp-demo` → trigger a tool → see invocation.
5. agentgateway logs: `kubectl -n agentgateway-system logs deploy/<gw> | grep gen_ai`.

**Beginner deliverable**: screenshots of 3 UIs + tool round-trip.

## Stage 4 — Experienced: ship via abox OCI flow

abox publishes `releases/` as OCI artifact on `v*` tag. Fork → add manifests → `make push` → cluster reconciles. No git polling.

1. Fork `den-vasyliev/abox` → clone fork → set `origin` to fork.
2. Edit `releases/`:
   - Add `releases/mcp-everything.yaml` (MCPServer + any Backend/Route).
   - Add `releases/agent-mcp.yaml` (Agent).
   - Add `releases/modelconfig.yaml` (if Stage 2 not already in cluster).
   - Add entries to `releases/kustomization.yaml`.
3. Bump CI workflow secrets: `GHCR_USERNAME`, `GHCR_TOKEN` (or rely on `GITHUB_TOKEN` if workflow uses it).
4. RSIP in `bootstrap/` points at `ghcr.io/den-vasyliev/abox/releases` — change to `ghcr.io/<your-user>/abox/releases`. Re-`tofu apply` OR edit the RSIP CR in cluster directly:
   ```bash
   kubectl -n flux-system edit resourcesetinputprovider <name>
   ```
5. Delete Stage 3 imperative resources (`kubectl delete -f lab-02/manifests/`).
6. `make push` → CI publishes new tag → RSIP picks it up → Kustomization reconciles → MCP + Agent recreated by Flux.

Verify:
- `flux get sources oci -A` → new revision.
- Weave UI shows reconciliation event.
- Kagent UI: agent reappears w/o `kubectl apply`.

**Experienced deliverable**: PR diff on fork + screenshot of Flux reconciling new tag.

## Stage 5 — Max: own MCP w/ KMCP + abox OCI

### 5a. Scaffold + build

```bash
kmcp init --name lab-mcp --language python   # or go
cd lab-mcp
# add tools, e.g. get_pod_count, current_time
kmcp run                                     # local smoke
kmcp build --image ghcr.io/<u>/lab-mcp:0.1.0 --push
```

### 5b. Ship via abox

1. In fork: `releases/lab-mcp.yaml` → `MCPServer` referencing `ghcr.io/<u>/lab-mcp:0.1.0`.
2. `releases/agent-lab-mcp.yaml` → `Agent` w/ tool ref → `lab-mcp`.
3. Add to `releases/kustomization.yaml`.
4. ghcr pull secret if image private: `kubectl create secret docker-registry ghcr-pull -n kagent ...` and reference in MCPServer/Agent pod spec (or via HelmRelease values overlay).
5. `make push` → reconcile.

### 5c. Iterate

- Edit tool → `kmcp build --image ghcr.io/<u>/lab-mcp:0.1.1 --push`.
- Bump image tag in `releases/lab-mcp.yaml`.
- `make push` → cluster pulls new image, restarts MCPServer pod.

### 5d. Verify

- `kubectl -n kagent get mcpserver lab-mcp -o yaml` → status Ready.
- Kagent UI → chat agent → call custom tool → tool JSON in response.
- agentgateway logs show MCP span w/ tool name.

**Max deliverable**: KMCP repo + fork of abox w/ `releases/lab-mcp*.yaml` + screenshot of custom tool call.

## Stage 6 — Verification checklist

- [ ] `flux get all -A` clean
- [ ] `kubectl get gateway,httproute -A` Programmed=True
- [ ] `kubectl -n kagent get mcpserver,agent,modelconfig` all Ready
- [ ] 3 UIs reachable (Flux/Weave, Kagent, agentgateway admin)
- [ ] LLM call round-trip via gateway IP (200 + tokens)
- [ ] MCP tool invocation visible in agentgateway logs (`gen_ai.tool.*`)
- [ ] (Exp/Max) `make push` → new RSIP revision → cluster reconciles w/o `kubectl apply`

## Cleanup

```bash
cd abox && make down    # tofu destroy → KinD cluster gone
```

## Risks / Notes

- KinD + cloud-provider-kind may need `sudo` on first run; abox script handles.
- RSIP lex sort: `v0.0.10 < v0.0.9` — bump minor when patch hits 9. Watch for this when iterating MCP image.
- abox `releases-crds` Kustomization is `wait: true` + `dependsOn` enforced. Don't reorder.
- agentgateway v2.2.1 in abox ≠ lab-01's v1.2.1. CRD field names may differ — recheck `AgentgatewayBackend` / route shape before copying lab-01 manifests.
- kagent MCP CRD field names version-dependent. Always `kubectl explain` first.
- Forking RSIP target: easier to patch the CR in-cluster than rerun tofu. Either works.
- KMCP image private by default on ghcr → make public OR add pull secret to kagent ns.
- Ollama on KinD: 3 nodes, schedule pod on worker w/ enough RAM (`llama3.2:1b` ≈ 1.5 GB).
- abox CI workflow `.github/workflows/flux-push.yaml` requires push perm on ghcr packages — confirm token scope before first `make push`.
