"""The HTML report: self-contained, chat-style, and honest about what failed."""

import re
from datetime import UTC, datetime
from pathlib import Path

from wa_agent_test.assertions import BotMessage, Button, CheckResult, Row
from wa_agent_test.baseline import Baseline, BaselineEntry, compare
from wa_agent_test.report import render_report, write_report
from wa_agent_test.scenarios import RejectedMessage, RunResult, ScenarioResult, TurnResult

NOW = datetime(2026, 11, 23, 10, 15, tzinfo=UTC)


def bot(
    text: str, *, buttons: list[str] | None = None, rows: list[str] | None = None
) -> BotMessage:
    return BotMessage(
        message_id="wamid.X",
        type="interactive" if buttons or rows else "text",
        text=text,
        buttons=[Button(id=f"b{i}", title=t) for i, t in enumerate(buttons or [])],
        rows=[Row(id=f"r{i}", title=t, description="row detail") for i, t in enumerate(rows or [])],
        latency_ms=120.0,
        raw={},
    )


def turn(
    index: int,
    *,
    user: str = "hello",
    status: str = "passed",
    messages: list[BotMessage] | None = None,
    checks: list[CheckResult] | None = None,
    rejected: list[RejectedMessage] | None = None,
    error: str | None = None,
) -> TurnResult:
    return TurnResult(
        index=index,
        action=f"say: {user!r}",
        user_text=user,
        status=status,  # type: ignore[arg-type]
        duration_ms=250.0,
        error=error,
        checks=checks or [],
        bot_messages=messages or [],
        rejected=rejected or [],
    )


def scenario(name: str, turns: list[TurnResult], passed: bool | None = None) -> ScenarioResult:
    ok = all(t.status == "passed" for t in turns) if passed is None else passed
    return ScenarioResult(
        name=name,
        user_wa_id="919800000000",
        passed=ok,
        duration_s=0.5,
        tags=["ipo", "facts"],
        turns=turns,
    )


def run_of(*scenarios: ScenarioResult) -> RunResult:
    return RunResult(started_at=NOW, duration_s=3.0, scenarios=list(scenarios))


def good(name: str = "good scenario") -> ScenarioResult:
    return scenario(name, [turn(1, messages=[bot("Price band is ₹210-221.")])])


def bad(name: str = "bad scenario") -> ScenarioResult:
    return scenario(
        name,
        [
            turn(
                1,
                status="failed",
                messages=[bot("listing date is 1 December 2026")],
                checks=[
                    CheckResult(
                        kind="fact", passed=False, message="reply says 1 Dec but data says 30 Nov"
                    ),
                    CheckResult(kind="contains", passed=True, message="reply contains 'listing'"),
                ],
            ),
            turn(2, status="skipped"),
        ],
    )


def baseline_of(**entries: bool) -> Baseline:
    return Baseline(
        saved_at=NOW, scenarios={n: BaselineEntry(passed=ok) for n, ok in entries.items()}
    )


# --- self-contained and safe ---------------------------------------------------------------------


def test_the_report_is_one_self_contained_file() -> None:
    html = render_report(run_of(good(), bad()))
    assert html.startswith("<!doctype html>") and "</html>" in html
    assert "<script" not in html and "<link" not in html and "<img" not in html
    assert not re.search(r"(src|href)=[\"']https?:", html)
    assert "@import" not in html and "url(" not in html  # no fonts or images from elsewhere
    assert '<meta charset="utf-8">' in html and "prefers-color-scheme: dark" in html


def test_everything_from_the_bot_and_scenario_is_escaped() -> None:
    evil = scenario(
        "<b>name</b>",
        [
            turn(
                1,
                user="<img src=x onerror=alert(1)>",
                messages=[bot("<script>alert('hi')</script>", buttons=["<i>Yes</i>"])],
                checks=[CheckResult(kind="contains", passed=False, message="<u>missing</u>")],
                status="failed",
            )
        ],
    )
    html = render_report(run_of(evil))
    for raw in ("<script>alert", "<img src=x", "<b>name</b>", "<i>Yes</i>", "<u>missing</u>"):
        assert raw not in html
    assert "&lt;script&gt;alert" in html and "&lt;b&gt;name&lt;/b&gt;" in html


# --- the summary at the top -----------------------------------------------------------------------


def test_without_a_baseline_the_headline_counts_passes_and_failures() -> None:
    html = render_report(run_of(good(), bad()))
    assert "<h1>1 passed, 1 failed</h1>" in html
    assert "Some scenarios failed" in html and "No baseline to compare with" in html
    assert "save one with --save-baseline" in html
    assert "Failed" in html and "Passed" in html


def test_with_a_baseline_the_headline_is_the_comparison_summary() -> None:
    run = run_of(good("fixed"), bad("broke"), good("same"))
    comparison = compare(run, baseline_of(fixed=False, broke=True, same=True))
    html = render_report(run, comparison, baseline_path="baselines/b.json")
    assert "<h1>1 newly broken, 1 fixed, 1 unchanged</h1>" in html
    assert "Regression: 1 scenario(s) broke" in html and 'class="verdict bad"' in html
    assert "Compared with the baseline saved 2026-11-23 10:15 UTC (baselines/b.json)" in html


def test_a_clean_comparison_says_no_new_breakage() -> None:
    run = run_of(good("a"), good("b"))
    html = render_report(run, compare(run, baseline_of(a=True, b=True)))
    assert "<h1>0 newly broken, 0 fixed, 2 unchanged</h1>" in html
    assert "No new breakage" in html and 'class="verdict good"' in html


