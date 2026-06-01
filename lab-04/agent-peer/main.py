"""agent-peer — enriches text with simple linguistic stats.

A2A v1.0 over JSON-RPC. Skill: `enrich`.
"""

import os
import re

import uvicorn
from starlette.applications import Starlette

from a2a.helpers import new_task_from_user_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import AgentCard, AgentInterface, Part


PORT = int(os.environ.get("PORT", "9001"))
SERVICE_URL = os.environ.get("SERVICE_URL", f"http://localhost:{PORT}")
RPC_URL = "/a2a/jsonrpc/"


STOPWORDS = {"the", "a", "an", "is", "was", "are", "were", "and", "or", "of", "to", "in", "on", "for", "it", "its"}


class EnrichExecutor(AgentExecutor):
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

        tokens = [t.lower() for t in re.findall(r"[A-Za-z']+", text)]
        unique = sorted(set(tokens))
        content_words = [t for t in tokens if t not in STOPWORDS]
        avg_len = (sum(len(t) for t in tokens) / len(tokens)) if tokens else 0

        enrichment = (
            f"tokens={len(tokens)} unique={len(unique)} "
            f"content_words={len(content_words)} avg_word_len={avg_len:.2f}\n"
            f"top_content_words: {', '.join(content_words[:8])}"
        )

        part = Part()
        part.text = enrichment
        await updater.add_artifact(parts=[part], name="enrichment")
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
        name="agent-peer",
        description="Enriches input text with linguistic stats (tokens, unique, content words, avg length).",
        version="0.1.0",
    )
    iface = AgentInterface(url=f"{SERVICE_URL}{RPC_URL}", protocol_binding="JSONRPC")
    card.supported_interfaces.append(iface)
    card.capabilities.streaming = True
    card.default_input_modes.extend(["text/plain"])
    card.default_output_modes.extend(["text/plain"])
    skill = card.skills.add()
    skill.id = "enrich"
    skill.name = "Enrich text"
    skill.description = "Linguistic enrichment: token/unique/content-word counts, avg word length."
    skill.tags.extend(["text", "enrichment", "linguistics"])
    skill.examples.append("Enrich: The quick brown fox jumps over the lazy dog.")
    return card


def build_app() -> Starlette:
    card = build_agent_card()
    handler = DefaultRequestHandler(
        agent_executor=EnrichExecutor(),
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
