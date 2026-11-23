"""Compare a run with a baseline and label every scenario."""

from __future__ import annotations

from wa_agent_test.baseline.models import (
    Baseline,
    Comparison,
    ScenarioComparison,
    Status,
)
from wa_agent_test.scenarios import RunResult, ScenarioResult


def failure_problems(scenario: ScenarioResult) -> list[str]:
    """Why a scenario failed: the scenario-level error, or the first failed turn's problems."""
    if scenario.passed:
        return []
    if scenario.error:
        return [scenario.error]
    for turn in scenario.turns:
        if turn.status == "failed":
            return [f"turn {turn.index}: {p}" for p in turn.problems]
    return []


def _status(passed: bool, was_passed: bool | None) -> Status:
    if was_passed is None:
        return "new_passing" if passed else "new_failing"
    if was_passed:
        return "still_passing" if passed else "newly_broken"
    return "newly_fixed" if passed else "still_failing"


def compare(run: RunResult, baseline: Baseline) -> Comparison:
    """Label each scenario: still passing / still failing / newly broken / newly fixed / new."""
    items: list[ScenarioComparison] = []
    for scenario in run.scenarios:
        before = baseline.scenarios.get(scenario.name)
        items.append(
            ScenarioComparison(
                name=scenario.name,
                status=_status(scenario.passed, None if before is None else before.passed),
                passed=scenario.passed,
                was_passed=None if before is None else before.passed,
                problems=failure_problems(scenario),
                was_problems=[] if before is None else before.problems,
            )
        )
    now = {s.name for s in run.scenarios}
    removed = [name for name in baseline.scenarios if name not in now]
    return Comparison(baseline_saved_at=baseline.saved_at, items=items, removed=removed)
