"""Webhook simulator tests against a fake bot served in-process via ASGI."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request, Response

from wa_agent_test.payloads import SIGNATURE_HEADER, make_users, verify_signature
from wa_agent_test.simulator import WebhookSimulator

SECRET = "app-secret"


class FakeBot:
    """Verifies signatures like a real bot and records what it receives."""

    def __init__(self) -> None:
        self.received: list[dict[str, Any]] = []
        self.app = FastAPI()

        @self.app.get("/webhook")
        async def verify(request: Request) -> Response:
            q = request.query_params
            if q.get("hub.mode") == "subscribe" and q.get("hub.verify_token") == "tok":
                return Response(q["hub.challenge"], media_type="text/plain")
            raise HTTPException(403)

        @self.app.post("/webhook")
        async def webhook(request: Request) -> dict[str, str]:
            body = await request.body()
            if not verify_signature(body, request.headers.get(SIGNATURE_HEADER), SECRET):
                raise HTTPException(401, "bad signature")
            self.received.append(await request.json())
            return {"status": "ok"}


@pytest.fixture
def bot() -> FakeBot:
    return FakeBot()


@pytest.fixture
async def sim(bot: FakeBot) -> AsyncIterator[WebhookSimulator]:
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=bot.app), base_url="http://bot")
    async with client:
        yield WebhookSimulator("http://bot/webhook", app_secret=SECRET, client=client)


async def test_signed_text_is_accepted(sim: WebhookSimulator, bot: FakeBot) -> None:
    (user,) = make_users(1, seed=1)
    result = await sim.send_text(user, "hello")
    assert result.ok and result.status_code == 200
    assert result.error is None and result.latency_ms >= 0
    assert result.signature == f"sha256={result.signature[7:]}"
    assert verify_signature(result.body, result.signature, SECRET)
    assert bot.received == [result.payload]
    assert (
        result.message_id == result.payload["entry"][0]["changes"][0]["value"]["messages"][0]["id"]
    )


async def test_wrong_secret_is_rejected_by_bot(bot: FakeBot) -> None:
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=bot.app), base_url="http://bot")
    async with client:
        sim = WebhookSimulator("http://bot/webhook", app_secret="wrong", client=client)
        (user,) = make_users(1)
        result = await sim.send_text(user, "hello")
    assert not result.ok and result.status_code == 401
    assert bot.received == []


async def test_all_message_types_delivered(sim: WebhookSimulator, bot: FakeBot) -> None:
    (user,) = make_users(1, seed=2)
    results = [
        await sim.send_text(user, "hi"),
        await sim.send_button_reply(user, "b1", "Dates", context_message_id="wamid.P"),
        await sim.send_list_reply(user, "r1", "Nova", "desc"),
        await sim.send_image(user, caption="pic"),
        await sim.send_status(user, "wamid.OUT", "sent"),
        await sim.send_status(user, "wamid.OUT", "delivered"),
        await sim.send_status(user, "wamid.OUT", "read"),
    ]
    assert all(r.ok for r in results)
    assert results[-1].message_id is None
    values = [p["entry"][0]["changes"][0]["value"] for p in bot.received]
    types = [
        v["messages"][0]["type"] if "messages" in v else v["statuses"][0]["status"] for v in values
    ]
    assert types == ["text", "interactive", "interactive", "image", "sent", "delivered", "read"]


async def test_many_users_concurrently_each_with_own_identity(
    sim: WebhookSimulator, bot: FakeBot
) -> None:
    users = make_users(50, seed=5)
    results = await asyncio.gather(*(sim.send_text(u, f"hi from {u.profile_name}") for u in users))
    assert all(r.ok for r in results)
    senders = [p["entry"][0]["changes"][0]["value"]["messages"][0]["from"] for p in bot.received]
    assert sorted(senders) == sorted(u.wa_id for u in users)
    assert len(set(senders)) == 50
    assert len({r.message_id for r in results}) == 50


async def test_connection_error_is_reported_not_raised() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(refuse))
    async with client:
        sim = WebhookSimulator("http://down/webhook", app_secret=SECRET, client=client)
        (user,) = make_users(1)
        result = await sim.send_text(user, "hi")
    assert not result.ok and result.status_code is None
    assert result.error is not None and "ConnectError" in result.error


async def test_verification_handshake(sim: WebhookSimulator) -> None:
    good = await sim.verify("tok", challenge="abc123")
    assert good.ok and good.response_text == "abc123"
    bad = await sim.verify("wrong")
    assert not bad.ok and bad.status_code == 403