def test_groups_are_ordered_worst_first_and_broken_ones_start_open() -> None:
    run = run_of(good("same"), good("fixed"), bad("broke"), bad("still bad"))
    comparison = compare(
        run, baseline_of(same=True, fixed=False, broke=True, **{"still bad": False})
    )
    html = render_report(run, comparison)
    order = [
        html.index(f'id="group-{k}"')
        for k in ("newly_broken", "newly_fixed", "still_failing", "still_passing")
    ]
    assert order == sorted(order)
    broke = html[html.index('id="s3-broke"') : html.index('id="s3-broke"') + 60]
    assert " open" in broke
    same = html[html.index('id="s1-same"') : html.index('id="s1-same"') + 60]
    assert " open" not in same
    assert "Passed in the baseline, fails now." in html
    assert "Failed in the baseline, passes now." in html
    assert "Already failing in the baseline (a known problem)." in html


def test_scenarios_missing_from_the_run_are_listed() -> None:
    run = run_of(good("a"))
    html = render_report(run, compare(run, baseline_of(a=True, vanished=True)))
    assert "In the baseline but not in this run" in html and "vanished" in html
    assert "1 removed" in html


# --- the chat ---------------------------------------------------------------------


def test_the_conversation_is_shown_as_bubbles() -> None:
    html = render_report(
        run_of(
            scenario(
                "chat",
                [
                    turn(
                        1,
                        user="Tell me about Nova",
                        messages=[
                            bot(
                                "Nova Textiles ...", buttons=["Dates", "Price band", "Subscription"]
                            ),
                            bot("Pick one", rows=["Nova Textiles", "Bharat GreenGrid"]),
                        ],
                    )
                ],
            )
        )
    )
    assert 'class="bubble user">Tell me about Nova' in html
    assert html.count('class="bubble bot"') == 2
    for label in (
        "Dates",
        "Price band",
        "Subscription",
        "Nova Textiles",
        "Bharat GreenGrid",
        "row detail",
    ):
        assert label in html
    assert html.count('class="btn"') == 3 and html.count('class="rowitem"') == 2
    assert "0.1s after the question" in html


def test_failed_checks_are_highlighted_with_the_reason_and_passes_are_quiet() -> None:
    html = render_report(run_of(bad()))
    assert 'class="check fail"' in html and 'class="check pass"' in html
    assert "reply says 1 Dec but data says 30 Nov" in html
    assert "✗" in html and "✓" in html
    # the "what went wrong" box repeats only the failure, not the passing check
    assert "<li>reply says 1 Dec but data says 30 Nov</li>" in html
    assert "<li>reply contains" not in html


def test_the_combined_rejected_and_also_lines_are_shown_as_one_callout() -> None:
    rejected = RejectedMessage(
        reasons=["interactive.action.buttons: has 4 buttons; at most 3 allowed"],
        payload={
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": "listing date is 1 December 2026. You should apply!"},
                "action": {
                    "buttons": [
                        {"type": "reply", "reply": {"id": str(i), "title": f"Option {i}"}}
                        for i in range(4)
                    ]
                },
            },
        },
    )
    failing = turn(
        1,
        status="failed",
        rejected=[rejected],
        checks=[
            CheckResult(
                kind="rejected_messages",
                passed=False,
                message="the bot sent a message WhatsApp would reject",
            ),
            CheckResult(
                kind="fact",
                passed=False,
                message="reply says 1 December 2026 but ipos says 30 November 2026",
            ),
            CheckResult(
                kind="not_contains",
                passed=False,
                message="reply must not contain ['you should apply']",
            ),
        ],
    )
    html = render_report(run_of(scenario("rejected", [failing])))
    assert "What went wrong" in html
    assert "rejected: interactive.action.buttons: has 4 buttons; at most 3 allowed" in html
    assert "also: reply says 1 December 2026 but ipos says 30 November 2026" in html
    assert "also: reply must not contain" in html
    assert "NOT DELIVERED" in html and 'class="bubble bot rejected"' in html
    assert "You should apply!" in html  # the text the bot tried to send
    assert html.count("Option ") == 4  # all four buttons it tried to send


def test_the_judges_verdict_and_reason_are_shown_with_a_judge_tag() -> None:
    judged = turn(
        1,
        status="failed",
        messages=[bot("Nova looks like a smart pick.")],
        checks=[
            CheckResult(
                kind="judge",
                passed=False,
                message="judge no_investment_advice [cached]: gives investment advice",
            )
        ],
    )
    html = render_report(run_of(scenario("judged", [judged])))
    assert 'class="tag judge">judge</span>' in html
    assert "judge no_investment_advice [cached]: gives investment advice" in html


def test_silent_errors_and_skipped_turns_are_visible() -> None:
    silent = turn(1, status="failed", error="the bot didn't reply within 30s")
    html = render_report(run_of(scenario("silent", [silent, turn(2, status="skipped")])))
    assert "the bot sent nothing" in html
    assert "skipped: an earlier turn failed" in html
    assert "Turn 1: failed" in html and "Turn 2: skipped" in html


def test_scenario_level_errors_show_up() -> None:
    timed_out = ScenarioResult(
        name="slow", user_wa_id="1", passed=False, duration_s=5, error="took longer than 5s overall"
    )
    assert "took longer than 5s overall" in render_report(run_of(timed_out))


def test_write_report_creates_folders_and_returns_the_path(tmp_path: Path) -> None:
    target = tmp_path / "deep" / "folder" / "report.html"
    written = write_report(target, run_of(good()), title="My report")
    assert written == target and target.is_file()
    content = target.read_text(encoding="utf-8")
    assert "<title>My report</title>" in content
