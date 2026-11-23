"""The agent with the deterministic fake LLM provider."""

from typing import Any

import pytest

from demo_bot.agent import FALLBACK_TEXT, Agent
from demo_bot.buggy import ADVICE_SENTENCE, BuggyMode
from demo_bot.config import DEFAULT_DATA_PATH
from demo_bot.data import IPOStore
from demo_bot.llm import FakeProvider, LLMResponse, Message


@pytest.fixture
def store() -> IPOStore:
    return IPOStore.load(DEFAULT_DATA_PATH)


def make_agent(store: IPOStore, buggy: BuggyMode | None = None, **kwargs: Any) -> Agent:
    return Agent(provider=FakeProvider(store), store=store, buggy=buggy, **kwargs)


async def test_open_ipos_gets_a_list_reply(store: IPOStore) -> None:
    reply = await make_agent(store).handle("u1", "Which IPOs are open?")
    assert reply.kind == "list"
    assert [r.id for r in reply.rows] == ["ipo:nova-textiles", "ipo:bharat-greengrid"]
    assert "Nova Textiles Ltd" in reply.text and "Bharat GreenGrid Energy Ltd" in reply.text
    assert all(len(r.title) <= 24 and len(r.description) <= 72 for r in reply.rows)


async def test_ipo_question_gets_three_buttons_and_correct_dates(store: IPOStore) -> None:
    reply = await make_agent(store).handle("u1", "When does Nova Textiles list?")
    assert reply.kind == "buttons" and reply.ipo_slug == "nova-textiles"
    assert [b.title for b in reply.buttons] == ["Dates", "Price band", "Subscription"]
    assert [b.id for b in reply.buttons] == [
        "dates:nova-textiles",
        "price:nova-textiles",
        "subscription:nova-textiles",
    ]
    assert "listing date is 30 November 2026" in reply.text
    assert "₹210-221" in reply.text and "67 shares" in reply.text
    assert len(reply.text) <= 1024


async def test_subscription_question(store: IPOStore) -> None:
    reply = await make_agent(store).handle("u1", "What's the subscription for Nova Textiles?")
    assert (
        "QIB 12.4x" in reply.text and "retail 3.2x" in reply.text and "overall 7.1x" in reply.text
    )


async def test_upcoming_ipo_has_no_subscription_yet(store: IPOStore) -> None:
    reply = await make_agent(store).handle("u1", "subscription status of Kaveri Agro")
    assert "opens on 2 December 2026" in reply.text


async def test_off_topic_gets_plain_text_help(store: IPOStore) -> None:
    reply = await make_agent(store).handle("u1", "what's the weather?")
    assert reply.kind == "text" and "Which IPOs are open?" in reply.text


async def test_history_is_kept_per_user_and_enables_follow_ups(store: IPOStore) -> None:
    agent = make_agent(store)
    await agent.handle("alice", "Tell me about Nova Textiles")
    await agent.handle("bob", "Tell me about Marwar Cement")
    follow_up = await agent.handle("alice", "and its subscription?")
    assert "Nova Textiles" in follow_up.text and "overall 7.1x" in follow_up.text
    roles = [m["role"] for m in agent.history("alice")]
    assert roles.count("user") == 2 and "tool" in roles
    assert all("Marwar" not in str(m.get("content")) for m in agent.history("alice"))
    assert agent.history("nobody") == []


async def test_history_is_trimmed_on_a_user_message_boundary(store: IPOStore) -> None:
    agent = make_agent(store, history_max_messages=6)
    for _ in range(5):
        await agent.handle("u1", "Tell me about Nova Textiles")
    history = agent.history("u1")
    assert len(history) <= 6 and history[0]["role"] == "user"


async def test_llm_failure_returns_fallback_and_keeps_history_valid(store: IPOStore) -> None:
    class Broken:
        async def complete(self, *args: Any) -> LLMResponse:
            raise RuntimeError("boom")

    agent = Agent(provider=Broken(), store=store)
    reply = await agent.handle("u1", "hi")
    assert reply.text == FALLBACK_TEXT and reply.kind == "text"
    assert agent.history("u1") == []


async def test_runaway_tool_loop_is_cut_off(store: IPOStore) -> None:
    class Looping:
        async def complete(self, system: str, messages: list[Message], tools: Any) -> LLMResponse:
            from demo_bot.llm import ToolCall

            return LLMResponse(tool_calls=[ToolCall("c", "list_open_ipos", {})])

    reply = await Agent(provider=Looping(), store=store).handle("u1", "hi")
    assert reply.text == FALLBACK_TEXT


def test_question_for_reply_maps_buttons_and_rows(store: IPOStore) -> None:
    agent = make_agent(store)
    assert agent.question_for_reply("dates:nova-textiles", "Dates") == (
        "What are the key dates for Nova Textiles Ltd?"
    )
    assert "price band" in agent.question_for_reply("price:marwar-cement", "Price band")
    assert "subscription" in agent.question_for_reply("subscription:kaveri-agro", "Subscription")
    assert agent.question_for_reply("ipo:bharat-greengrid", "Bharat GreenGrid").startswith(
        "Tell me about Bharat GreenGrid Energy"
    )
    assert agent.question_for_reply("mystery", "Some title") == "Some title"


# --- the three bugs, end to end through the agent ---------------------------------------------


def buggy(*kinds: str) -> BuggyMode:
    return BuggyMode(enabled=True, force=frozenset(kinds), seed=1)


async def test_bug_wrong_listing_date(store: IPOStore) -> None:
    reply = await make_agent(store, buggy("listing_date")).handle("u1", "Nova Textiles details")
    assert "30 November 2026" not in reply.text
    assert "1 December 2026" in reply.text or "2 December 2026" in reply.text


async def test_bug_four_buttons(store: IPOStore) -> None:
    reply = await make_agent(store, buggy("buttons")).handle("u1", "Nova Textiles details")
    assert len(reply.buttons) == 4 and reply.buttons[3].title == "Apply now"


async def test_bug_you_should_apply(store: IPOStore) -> None:
    reply = await make_agent(store, buggy("advice")).handle("u1", "Nova Textiles details")
    assert "you should apply" in reply.text.lower() and ADVICE_SENTENCE in reply.text
    assert len(reply.text) <= 1024


async def test_bugs_do_not_touch_list_replies_and_off_topic(store: IPOStore) -> None:
    agent = make_agent(store, buggy("buttons", "advice"))
    listing = await agent.handle("u1", "Which IPOs are open?")
    assert listing.kind == "list" and "should apply" not in listing.text.lower()
    assert (await agent.handle("u1", "weather?")).kind == "text"


async def test_clean_agent_has_none_of_the_bugs(store: IPOStore) -> None:
    reply = await make_agent(store).handle("u1", "Nova Textiles details")
    assert len(reply.buttons) == 3 and "should apply" not in reply.text.lower()
    assert "30 November 2026" in reply.text
