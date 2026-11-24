"""A short Markdown summary of a run, for pull-request comments and the Actions run page."""

from __future__ import annotations

from pathlib import Path

from wa_agent_test.baseline import Comparison
from wa_agent_test.scenarios import RunResult, ScenarioResult

# Hidden marker, so a workflow can find and update its earlier comment instead of adding more.
MARKER = "<!-- wa-agent-test-summary -->"
MAX_ROWS = 15


def _clean(text: str, limit: int = 220) -> str:
    """One line, safe inside a Markdown table cell and inside backticks."""
    flat = " ".join(text.split()).replace("|", "/").replace("`", "'")
    return flat if len(flat) <= limit else flat[: limit - 3] + "..."


def _why(scenario: ScenarioResult) -> str:
    if scenario.error:
        return scenario.error
    for turn in scenario.turns:
        if turn.status == "failed":
            return f"turn {turn.index}: {turn.summary}"
    return ""


def _table(rows: list[tuple[str, str]]) -> list[str]:
    lines = ["| Scenario | What went wrong |", "|---|---|"]
    for name, why in rows[:MAX_ROWS]:
        lines.append(f"| `{_clean(name, 80)}` | {_clean(why)} |")
    if len(rows) > MAX_ROWS:
        lines.append(f"| _and {len(rows) - MAX_ROWS} more_ | see the HTML report |")
    return lines


def render_summary(
    run: RunResult,
    comparison: Comparison | None = None,
    *,
    baseline_path: str | None = None,
) -> str:
    """The run's headline, verdict and the scenarios that need attention, as Markdown."""
    by_name = {s.name: s for s in run.scenarios}
    lines = [MARKER]
    if comparison is not None:
        lines.append(f"## wa-agent-test: {comparison.summary}")
        lines.append("")
        broken = comparison.with_status("newly_broken", "new_failing")
        if comparison.has_regression:
            lines.append(f"**Regression:** {len(broken)} scenario(s) broke. This check fails.")
            lines.append("")
            lines += _table([(i.name, _why(by_name[i.name])) for i in broken])
        else:
            lines.append("**No new breakage.**")
        fixed = comparison.with_status("newly_fixed")
        if fixed:
            lines += [
                "",
                f"Fixed since the baseline: {', '.join(f'`{_clean(i.name, 80)}`' for i in fixed)}",
            ]
        known = comparison.with_status("still_failing")
        if known:
            lines += ["", f"Known failures (already failing in the baseline): {len(known)}"]
        if comparison.removed:
            lines += ["", f"In the baseline but not run: {len(comparison.removed)}"]
        saved = comparison.baseline_saved_at.strftime("%Y-%m-%d %H:%M UTC")
        source = f" (`{_clean(baseline_path, 100)}`)" if baseline_path else ""
        footer = f"Compared with the baseline saved {saved}{source}."
    else:
        lines.append(f"## wa-agent-test: {run.passed} passed, {run.failed} failed")
        lines.append("")
        failing = [s for s in run.scenarios if not s.passed]
        if failing:
            lines += _table([(s.name, _why(s)) for s in failing])
        else:
            lines.append("**All scenarios passed.**")
        footer = "No baseline to compare with."
    if run.warning_count:
        lines += [
            "",
            f"Warnings: {run.warning_count} (shown in the report; they never fail the run).",
        ]
    lines += ["", f"_{run.total} scenario(s) in {run.duration_s:.0f}s. {footer}_", ""]
    return "\n".join(lines)


def write_summary(
    path: Path,
    run: RunResult,
    comparison: Comparison | None = None,
    *,
    baseline_path: str | None = None,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_summary(run, comparison, baseline_path=baseline_path), encoding="utf-8")
    return path
