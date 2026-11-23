"""The scenario runner, against a scripted bot wired to the real mock Graph API."""

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from scripted_bot import (
    Inbound,
    Send,
    buttons_body,
    list_body,
    scripted_rig,
    text_body,
)

from wa_agent_test.payloads import make_users
from wa_agent_test.scenarios import RunResult, Scenario, ScenarioResult, ScenarioRunner
from wa_agent_test.simulator import WebhookSimulator
from wa_agent_test.truth import FileTruthSource

IPOS = Path(__file__).parents[2] / "demo_bot" / "data" / "ipos.json"
USER = make_users(1, seed=1)[0]


def scenario(turns: list[dict[str, Any]], name: str = "s", **defaults: Any) -> Scenario:
    return Scenario.model_validate(
        {
            "name": name,
            "defaults": {"timeout_s": 1.0, "settle_ms": 50, **defaults},
            "turns": turns,
        }
    )


def runner(rig: Any, **kwargs: Any) -> ScenarioRunner:
    truth = {
        "ipos": FileTruthSource(
            IPOS,
            records="ipos",
            entity_match=["name", "short_name"],
            fields={"listing_date": "dates.listing"},
        )
    }
    return ScenarioRunner(simulator=rig.sim, store=rig.store, truth=truth, **kwargs)


async def echo(inbound: Inbound, send: Send) -> None:
    await send(text_body(inbound.sender, f"echo {inbound.text}"))


async def silent(inbound: Inbound, send: Send) -> None:
    return None


async def play(handler: Any, sc: Scenario, **runner_kwargs: Any) -> ScenarioResult:
    async with scripted_rig(handler) as rig:
        return await runner(rig, **runner_kwargs).run_scenario(sc, USER)


# --- the basics ---------------------------------------------------------------------------


async def test_a_passing_scenario_records_everything() -> None:
    sc = scenario([{"say": "hello", "expect": [{"contains": "echo hello"}, {"message_count": 1}]}])
    result = await play(echo, sc)
    assert result.passed and result.user_wa_id == USER.wa_id
    (turn,) = result.turns
    assert turn.status == "passed" and turn.index == 1 and turn.action == "say: 'hello'"
    assert [m.text for m in turn.bot_messages] == ["echo hello"]
    assert turn.bot_messages[0].message_id.startswith("wamid.")
    assert [(c.kind, c.passed) for c in turn.checks] == [
        ("contains", True),
        ("message_count", True),
    ]


async def test_a_failing_check_fails_the_turn_and_skips_the_rest() -> None:
    sc = scenario(
        [
            {"say": "one", "expect": [{"contains": "nope"}]},
            {"say": "two", "expect": [{"contains": "echo two"}]},
        ]
    )
    result = await play(echo, sc)
    assert not result.passed
    first, second = result.turns
    assert first.status == "failed" and "missing ['nope']" in first.checks[0].message
    assert second.status == "skipped" and second.checks == []


async def test_several_bot_messages_in_one_turn_are_all_collected() -> None:
    async def chatty(inbound: Inbound, send: Send) -> None:
        for i in range(3):
            await send(text_body(inbound.sender, f"part {i}"))
            await asyncio.sleep(0.05)

    sc = scenario(
        [{"say": "go", "expect": [{"message_count": 3}, {"contains": "part 2"}]}], settle_ms=250
    )
    result = await play(chatty, sc)
    assert result.passed, result.turns[0].checks
    assert [m.text for m in result.turns[0].bot_messages] == ["part 0", "part 1", "part 2"]


async def test_expect_messages_is_an_exact_count() -> None:
    async def two(inbound: Inbound, send: Send) -> None:
        await send(text_body(inbound.sender, "a"))
        await send(text_body(inbound.sender, "b"))

    result = await play(two, scenario([{"say": "x", "expect_messages": 1}]))
    (check,) = result.turns[0].checks
    assert not result.passed and check.kind == "expect_messages"
    assert "expected exactly 1 bot message(s), got 2" in check.message
    assert (await play(two, scenario([{"say": "x", "expect_messages": 2}]))).passed


async def test_expect_zero_messages() -> None:
    assert (await play(silent, scenario([{"say": "x", "expect_messages": 0}]))).passed
    result = await play(echo, scenario([{"say": "x", "expect_messages": 0}]))
    assert not result.passed and "got 1" in result.turns[0].checks[0].message


# --- waiting and timeouts -----------------------------------------------------------------


