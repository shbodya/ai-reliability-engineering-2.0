# A2A Protocol — Spec Notes

Source: https://a2a-protocol.org/latest/ (v1.0). Open standard, originally Google, now Linux Foundation.

## Discovery — Well-Known URI

- Exact path: `https://{agent-server-domain}/.well-known/agent-card.json` (RFC 8615).
- Client flow: know domain → HTTP GET well-known URI → server returns Agent Card JSON.
- Alternatives: curated registries (search by skills/tags), direct hardcoded URLs.

## Agent Card (core fields)

Published at well-known URI. Declares identity + capabilities + auth.

- `name`, `description`, `version`, `url` (service endpoint)
- `capabilities` (AgentCapabilities — streaming, pushNotifications, stateTransitionHistory)
- `skills[]` (AgentSkill — id, name, description, tags, examples, inputModes, outputModes)
- `defaultInputModes`, `defaultOutputModes`
- `securitySchemes` (map): `APIKeySecurityScheme`, `HTTPAuthSecurityScheme`, `OAuth2SecurityScheme` (authCode/clientCreds/deviceCode flows), `OpenIdConnectSecurityScheme`, `MutualTlsSecurityScheme`
- `provider` (AgentProvider — org, url)
- Extended card endpoint: `GET /agentCard/extended` (auth'd, richer)

## Task — core object

- `id` (server UUID)
- `contextId` (optional grouping across tasks)
- `status` (TaskStatus)
- `artifacts[]`
- `history[]` (Messages)
- `metadata` (k/v)

### Task lifecycle states

`TASK_STATE_UNSPECIFIED`, `SUBMITTED`, `WORKING`, `COMPLETED`, `FAILED`, `CANCELED`, `INPUT_REQUIRED`, `REJECTED`, `AUTH_REQUIRED`.

## Message

- `messageId` (req)
- `role`: `ROLE_USER` | `ROLE_AGENT`
- `parts[]` (req)
- optional: `contextId`, `taskId`, `metadata`, `extensions`, `referenceTaskIds`

### Part (OneOf)

Exactly one of: `text` (string), `raw` (base64 bytes), `url` (ref), `data` (JSON). Plus optional `mediaType`, `filename`.

### Artifact

`artifactId` (task-unique UUID) + optional `name`, `description`, composed of Parts.

## RPC methods (11 binding-agnostic)

1. SendMessage
2. SendStreamingMessage
3. GetTask
4. ListTasks
5. CancelTask
6. SubscribeToTask
7. CreatePushNotificationConfig
8. GetPushNotificationConfig
9. ListPushNotificationConfigs
10. DeletePushNotificationConfig
11. GetExtendedAgentCard

### SendMessage params

- `message` (Message, req)
- `configuration` (SendMessageConfiguration): `acceptedOutputModes`, `taskPushNotificationConfig`, `historyLength`, `returnImmediately`
- `metadata` (k/v, opt)
- `tenant` (opaque routing, opt)

## Transport bindings

### JSON-RPC 2.0

`{"jsonrpc":"2.0","method":"...","params":{...},"id":...}` — methods map 1:1.

### HTTP+JSON / REST

| Method | Path |
|---|---|
| SendMessage | `POST /messages/send` |
| SendStreamingMessage | `POST /messages/send-streaming` |
| GetTask | `GET /tasks/{id}` |
| ListTasks | `GET /tasks` |
| CancelTask | `POST /tasks/{id}/cancel` |
| SubscribeToTask | `GET /tasks/{id}/subscribe` (SSE) |
| CreatePushNotificationConfig | `POST /tasks/{id}/pushNotificationConfigs` |
| GetPushNotificationConfig | `GET /tasks/{id}/pushNotificationConfigs/{configId}` |
| ListPushNotificationConfigs | `GET /tasks/{id}/pushNotificationConfigs` |
| DeletePushNotificationConfig | `DELETE /tasks/{id}/pushNotificationConfigs/{configId}` |
| GetExtendedAgentCard | `GET /agentCard/extended` |

### gRPC

Service def w/ ServerStream for streaming.

## Streaming / updates

3 delivery modes:
1. Polling — `GetTask` synchronous
2. Streaming — `SendStreamingMessage`, `SubscribeToTask` (SSE on HTTP binding)
3. Push notifications — webhook POST to client-registered endpoint

Stream wrapper (OneOf): `task` | `message` | `statusUpdate` (TaskStatusUpdateEvent) | `artifactUpdate` (TaskArtifactUpdateEvent).

## Service params (headers/metadata)

- `A2A-Version` — protocol version, e.g. `1.0`; empty -> defaults `0.3`
- `A2A-Extensions` — CSV of extension URIs
- Keys case-insensitive, values case-sensitive

## Errors

Structure: `code` (machine), `message` (human), `details[]` w/ `@type` ProtoJSON Any.

A2A-specific:
- `TaskNotFoundError`
- `TaskNotCancelableError`
- `PushNotificationNotSupportedError`
- `UnsupportedOperationError`
- `ContentTypeNotSupportedError`
- `InvalidAgentResponseError`
- `ExtendedAgentCardNotConfiguredError`
- `ExtensionSupportRequiredError`
- `VersionNotSupportedError`

## Key takeaways for lab

- Card path = `/.well-known/agent-card.json` (NOT `agent.json` — common mistake).
- Default transport for lab: JSON-RPC 2.0 over HTTP — simplest w/ a2a-python SDK.
- Pick streaming=true in card -> use `SendStreamingMessage` for live updates.
- Task delegation (Stage 4/5): agent A acts as client → discover B via well-known → `SendMessage` or `SendStreamingMessage` w/ child task → poll `GetTask` or subscribe SSE.
