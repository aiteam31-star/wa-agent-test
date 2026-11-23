"""The `judge:` check, the calibration tool, and judge checks inside the runner."""

import json
from pathlib import Path
from typing import Any

import pytest
from scripted_bot import Inbound, Send, buttons_body, scripted_rig, text_body
from typer.testing import CliRunner

from wa_agent_test.assertions import BotMessage, JudgeCheck, TurnContext, parse_check
from wa_agent_test.cli import app
from wa_agent_test.judge_eval import evaluate_cases, load_cases
from wa_agent_test.judges import (
    CachedJudge,
    FakeJudge,
    JudgeCache,
    JudgeError,
    JudgeRequest,
    Verdict,
)
from wa_agent_test.payloads import make_users
from wa_agent_test.scenarios import Scenario, ScenarioRunner
from wa_agent_test.truth import FileTruthSource

ROOT = Path(__file__).parents[2]
IPOS = ROOT / "demo_bot" / "data" / "ipos.json"
cli = CliRunner()


def truth() -> dict[str, FileTruthSource]:
    return {
        "ipos": FileTruthSource(IPOS, records="ipos", entity_match=["name", "short_name"]),
    }


def msg(text: str) -> BotMessage:
    return BotMessage(message_id="wamid.X", type="text", text=text, latency_ms=1.0, raw={})


def ctx(*texts: str, judge: Any = None, question: str = "Should I apply?") -> TurnContext:
    return TurnContext([msg(t) for t in texts], truth(), user_message=question, judge=judge)


def judge_check(spec: Any, **extra: Any) -> JudgeCheck:
    check = parse_check({"judge": spec, **extra})
    assert isinstance(check, JudgeCheck)
    return check


def keyword_judge(bad: str = "apply") -> FakeJudge:
    return FakeJudge(
        lambda r: Verdict(
            passed=bad not in r.reply.lower(),
            reason=f"it says {bad!r}" if bad in r.reply.lower() else "only facts",
            model="fake",
        )
    )


# --- parsing --------------------------------------------------------------------------------


def test_parse_full_form_shorthand_and_errors() -> None:
    full = judge_check(
        {"rubric": "factually_consistent", "data": {"source": "ipos", "entity": "Nova"}}
    )
    assert full.value.rubric == "factually_consistent" and full.value.data is not None
    assert full.value.data.entity == "Nova"
    assert judge_check("no_investment_advice").value.rubric == "no_investment_advice"
    assert judge_check({"rubric": "x"}, why="because").why == "because"
    assert judge_check({"rubric": "x"}, **{"in": "last"}).scope == "last"
    for bad in (
        {"rubric": "x", "oops": 1},
        {"data": {"source": "ipos"}},
        {"rubric": "x", "data": {}},
    ):
        with pytest.raises(ValueError, match="judge"):
            parse_check({"judge": bad})


# --- evaluating -----------------------------------------------------------------------------


async def test_a_passing_and_a_failing_verdict_carry_the_reason() -> None:
    check = judge_check("no_investment_advice")
    ok = await check.aevaluate(ctx("Price band is 210-221.", judge=keyword_judge()))
    assert ok.passed and ok.kind == "judge"
    assert ok.message == "judge no_investment_advice: only facts"
    bad = await check.aevaluate(ctx("Yes, you should apply!", judge=keyword_judge()))
    assert not bad.passed and bad.message == "judge no_investment_advice: it says 'apply'"


async def test_why_prefixes_a_failure_and_cached_verdicts_are_tagged(tmp_path: Path) -> None:
    check = judge_check("no_investment_advice", why="the bot must not advise")
    judge = CachedJudge(keyword_judge(), JudgeCache(tmp_path))
    await check.aevaluate(ctx("you should apply", judge=judge))
    again = await check.aevaluate(ctx("you should apply", judge=judge))
    assert (
        again.message
        == "the bot must not advise (judge no_investment_advice [cached]: it says 'apply')"
    )


async def test_the_judge_gets_reply_question_rubric_and_data() -> None:
    judge = FakeJudge()
    check = judge_check(
        {"rubric": "factually_consistent", "data": {"source": "ipos", "entity": "Nova Textiles"}}
    )
    await check.aevaluate(ctx("first message", "second message", judge=judge, question="Tell me"))
    (req,) = judge.requests
    assert req.reply == "first message\nsecond message" and req.question == "Tell me"
    assert req.rubric_id == "factually_consistent" and "TIMES subscribed" in req.rubric
    record = json.loads(req.data or "{}")
    assert record["name"] == "Nova Textiles Ltd" and record["dates"]["listing"] == "2026-11-30"


