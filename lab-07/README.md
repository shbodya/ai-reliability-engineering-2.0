# Lab-07 — Final / "Vin's Questions"

Research-style answers to a real customer/interviewer questionnaire about the
AI-infrastructure stack we've been building across labs 01–04: **kagent +
agentgateway / kgateway + Ollama (and optionally vLLM / llm-d) on Kubernetes,
served through the Gateway API**.

Each answer is grounded in (a) what the stack actually offers today and (b)
how it maps onto the lab setup (`lab-01` agentgateway+kagent, `lab-02` MCP
server, `lab-04` A2A team). Where the question targets a project we have not
deployed yet (`kgateway`, `vLLM`, `llm-d`, `fastmcp`), the answer is research
+ "what would change if we wired it in".

---

## 1. How could we handle "agent got stuck" scenarios?

Three independent layers, each catching a different failure mode:

| Layer | Mechanism | Catches |
|---|---|---|
| **Pod / process** | `livenessProbe` + `readinessProbe` on the agent Deployment; `terminationGracePeriodSeconds`; `activeDeadlineSeconds` on Jobs | crashed runtime, deadlocked event loop |
| **Request / route** | `HTTPRoute` + `BackendTrafficPolicy` (agentgateway) / Envoy `route.timeout`, `idle_timeout`, `per_try_timeout`; retries with budget | hung upstream LLM call, slow MCP tool |
| **Agent task** | A2A task lifecycle — `TaskStatusUpdateEvent(state=working)` heartbeat, client-driven `tasks/cancel`; kagent `Agent` CR `spec.timeoutSeconds`; LangGraph/Autogen step timeout | infinite tool-loop, runaway reasoning |

In practice for our stack:

- **A2A heartbeat** — `agent-own` already emits periodic `working` events
  (lab-04). A watchdog on the orchestrator side cancels the task if no
  heartbeat arrives within N seconds.
- **agentgateway HTTPRoute** — set `spec.rules[].timeouts.request` and
  `backendRequest` (Gateway API v1 timeouts) on the route to the agent
  Service. Default Envoy idle timeout (1 h) is too generous for an agent.
- **kagent Agent CR** — bound max steps / max tokens via the agent's
  ModelConfig + system prompt; surface "stuck" as a metric.

Recovery: `kubectl rollout restart deploy/<agent>` is brutal but safe; a
better pattern is a sidecar / controller that emits a Kubernetes `Event` and
flips readiness so the gateway drains traffic.

---

## 2. Any automatic timeout / circuit-breaker patterns coming out of this framework?

Yes — agentgateway and kgateway both ride on **Envoy**, so the full
circuit-breaker / outlier-detection surface is available out of the box:

- **Timeouts** — Gateway API v1 `HTTPRoute.spec.rules[].timeouts.request` and
  `backendRequest`; per-try timeout on retries.
- **Retries** — `BackendTrafficPolicy` (kgateway) / `TrafficPolicy`
  (agentgateway) with `numRetries`, `retryOn`, `perTryTimeout`, retry budget.
- **Circuit breaker** — `connectionPool.http.maxRequests`,
  `maxPendingRequests`, `maxConnections`; opens when the upstream is
  saturated.
- **Outlier detection** — eject backend endpoints after N consecutive 5xx /
  gateway errors (e.g. an Ollama replica that OOMs).
- **Rate limit** — `RateLimitPolicy` (local token-bucket and/or global via
  Redis); for AI specifically kgateway has **AI rate limit by tokens**, not
  only by requests.

What's **agent-specific** on top of Envoy:

- kgateway **AI BackendPolicy** — request transformation, prompt guard
  (PII / regex), **token-based rate limiting** per `x-user-id`, response
  streaming budget.
- kagent — no first-class circuit breaker yet; relies on the gateway in
  front of it.

