# Lab-02 — abox + Kagent MCP + Gitless GitOps

End-to-end run of [den-vasyliev/abox](https://github.com/den-vasyliev/abox) (KinD + Flux Operator + agentgateway + kagent) extended with an in-cluster LLM, a stock MCP tool server, and a custom KMCP-built MCP server shipped via OCI artifact (no Git polling).

Covers all three tracks from `task.md`:

- **Beginner (cert):** abox up, UI access, declarative MCP + Agent.
- **Experienced:** same deployed via Flux from an OCI artifact (GitlessOps).
- **Max:** custom MCP server scaffolded with [KMCP](https://github.com/kagent-dev/kmcp), built, pushed, and consumed by an Agent.

## Stack

| Layer | Component | Version |
|---|---|---|
| Cluster | KinD (1 control-plane + 2 workers) | k8s v1.35 |
| LB | cloud-provider-kind | v0.6.0 |
| GitOps | Flux Operator + FluxInstance + RSIP polling `oci://ghcr.io/den-vasyliev/abox/releases` | flux 2.x |
| Gateway | agentgateway (`agentgateway-external` Gateway, IP `172.22.0.5`) | v2.2.1 |
| Agents | kagent (controller, UI, KMCP controller, 6 stock agents) | 0.7.23 |
| LLM | Ollama in-cluster, `llama3.2:1b` | — |
| MCP | `mcp-server-fetch` (stdio via uvx) + custom `lab-mcp` (FastMCP Python) | — |

## Repo layout (this lab)

```
lab-02/
├── README.md              # this file
├── task.md                # original Ukrainian task brief
├── tasks.md               # step-by-step plan
├── manifests/             # imperative copies (kubectl apply path)
│   ├── ollama.yaml
│   ├── backend-ollama.yaml
│   ├── modelconfig.yaml
│   └── mcp-fetch.yaml
├── flux/
│   └── lab-02-source.yaml # OCIRepository + Kustomization in cluster
├── oci-bundle/            # source for the OCI artifact pushed to ghcr
│   ├── kustomization.yaml
│   ├── ollama.yaml
│   ├── backend-ollama.yaml
│   ├── modelconfig.yaml
│   ├── mcp-fetch.yaml
│   ├── lab-mcp.yaml
│   └── lab-mcp-rbac.yaml
└── lab-mcp/               # KMCP-scaffolded Python MCP server
    ├── kmcp.yaml
    ├── Dockerfile
    ├── pyproject.toml
    └── src/
        ├── main.py
        ├── core/
        └── tools/
            ├── echo.py          # scaffold default
            ├── current_time.py  # custom
            └── pod_count.py     # custom
```

## What was done

### Stage 0 — abox up
- `git clone https://github.com/den-vasyliev/abox.git`
- `make tools` (OpenTofu via `tenv`, k9s)
- `cd bootstrap && tofu init && tofu apply -auto-approve`
  - creates KinD cluster `abox`
  - installs Flux Operator + FluxInstance
  - installs `ResourceSetInputProvider` polling `oci://ghcr.io/den-vasyliev/abox/releases`
  - installs `ResourceSet` that materialises `OCIRepository` + two `Kustomization` objects (`releases-crds`, `releases`)
- `sudo nohup cloud-provider-kind &` — gives LoadBalancer Services real IPs
- Flux reconciled to abox releases tag `0.5.7` → agentgateway 2.2.1, kagent 0.7.23, gateway-api 1.4.0 CRDs.

Cluster end-state:
```
kubectl get gateway,httproute -A
# agentgateway-system  gateway/agentgateway-external  agentgateway  172.22.0.5  PROGRAMMED=True
# kagent               httproute/kagent
```

### Stage 1 — UI access
- **Kagent UI** is already exposed: kagent's `HTTPRoute` attaches to `agentgateway-external` with `/` → `kagent-ui:8080` and `/api` → `kagent-controller:8083`. → `http://172.22.0.5/` returns 200.
- **agentgateway admin UI** runs on `127.0.0.1:15000` inside the gateway pod (not exposed by abox). Use `kubectl -n agentgateway-system port-forward deploy/agentgateway-external 15000:15000` → `http://localhost:15000/ui/`.
- **Flux UI:** abox doesn't ship one. `flux get all -A` CLI is the source of truth. Capacitor / Weave GitOps can be added later (require an OCI/Helm chart that's currently behind auth or non-trivial config).

### Stage 2 — Model (Ollama via agentgateway)
- Applied `manifests/ollama.yaml` — namespace `ollama`, Deployment, Service.
- `ollama pull llama3.2:1b` inside the pod.
- `AgentgatewayBackend` (`ollama.ollama`) wraps Ollama as an OpenAI-compatible LLM provider:
  ```yaml
  spec:
    ai:
      provider:
        openai: { model: llama3.2:1b }
        host: ollama.ollama.svc.cluster.local
        port: 11434
  ```
- `HTTPRoute` `/v1` → that backend, attached to `agentgateway-external`.
- `ModelConfig` `ollama-via-gw` (provider `OpenAI`, `baseUrl=http://agentgateway-external.agentgateway-system.svc.cluster.local/v1`).

Smoke test:
```bash
curl -X POST http://172.22.0.5/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"llama3.2:1b","messages":[{"role":"user","content":"reply OK"}],"max_tokens":3}'
# {"choices":[{"message":{"content":"OK.","role":"assistant"} ...}], "usage":{...}}
```

### Stage 3 — Declarative MCP + Agent (Beginner cert exit)
- `MCPServer mcp-fetch`: stock `mcp-server-fetch` Python tool, image `ghcr.io/astral-sh/uv:python3.12-bookworm-slim`, run via `uvx mcp-server-fetch`, stdio transport. Kagent injects a sidecar agentgateway that exposes the stdio tool as HTTP `/mcp` inside the cluster.
- `Agent mcp-demo`: `modelConfig=ollama-via-gw`, single tool `fetch` from `mcp-fetch`.

Both Ready, `mcp-demo` A2A agent card responds:
```bash
kubectl -n kagent port-forward svc/mcp-demo 18080:8080
curl http://localhost:18080/.well-known/agent.json
```

### Stage 4 — Gitless GitOps via OCI
- `oci-bundle/` collects every cluster-side YAML for lab-02 (Ollama, Backend, HTTPRoute, ModelConfig, mcp-fetch).
- Pushed as OCI artifact via `flux push artifact`:
  ```
  flux push artifact \
    oci://ghcr.io/shbodya/ai-reliability-engineering-2.0/lab-02:0.1.0 \
    --path lab-02/oci-bundle \
    --source https://github.com/shbodya/ai-reliability-engineering-2.0 \
    --revision "main@$(git rev-parse --short HEAD)" \
    --creds shbodya:$(gh auth token)
  ```
- Pull secret: `flux create secret oci ghcr-lab02 --url=ghcr.io --username=shbodya --password=$(gh auth token)`.
- In-cluster source + target (`flux/lab-02-source.yaml`):
  - `OCIRepository lab-02` (`tag=0.1.0`, `secretRef=ghcr-lab02`)
  - `Kustomization lab-02` (path `./`, `prune=true`, `wait=true`)
- After apply, every lab-02 resource gets the Flux labels `kustomize.toolkit.fluxcd.io/{name,namespace}=lab-02/flux-system`. Imperative state was adopted via SSA; Flux is the sole owner.

No `git` repo or CI involved — the workflow is `push artifact → bump tag → reconcile`.

### Stage 5 — Custom MCP with KMCP (Max)
- `kmcp init python lab-mcp` — FastMCP-Python project with auto tool discovery from `src/tools/*.py`.
- Two custom tools added with `kmcp add-tool`:
  - `current_time()` → ISO-8601 UTC.
  - `pod_count(namespace)` → counts pods using the SA token at `/var/run/secrets/kubernetes.io/serviceaccount` against `https://kubernetes.default.svc/api/v1/namespaces/{ns}/pods`.
- `kmcp build -t ghcr.io/shbodya/ai-reliability-engineering-2.0/lab-mcp:0.1.0 --kind-load --kind-load-cluster abox` — builds the image and side-loads it into every KinD node so the cluster can use it even if the registry copy is private.
- `docker push` to ghcr (registry copy kept for future clusters / for completeness).
- `oci-bundle/lab-mcp.yaml`: `MCPServer lab-mcp` referencing the image, stdio transport; `Agent lab-mcp-agent` (model `ollama-via-gw`, tools `current_time` + `pod_count`).
- `oci-bundle/lab-mcp-rbac.yaml`: `ClusterRole` + `ClusterRoleBinding` granting `get,list pods` to the SA `lab-mcp` (created by the kmcp controller for the MCP pod).
- Pushed artifact `0.1.2` → bumped `OCIRepository.spec.ref.tag` → `flux reconcile`.

Direct MCP verification (port-forward `svc/lab-mcp:8080` → `/mcp`, JSON-RPC):
```
tools/list  → echo, current_time, pod_count
current_time({})            → "2026-05-31T18:12:24.070970+00:00"
pod_count({"namespace":"kagent"})  → "kagent: 15 pods"
pod_count({"namespace":"ollama"})  → "ollama: 1 pods"
```

### Stage 6 — Verification

| Check | Result |
|---|---|
| `flux get all -A` (releases, releases-crds, lab-02) | all `Ready=True` |
| `kubectl get gateway,httproute -A` | `agentgateway-external Programmed=True`, routes for kagent/ollama |
| `kubectl -n kagent get modelconfig,mcpserver,agent` | `ollama-via-gw`, `mcp-fetch`, `lab-mcp` Ready; `mcp-demo`, `lab-mcp-agent` Ready |
| LLM round-trip via `http://172.22.0.5/v1/chat/completions` | 200 + usage tokens |
| MCP `tools/call current_time` | returns ISO-8601 UTC |
| MCP `tools/call pod_count` | returns correct count after RBAC |
| Bump artifact tag → `flux reconcile` → cluster updates | observed on 0.1.0 → 0.1.1 → 0.1.2 |

## Known limitations / open items

- **agentgateway admin UI** is not exposed by abox (config map is empty). Port-forward to reach.
- **Flux UI:** none installed. Capacitor's OCI chart is currently behind anon-pull denial and its self-host YAML needs an external auth ConfigMap+Secret; left for a follow-up.
- **A2A through `lab-mcp-agent`:** `llama3.2:1b` is too small to consistently emit tool-call JSON — it hallucinated a tool descriptor instead of invoking. The MCP layer is fine (verified by raw JSON-RPC). For a clean LLM-driven tool call, point `ModelConfig` at OpenAI / Anthropic / a larger Ollama model.
- **Container image visibility:** `ghcr.io/shbodya/ai-reliability-engineering-2.0/lab-mcp` was kept private. Cluster uses the `kind load` copy. To run on a fresh cluster, either make the package public (`gh api -X PATCH .../packages/container/...`) or add an imagePullSecret.
- **abox RSIP** still points at `oci://ghcr.io/den-vasyliev/abox/releases`. Lab-02 added its own `OCIRepository` rather than forking the abox CI flow.

## Commands cheat sheet

Bootstrap:
```bash
git clone https://github.com/den-vasyliev/abox.git
cd abox && make tools
cd bootstrap && tofu init && tofu apply -auto-approve
sudo nohup /tmp/cloud-provider-kind > /tmp/cpk.log 2>&1 &
```

Ship a new lab-02 bundle revision:
```bash
flux push artifact \
  oci://ghcr.io/shbodya/ai-reliability-engineering-2.0/lab-02:<tag> \
  --path lab-02/oci-bundle \
  --source https://github.com/shbodya/ai-reliability-engineering-2.0 \
  --revision "main@$(date +%Y%m%d-%H%M%S)" \
  --creds shbodya:$(gh auth token)

kubectl -n flux-system patch ocirepository lab-02 \
  --type merge -p '{"spec":{"ref":{"tag":"<tag>"}}}'

flux reconcile kustomization -n flux-system lab-02 --with-source
```

Rebuild + redeploy the KMCP server:
```bash
cd lab-02/lab-mcp
# edit src/tools/*.py
kmcp build -t ghcr.io/shbodya/ai-reliability-engineering-2.0/lab-mcp:<tag> \
  --kind-load --kind-load-cluster abox --push
# bump image tag in oci-bundle/lab-mcp.yaml, then push a new lab-02 artifact tag.
```

Teardown:
```bash
cd abox && make down       # tofu destroy → KinD gone
sudo pkill cloud-provider-kind
```