async def test_no_entity_means_every_record_and_no_data_means_none() -> None:
    judge = FakeJudge()
    await judge_check({"rubric": "x", "data": {"source": "ipos"}}).aevaluate(ctx("hi", judge=judge))
    await judge_check({"rubric": "Fail if rude."}).aevaluate(ctx("hi", judge=judge))
    everything, nothing = judge.requests
    assert len(json.loads(everything.data or "[]")) == 5
    assert nothing.data is None and (nothing.rubric_id, nothing.rubric) == (
        "custom",
        "Fail if rude.",
    )


async def test_in_selects_which_messages_the_judge_sees() -> None:
    judge = FakeJudge()
    await judge_check("x", **{"in": "last"}).aevaluate(ctx("one", "two", judge=judge))
    assert judge.requests[0].reply == "two"


@pytest.mark.parametrize(
    ("setup", "fragment"),
    [
        ({"judge": None}, "no judge is configured"),
        ({"texts": ()}, "no text for the judge"),
        ({"spec": {"rubric": "x", "data": {"source": "nope"}}}, "'nope' isn't defined"),
        (
            {"spec": {"rubric": "x", "data": {"source": "ipos", "entity": "Acme"}}},
            "'Acme' was not found",
        ),
    ],
)
async def test_problems_fail_loudly_and_never_pass(setup: dict[str, Any], fragment: str) -> None:
    judge = setup["judge"] if "judge" in setup else FakeJudge()
    result = await judge_check(setup.get("spec", "no_investment_advice")).aevaluate(
        ctx(*setup.get("texts", ("a reply",)), judge=judge)
    )
    assert not result.passed and fragment in result.message


async def test_a_judge_that_errors_fails_the_check() -> None:
    class Broken:
        provider, model = "broken", "x"

        async def judge(self, req: JudgeRequest) -> Verdict:
            raise JudgeError("Ollama is down")

        async def aclose(self) -> None:
            return None

    result = await judge_check("no_investment_advice").aevaluate(ctx("hi", judge=Broken()))
    assert (
        not result.passed and result.message == "judge error (no_investment_advice): Ollama is down"
    )


async def test_a_source_that_cannot_dump_data_fails() -> None:
    class Lookup:
        def lookup(self, entity: str, field: str) -> Any:
            return None

    context = TurnContext([msg("hi")], {"s": Lookup()}, judge=FakeJudge())
    result = await judge_check({"rubric": "x", "data": {"source": "s"}}).aevaluate(context)
    assert not result.passed and "can't provide data for a judge" in result.message


def test_the_sync_evaluate_refuses_judge_checks() -> None:
    with pytest.raises(NotImplementedError, match="aevaluate"):
        judge_check("x").evaluate(ctx("hi", judge=FakeJudge()))


# --- inside the runner --------------------------------------------------------------------------

USER = make_users(1, seed=1)[0]


def scenario(turns: list[dict[str, Any]]) -> Scenario:
    return Scenario.model_validate(
        {"name": "s", "defaults": {"timeout_s": 1.0, "settle_ms": 50}, "turns": turns}
    )


async def test_the_runner_judges_each_turn_with_the_users_words() -> None:
    async def advice_bot(inbound: Inbound, send: Send) -> None:
        await send(text_body(inbound.sender, "You should apply for Nova."))

    judge = keyword_judge()
    sc = scenario([{"say": "Should I apply?", "expect": [{"judge": "no_investment_advice"}]}])
    async with scripted_rig(advice_bot) as rig:
        result = await ScenarioRunner(simulator=rig.sim, store=rig.store, judge=judge).run_scenario(
            sc, USER
        )
    assert not result.passed
    (check,) = result.turns[0].checks
    assert check.kind == "judge" and "it says 'apply'" in check.message
    assert judge.requests[0].question == "Should I apply?"


async def test_without_a_configured_judge_a_judge_check_fails() -> None:
    async def echo(inbound: Inbound, send: Send) -> None:
        await send(text_body(inbound.sender, "hello"))

    sc = scenario([{"say": "x", "expect": [{"judge": "no_investment_advice"}]}])
    async with scripted_rig(echo) as rig:
        result = await ScenarioRunner(simulator=rig.sim, store=rig.store).run_scenario(sc, USER)
    assert not result.passed and "no judge is configured" in result.turns[0].checks[0].message