Default rule of thumb in our lab: always pair an `HTTPRoute` with a
`BackendTrafficPolicy` that sets `timeouts`, `retries (max 2, on 5xx,
reset, connect-failure)`, and `outlierDetection`.

---

## 3. How does kgateway handle model failover?

kgateway's **AI gateway** ([kgateway.dev](https://kgateway.dev)) models
upstream LLMs as a typed `Backend` of kind `AI`. A single `Backend` can
declare **multiple providers** with **priority groups**:

```yaml
apiVersion: gateway.kgateway.dev/v1alpha1
kind: Backend
metadata: { name: llm-pool }
spec:
  type: AI
  ai:
    multipool:
      priorities:
      - pool:                       # priority 0 — try first
        - provider:
            openai:
              authToken: { kind: SecretRef, secretRef: { name: openai } }
              model: gpt-4o-mini
      - pool:                       # priority 1 — fallback
        - provider:
            anthropic:
              authToken: { kind: SecretRef, secretRef: { name: anthropic } }
              model: claude-3-7-sonnet
      - pool:                       # priority 2 — local fallback
        - provider:
            openai:                 # OpenAI-compatible (vLLM / Ollama)
              authToken: { kind: SecretRef, secretRef: { name: local } }
              customHost: { host: ollama.ollama.svc, port: 11434 }
              model: llama3.2:1b
```

On a **retriable** failure (5xx, timeout, configured `retryOn` codes) the
gateway falls through priorities. Inside a pool, weighted load balancing
applies. Combined with `BackendTrafficPolicy.retries` + `outlierDetection`,
that gives provider-level failover without changing the client.

Caveat: failover is **best-effort** — semantics differ across providers
(streaming chunks already sent are not replayable), so retries should
generally fire **before** the first byte to the client.

---

## 4. Can we automatically switch from OpenAI → Claude → local model?

Yes — same mechanism as Q3. Two flavors:

- **Failover** (priority list above) — provider B is used only when A
  fails / is ejected by outlier detection.
- **Active routing** — `HTTPRoute` rules + headers / weights:
  - header-based (`x-model: cheap` → local; `x-model: premium` → Claude),
  - weight-based canary (90 % OpenAI / 10 % Claude),
  - cost-based: a small request-transform Lua/Wasm filter inspects
    estimated token count and picks the cheaper backend.

For our lab-01 setup, "Ollama only" is just the priority-2 pool; adding
OpenAI is a Secret + one extra `provider:` entry; the agents (kagent
ModelConfig pointing at `ai-gw`) need no code change because the gateway
exposes the **OpenAI-compatible** schema.

---

## 5. Could we seamlessly handle the response formats from these providers?

Largely yes, with caveats.

- kgateway / agentgateway **normalize on the OpenAI Chat Completions
  schema** in and out. Anthropic Messages, Gemini, Bedrock are mapped to/from
  it by the gateway's AI filter. Streaming SSE works across providers.
- **Tool / function calls** — OpenAI `tools[]` vs Anthropic `tool_use` vs
  Gemini `functionCall` are mapped, but mapping is **lossy** at edges
  (`tool_choice`, parallel tool calls, JSON-mode strictness).
- **Reasoning / thinking tokens** (Claude `thinking`, OpenAI `o`-series
  reasoning summaries) — not yet uniformly surfaced.
- **Vision / multimodal** — image URL vs base64 differ; mostly handled, but
  document this in agent code.

