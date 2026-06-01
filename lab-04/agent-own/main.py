"""own-agent — A2A orchestrator.

Exposes summarize skill at /.well-known/agent-card.json + /a2a/jsonrpc/.
After local summary, delegates to peer agent (A2A discovery via well-known URI)
for enrichment, then merges artifacts into a single response.
"""

import os
import re

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


PORT = int(os.environ.get("PORT", "9000"))
SERVICE_URL = os.environ.get("SERVICE_URL", f"http://localhost:{PORT}")
RPC_URL = "/a2a/jsonrpc/"
PEER_BASE_URL = os.environ.get("PEER_BASE_URL", "http://localhost:9001")
A2A_VERSION = "1.0"


async def call_peer(text: str) -> tuple[str, dict]:
    """Discover peer via well-known URI, send A2A task, return (enrichment_text, raw_response)."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        card_resp = await client.get(f"{PEER_BASE_URL}/.well-known/agent-card.json")
        card_resp.raise_for_status()
        card = card_resp.json()
        rpc_url = card["supportedInterfaces"][0]["url"]

        rpc_body = {
            "jsonrpc": "2.0",
            "id": "delegate-1",
            "method": "SendMessage",
            "params": {
                "message": {
                    "messageId": "delegate-msg",
                    "role": "ROLE_USER",
                    "parts": [{"text": text}],
                }
            },
        }
        resp = await client.post(
            rpc_url,
            json=rpc_body,
            headers={"A2A-Version": A2A_VERSION, "Content-Type": "application/json"},
        )
        resp.raise_for_status()
        body = resp.json()

    if "error" in body:
        return f"<peer error: {body['error']}>", body

    artifacts = body.get("result", {}).get("task", {}).get("artifacts", [])
    chunks: list[str] = []
    for art in artifacts:
        for part in art.get("parts", []):
            if "text" in part:
                chunks.append(part["text"])
    return "\n".join(chunks) or "<no artifacts>", body


class SummarizeExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        text = context.get_user_input() or ""
        task = context.current_task or new_task_from_user_message(context.message)
        await event_queue.enqueue_event(task)

        updater = TaskUpdater(
            event_queue=event_queue,
            task_id=task.id,
            context_id=task.context_id,
        )
        await updater.start_work()

        # Local summary
        words = re.findall(r"\S+", text)
        first_sentence = (
            re.split(r"(?<=[.!?])\s+", text.strip(), maxsplit=1)[0]
            if text.strip()
            else ""
        )
        summary = (
            f"chars={len(text)} words={len(words)} lines={text.count(chr(10)) + 1}\n"
            f"first_sentence: {first_sentence}"
        )
        sp = Part()
        sp.text = summary
        await updater.add_artifact(parts=[sp], name="summary")

        # Delegate to peer agent via A2A
        try:
            enrichment, _raw = await call_peer(text)
        except Exception as exc:  # pragma: no cover
            enrichment = f"<peer call failed: {exc}>"

        ep = Part()
        ep.text = enrichment
        await updater.add_artifact(parts=[ep], name="peer-enrichment")

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
        name="own-agent",
        description="Summarizes input text + delegates to peer agent via A2A for enrichment.",
        version="0.2.0",
    )
    iface = AgentInterface(url=f"{SERVICE_URL}{RPC_URL}", protocol_binding="JSONRPC")
    card.supported_interfaces.append(iface)
    card.capabilities.streaming = True
    card.default_input_modes.extend(["text/plain"])
    card.default_output_modes.extend(["text/plain"])
    skill = card.skills.add()
    skill.id = "summarize"
    skill.name = "Summarize text"
    skill.description = "Stats (chars/words/lines) + first sentence + peer enrichment."
    skill.tags.extend(["text", "summary", "orchestrator"])
    skill.examples.append("Summarize: The quick brown fox jumps over the lazy dog.")
    return card


def build_app() -> Starlette:
    agent_card = build_agent_card()
    handler = DefaultRequestHandler(
        agent_executor=SummarizeExecutor(),
        task_store=InMemoryTaskStore(),
        agent_card=agent_card,
    )
    routes = []
    routes.extend(create_agent_card_routes(agent_card))
    routes.extend(create_jsonrpc_routes(handler, rpc_url=RPC_URL))
    return Starlette(routes=routes)


app = build_app()


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
