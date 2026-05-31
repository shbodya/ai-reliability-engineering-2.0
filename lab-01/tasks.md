# Lab-01 Plan

Goal: agentgateway + kagent on **minikube** via Gateway API (Max track). LLM = in-cluster Ollama. Traefik as second Gateway API impl. cert-manager self-signed TLS. Ephemeral kagent. LoadBalancer Services exposed on macOS host via `minikube tunnel`.

## Decisions

- **Cluster:** minikube, single node, docker driver, k8s 1.35.1, 4 CPU / 7000 MB.
- **LLM provider:** Ollama, in-cluster Deployment (CPU). Service `ollama.ollama.svc:11434`. Model `llama3.2:1b`.
- **Gateway API impls:**
  - `agentgateway` (LLM data path).
  - `traefik` (non-LLM ingress, optional).
- **Host LB access:** `sudo minikube tunnel` → every `LoadBalancer` Service gets `EXTERNAL-IP=127.0.0.1` → reachable on `http://localhost:<port>`.
- **TLS:** cert-manager + self-signed `ClusterIssuer`. Plain HTTP for lab.
- **Persistence:** none. kagent uses bundled Postgres (dev-only) + Ollama uses emptyDir.

## Decision history (why minikube?)

1. Started on kind v0.31 (3 nodes, extraPortMappings 80/443).
2. LoadBalancer svcs stayed `<pending>` — kind has no LB controller.
3. Tried MetalLB L2 — assigned `172.22.255.x` IPs, reachable from docker network but **not** from macOS host (Docker Desktop VM isolates the bridge).
4. Tried `cloud-provider-kind` — refused to start without `sudo`; auto-mode blocked.
5. Switched to **minikube** + `minikube tunnel`. One sudo command, all LB svcs on `127.0.0.1`. Works.

## Prereqs

- [x] `brew install minikube` (v1.38.1)
- [x] Docker Desktop running with ≥ 7 GB RAM
- [x] `kubectl`, `helm`, `curl` on PATH

## Stage 0 — Cluster

```
minikube start --profile=lab-01 --driver=docker --cpus=4 --memory=7000 --kubernetes-version=stable
kubectl config use-context lab-01
```

## Stage 1 — Gateway API CRDs (experimental)

Required for Traefik v3.7 (BackendTLSPolicy, TLSRoute).

1. Remove `safe-upgrades` ValidatingAdmissionPolicy if present (blocks experimental over standard).
2. `kubectl apply` experimental manifest. `httproutes` will fail with annotation-too-long.
3. Carve out the httproutes CRD with `awk` and `kubectl create` it.

## Stage 2 — cert-manager

Helm install jetstack/cert-manager with CRDs, then apply `manifests/cluster-issuer.yaml` (self-signed).

## Stage 3 — Traefik (optional second GatewayClass)

Helm install with `providers.kubernetesGateway.enabled=true`, `service.type=LoadBalancer`. Tunnel assigns it `127.0.0.1:80/443`.

## Stage 4 — Ollama in-cluster

Apply `manifests/ollama.yaml` (ns + Deployment + Service), then `ollama pull llama3.2:1b` inside pod.

## Stage 5 — agentgateway + route

1. `helm install agentgateway-crds` (OCI: cr.agentgateway.dev v1.2.1).
2. `helm install agentgateway` (same registry, same version).
3. Apply `manifests/agentgateway-route.yaml` — creates:
   - `Namespace ai`
   - `AgentgatewayBackend ollama` (provider.openai.model=llama3.2:1b, host=ollama.ollama.svc, port=11434)
   - `Gateway ai-gw` (gatewayClassName=agentgateway, listener HTTP :8080)
   - `HTTPRoute ollama-route` (backendRef → AgentgatewayBackend)
4. agentgateway controller spawns `Deployment ai-gw` + `Service ai-gw` (type=LoadBalancer, port 8080).

## Stage 6 — kagent + ModelConfig + agent patch