async def test_no_reply_fails_with_a_clear_error_and_skips_later_turns() -> None:
    sc = scenario([{"say": "a"}, {"say": "b"}], timeout_s=0.3)
    result = await play(silent, sc)
    first, second = result.turns
    assert first.status == "failed" and first.error == "the bot didn't reply within 0.3s"
    assert first.checks == [] and second.status == "skipped"


async def test_a_per_turn_timeout_overrides_the_default() -> None:
    sc = scenario([{"say": "a", "timeout_s": 0.2}], timeout_s=30)
    start = time.monotonic()
    result = await play(silent, sc)
    assert time.monotonic() - start < 3
    assert result.turns[0].error == "the bot didn't reply within 0.2s"


async def test_a_slow_reply_within_the_timeout_passes_and_latency_is_measured() -> None:
    async def slow(inbound: Inbound, send: Send) -> None:
        await asyncio.sleep(0.2)
        await send(text_body(inbound.sender, "finally"))

    sc = scenario([{"say": "a", "expect": [{"reply_within_ms": 3000}]}], timeout_s=2)
    result = await play(slow, sc)
    assert result.passed
    assert result.turns[0].bot_messages[0].latency_ms >= 150
    fast_limit = scenario([{"say": "a", "expect": [{"reply_within_ms": 20}]}], timeout_s=2)
    assert not (await play(slow, fast_limit)).passed


async def test_the_whole_scenario_can_time_out() -> None:
    sc = scenario([{"say": "a", "timeout_s": 10}])
    result = await play(silent, sc, scenario_timeout_s=0.3)
    assert not result.passed and "longer than 0.3s overall" in (result.error or "")


# --- buttons, lists, images ---------------------------------------------------------------


async def menu_bot(inbound: Inbound, send: Send) -> None:
    to = inbound.sender
    if inbound.kind == "text":
        await send(buttons_body(to, "Pick", [("b_yes", "Yes"), ("b_no", "No")]))
    elif inbound.kind == "button_reply":
        await send(
            text_body(to, f"tapped {inbound.reply_id}/{inbound.text}/ctx={inbound.context_id}")
        )
    elif inbound.kind == "image":
        await send(text_body(to, "got an image"))


async def test_tap_button_sends_the_buttons_id_title_and_context() -> None:
    sc = scenario(
        [{"say": "menu"}, {"tap_button": "yes", "expect": [{"contains": "tapped b_yes/Yes"}]}]
    )
    result = await play(menu_bot, sc)
    assert result.passed, result.turns
    menu_id = result.turns[0].bot_messages[0].message_id
    assert f"ctx={menu_id}" in result.turns[1].bot_messages[0].text


async def test_tap_by_button_id_works() -> None:
    result = await play(menu_bot, scenario([{"say": "menu"}, {"tap_button": "b_no"}]))
    assert result.passed and "tapped b_no/No" in result.turns[1].bot_messages[0].text


async def test_tapping_a_button_that_was_not_offered_fails_clearly() -> None:
    result = await play(
        menu_bot, scenario([{"say": "menu"}, {"tap_button": "Maybe"}, {"say": "x"}])
    )
    turn = result.turns[1]
    assert turn.status == "failed"
    assert (
        turn.error
        == "no button 'Maybe' on the bot's previous reply (buttons it sent: ['Yes', 'No'])"
    )
    assert result.turns[2].status == "skipped"


async def test_tapping_when_there_were_no_buttons() -> None:
    result = await play(echo, scenario([{"say": "hi"}, {"tap_button": "Yes"}]))
    assert "previous reply had no reply buttons" in (result.turns[1].error or "")
    first_turn = await play(menu_bot, scenario([{"tap_button": "Yes"}]))
    assert "previous reply had no reply buttons" in (first_turn.turns[0].error or "")


async def test_pick_row() -> None:
    async def list_bot(inbound: Inbound, send: Send) -> None:
        if inbound.kind == "text":
            await send(list_body(inbound.sender, "Choose", [("r1", "Nova"), ("r2", "Marwar")]))
        else:
            await send(text_body(inbound.sender, f"picked {inbound.reply_id}/{inbound.text}"))

    ok = await play(
        list_bot,
        scenario(
            [{"say": "list"}, {"pick_row": "marwar", "expect": [{"contains": "picked r2/Marwar"}]}]
        ),
    )
    assert ok.passed
    bad = await play(list_bot, scenario([{"say": "list"}, {"pick_row": "Acme"}]))
    assert (
        bad.turns[1].error
        == "no list row 'Acme' on the bot's previous reply (rows it sent: ['Nova', 'Marwar'])"
    )
    no_list = await play(echo, scenario([{"say": "x"}, {"pick_row": "Nova"}]))
    assert "had no list" in (no_list.turns[1].error or "")


