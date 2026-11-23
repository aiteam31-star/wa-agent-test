"""Baseline and comparison models: plain data, JSON-serializable."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, computed_field

Status = Literal[
    "still_passing",  # passed before, passes now
    "still_failing",  # failed before, fails now (a known problem)
    "newly_broken",  # passed before, fails now
    "newly_fixed",  # failed before, passes now
    "new_passing",  # not in the baseline, passes
    "new_failing",  # not in the baseline, fails
]

LABELS: dict[str, str] = {
    "newly_broken": "Newly broken",
    "newly_fixed": "Newly fixed",
    "new_failing": "New, failing",
    "new_passing": "New, passing",
    "still_failing": "Still failing",
    "still_passing": "Still passing",
}


class BaselineEntry(BaseModel):
    """What the baseline remembers about one scenario."""

    passed: bool
    problems: list[str] = []  # why it failed, if it did


class Baseline(BaseModel):
    """A saved run: the known-good reference later runs are compared with."""

    version: Literal[1] = 1
    saved_at: datetime
    scenarios: dict[str, BaselineEntry]


class ScenarioComparison(BaseModel):
    name: str
    status: Status
    passed: bool  # in this run
    was_passed: bool | None  # in the baseline; None if the scenario is new
    problems: list[str] = []  # why it fails now
    was_problems: list[str] = []  # why it failed in the baseline

    @property
    def label(self) -> str:
        return LABELS[self.status]


class Comparison(BaseModel):
    """A run compared with a baseline."""

    baseline_saved_at: datetime
    items: list[ScenarioComparison]
    removed: list[str] = []  # in the baseline, not in this run

    def with_status(self, *statuses: str) -> list[ScenarioComparison]:
        return [i for i in self.items if i.status in statuses]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def has_regression(self) -> bool:
        """True if anything is newly broken, or is new and already failing."""
        return bool(self.with_status("newly_broken", "new_failing"))

    @computed_field  # type: ignore[prop-decorator]
    @property
    def summary(self) -> str:
        """One line, such as ``2 newly broken, 1 fixed, 27 unchanged``."""
        broken = len(self.with_status("newly_broken"))
        fixed = len(self.with_status("newly_fixed"))
        unchanged = len(self.with_status("still_passing", "still_failing"))
        parts = [f"{broken} newly broken", f"{fixed} fixed", f"{unchanged} unchanged"]
        new = len(self.with_status("new_passing", "new_failing"))
        if new:
            failing = len(self.with_status("new_failing"))
            parts.append(f"{new} new" + (f" ({failing} failing)" if failing else ""))
        if self.removed:
            parts.append(f"{len(self.removed)} removed")
        return ", ".join(parts)