1. `helm install kagent-crds` (OCI: ghcr.io/kagent-dev v0.9.4).
2. Create placeholder Secret `kagent-openai` (key value unused — agentgateway ignores it).
3. `helm install kagent`.
4. Apply `manifests/kagent-modelconfig.yaml` → `ModelConfig ai-gw-llama` with `openAI.baseUrl=http://ai-gw.ai.svc:8080/v1`.
5. Patch `agent k8s-agent` → `spec.declarative.modelConfig: ai-gw-llama`.
6. Patch `svc kagent-ui` → `type=LoadBalancer`, port `8082` (avoid 8080 collision with ai-gw).

## Stage 7 — Tunnel + host verification

1. In a separate terminal: `sudo minikube tunnel --profile=lab-01`.
2. Confirm EXTERNAL-IPs:
   ```
   kubectl get svc -A | grep LoadBalancer
   ```
   Expect: ai-gw, kagent-ui, traefik all show `127.0.0.1`.
3. Host smoke:
   ```
   curl -s -X POST http://localhost:8080/v1/chat/completions \
     -H 'Content-Type: application/json' \
     -d '{"model":"llama3.2:1b","messages":[{"role":"user","content":"ping"}],"stream":false,"max_tokens":10}'
   curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8082/
   curl -s -o /dev/null -w "%{http_code}\n" http://localhost/
   ```
   All return 200 / valid JSON (Traefik 404 is fine — no route yet).
4. agentgateway admin UI (no LB by default):
   ```
   kubectl -n ai port-forward deploy/ai-gw 15000:15000
   open http://localhost:15000/ui/
   ```

## Stage 8 — Verification checklist

- [x] `kubectl get gatewayclass` — both `agentgateway` and `traefik` Accepted=True
- [x] `kubectl get gateway -A` — `ai/ai-gw` Programmed=True
- [x] `kubectl get httproute -A` — `ai/ollama-route` present
- [x] `kubectl -n ai get agentgatewaybackend` — `ollama` Accepted=True
- [x] `kubectl get clusterissuer` — `selfsigned` Ready=True
- [x] `kubectl -n kagent get modelconfig` — `ai-gw-llama` listed
- [x] In-cluster LLM call returns 200 + token usage
- [x] Host LLM call returns 200 + token usage
- [x] kagent UI on `http://localhost:8082/` returns 200
- [x] agentgateway admin UI on `http://localhost:15000/ui/` returns 200
- [ ] Drive a real conversation through kagent UI; see request appear in agentgateway logs (`gen_ai.*`)
- [ ] Apply rate-limit `AgentgatewayPolicy`; verify 429

## Stage 9 — Research-1: ADR review (S&T DevOps Bot/Agent)

1. Read project ADR.
2. Map ADR decisions vs Lab observations (Gateway API, model routing, policies).
3. Draft questions: scope, model-routing strategy, secret mgmt, multi-tenant, observability, fallback/retry, cost controls, eval harness.
4. Improvements proposal: adopt Gateway API, policy-as-code, prompt caching, audit trail, eval pipeline.
5. Output: `research-1.md` (already drafted).

## Cleanup

```
# stop tunnel (Ctrl-C in its terminal)
minikube delete --profile=lab-01
```

## Risks / Notes

- minikube tunnel needs sudo every time. Stays foreground.
- Single-node minikube — no scheduling realism; fine for lab.
- Ollama emptyDir → model re-pulled on pod restart.
- Traefik v3.7 deprecation warning is harmless; chart will drop Gateway API CRD shipping next major.
- agentgateway controller owns `Service ai-gw`. Manual patches to its spec may be reconciled away. Configure via `Gateway` listener / `AgentgatewayParameters` instead when possible.
- kagent bundled Postgres = data loss on pod restart; for prod set `database.postgres.url`.
- kind path (extraPortMappings, MetalLB, CPK) is documented in decision history for context — not used here.
