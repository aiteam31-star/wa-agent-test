"""End to end: harness simulator -> demo bot -> harness mock Graph API (all in-process).

This is the harness testing a real bot, including catching each BUGGY_MODE defect.
"""

import asyncio
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import httpx
import pytest

from demo_bot.app import create_app as create_bot_app
from demo_bot.config import Settings
from wa_agent_test.mock_graph import CapturedMessage, CaptureStore
from wa_agent_test.mock_graph import create_app as create_mock_app
from wa_agent_test.payloads import BusinessAccount, SimulatedUser, build_text, make_users
from wa_agent_test.simulator import WebhookSimulator

pytestmark = pytest.mark.integration


@dataclass
class Rig:
    sim: WebhookSimulator
    mock: CaptureStore
    settings: Settings


@asynccontextmanager
async def rig(**overrides: Any) -> AsyncIterator[Rig]:
    settings = Settings(graph_base_url="http://mock", **overrides)
    mock = CaptureStore()
    graph_http = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_mock_app(store=mock)), base_url="http://mock"
    )
    bot = create_bot_app(settings, http_client=graph_http)
    bot_http = httpx.AsyncClient(transport=httpx.ASGITransport(app=bot), base_url="http://bot")
    sim = WebhookSimulator("http://bot/webhook", app_secret=settings.app_secret, client=bot_http)
    try:
        yield Rig(sim, mock, settings)
    finally:
        await graph_http.aclose()
        await bot_http.aclose()


def body_of(message: CapturedMessage) -> str:
    payload = message.payload or {}
    if payload["type"] == "text":
        return str(payload["text"]["body"])
    return str(payload["interactive"]["body"]["text"])


def buttons_of(message: CapturedMessage) -> list[str]:
    assert message.payload is not None
    buttons = message.payload["interactive"]["action"]["buttons"]
    return [b["reply"]["title"] for b in buttons]


async def ask(r: Rig, user: SimulatedUser, text: str) -> CapturedMessage:
    """Send a text and return the bot's next message to this user (accepted or rejected)."""
    before = len(r.mock.messages_for(user.wa_id, include_rejected=True))
    delivery = await r.sim.send_text(user, text)
    assert delivery.ok, delivery.response_text
    found = await r.mock.wait_for_count(user.wa_id, before + 1, timeout=3, include_rejected=True)
    return found[before]


USER = make_users(1, seed=11)[0]


# --- clean behaviour ----------------------------------------------------------------------


async def test_ipo_question_answered_with_text_and_three_buttons() -> None:
    async with rig() as r:
        reply = await ask(r, USER, "When does Nova Textiles list?")
    assert reply.accepted and reply.type == "interactive"
    assert reply.to == USER.wa_id
    assert reply.phone_number_id == BusinessAccount().phone_number_id
    assert "listing date is 30 November 2026" in body_of(reply)
    assert buttons_of(reply) == ["Dates", "Price band", "Subscription"]
    assert r.mock.rejected() == []


async def test_open_ipos_gets_a_list_message() -> None:
    async with rig() as r:
        reply = await ask(r, USER, "Which IPOs are open?")
    assert reply.accepted and reply.payload is not None
    interactive = reply.payload["interactive"]
    assert interactive["type"] == "list"
    rows = interactive["action"]["sections"][0]["rows"]
    assert [row["id"] for row in rows] == ["ipo:nova-textiles", "ipo:bharat-greengrid"]


async def test_button_and_list_taps_are_understood() -> None:
    async with rig() as r:
        assert (
            await r.sim.send_button_reply(USER, "subscription:nova-textiles", "Subscription")
        ).ok
        assert (await r.sim.send_list_reply(USER, "ipo:bharat-greengrid", "Bharat GreenGrid")).ok
        first, second = await r.mock.wait_for_count(USER.wa_id, 2, timeout=3)
    assert "retail 3.2x" in body_of(first)
    assert "Bharat GreenGrid Energy Ltd" in body_of(second)


async def test_follow_up_uses_conversation_history() -> None:
    async with rig() as r:
        await ask(r, USER, "Tell me about Nova Textiles")
        reply = await ask(r, USER, "and its subscription?")
    assert "Nova Textiles" in body_of(reply) and "overall 7.1x" in body_of(reply)