async def test_send_image() -> None:
    sc = scenario([{"send_image": {"caption": "pic"}, "expect": [{"contains": "got an image"}]}])
    assert (await play(menu_bot, sc)).passed
    assert (await play(menu_bot, scenario([{"send_image": None}]))).passed


# --- rejected messages fail by default ------------------------------------------------------


async def four_buttons(inbound: Inbound, send: Send) -> None:
    buttons = [(f"b{i}", f"Option {i}") for i in range(4)]
    await send(buttons_body(inbound.sender, "Too many", buttons))


async def test_a_message_the_mock_rejects_fails_the_turn() -> None:
    result = await play(four_buttons, scenario([{"say": "x", "expect_messages": 1}]))
    turn = result.turns[0]
    assert not result.passed and turn.bot_messages == []
    (rejected,) = turn.rejected
    assert rejected.reasons == ["interactive.action.buttons: has 4 buttons; at most 3 allowed"]
    assert rejected.payload is not None
    check = next(c for c in turn.checks if c.kind == "rejected_messages")
    assert (
        not check.passed
        and "WhatsApp would reject" in check.message
        and "4 buttons" in check.message
    )
    # one attempt was made, so the count itself is fine
    assert next(c for c in turn.checks if c.kind == "expect_messages").passed


async def test_the_text_of_a_rejected_message_is_checked_too() -> None:
    """A rejected 4-button message that ALSO has a wrong date and advice reports all three."""

    async def bad_everything(inbound: Inbound, send: Send) -> None:
        body = buttons_body(
            inbound.sender,
            "listing date is 1 December 2026. You should apply!",
            [(f"b{i}", f"Option {i}") for i in range(4)],
        )
        await send(body)

    sc = scenario(
        [
            {
                "say": "x",
                "expect": [
                    FACT,
                    {"not_contains": "you should apply"},
                    {"button_count": 3},
                    {"contains": "listing date"},  # this one is fine
                ],
            }
        ]
    )
    result = await play(bad_everything, sc)
    turn = result.turns[0]
    assert turn.status == "failed" and not result.passed
    assert [(c.kind, c.passed) for c in turn.checks] == [
        ("rejected_messages", False),
        ("fact", False),
        ("not_contains", False),
        ("button_count", False),
        ("contains", True),
    ]
    assert turn.bot_messages == []  # still: nothing was delivered
    assert (
        turn.problems[0] == "rejected: interactive.action.buttons: has 4 buttons; at most 3 allowed"
    )
    assert [p.split(":")[0] for p in turn.problems[1:]] == ["also", "also", "also"]
    assert (
        "also: reply says listing date 1 December 2026 but ipos says 30 November 2026"
        in turn.summary
    )
    assert "also: reply must not contain ['you should apply']" in turn.summary
    assert "also: expected 3 reply buttons but got [4]" in turn.summary


async def test_a_rejected_message_with_clean_text_still_fails_the_turn() -> None:
    sc = scenario([{"say": "x", "expect": [{"contains": "Too many"}]}])
    result = await play(four_buttons, sc)
    turn = result.turns[0]
    assert turn.status == "failed" and not result.passed
    assert [(c.kind, c.passed) for c in turn.checks] == [
        ("rejected_messages", False),
        ("contains", True),
    ]
    assert turn.problems == [
        "rejected: interactive.action.buttons: has 4 buttons; at most 3 allowed"
    ]


async def test_problems_and_summary_cover_errors_and_are_empty_when_passing() -> None:
    ok = await play(echo, scenario([{"say": "x"}]))
    assert ok.turns[0].problems == [] and ok.turns[0].summary == ""
    silent_result = await play(silent, scenario([{"say": "x"}], timeout_s=0.2))
    assert silent_result.turns[0].problems == ["the bot didn't reply within 0.2s"]


async def test_allow_rejected_lets_the_turn_pass() -> None:
    sc = scenario([{"say": "x", "expect_messages": 1, "allow_rejected": True}])
    result = await play(four_buttons, sc)
    assert result.passed and len(result.turns[0].rejected) == 1
    by_default = scenario([{"say": "x"}], allow_rejected=True)
    assert (await play(four_buttons, by_default)).passed