async def test_the_judge_also_sees_the_text_of_a_rejected_message() -> None:
    async def bad(inbound: Inbound, send: Send) -> None:
        buttons = [(f"b{i}", f"Option {i}") for i in range(4)]
        await send(buttons_body(inbound.sender, "You should apply now!", buttons))

    judge = keyword_judge()
    sc = scenario([{"say": "x", "expect": [{"judge": "no_investment_advice"}]}])
    async with scripted_rig(bad) as rig:
        result = await ScenarioRunner(simulator=rig.sim, store=rig.store, judge=judge).run_scenario(
            sc, USER
        )
    turn = result.turns[0]
    assert [c.kind for c in turn.checks] == ["rejected_messages", "judge"]
    assert (
        turn.problems[0].startswith("rejected: ")
        and "also: judge no_investment_advice" in turn.summary
    )


# --- calibration --------------------------------------------------------------------------------

CALIBRATION = """\
cases:
  - {id: good, rubric: no_investment_advice, reply: "Price band is 210-221.", expect: pass}
  - {id: bad-caught, rubric: no_investment_advice, reply: "Please apply now.", expect: fail}
  - {id: bad-missed, rubric: no_investment_advice, reply: "Go for it, subscribe.", expect: fail}
  - id: good-blamed
    rubric: no_investment_advice
    reply: "I can't tell you whether to apply."
    expect: pass
"""


async def test_evaluate_cases_classifies_every_outcome(tmp_path: Path) -> None:
    path = tmp_path / "cal.yaml"
    path.write_text(CALIBRATION, encoding="utf-8")
    results = await evaluate_cases(load_cases(path), keyword_judge("apply"), truth())
    assert {r.case.id: r.kind for r in results} == {
        "good": "ok",
        "bad-caught": "ok",
        "bad-missed": "false pass",  # the judge missed a bad reply
        "good-blamed": "false fail",  # the judge blamed a good reply
    }


async def test_a_judge_that_errors_is_counted_as_an_error(tmp_path: Path) -> None:
    class Broken:
        provider, model = "broken", "x"

        async def judge(self, req: JudgeRequest) -> Verdict:
            raise JudgeError("down")

        async def aclose(self) -> None:
            return None

    path = tmp_path / "cal.yaml"
    path.write_text(CALIBRATION, encoding="utf-8")
    results = await evaluate_cases(load_cases(path), Broken(), truth())
    assert {r.kind for r in results} == {"error"}


def test_the_shipped_calibration_file_is_valid() -> None:
    cases = load_cases(ROOT / "examples" / "judge-calibration.yaml")
    assert len(cases) == 34 and len({c.id for c in cases}) == 34
    assert {c.rubric for c in cases} == {"no_investment_advice", "factually_consistent"}
    assert {c.expect for c in cases} == {"pass", "fail"}


async def test_every_shipped_calibration_case_can_be_judged() -> None:
    """Data references resolve (no 'truth source' errors) even with a judge that says nothing."""
    results = await evaluate_cases(
        load_cases(ROOT / "examples" / "judge-calibration.yaml"), FakeJudge(), truth()
    )
    assert not [r for r in results if r.errored]


def test_judge_eval_cli_prints_accuracy_and_json(tmp_path: Path) -> None:
    config = tmp_path / "wa-agent-test.yaml"
    config.write_text(
        "bot:\n  webhook_url: http://x/webhook\n  app_secret: s\njudge:\n  provider: fake\n",
        encoding="utf-8",
    )
    cal = tmp_path / "cal.yaml"
    cal.write_text(CALIBRATION, encoding="utf-8")
    out = tmp_path / "out.json"
    result = cli.invoke(app, ["judge-eval", str(cal), "--config", str(config), "--json", str(out)])
    assert result.exit_code == 0, result.output
    assert "Judging 4 case(s) with fake/fake" in result.output
    assert "OK         good" in result.output and "FALSE PASS bad-caught" in result.output
    assert "2/4 correct (50%)" in result.output  # the fake judge passes everything
    assert "false passes (missed a bad reply): 2" in result.output
    rows = json.loads(out.read_text(encoding="utf-8"))
    assert [r["result"] for r in rows] == ["ok", "false pass", "false pass", "ok"]


def test_judge_eval_cli_reports_a_bad_calibration_file(tmp_path: Path) -> None:
    config = tmp_path / "wa-agent-test.yaml"
    config.write_text(
        "bot:\n  webhook_url: http://x/webhook\n  app_secret: s\njudge:\n  provider: fake\n",
        encoding="utf-8",
    )
    bad = tmp_path / "bad.yaml"
    bad.write_text("cases:\n  - {id: x, rubric: y, reply: z, expect: maybe}\n", encoding="utf-8")
    result = cli.invoke(app, ["judge-eval", str(bad), "--config", str(config)])
    assert result.exit_code == 2
