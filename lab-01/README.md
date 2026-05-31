# Lab-01 — agentgateway + kagent on minikube (Gateway API)

End-to-end local LLM gateway lab. Routes a kagent built-in agent through **agentgateway** (Kubernetes Gateway API LLM provider) to an **in-cluster Ollama** running `llama3.2:1b`. No external API key, no host dependencies. LoadBalancer Services exposed on host via `minikube tunnel`.

## Topology

```
 macOS host
  │  curl http://localhost:8080  ─┐
  │  browser  http://localhost:8082│  (minikube tunnel: LB EXTERNAL-IP=127.0.0.1)
  ▼                                ▼
 minikube node (docker driver)
  │
 Service ai-gw (LoadBalancer, :8080) ── Deployment ai-gw (agentgateway data plane)
  │                                           │
  │      Gateway ai/ai-gw (gatewayClassName: agentgateway)
  │      HTTPRoute ollama-route ──► AgentgatewayBackend ollama
  ▼                                           ▼
 Service ollama.ollama.svc:11434 ── Deployment ollama (llama3.2:1b, emptyDir)

 Service kagent-ui (LoadBalancer, :8082) ── kagent UI ── Agents ─┐
                                                                │ ModelConfig ai-gw-llama
                                                                ▼ baseUrl http://ai-gw.ai.svc:8080/v1
                                                              ai-gw (loop)
```

Traefik is installed as a second `GatewayClass` (`traefik.io/gateway-controller`) for non-LLM ingress and is on `http://localhost/` (404 until routes are added).

## What is deployed

| Component       | Version  | Namespace             | Purpose                                              |
|-----------------|----------|-----------------------|------------------------------------------------------|
| minikube        | 1.38.1   | —                     | Single-node cluster, docker driver, 4 CPU / 7 GB     |
| Kubernetes      | 1.35.1   | —                     |                                                      |
| Gateway API CRDs| v1.5.1   | cluster-scope         | Experimental channel (Traefik 3.7 needs it)          |
| cert-manager    | latest   | cert-manager          | TLS issuance, self-signed `ClusterIssuer`            |
| Traefik         | v3.7.1   | traefik               | GatewayClass `traefik`, LB :80/:443                  |
| Ollama          | latest   | ollama                | LLM runtime, `llama3.2:1b` in emptyDir               |
| agentgateway    | v1.2.1   | agentgateway-system   | GatewayClass `agentgateway` controller               |
| ai-gw           | v1.2.1   | ai                    | agentgateway data plane Deployment + LB :8080        |
| kagent          | v0.9.4   | kagent                | Controller + UI + 10 built-in agents + Postgres      |

## Files

```
lab-01/
├── README.md                      # this file
├── tasks.md                       # step-by-step plan (history of decisions)
├── research-1.md                  # ADR review template (S&T DevOps Bot)
├── kind-config.yaml               # legacy kind config (no longer used; retained for reference)
└── manifests/
    ├── cluster-issuer.yaml        # cert-manager self-signed ClusterIssuer
    ├── ollama.yaml                # ns + Deployment + Service
    ├── agentgateway-route.yaml    # AgentgatewayBackend + Gateway + HTTPRoute
    ├── kagent-modelconfig.yaml    # ModelConfig pointing at ai-gw
    └── metallb-pool.yaml          # legacy MetalLB pool (kind path; unused on minikube)
```

## Bring-up

### 0. Start cluster

```bash
brew install minikube
minikube start --profile=lab-01 --driver=docker --cpus=4 --memory=7000 --kubernetes-version=stable
kubectl config use-context lab-01
```

### 1. Gateway API experimental CRDs

```bash
kubectl delete validatingadmissionpolicybinding safe-upgrades.gateway.networking.k8s.io --ignore-not-found
kubectl delete validatingadmissionpolicy        safe-upgrades.gateway.networking.k8s.io --ignore-not-found
kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.5.1/experimental-install.yaml || true
# httproutes CRD too large for apply (256 KiB annotation limit) — use create:
curl -sL https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.5.1/experimental-install.yaml -o /tmp/gw.yaml
awk 'BEGIN{RS="---\n"} /name: httproutes\.gateway\.networking\.k8s\.io/ {print "---"; print}' /tmp/gw.yaml \
  | kubectl create -f -
```

### 2. cert-manager

```bash
helm repo add jetstack https://charts.jetstack.io && helm repo update
helm install cert-manager jetstack/cert-manager \
  -n cert-manager --create-namespace --set crds.enabled=true --wait
kubectl apply -f manifests/cluster-issuer.yaml
```

### 3. Traefik (second GatewayClass, optional)

```bash
helm repo add traefik https://traefik.github.io/charts && helm repo update
helm install traefik traefik/traefik -n traefik --create-namespace \
  --set providers.kubernetesGateway.enabled=true \
  --set gateway.enabled=false \
  --set service.type=LoadBalancer --wait
```

### 4. Ollama + model

```bash
kubectl apply -f manifests/ollama.yaml
kubectl -n ollama rollout status deploy/ollama
kubectl -n ollama exec deploy/ollama -- ollama pull llama3.2:1b
```

### 5. agentgateway + route

