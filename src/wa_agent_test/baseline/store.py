"""Save and load baselines (one small JSON file)."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from wa_agent_test.baseline.compare import failure_problems
from wa_agent_test.baseline.models import Baseline, BaselineEntry
from wa_agent_test.scenarios import RunResult


class BaselineError(Exception):
    """The baseline file exists but can't be read."""


def baseline_from_run(run: RunResult, saved_at: datetime | None = None) -> Baseline:
    return Baseline(
        saved_at=saved_at or datetime.now(UTC),
        scenarios={
            s.name: BaselineEntry(passed=s.passed, problems=failure_problems(s))
            for s in run.scenarios
        },
    )


def save_baseline(path: Path, run: RunResult) -> Baseline:
    """Write ``run`` as the baseline at ``path`` (folders are created; the write is atomic)."""
    baseline = baseline_from_run(run)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(baseline.model_dump_json(indent=2), encoding="utf-8")
    os.replace(temp, path)
    return baseline


def load_baseline(path: Path) -> Baseline | None:
    """The saved baseline, or None if there is no file yet."""
    if not path.is_file():
        return None
    try:
        return Baseline.model_validate_json(path.read_text(encoding="utf-8"))
    except (ValidationError, ValueError, OSError) as exc:
        raise BaselineError(
            f"can't read the baseline {path}: {exc} (delete it and save a new one with "
            "--save-baseline)"
        ) from exc
