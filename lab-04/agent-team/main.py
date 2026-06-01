"""agent-team — A2A orchestrator that fans out to kagent agents.

Dispatches sub-tasks to multiple kagent agents (k8s-agent + observability-agent)
via A2A v0.3 message/send, aggregates artifacts, returns single Task.

kagent serves Agent Card at /.well-known/agent-card.json and JSON-RPC at /.
"""

import json
import os

import httpx
import uvicorn
from starlette.applications import Starlette

from a2a.helpers import new_task_from_user_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import AgentCard, AgentInterface, Part


PORT = int(os.environ.get("PORT", "9002"))
SERVICE_URL = os.environ.get("SERVICE_URL", f"http://localhost:{PORT}")
RPC_URL = "/a2a/jsonrpc/"

PEER_URLS_RAW = os.environ.get(
    "KAGENT_PEERS",
    "http://localhost:18080,http://localhost:18081",
)
PEER_URLS = [u.strip() for u in PEER_URLS_RAW.split(",") if u.strip()]
PEER_TIMEOUT_S = float(os.environ.get("PEER_TIMEOUT_S", "180"))


async def call_kagent_peer(client: httpx.AsyncClient, base: str, prompt: str) -> tuple[str, str]:
    """A2A v0.3 round-trip: discover card → message/send → return (peer-name, text-result)."""
    try:
        card = (await client.get(f"{base}/.well-known/agent-card.json")).json()
        # Card advertises in-cluster URL; reuse the reachable `base` for transport.
        rpc_url = base.rstrip("/") + "/"
        name = card.get("name", base)

        body = {
            "jsonrpc": "2.0",
            "id": f"team-{name}",
            "method": "message/send",
            "params": {
                "message": {
                    "messageId": f"team-msg-{name}",
                    "role": "user",
                    "parts": [{"kind": "text", "text": prompt}],
                },
                "configuration": {"acceptedOutputModes": ["text"], "blocking": True},
            },
        }
        resp = await client.post(rpc_url, json=body, headers={"Content-Type": "application/json"})
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        return base, f"<error: {exc}>"

    if "error" in data:
        return name, f"<rpc error: {data['error']}>"

    # v0.3 result is a Task; pull last agent message
    result = data.get("result", {})
    history = result.get("history", [])
    agent_texts: list[str] = []
    for msg in history:
        if msg.get("role") == "agent":
            for p in msg.get("parts", []):
                if p.get("kind") == "text" and p.get("text"):
                    agent_texts.append(p["text"])
    if not agent_texts:
        status_msg = result.get("status", {}).get("message", {})
        for p in status_msg.get("parts", []):
            if p.get("kind") == "text":
                agent_texts.append(p["text"])
    return name, "\n".join(agent_texts) or json.dumps(result)[:500]


class TeamExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        prompt = context.get_user_input() or ""
        task = context.current_task or new_task_from_user_message(context.message)
        await event_queue.enqueue_event(task)
        updater = TaskUpdater(
            event_queue=event_queue,
            task_id=task.id,
            context_id=task.context_id,
        )
        await updater.start_work()

        results: list[tuple[str, str]] = []
        async with httpx.AsyncClient(timeout=PEER_TIMEOUT_S) as client:
            for base in PEER_URLS:
                results.append(await call_kagent_peer(client, base, prompt))

        for peer_name, text in results:
            part = Part()
            part.text = text
            await updater.add_artifact(parts=[part], name=f"peer:{peer_name}")

        summary_part = Part()
        summary_part.text = (
            f"orchestrated {len(results)} kagent peers via A2A:\n"
            + "\n".join(f"  - {n}" for n, _ in results)
        )
        await updater.add_artifact(parts=[summary_part], name="team-summary")
        await updater.complete()

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        updater = TaskUpdater(
            event_queue=event_queue,
            task_id=context.task_id,
            context_id=context.context_id,
        )
        await updater.cancel()


def build_agent_card() -> AgentCard:
    card = AgentCard(
        name="agent-team",
        description="A2A orchestrator — fans out single prompt to kagent agents in parallel, aggregates.",
        version="0.1.0",
    )
    iface = AgentInterface(url=f"{SERVICE_URL}{RPC_URL}", protocol_binding="JSONRPC")
    card.supported_interfaces.append(iface)
    card.capabilities.streaming = True
    card.default_input_modes.extend(["text/plain"])
    card.default_output_modes.extend(["text/plain"])
    skill = card.skills.add()
    skill.id = "orchestrate"
    skill.name = "Orchestrate A2A team"
    skill.description = "Send prompt to multiple kagent agents in parallel, merge results."
    skill.tags.extend(["a2a", "team", "orchestrator", "kagent"])
    return card


def build_app() -> Starlette:
    card = build_agent_card()
    handler = DefaultRequestHandler(
        agent_executor=TeamExecutor(),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )
    routes = []
    routes.extend(create_agent_card_routes(card))
    routes.extend(create_jsonrpc_routes(handler, rpc_url=RPC_URL))
    return Starlette(routes=routes)


app = build_app()


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