```bash
helm upgrade -i --create-namespace -n agentgateway-system \
  agentgateway-crds oci://cr.agentgateway.dev/charts/agentgateway-crds --version v1.2.1
helm upgrade -i -n agentgateway-system \
  agentgateway oci://cr.agentgateway.dev/charts/agentgateway --version v1.2.1 --wait
kubectl apply -f manifests/agentgateway-route.yaml
```

### 6. kagent + custom ModelConfig

```bash
helm install kagent-crds oci://ghcr.io/kagent-dev/kagent/helm/kagent-crds \
  --version 0.9.4 -n kagent --create-namespace
kubectl -n kagent create secret generic kagent-openai --from-literal=OPENAI_API_KEY=unused
helm install kagent oci://ghcr.io/kagent-dev/kagent/helm/kagent \
  --version 0.9.4 -n kagent --wait
kubectl apply -f manifests/kagent-modelconfig.yaml
kubectl -n kagent patch agent k8s-agent --type merge \
  -p '{"spec":{"declarative":{"modelConfig":"ai-gw-llama"}}}'
# expose UI on host via LB
kubectl -n kagent patch svc kagent-ui --type merge \
  -p '{"spec":{"type":"LoadBalancer","ports":[{"name":"http","port":8082,"targetPort":8080,"protocol":"TCP"}]}}'
```

### 7. Start tunnel for host access

```bash
sudo minikube tunnel --profile=lab-01
```

Tunnel sets `EXTERNAL-IP=127.0.0.1` on every `LoadBalancer` Service, so each LB port is reachable on macOS as `http://localhost:<port>`.

## Host access (verified)

| URL                                                   | Service        | Status |
|--------------------------------------------------------|----------------|--------|
| `http://localhost:8080/v1/chat/completions`           | `ai/ai-gw`     | 200 — OpenAI-compatible LLM via agentgateway → Ollama |
| `http://localhost:8082/`                              | `kagent/kagent-ui` | 200 — kagent dashboard |
| `http://localhost/`                                   | `traefik/traefik` | 404 — Traefik running, no route yet |
| `http://localhost:15000/ui/` (via `kubectl port-forward deploy/ai-gw -n ai 15000:15000`) | agentgateway admin UI | 200 |

### Smoke test (LLM through gateway)

```bash
curl -s -X POST http://localhost:8080/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"llama3.2:1b","messages":[{"role":"user","content":"ping"}],"stream":false,"max_tokens":10}'
```

Expected: 200 + `gen_ai.*` request log on `deploy/ai-gw`:
```
http.status=200 protocol=llm gen_ai.provider.name=openai
gen_ai.request.model=llama3.2:1b gen_ai.response.model=llama3.2:1b
gen_ai.usage.input_tokens=N gen_ai.usage.output_tokens=N duration=...
```

### State snapshot

```bash
kubectl get gatewayclass
kubectl get gateway -A
kubectl get httproute -A
kubectl -n ai     get agentgatewaybackend
kubectl -n kagent get modelconfig
kubectl -n kagent get agent k8s-agent -o jsonpath='{.spec.declarative.modelConfig}'
kubectl get svc -A | grep LoadBalancer
```

## Notes / gotchas

- **Why minikube, not kind?** kind on macOS Docker Desktop has no path from host to a LoadBalancer `EXTERNAL-IP` (docker bridge is inside the Docker VM). MetalLB assigns IPs that are only reachable from inside the docker network. `cloud-provider-kind` needs `sudo` to bind low ports. `minikube tunnel` is the simplest solution — one `sudo` command, all LB svcs land on `127.0.0.1`.
- **Tunnel must stay running.** Kill it and LB EXTERNAL-IPs flip back to `<pending>`.
- **Traefik v3.7 needs Gateway API experimental** channel (`BackendTLSPolicy`, `TLSRoute`). Remove the `safe-upgrades` ValidatingAdmissionPolicy (it blocks experimental-over-standard). `httproutes` CRD exceeds the 256 KiB `kubectl apply` annotation limit — use `kubectl create` for that one CRD.
- **agentgateway IS a Gateway API implementation.** LLM data path is `gatewayClassName: agentgateway` — Traefik is NOT in the LLM hop.
- **`AgentgatewayBackend` v1alpha1 schema:** providers live under `spec.ai.groups[].providers[]` with sibling fields `name`, `host`, `port`, `openai.model` (no `provider:` wrapper, no `hostOverride`).
- **kagent default ModelConfig** is `OpenAI / gpt-4.1-mini` and needs a real key. Lab adds `ai-gw-llama` ModelConfig with `openAI.baseUrl=http://ai-gw.ai.svc:8080/v1` + placeholder secret (gateway ignores the key). Per-agent override via `agent.spec.declarative.modelConfig`.
- **Bundled Postgres** in kagent chart is dev-only — emits a warning. Acceptable for lab.
- **Ollama uses `emptyDir`** — model is re-pulled on pod restart.
- **Port plan on host:** 80 (Traefik), 443 (Traefik), 8080 (ai-gw), 8082 (kagent-ui). Tunnel needs these free.

## Cleanup

```bash
# stop tunnel (Ctrl-C in its terminal), then:
minikube delete --profile=lab-01
```