Recommendation: pin agents to the **OpenAI-compatible** dialect everywhere
(that's what `kagent` ModelConfig + most Python frameworks already speak),
and let the gateway translate. Treat reasoning tokens and vendor-specific
fields as best-effort; don't depend on them in business logic.

---

## 6. Can we version the agents built from kagent?

Yes — versioning happens at **three levels**, none of which kagent invents
(by design — it's "just Kubernetes CRDs"):

1. **Container image** — agent runtime image tag (`agent-own:1.4.2`,
   never `:latest`). Pin a digest in production.
2. **`Agent` CR** — the kagent CRD itself is a versioned k8s object;
   store under Git, deploy via Flux/Argo. Two `Agent` CRs can coexist
   (`agent-own-v1`, `agent-own-v2`) with different model configs / system
   prompts.
3. **ModelConfig** — also a CR; pin model name + provider per environment.

GitOps gives you the audit trail. There's no built-in "kagent agent
version" field, but `metadata.labels.app.kubernetes.io/version` is the
convention and the gateway can route on it (see Q7).

---

## 7. Any blue/green or canary deployment patterns for agents?

Yes — and you get them basically for free because everything is a `Service`
behind an `HTTPRoute`:

- **Canary by weight** — split `HTTPRoute.spec.rules[].backendRefs` 90/10
  between `agent-own-v1` and `agent-own-v2`:

  ```yaml
  backendRefs:
  - { name: agent-own-v1, port: 8000, weight: 90 }
  - { name: agent-own-v2, port: 8000, weight: 10 }
  ```

- **Blue/green** — two Deployments, single Service selector swap, or two
  Services + an `HTTPRoute` whose weights flip from `100/0` to `0/100`.
- **Header / shadow traffic** — `matches: [{ headers: [{ name: x-canary,
  value: "true" }] }]` for opt-in users; `requestMirror` filter for shadow
  traffic to the new version with responses dropped.
- **Progressive delivery controllers** — **Flagger** or **Argo Rollouts**
  drive the weight ramp based on Prometheus SLOs (error rate, p95 latency,
  cost-per-token). Both speak Gateway API natively.

For A2A specifically, the **AgentCard** advertises the in-cluster URL; the
gateway is what flips between versions, so the card stays stable.

---

## 8. What's the fastmcp-python framework mentioned?

[`fastmcp`](https://github.com/jlowin/fastmcp) — a Pythonic, decorator-based
SDK for building **Model Context Protocol** servers (and clients). Originally
a third-party project by Jeremy Lowin; v1 was later upstreamed into the
official `mcp` Python SDK as `mcp.server.fastmcp`. v2 (current) lives
separately and adds: proxying / mounting other MCP servers, OpenAPI →
MCP generation, an `fastmcp` CLI, auth, transport choices (stdio / SSE /
streamable-http), and a test client.

Minimal server:

```python
from fastmcp import FastMCP
mcp = FastMCP("inventory")

@mcp.tool()
def list_skus(prefix: str = "") -> list[str]:
    """Return SKUs from inventory."""
    return [s for s in INVENTORY if s.startswith(prefix)]

if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8000)
```

In lab-02 our MCP server uses this exact pattern; agentgateway then exposes
it as an `MCPRoute` to clients.

---

## 9. Is it the easiest path to MCP?

For **Python**, yes — `fastmcp` is the lowest-friction option today:
decorators, type-hints become the JSON schema, transport is one line. The
alternatives:

| Path | When to pick it |
|---|---|
| **fastmcp** (Python) | Most servers; fastest to start; prod-ready |
| `mcp` SDK directly (Python) | Need full control over lifecycle / capabilities |
| `@modelcontextprotocol/sdk` (TS) | Server lives in a Node stack |
| Rust / Go SDKs | Perf-critical or already in those stacks |
| **agentgateway MCP federation** | You don't write a new server — you expose existing HTTP/OpenAPI/A2A/k8s endpoints as MCP |

Caveats: streamable-http is the path forward, SSE is deprecated; if you
need OAuth in front of MCP, the gateway is the right place (don't bake
auth into every tool).

---

## 10. About FinOps: how much control can I have?

A lot, and it splits cleanly by layer:

| Layer | Control surface | Granularity |
|---|---|---|
| **K8s** | requests/limits, ResourceQuota, namespace cost via **OpenCost / Kubecost** | per ns / per workload |
| **Gateway (kgateway AI)** | token-based rate limit, per-consumer quotas, prompt-guard rejects, model routing by cost | per API key / per user / per route |
| **Provider** | OpenAI / Anthropic usage limits + budget alerts | per org / per key |
| **Agent runtime** | max_tokens, max_steps, tool-call budget, retry caps | per agent / per session |
| **Observability** | Prometheus counters of `tokens_in/out` by `{model, agent, user}`; Grafana dashboards | any dimension you label |

The gateway is the single best chokepoint — it sees every request, can
attribute it, and can refuse it. Everything else is supplementary.

---

## 11. Token-level / per-agent-level

Both, and they compose:

- **Per-token** (cost-shaped) — kgateway AI rate-limit counts **input +
  output tokens** against a bucket per consumer (`x-user-id` /
  `x-api-key`). When the bucket empties, requests get 429. Buckets are
  Redis-backed via Envoy `ratelimit`.
- **Per-agent** — apply a `RateLimitPolicy` at the `HTTPRoute` for that
  agent's Service; that limit is independent of who calls.
- **Per-(agent × user)** — descriptors combine: rate-limit key
  `("agent", "tenant", "user")` gives you a 3-D budget.
- **Per-session** — the agent runtime caps `max_steps` / `max_tokens` per
  conversation; the gateway can't see "session" without a header.

Tokens are denominated, not requests — that's the FinOps win, because a
single 32k-token request costs hundreds of small ones.

---

## 12. Can I implement custom cost controls?

Yes — increasing order of effort:

1. **Declarative policy** — kgateway/agentgateway `RateLimitPolicy` +
   `BackendPolicy` (token limit, prompt guard, response transform). No
   code.
2. **OPA / Rego at the gateway** — `ExtAuthz` filter calls OPA before the
   LLM call; reject by tenant, time window, model, prompt size.
3. **Custom Envoy / Wasm filter** — inspect request, call your billing
   service, set headers, allow/deny. ~50 lines of Rust / Go / AssemblyScript.
4. **Agent-side budget** — wrap the LLM client with a `Budget` object;
   decrement after each call; fail closed when empty.
5. **Webhook controller** — admission webhook that rejects `Agent` /
   `ModelConfig` CRs that ask for too-expensive models in cheap namespaces.

For our lab, (1) + (4) cover ~90 % of needs; (3) is the right place to put
"don't let dev spend > $50/day on GPT-4o".

---

## 13. Per-agent budgets or depth of token limits

Yes to both — combine the policies:

- **Per-agent monthly budget** — Prometheus counter
  `llm_tokens_total{agent="X"}` + an Alertmanager rule + a controller that
  flips the agent's `HTTPRoute` to `503 Budget exceeded` (or to a cheaper
  ModelConfig) when the counter crosses the budget.
- **Depth of conversation** — agent runtime caps `max_steps` (LangGraph
  `recursion_limit`, Autogen `max_turns`); A2A: orchestrator caps
  `tasks/send` retries / fan-out.
- **Tool-call depth** — separately cap `max_tool_calls_per_turn`; many
  "stuck agent" incidents are unbounded tool loops.
- **KV/context depth** — limit input context length at the gateway via
  prompt-guard; long contexts are the dominant cost on most providers.

Practical defaults we'd set for kagent agents: `max_steps=10`,
`max_tokens_per_turn=4096`, gateway token bucket `100k tokens / hour /
user`, prompt-guard reject inputs > 32k tokens.

---

## 14. Is vLLM suitable for agents with many back-and-forth tool calls, or is it better for single-shot inference?

**Suitable, often preferable**, with caveats:

Why it works well for agents:

- **Continuous batching** — vLLM merges in-flight requests every step;
  agents that spray many small turn-by-turn requests are exactly the
  workload that gets the biggest throughput win.
- **PagedAttention + Automatic Prefix Caching (APC)** — repeated system
  prompts and chat history between turns are cached at the block level;
  the second turn of a conversation reuses the KV of the first → big TTFT
  reduction.
- **OpenAI-compatible API**, including `tools[]` and structured outputs —
  drop-in for kagent ModelConfig (`baseUrl: http://vllm.svc/v1`).
- **Speculative decoding** + **chunked prefill** smooth tail latency for
  short tool-result turns.

Caveats:

- **Tool-call accuracy** is model-dependent, not server-dependent — pick a
  base model that's been tool-tuned (Llama 3.1 Instruct, Qwen2.5 Instruct,
  Mistral-Large-Instruct).
- **Session affinity** matters for prefix-cache hits: route the same
  conversation to the same replica (consistent hashing on `session_id`).
  Without affinity, KV cache hits drop and you're back to single-shot
  perf.
- **Cold KV** on the very first request of a session is unchanged from
  single-shot; the win is from turn 2 onward.

Verdict: yes for multi-turn agents, *as long as* you give it session
affinity. That's exactly llm-d's pitch — see Q15.

---

## 15. llm-d's scheduler — does it help when an agent makes 15 LLM calls?

Yes — that's the canonical workload it optimizes for.

[llm-d](https://llm-d.ai) is a Kubernetes-native distributed inference
framework (Red Hat / IBM / Google / Nvidia / CoreWeave) built on **vLLM +
Inference Gateway API**. Its **inference scheduler** is the piece that
differs from a generic Service load-balancer:

- **KV-cache-aware routing** — picks the replica that already holds the
  longest matching **prefix** for this request (system prompt, prior turns,
  RAG-retrieved chunks). For an agent doing 15 calls in the same session,
  calls 2…15 land on the replica that already has calls 1…(N-1) cached.
- **Disaggregated prefill / decode** — heavy prefill (long context) goes to
  prefill-tuned pods; decode (token streaming) goes to decode-tuned pods.
  Multi-turn agents benefit because each turn is mostly decode after the
  first.
- **Session affinity** — explicit via headers, falls back to
  cache-similarity scoring.
- **SLO-driven autoscaling** — scales on tokens-per-second / queue depth,
  not CPU.

Concretely for "agent makes 15 LLM calls":

| Without llm-d (round-robin SVC) | With llm-d scheduler |
|---|---|
| Each call may hit a different replica | All 15 land on the same hot replica |
| KV cache miss every other call | Prefix cache hit from call 2 onward |
| p50 TTFT dominated by reprefill | p50 TTFT dominated by network |
| Cost / call ≈ flat | Cost / call drops sharply after turn 1 |

Order-of-magnitude TTFT improvement on multi-turn / RAG / tool-loop
workloads is the headline result llm-d publishes. The 15-call agent is
exactly the case where it pays back.

Tradeoff: llm-d is heavier than "just vLLM" — adds the InferencePool /
InferenceModel CRDs, a scheduler component, and assumes a kgateway-class
Gateway in front. For lab-scale single-replica Ollama it's overkill; for
prod multi-replica vLLM it's the right answer.

---

## TL;DR for the interviewer

- "Stuck agents" / timeouts / circuit-breakers / failover / canary —
  **already there, via Envoy + Gateway API + kagent CRs**. We configure,
  we don't write.
- Provider switch / response normalization — **kgateway AI Backend** with
  priority pools; OpenAI-schema in/out.
- Versioning + blue/green — **GitOps + HTTPRoute weights** (+ Flagger /
  Argo Rollouts for automation).
- fastmcp — Python's lowest-friction MCP path; v1 is in the official SDK,
  v2 (jlowin) adds proxying / OpenAPI / auth.
- FinOps — **gateway is the chokepoint**. Token-based rate limit per
  consumer + per agent + Prometheus attribution + agent-side step/budget
  caps. Custom controls via OPA, Wasm filters, or admission webhooks.
- vLLM is great for multi-turn agents *with session affinity*; **llm-d**
  is what makes that affinity automatic and cache-aware, and is the
  scheduler you want once an agent fires 15 LLM calls.
