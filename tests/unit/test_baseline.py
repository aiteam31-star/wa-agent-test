"""Baselines: saving, loading, and labelling a run against one."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from wa_agent_test.assertions import CheckResult
from wa_agent_test.baseline import (
    Baseline,
    BaselineEntry,
    BaselineError,
    baseline_from_run,
    compare,
    failure_problems,
    load_baseline,
    save_baseline,
)
from wa_agent_test.scenarios import RejectedMessage, RunResult, ScenarioResult, TurnResult

NOW = datetime(2026, 11, 23, 10, 15, tzinfo=UTC)


def scenario(
    name: str, passed: bool = True, why: str = "reply says 1 Dec but data says 30 Nov"
) -> ScenarioResult:
    turns: list[TurnResult] = []
    if not passed:
        turns = [
            TurnResult(index=1, action="say: 'x'", status="passed"),
            TurnResult(
                index=2,
                action="say: 'y'",
                status="failed",
                checks=[CheckResult(kind="fact", passed=False, message=why)],
            ),
        ]
    return ScenarioResult(
        name=name, user_wa_id="919800000000", passed=passed, duration_s=0.1, turns=turns
    )


def run_of(*scenarios: ScenarioResult) -> RunResult:
    return RunResult(started_at=NOW, duration_s=1.0, scenarios=list(scenarios))


def baseline_of(**entries: bool) -> Baseline:
    return Baseline(
        saved_at=NOW, scenarios={name: BaselineEntry(passed=ok) for name, ok in entries.items()}
    )


# --- failure_problems -----------------------------------------------------------------------


def test_failure_problems() -> None:
    assert failure_problems(scenario("a")) == []
    assert failure_problems(scenario("a", False, "wrong date")) == ["turn 2: wrong date"]


def test_failure_problems_for_a_scenario_level_error_and_combined_lines() -> None:
    timed_out = ScenarioResult(
        name="a", user_wa_id="1", passed=False, duration_s=1, error="took longer than 5s overall"
    )
    assert failure_problems(timed_out) == ["took longer than 5s overall"]
    rejected = ScenarioResult(
        name="b",
        user_wa_id="1",
        passed=False,
        duration_s=1,
        turns=[
            TurnResult(
                index=1,
                action="say: 'x'",
                status="failed",
                rejected=[RejectedMessage(reasons=["has 4 buttons; at most 3 allowed"])],
                checks=[
                    CheckResult(kind="rejected_messages", passed=False, message="rejected"),
                    CheckResult(kind="fact", passed=False, message="wrong date"),
                ],
            )
        ],
    )
    assert failure_problems(rejected) == [
        "turn 1: rejected: has 4 buttons; at most 3 allowed",
        "turn 1: also: wrong date",
    ]


# --- the four labels, plus new and removed -----------------------------------------------------


def test_every_label() -> None:
    run = run_of(
        scenario("still-pass", True),
        scenario("still-fail", False),
        scenario("broke", False),
        scenario("fixed", True),
        scenario("brand-new-ok", True),
        scenario("brand-new-bad", False),
    )
    before = baseline_of(**{"still-pass": True, "still-fail": False, "broke": True, "fixed": False})
    comparison = compare(run, before)
    assert {i.name: i.status for i in comparison.items} == {
        "still-pass": "still_passing",
        "still-fail": "still_failing",
        "broke": "newly_broken",
        "fixed": "newly_fixed",
        "brand-new-ok": "new_passing",
        "brand-new-bad": "new_failing",
    }
    assert [i.label for i in comparison.items][2:4] == ["Newly broken", "Newly fixed"]
    broke = next(i for i in comparison.items if i.name == "broke")
    assert broke.was_passed is True and broke.passed is False
    assert broke.problems == ["turn 2: reply says 1 Dec but data says 30 Nov"]


def test_removed_scenarios_are_listed() -> None:
    comparison = compare(run_of(scenario("a")), baseline_of(a=True, gone=True, also_gone=False))
    assert comparison.removed == ["gone", "also_gone"]


def test_was_problems_come_from_the_baseline() -> None:
    before = Baseline(
        saved_at=NOW,
        scenarios={"a": BaselineEntry(passed=False, problems=["turn 1: it was wrong"])},
    )
    (item,) = compare(run_of(scenario("a", True)), before).items
    assert item.status == "newly_fixed" and item.was_problems == ["turn 1: it was wrong"]


# --- summary and the regression rule ------------------------------------------------------------


def test_the_summary_line() -> None:
    scenarios = (
        [scenario(f"ok{i}") for i in range(27)]
        + [scenario("b1", False), scenario("b2", False)]
        + [scenario("f1", True)]
    )
    before = baseline_of(**{f"ok{i}": True for i in range(27)}, b1=True, b2=True, f1=False)
    assert compare(run_of(*scenarios), before).summary == "2 newly broken, 1 fixed, 27 unchanged"


def test_summary_counts_still_failing_as_unchanged_and_mentions_new_and_removed() -> None:
    run = run_of(scenario("a", False), scenario("b"), scenario("n1"), scenario("n2", False))
    comparison = compare(run, baseline_of(a=False, b=True, old=True))
    assert comparison.summary == (
        "0 newly broken, 0 fixed, 2 unchanged, 2 new (1 failing), 1 removed"
    )


@pytest.mark.parametrize(
    ("run_passed", "was_passed", "regression"),
    [
        (False, True, True),  # newly broken
        (False, None, True),  # new and failing
        (False, False, False),  # known failure
        (True, False, False),  # fixed
        (True, True, False),
        (True, None, False),
    ],
)
def test_what_counts_as_a_regression(
    run_passed: bool, was_passed: bool | None, regression: bool
) -> None:
    before = baseline_of() if was_passed is None else baseline_of(a=was_passed)
    assert compare(run_of(scenario("a", run_passed)), before).has_regression is regression


def test_comparison_json_includes_the_summary_and_the_verdict() -> None:
    data = compare(run_of(scenario("a", False)), baseline_of(a=True)).model_dump(mode="json")
    assert data["summary"] == "1 newly broken, 0 fixed, 0 unchanged"
    assert data["has_regression"] is True and data["items"][0]["status"] == "newly_broken"


# --- storage --------------------------------------------------------------------------------------


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "dir" / "baseline.json"
    saved = save_baseline(path, run_of(scenario("a"), scenario("b", False, "wrong date")))
    assert load_baseline(path) == saved
    assert saved.scenarios["a"].passed is True
    assert saved.scenarios["b"] == BaselineEntry(passed=False, problems=["turn 2: wrong date"])
    assert [p.name for p in path.parent.iterdir()] == ["baseline.json"]  # no temp file left behind


def test_saving_again_replaces_the_baseline(tmp_path: Path) -> None:
    path = tmp_path / "baseline.json"
    save_baseline(path, run_of(scenario("a", False)))
    save_baseline(path, run_of(scenario("a", True)))
    loaded = load_baseline(path)
    assert loaded is not None and loaded.scenarios["a"].passed is True


def test_a_missing_file_means_no_baseline(tmp_path: Path) -> None:
    assert load_baseline(tmp_path / "nope.json") is None


@pytest.mark.parametrize("content", ["{not json", "[]", '{"version": 2, "saved_at": "x"}', ""])
def test_a_damaged_file_is_a_clear_error(tmp_path: Path, content: str) -> None:
    path = tmp_path / "baseline.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(BaselineError, match="can't read the baseline"):
        load_baseline(path)


def test_the_file_is_plain_readable_json(tmp_path: Path) -> None:
    path = tmp_path / "baseline.json"
    save_baseline(path, run_of(scenario("a")))
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == 1 and data["scenarios"] == {"a": {"passed": True, "problems": []}}
    assert baseline_from_run(run_of(scenario("a")), NOW).saved_at == NOW