async def test_checks_still_run_when_some_messages_were_accepted() -> None:
    async def mixed(inbound: Inbound, send: Send) -> None:
        await four_buttons(inbound, send)
        await send(text_body(inbound.sender, "fine"))

    result = await play(mixed, scenario([{"say": "x", "expect": [{"contains": "fine"}]}]))
    kinds = {c.kind: c.passed for c in result.turns[0].checks}
    assert kinds == {"rejected_messages": False, "contains": True}


# --- facts through the runner -----------------------------------------------------------------

FACT = {
    "fact": {
        "source": "ipos",
        "entity": "Nova Textiles",
        "field": "listing_date",
        "extract": {"regex": r"listing date is (\d{1,2} \w+ \d{4})", "parser": "date"},
    }
}


async def test_fact_check_passes_with_the_right_date() -> None:
    async def right(inbound: Inbound, send: Send) -> None:
        await send(text_body(inbound.sender, "Nova: listing date is 30 November 2026."))

    assert (await play(right, scenario([{"say": "x", "expect": [FACT]}]))).passed


async def test_fact_check_fails_when_the_reply_has_no_date_at_all() -> None:
    async def vague(inbound: Inbound, send: Send) -> None:
        await send(text_body(inbound.sender, "Nova Textiles lists soon. Anything else?"))

    result = await play(vague, scenario([{"say": "x", "expect": [FACT]}]))
    assert not result.passed
    (check,) = result.turns[0].checks
    assert check.kind == "fact" and not check.passed
    assert "couldn't find a listing date in the reply" in check.message


async def test_fact_check_fails_when_the_bot_says_a_wrong_date() -> None:
    async def wrong(inbound: Inbound, send: Send) -> None:
        await send(text_body(inbound.sender, "listing date is 1 December 2026"))

    result = await play(wrong, scenario([{"say": "x", "expect": [FACT]}]))
    assert "1 December 2026 but ipos says 30 November 2026" in result.turns[0].checks[0].message


# --- other failure modes --------------------------------------------------------------------


async def test_a_bot_that_rejects_the_webhook_is_reported() -> None:
    async with scripted_rig(echo) as rig:
        bad = WebhookSimulator("http://bot/webhook", app_secret="wrong", client=rig.sim._client)
        result = await ScenarioRunner(simulator=bad, store=rig.store).run_scenario(
            scenario([{"say": "x"}]), USER
        )
    assert result.turns[0].error == "the bot answered the webhook with HTTP 401"


# --- many scenarios at once -------------------------------------------------------------------


async def test_parallel_scenarios_do_not_cross_talk() -> None:
    scenarios = [
        scenario(
            [{"say": f"msg-{i}", "expect": [{"contains": f"echo msg-{i}"}, {"message_count": 1}]}],
            name=f"s{i}",
        )
        for i in range(12)
    ]
    async with scripted_rig(echo) as rig:
        run = await runner(rig, concurrency=6).run(scenarios, seed=5)
    assert run.total == 12 and run.passed == 12 and run.exit_code == 0
    assert [r.name for r in run.scenarios] == [f"s{i}" for i in range(12)]  # input order
    assert len({r.user_wa_id for r in run.scenarios}) == 12


async def test_concurrency_is_bounded() -> None:
    active = peak = 0

    async def slow(inbound: Inbound, send: Send) -> None:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.1)
        await send(text_body(inbound.sender, "ok"))
        active -= 1

    scenarios = [scenario([{"say": "x"}], name=f"s{i}") for i in range(9)]
    async with scripted_rig(slow) as rig:
        await runner(rig, concurrency=3).run(scenarios)
    assert 2 <= peak <= 3


async def test_run_result_summary_callback_and_json() -> None:
    scenarios = [
        scenario([{"say": "x", "expect": [{"contains": "echo"}]}], name="good"),
        scenario([{"say": "x", "expect": [{"contains": "nope"}]}], name="bad"),
    ]
    done: list[str] = []
    async with scripted_rig(echo) as rig:
        run = await runner(rig).run(scenarios, on_done=lambda r: done.append(r.name))
    assert sorted(done) == ["bad", "good"]
    assert (run.total, run.passed, run.failed, run.exit_code) == (2, 1, 1, 1)
    again = RunResult.model_validate_json(run.model_dump_json())
    assert [s.name for s in again.scenarios] == ["good", "bad"]
    assert (
        json.loads(run.model_dump_json())["scenarios"][1]["turns"][0]["checks"][0]["passed"]
        is False
    )
