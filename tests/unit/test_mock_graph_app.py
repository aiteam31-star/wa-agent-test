"""Mock Graph API endpoint tests (in-process via ASGI, no sockets)."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from wa_agent_test.mock_graph import CaptureStore, create_app

URL = "/v21.0/106540352242922/messages"
WA_ID = "919876543210"


def text(to: str = WA_ID, body: str = "hi") -> dict[str, Any]:
    return {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": body}}


def buttons(n: int) -> dict[str, Any]:
    return {
        "messaging_product": "whatsapp",
        "to": WA_ID,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": "Pick"},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": f"b{i}", "title": f"Btn {i}"}}
                    for i in range(n)
                ]
            },
        },
    }


@pytest.fixture
def store() -> CaptureStore:
    return CaptureStore()


@pytest.fixture
async def client(store: CaptureStore) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(store=store)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://mock"
    ) as c:
        yield c


async def test_text_success_response_shape(client: httpx.AsyncClient) -> None:
    r = await client.post(URL, json=text(to="+91 98765 43210"))
    assert r.status_code == 200
    data = r.json()
    assert data["messaging_product"] == "whatsapp"
    assert data["contacts"] == [{"input": "+91 98765 43210", "wa_id": WA_ID}]
    (msg,) = data["messages"]
    assert msg["id"].startswith("wamid.")


async def test_each_response_gets_a_unique_message_id(client: httpx.AsyncClient) -> None:
    ids = {(await client.post(URL, json=text())).json()["messages"][0]["id"] for _ in range(20)}
    assert len(ids) == 20


async def test_interactive_and_template_accepted(client: httpx.AsyncClient) -> None:
    template = {
        "messaging_product": "whatsapp",
        "to": WA_ID,
        "type": "template",
        "template": {"name": "hello_world", "language": {"code": "en_US"}},
    }
    assert (await client.post(URL, json=buttons(3))).status_code == 200
    assert (await client.post(URL, json=template)).status_code == 200


async def test_messages_recorded_by_recipient_with_timestamps(
    client: httpx.AsyncClient, store: CaptureStore
) -> None:
    await client.post(URL, json=text(to="911111111111", body="one"))
    await client.post(URL, json=text(to="922222222222", body="two"))
    r = await client.post(URL, json=text(to="911111111111", body="three"))

    first = store.messages_for("911111111111")
    assert [m.payload["text"]["body"] for m in first if m.payload] == ["one", "three"]
    assert [m.payload["text"]["body"] for m in store.messages_for("922222222222") if m.payload] == [
        "two"
    ]
    assert first[1].message_id == r.json()["messages"][0]["id"]
    assert first[0].received_at.tzinfo is not None
    assert first[0].received_monotonic <= first[1].received_monotonic
    assert first[0].api_version == "v21.0"
    assert first[0].phone_number_id == "106540352242922"
    assert first[0].type == "text"
    assert store.messages_for("nobody") == []


async def test_too_many_buttons_rejected_logged_and_recorded(
    client: httpx.AsyncClient, store: CaptureStore, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="wa_agent_test.mock_graph"):
        r = await client.post(URL, json=buttons(4))
    assert r.status_code == 400
    error = r.json()["error"]
    assert error["code"] == 100
    assert error["type"] == "OAuthException"
    assert "interactive.action.buttons" in error["message"]
    assert error["error_data"]["messaging_product"] == "whatsapp"
    assert "at most 3" in error["error_data"]["details"]
    assert error["fbtrace_id"]

    assert "rejected message" in caplog.text and "at most 3" in caplog.text

    assert store.messages_for(WA_ID) == []  # not among delivered messages
    (rejected,) = store.rejected(WA_ID)
    assert not rejected.accepted and rejected.message_id is None
    assert rejected.violations[0].limit == "reply_buttons_max"
    assert store.messages_for(WA_ID, include_rejected=True) == [rejected]


async def test_text_over_4096_rejected(client: httpx.AsyncClient, store: CaptureStore) -> None:
    r = await client.post(URL, json=text(body="x" * 4097))
    assert r.status_code == 400
    assert "4096" in r.json()["error"]["error_data"]["details"]
    assert len(store.rejected()) == 1


async def test_invalid_json_rejected_and_recorded(
    client: httpx.AsyncClient, store: CaptureStore
) -> None:
    r = await client.post(URL, content=b"{nope", headers={"Content-Type": "application/json"})
    assert r.status_code == 400
    (rejected,) = store.rejected()
    assert rejected.payload is None


async def test_bad_version_path(client: httpx.AsyncClient, store: CaptureStore) -> None:
    r = await client.post("/latest/123/messages", json=text())
    assert r.status_code == 400
    assert store.all() == []


async def test_access_token_enforced(store: CaptureStore) -> None:
    app = create_app(store=store, access_token="tok")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://mock"
    ) as c:
        assert (await c.post(URL, json=text())).status_code == 401
        bad = await c.post(URL, json=text(), headers={"Authorization": "Bearer nope"})
        assert bad.status_code == 401 and bad.json()["error"]["code"] == 190
        ok = await c.post(URL, json=text(), headers={"Authorization": "Bearer tok"})
        assert ok.status_code == 200
    assert len(store.all()) == 1  # only the authorised request was captured


async def test_wait_for_count_resolves_when_message_arrives(
    client: httpx.AsyncClient, store: CaptureStore
) -> None:
    waiter = asyncio.create_task(store.wait_for_count(WA_ID, 2, timeout=2))
    await asyncio.sleep(0)
    await client.post(URL, json=text(body="a"))
    assert not waiter.done()
    await client.post(URL, json=text(body="b"))
    assert len(await waiter) == 2


async def test_wait_for_count_times_out(store: CaptureStore) -> None:
    with pytest.raises(TimeoutError, match="expected 1 message"):
        await store.wait_for_count(WA_ID, 1, timeout=0.05)


async def test_response_is_json_serialisable_and_content_type(client: httpx.AsyncClient) -> None:
    r = await client.post(URL, json=text())
    assert r.headers["content-type"].startswith("application/json")
    json.loads(r.text)
