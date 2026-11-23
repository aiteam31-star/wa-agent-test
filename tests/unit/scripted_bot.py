"""A bot whose replies a test scripts, wired to the real mock Graph API (all in-process).

Lets runner tests control exactly what the bot sends, when, and how many messages.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request

from wa_agent_test.mock_graph import CaptureStore
from wa_agent_test.mock_graph import create_app as create_mock_app
from wa_agent_test.payloads import BusinessAccount, verify_signature
from wa_agent_test.simulator import WebhookSimulator

SECRET = "scripted-secret"


@dataclass
class Inbound:
    sender: str
    kind: str  # text | button_reply | list_reply | image
    text: str = ""  # text body, or the button/row title
    reply_id: str = ""
    context_id: str | None = None


Send = Callable[[dict[str, Any]], Awaitable[httpx.Response]]
Handler = Callable[[Inbound, Send], Awaitable[None]]


def text_body(to: str, text: str) -> dict[str, Any]:
    return {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": text}}


def buttons_body(to: str, text: str, buttons: list[tuple[str, str]]) -> dict[str, Any]:
    return {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": text},
            "action": {
                "buttons": [{"type": "reply", "reply": {"id": i, "title": t}} for i, t in buttons]
            },
        },
    }


def list_body(to: str, text: str, rows: list[tuple[str, str]]) -> dict[str, Any]:
    return {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": text},
            "action": {
                "button": "Choose",
                "sections": [
                    {"title": "Options", "rows": [{"id": i, "title": t} for i, t in rows]}
                ],
            },
        },
    }


def _parse(message: dict[str, Any]) -> Inbound:
    sender = str(message["from"])
    context = message.get("context", {}).get("id")
    kind = message["type"]
    if kind == "text":
        return Inbound(sender, "text", message["text"]["body"], context_id=context)
    if kind == "interactive":
        inner = message["interactive"]
        reply = inner[inner["type"]]
        return Inbound(sender, inner["type"], reply["title"], reply["id"], context)
    return Inbound(sender, kind, context_id=context)


@dataclass
class Rig:
    sim: WebhookSimulator
    store: CaptureStore
    tasks: set[asyncio.Task[None]] = field(default_factory=set)


@asynccontextmanager
async def scripted_rig(handler: Handler) -> AsyncIterator[Rig]:
    store = CaptureStore()
    graph = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_mock_app(store=store)), base_url="http://mock"
    )
    pnid = BusinessAccount().phone_number_id
    tasks: set[asyncio.Task[None]] = set()
    app = FastAPI()

    @app.post("/webhook")
    async def webhook(request: Request) -> dict[str, str]:
        body = await request.body()
        if not verify_signature(body, request.headers.get("X-Hub-Signature-256"), SECRET):
            raise HTTPException(401)
        payload = await request.json()
        for entry in payload["entry"]:
            for change in entry["changes"]:
                for message in change["value"].get("messages", []):
                    inbound = _parse(message)

                    async def send(body: dict[str, Any]) -> httpx.Response:
                        return await graph.post(f"/v21.0/{pnid}/messages", json=body)

                    task = asyncio.create_task(handler(inbound, send))
                    tasks.add(task)
                    task.add_done_callback(tasks.discard)
        return {"status": "ok"}

    bot_http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://bot")
    sim = WebhookSimulator("http://bot/webhook", app_secret=SECRET, client=bot_http)
    try:
        yield Rig(sim, store, tasks)
    finally:
        for task in list(tasks):
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await graph.aclose()
        await bot_http.aclose()
