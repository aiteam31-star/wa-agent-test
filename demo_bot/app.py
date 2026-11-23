"""FastAPI app: the WhatsApp Cloud API webhook endpoint."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from collections import defaultdict
from typing import Any

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Response

from demo_bot.agent import Agent
from demo_bot.buggy import BuggyMode
from demo_bot.config import Settings
from demo_bot.data import IPOStore
from demo_bot.graph import GraphClient
from demo_bot.llm import create_provider

logger = logging.getLogger("demo_bot.app")

UNSUPPORTED_TEXT = "Sorry, I can only read text messages and button or list replies."


def signature_ok(body: bytes, header: str | None, app_secret: str) -> bool:
    """Check ``X-Hub-Signature-256`` (``sha256=`` + HMAC-SHA256 of the raw body)."""
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


def create_app(
    settings: Settings | None = None,
    *,
    http_client: httpx.AsyncClient | None = None,
    agent: Agent | None = None,
) -> FastAPI:
    """Build the bot. ``http_client`` is used for both the LLM and Graph API calls (tests)."""
    settings = settings or Settings.from_env()
    store = IPOStore.load(settings.data_path)
    client = http_client or httpx.AsyncClient(timeout=settings.request_timeout_s)
    buggy = BuggyMode(
        enabled=settings.buggy_mode,
        rate=settings.buggy_rate,
        seed=settings.buggy_seed,
        force=settings.buggy_force,
    )
    agent = agent or Agent(
        provider=create_provider(settings, store, client),
        store=store,
        buggy=buggy,
        history_max_messages=settings.history_max_messages,
    )
    graph = GraphClient(
        base_url=settings.graph_base_url,
        version=settings.graph_version,
        access_token=settings.access_token,
        client=client,
    )
    locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
    seen_message_ids: set[str] = set()

    app = FastAPI(title="IPO demo bot", docs_url=None, redoc_url=None)
    app.state.settings = settings
    app.state.agent = agent
    app.state.graph = graph

    if settings.buggy_mode:
        logger.warning(
            "BUGGY_MODE is ON (force=%s rate=%s)", sorted(settings.buggy_force), settings.buggy_rate
        )

    @app.get("/webhook")
    async def verify(request: Request) -> Response:
        q = request.query_params
        if q.get("hub.mode") == "subscribe" and q.get("hub.verify_token") == settings.verify_token:
            return Response(q.get("hub.challenge", ""), media_type="text/plain")
        raise HTTPException(status_code=403, detail="verification failed")

    @app.post("/webhook")
    async def receive(request: Request, background: BackgroundTasks) -> dict[str, str]:
        body = await request.body()
        if not signature_ok(body, request.headers.get("X-Hub-Signature-256"), settings.app_secret):
            raise HTTPException(status_code=401, detail="invalid signature")
        try:
            payload = json.loads(body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid JSON") from exc
        for message, phone_number_id in _inbound_messages(payload):
            message_id = str(message.get("id", ""))
            if message_id and message_id in seen_message_ids:
                continue  # Meta retries deliveries; don't answer twice
            seen_message_ids.add(message_id)
            background.add_task(process, message, phone_number_id)
        return {"status": "ok"}

    async def process(message: dict[str, Any], phone_number_id: str) -> None:
        sender = str(message.get("from", ""))
        async with locks[sender]:  # keep one user's messages in order
            try:
                text = _user_text(message, agent)
                reply = await agent.handle(sender, text) if text else None
                if reply is None:
                    result = await graph.send_text(phone_number_id, sender, UNSUPPORTED_TEXT)
                else:
                    result = await graph.send_reply(phone_number_id, sender, reply)
                if not result.ok:
                    logger.error("reply to %s was not delivered: %s", sender, result.detail)
            except Exception:
                logger.exception("failed handling message from %s", sender)

    return app


def _inbound_messages(payload: dict[str, Any]) -> list[tuple[dict[str, Any], str]]:
    """Pull (message, phone_number_id) pairs out of a webhook payload; ignore statuses."""
    found: list[tuple[dict[str, Any], str]] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            phone_number_id = str(value.get("metadata", {}).get("phone_number_id", ""))
            for message in value.get("messages", []):
                found.append((message, phone_number_id))
    return found


def _user_text(message: dict[str, Any], agent: Agent) -> str | None:
    """The user's question as text, or None for unsupported message types."""
    kind = message.get("type")
    if kind == "text":
        return str(message.get("text", {}).get("body", "")) or None
    if kind == "interactive":
        interactive = message.get("interactive", {})
        reply = interactive.get(interactive.get("type", ""), {})
        if reply.get("id"):
            return agent.question_for_reply(str(reply["id"]), str(reply.get("title", "")))
    return None
