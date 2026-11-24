"""The Markdown summary posted on pull requests and shown on the Actions run page."""

from datetime import UTC, datetime

from wa_agent_test.assertions import CheckResult
from wa_agent_test.baseline import Baseline, BaselineEntry, compare
from wa_agent_test.report import MARKER, render_summary, write_summary
from wa_agent_test.scenarios import RunResult, ScenarioResult, TurnResult

NOW = datetime(2026, 11, 23, 10, 15, tzinfo=UTC)


def scenario(
    name: str, passed: bool = True, why: str = "reply says 1 Dec but data says 30 Nov"
) -> ScenarioResult:
    turns = []
    if not passed:
        turns = [
            TurnResult(
                index=1,
                action="say: 'x'",
                status="failed",
                checks=[CheckResult(kind="fact", passed=False, message=why)],
            )
        ]
    return ScenarioResult(name=name, user_wa_id="1", passed=passed, duration_s=0.1, turns=turns)


def run_of(*scenarios: ScenarioResult) -> RunResult:
    return RunResult(started_at=NOW, duration_s=4.4, scenarios=list(scenarios))


def baseline_of(**entries: bool) -> Baseline:
    return Baseline(
        saved_at=NOW, scenarios={n: BaselineEntry(passed=ok) for n, ok in entries.items()}
    )


def test_a_regression_lists_the_broken_scenarios_with_their_reasons() -> None:
    run = run_of(scenario("fine"), scenario("broke", False))
    text = render_summary(
        run, compare(run, baseline_of(fine=True, broke=True)), baseline_path="baselines/b.json"
    )
    assert text.startswith(MARKER + "\n## wa-agent-test: 1 newly broken, 0 fixed, 1 unchanged")
    assert "**Regression:** 1 scenario(s) broke. This check fails." in text
    assert "| `broke` | turn 1: reply says 1 Dec but data says 30 Nov |" in text
    assert "`fine`" not in text
    assert "Compared with the baseline saved 2026-11-23 10:15 UTC (`baselines/b.json`)" in text
    assert "_2 scenario(s) in 4s." in text


def test_a_clean_run_says_no_new_breakage() -> None:
    run = run_of(scenario("a"), scenario("b"))
    text = render_summary(run, compare(run, baseline_of(a=True, b=True)))
    assert "## wa-agent-test: 0 newly broken, 0 fixed, 2 unchanged" in text
    assert "**No new breakage.**" in text and "Regression" not in text and "| Scenario" not in text


def test_fixed_known_and_removed_are_mentioned_but_do_not_make_it_a_regression() -> None:
    run = run_of(scenario("fixed"), scenario("known", False))
    text = render_summary(run, compare(run, baseline_of(fixed=False, known=False, gone=True)))
    assert "**No new breakage.**" in text
    assert "Fixed since the baseline: `fixed`" in text
    assert "Known failures (already failing in the baseline): 1" in text
    assert "In the baseline but not run: 1" in text


def test_without_a_baseline_it_lists_failures_or_says_all_passed() -> None:
    assert "**All scenarios passed.**" in render_summary(run_of(scenario("a")))
    text = render_summary(run_of(scenario("a"), scenario("b", False)))
    assert "## wa-agent-test: 1 passed, 1 failed" in text and "| `b` |" in text
    assert "No baseline to compare with." in text


def test_warnings_are_counted_but_not_listed_as_problems() -> None:
    warned = ScenarioResult(
        name="w",
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
    text = render_summary(run_of(warned))
    assert "Warnings: 1 (shown in the report; they never fail the run)." in text
    assert "**All scenarios passed.**" in text


def test_long_lists_are_cut_and_markdown_unsafe_characters_are_neutralised() -> None:
    names = [f"s{i}" for i in range(20)]
    run = run_of(*[scenario(n, False, "bad | `code` text\nwith a newline") for n in names])
    text = render_summary(run, compare(run, baseline_of(**{n: True for n in names})))
    assert text.count("| `s") == 15 and "_and 5 more_" in text
    assert (
        "bad / 'code' text with a newline" in text
    )  # no pipe, backtick or newline left to break the table


def test_write_summary_creates_folders(tmp_path) -> None:  # type: ignore[no-untyped-def]
    target = tmp_path / "a" / "b" / "summary.md"
    assert write_summary(target, run_of(scenario("a"))) == target
    assert target.read_text(encoding="utf-8").startswith(MARKER)
