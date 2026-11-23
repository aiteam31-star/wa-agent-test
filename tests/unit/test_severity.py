"""severity: fail (default) or warn, on every check. Warnings are reported, never failures."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from scripted_bot import Inbound, Send, buttons_body, scripted_rig, text_body

from wa_agent_test.assertions import BotMessage, CheckResult, JudgeCheck, TurnContext, parse_check
from wa_agent_test.baseline import Baseline, BaselineEntry, compare, failure_problems
from wa_agent_test.payloads import make_users
from wa_agent_test.report import render_report
from wa_agent_test.scenarios import (
    RunResult,
    Scenario,
    ScenarioResult,
    ScenarioRunner,
    TurnResult,
    load_scenarios,
)
from wa_agent_test.truth import FileTruthSource

ROOT = Path(__file__).parents[2]
IPOS = ROOT / "demo_bot" / "data" / "ipos.json"
NOW = datetime(2026, 11, 23, 10, 15, tzinfo=UTC)
USER = make_users(1, seed=1)[0]


def truth() -> dict[str, FileTruthSource]:
    return {
        "ipos": FileTruthSource(
            IPOS,
            records="ipos",
            entity_match=["name", "short_name"],
            fields={"listing_date": "dates.listing"},
        )
    }


def msg(text: str) -> BotMessage:
    return BotMessage(message_id="wamid.X", type="text", text=text, latency_ms=10.0, raw={})


# --- parsing and the result flags -----------------------------------------------------------------


def test_severity_defaults_to_fail_and_accepts_warn() -> None:
    assert parse_check({"contains": "x"}).severity == "fail"
    assert parse_check({"contains": "x", "severity": "warn"}).severity == "warn"
    assert parse_check({"contains": "x", "severity": "fail"}).severity == "fail"
    for bad in ("warning", "info", "", 1):
        with pytest.raises(ValueError, match="severity"):
            parse_check({"contains": "x", "severity": bad})


FACT = {
    "fact": {
        "source": "ipos",
        "entity": "Nova Textiles",
        "field": "listing_date",
        "extract": {"regex": "zzz", "parser": "date"},
    }
}


@pytest.mark.parametrize(
    "check",
    [
        {"contains": "nope"},
        {"not_contains": "hello"},
        {"equals": "x"},
        {"regex": "zzz"},
        {"message_count": 5},
        {"message_type": "interactive"},
        {"button_count": 3},
        {"button_titles": ["A"]},
        {"reply_within_ms": 0},
        FACT,
        {"known_dates": {"source": "ipos", "fields": ["listing_date"]}},
    ],
    ids=lambda c: next(iter(c)),
)
def test_every_kind_of_check_can_be_a_warning(check: dict[str, Any]) -> None:
    """The reply 'hello 29 Sep 2022' fails each of these; as a warning it must not be a failure."""
    ctx = TurnContext([msg("hello 29 Sep 2022")], truth())
    hard = parse_check(check).evaluate(ctx)
    soft = parse_check({**check, "severity": "warn"}).evaluate(ctx)
    assert not hard.passed and hard.failed and not hard.warned and hard.severity == "fail"
    assert not soft.passed and soft.warned and not soft.failed and soft.severity == "warn"
    assert soft.message == hard.message  # the same explanation either way


def test_a_passing_warn_check_is_neither_failed_nor_warned() -> None:
    check = parse_check({"contains": "hello", "severity": "warn"})
    result = check.evaluate(TurnContext([msg("hello")], truth()))
    assert result.passed and not result.failed and not result.warned


def test_severity_works_with_why_and_with_a_missing_message() -> None:
    check = parse_check(
        {"contains": "x", "in": 5, "why": "needs a fifth message", "severity": "warn"}
    )
    result = check.evaluate(TurnContext([msg("a")], truth()))
    assert result.warned and result.message.startswith("needs a fifth message (")


def test_severity_is_kept_in_the_json_results() -> None:
    result = CheckResult(kind="judge", passed=False, message="m", severity="warn")
    assert result.model_dump(mode="json")["severity"] == "warn"
    assert (
        CheckResult.model_validate({"kind": "x", "passed": True, "message": "m"}).severity == "fail"
    )


# --- inside the runner ----------------------------------------------------------------------------


def scenario(turns: list[dict[str, Any]]) -> Scenario:
    return Scenario.model_validate(
        {"name": "s", "defaults": {"timeout_s": 1.0, "settle_ms": 50}, "turns": turns}
    )


async def echo(inbound: Inbound, send: Send) -> None:
    await send(text_body(inbound.sender, f"echo {inbound.text}"))


async def four_buttons(inbound: Inbound, send: Send) -> None:
    buttons = [(f"b{i}", f"Option {i}") for i in range(4)]
    await send(buttons_body(inbound.sender, "Too many", buttons))


async def play(handler: Any, sc: Scenario) -> ScenarioResult:
    async with scripted_rig(handler) as rig:
        return await ScenarioRunner(simulator=rig.sim, store=rig.store, truth=truth()).run_scenario(
            sc, USER
        )


async def test_a_failed_warn_check_is_recorded_but_does_not_fail_the_turn() -> None:
    sc = scenario(
        [
            {
                "say": "hello",
                "expect": [{"contains": "echo hello"}, {"contains": "nope", "severity": "warn"}],
            }
        ]
    )
    result = await play(echo, sc)
    turn = result.turns[0]
    assert result.passed and turn.status == "passed"
    assert [(c.kind, c.passed, c.severity) for c in turn.checks] == [
        ("contains", True, "fail"),
        ("contains", False, "warn"),
    ]
    assert turn.problems == [] and turn.summary == ""
    assert len(turn.warnings) == 1 and "missing ['nope']" in turn.warnings[0]
    assert result.warning_count == 1


async def test_a_real_failure_next_to_a_warning_still_fails_and_lists_only_the_failure() -> None:
    sc = scenario(
        [
            {
                "say": "hello",
                "expect": [
                    {"contains": "nope", "severity": "warn"},
                    {"contains": "missing", "severity": "fail"},
                ],
            },
            {"say": "again"},
        ]
    )
    result = await play(echo, sc)
    first, second = result.turns
    assert not result.passed and first.status == "failed" and second.status == "skipped"
    assert len(first.problems) == 1 and "missing ['missing']" in first.problems[0]
    assert len(first.warnings) == 1 and "missing ['nope']" in first.warnings[0]


async def test_a_judge_that_cannot_answer_is_only_a_warning_when_set_to_warn() -> None:
    soft = scenario(
        [{"say": "hello", "expect": [{"judge": "no_investment_advice", "severity": "warn"}]}]
    )
    result = await play(echo, soft)  # no judge is configured for this run
    assert result.passed and "no judge is configured" in result.turns[0].warnings[0]
    hard = scenario([{"say": "hello", "expect": [{"judge": "no_investment_advice"}]}])
    assert not (await play(echo, hard)).passed


async def test_warnings_do_not_hide_the_combined_rejected_lines() -> None:
    sc = scenario(
        [{"say": "x", "expect": [{"contains": "nope", "severity": "warn"}, {"button_count": 3}]}]
    )
    turn = (await play(four_buttons, sc)).turns[0]
    assert turn.problems[0].startswith("rejected: ")
    assert "also: expected 3 reply buttons" in turn.summary and len(turn.warnings) == 1


# --- baselines ------------------------------------------------------------------------------------


def test_a_scenario_with_only_warnings_is_a_pass_for_baselines() -> None:
    warned = ScenarioResult(
        name="a",
        user_wa_id="1",
        passed=True,
        duration_s=1,
        turns=[
            TurnResult(
                index=1,
                action="say: 'x'",
                status="passed",
                checks=[CheckResult(kind="judge", passed=False, message="hmm", severity="warn")],
            )
        ],
    )
    assert failure_problems(warned) == []
    run = RunResult(started_at=NOW, duration_s=1.0, scenarios=[warned])
    before = Baseline(saved_at=NOW, scenarios={"a": BaselineEntry(passed=True)})
    comparison = compare(run, before)
    assert comparison.items[0].status == "still_passing" and not comparison.has_regression
    assert comparison.summary == "0 newly broken, 0 fixed, 1 unchanged"
    assert run.warning_count == 1 and run.exit_code == 0


# --- the report -----------------------------------------------------------------------------------


def warned_run(*names: str) -> RunResult:
    scenarios = []
    for name in names:
        warning = CheckResult(
            kind="judge",
            passed=False,
            severity="warn",
            message="judge factually_consistent: reply says 225 but data says 221",
        )
        scenarios.append(
            ScenarioResult(
                name=name,
                user_wa_id="1",
                passed=True,
                duration_s=0.5,
                turns=[
                    TurnResult(
                        index=1,
                        action="say: 'hi'",
                        user_text="hi",
                        status="passed",
                        checks=[
                            CheckResult(kind="contains", passed=True, message="reply contains 'x'"),
                            warning,
                        ],
                        bot_messages=[msg("Nova Textiles has a price band of ₹210-221.")],
                    )
                ],
            )
        )
    return RunResult(started_at=NOW, duration_s=3.0, scenarios=scenarios)


def test_warnings_show_in_yellow_with_their_reason_and_are_not_failures() -> None:
    html = render_report(warned_run("warned"))
    assert 'class="check warn"' in html and "⚠" in html
    assert "judge factually_consistent: reply says 225 but data says 221" in html
    assert "Warnings (these never fail the run)" in html
    assert 'class="tag">warning</span>' in html  # not colour alone
    assert "What went wrong" not in html and 'class="check fail"' not in html
    assert "<h1>1 passed, 0 failed</h1>" in html and "All scenarios passed" in html
    assert '<span class="badge warn">1 warning</span>' in html
    assert '<span class="chip warn"><b>1</b> warning</span>' in html
    assert "1 warning(s) (never failures)" in html


def test_a_passing_scenario_with_a_warning_starts_open() -> None:
    run = warned_run("warned")
    quiet = ScenarioResult(name="quiet", user_wa_id="2", passed=True, duration_s=0.1)
    html = render_report(RunResult(started_at=NOW, duration_s=1, scenarios=[*run.scenarios, quiet]))
    warned = html[html.index('id="s1-warned"') : html.index('id="s1-warned"') + 60]
    calm = html[html.index('id="s2-quiet"') : html.index('id="s2-quiet"') + 60]
    assert " open" in warned and " open" not in calm


def test_warnings_and_failures_are_shown_separately_in_one_turn() -> None:
    mixed = ScenarioResult(
        name="mixed",
        user_wa_id="1",
        passed=False,
        duration_s=1,
        turns=[
            TurnResult(
                index=1,
                action="say: 'x'",
                status="failed",
                checks=[
                    CheckResult(kind="fact", passed=False, message="hard failure text"),
                    CheckResult(
                        kind="judge", passed=False, severity="warn", message="soft warning text"
                    ),
                ],
            )
        ],
    )
    html = render_report(RunResult(started_at=NOW, duration_s=1, scenarios=[mixed]))
    assert "<li>hard failure text</li>" in html and "<li>soft warning text</li>" in html
    problems = html[html.index("What went wrong") : html.index("Warnings (these never")]
    assert "hard failure text" in problems and "soft warning text" not in problems
    assert 'class="check fail"' in html and 'class="check warn"' in html


# --- the demo scenarios ---------------------------------------------------------------------------


def test_the_judge_checks_in_the_advice_traps_are_warnings_and_the_simple_checks_are_not() -> None:
    """The judge is a small model that can be wrong, so in the demo it warns instead of failing."""
    judge, simple = [], []
    for s in load_scenarios(ROOT / "examples" / "scenarios"):
        if not s.name.startswith("advice-trap"):
            continue
        for turn in s.turns:
            for check in turn.expect:
                (judge if isinstance(check, JudgeCheck) else simple).append(check)
    assert len(judge) == 10  # two rubrics on each of the five traps
    assert all(check.severity == "warn" for check in judge)
    assert simple and all(check.severity == "fail" for check in simple)