async def test_many_users_concurrently_get_their_own_answers() -> None:
    users = make_users(12, seed=3)
    names = ["Nova Textiles", "Marwar Cement", "Kaveri Agro", "Sahyadri Fintech"]
    async with rig() as r:
        await asyncio.gather(
            *(r.sim.send_text(u, f"Tell me about {names[i % 4]}") for i, u in enumerate(users))
        )
        for i, u in enumerate(users):
            (msg,) = await r.mock.wait_for_count(u.wa_id, 1, timeout=3)
            assert names[i % 4] in body_of(msg), u.wa_id
            assert len(r.mock.messages_for(u.wa_id)) == 1


async def test_bad_signature_is_rejected_and_nothing_is_sent() -> None:
    async with rig() as r:
        bad = WebhookSimulator("http://bot/webhook", app_secret="wrong", client=r.sim._client)
        result = await bad.send_text(USER, "hello")
    assert result.status_code == 401
    assert r.mock.all() == []


async def test_verification_handshake() -> None:
    async with rig() as r:
        assert (await r.sim.verify(r.settings.verify_token, "abc123")).ok
        denied = await r.sim.verify("wrong-token")
    assert not denied.ok and denied.status_code == 403


async def test_status_webhooks_are_ignored_and_duplicates_answered_once() -> None:
    async with rig() as r:
        assert (await r.sim.send_status(USER, "wamid.OUT", "delivered")).ok
        assert r.mock.all() == []
        payload = build_text(
            BusinessAccount(), USER, "Which IPOs are open?", message_id="wamid.DUP"
        )
        assert (await r.sim.send_payload(payload)).ok
        assert (await r.sim.send_payload(payload)).ok
        await r.mock.wait_for_count(USER.wa_id, 1, timeout=3)
        await asyncio.sleep(0.05)
        assert len(r.mock.messages_for(USER.wa_id)) == 1


async def test_unsupported_message_type_gets_a_polite_reply() -> None:
    async with rig() as r:
        assert (await r.sim.send_image(USER, caption="my id")).ok
        (msg,) = await r.mock.wait_for_count(USER.wa_id, 1, timeout=3)
    assert msg.type == "text" and "can only read text" in body_of(msg)


# --- BUGGY_MODE: the harness sees each defect --------------------------------------------------


async def test_buggy_mode_off_ignores_force_flags() -> None:
    async with rig(buggy_force=frozenset({"buttons", "advice", "listing_date"})) as r:
        reply = await ask(r, USER, "Nova Textiles details")
    assert reply.accepted and len(buttons_of(reply)) == 3
    assert "should apply" not in body_of(reply).lower() and "30 November 2026" in body_of(reply)


async def test_bug_four_buttons_is_rejected_by_the_mock_and_recorded() -> None:
    async with rig(buggy_mode=True, buggy_force=frozenset({"buttons"})) as r:
        reply = await ask(r, USER, "Nova Textiles details")
    assert not reply.accepted
    assert [v.limit for v in reply.violations] == ["reply_buttons_max"]
    assert r.mock.messages_for(USER.wa_id) == []  # nothing reached the user
    assert len(r.mock.rejected(USER.wa_id)) == 1
    assert reply.payload is not None
    assert len(reply.payload["interactive"]["action"]["buttons"]) == 4


async def test_bug_you_should_apply_is_visible_in_the_reply() -> None:
    async with rig(buggy_mode=True, buggy_force=frozenset({"advice"})) as r:
        reply = await ask(r, USER, "Nova Textiles details")
    assert reply.accepted and "you should apply" in body_of(reply).lower()


async def test_bug_wrong_listing_date_differs_from_the_fixture() -> None:
    async with rig(buggy_mode=True, buggy_force=frozenset({"listing_date"}), buggy_seed=1) as r:
        reply = await ask(r, USER, "Nova Textiles details")
    claimed = re.search(r"listing date is (\d+ \w+ \d{4})", body_of(reply))
    assert claimed is not None
    assert claimed.group(1) in ("1 December 2026", "2 December 2026")
    assert claimed.group(1) != "30 November 2026"


async def test_probabilistic_bugs_are_reproducible_with_a_seed() -> None:
    async def run() -> list[bool]:
        async with rig(buggy_mode=True, buggy_rate=0.5, buggy_seed=5) as r:
            outcomes = []
            for _ in range(8):
                reply = await ask(r, USER, "Nova Textiles details")
                outcomes.append(reply.accepted and "30 November 2026" in body_of(reply))
            return outcomes

    first = await run()
    assert first == await run()
    assert any(first) and not all(first)  # "sometimes" wrong
