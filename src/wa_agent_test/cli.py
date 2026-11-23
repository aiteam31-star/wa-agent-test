"""Typer CLI (wa-agent-test). Thin: loading, running and printing only.

Exit codes: 0 all passed, 1 failures, 2 usage/config/scenario errors, 3 harness problem
(for example the bot is unreachable or the mock port is busy).
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx
import typer

from wa_agent_test.assertions import JudgeCheck
from wa_agent_test.baseline import (
    Baseline,
    BaselineError,
    Comparison,
    compare,
    load_baseline,
    save_baseline,
)
from wa_agent_test.config import (
    ConfigError,
    ProjectConfig,
    build_judge,
    build_truth_sources,
    find_config,
    load_config,
)
from wa_agent_test.judge_eval import CaseResult, evaluate_cases, load_cases
from wa_agent_test.judges import CachedJudge, Judge
from wa_agent_test.mock_graph import CaptureStore, MockGraphServer, create_app
from wa_agent_test.report import attempt_text, write_report
from wa_agent_test.scenarios import (
    RunResult,
    Scenario,
    ScenarioLoadError,
    ScenarioResult,
    ScenarioRunner,
    load_scenarios,
)
from wa_agent_test.simulator import WebhookSimulator

app = typer.Typer(
    no_args_is_help=True, add_completion=False, help="Test WhatsApp Cloud API bots without a phone."
)


def _safe_output() -> None:
    """Never crash on characters (like the rupee sign) the console can't show."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="replace")


def _fail(message: str, code: int) -> typer.Exit:
    typer.echo(message, err=True)
    return typer.Exit(code)


def _filter(scenarios: list[Scenario], tags: list[str], name: str | None) -> list[Scenario]:
    if tags:
        scenarios = [s for s in scenarios if set(tags) & set(s.tags)]
    if name:
        scenarios = [s for s in scenarios if name.lower() in s.name.lower()]
    return scenarios


def _uses_judge(scenarios: list[Scenario]) -> bool:
    return any(isinstance(c, JudgeCheck) for s in scenarios for t in s.turns for c in t.expect)


def _excerpt(text: str, limit: int = 200) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "..."


def _print_result(result: ScenarioResult, verbose: bool) -> None:
    mark = "PASS" if result.passed else "FAIL"
    typer.echo(f"{mark}  {result.name}  ({result.duration_s:.1f}s)")
    if result.error:
        typer.echo(f"      {result.error}")
    for turn in result.turns:
        if turn.status == "passed" and not verbose:
            for warning in turn.warnings:  # a passing turn can still carry yellow warnings
                typer.echo(f"      warning (turn {turn.index}): {_excerpt(warning, 220)}")
            continue
        if turn.status == "skipped":
            typer.echo(f"      turn {turn.index} [{turn.action}] skipped")
            continue
        typer.echo(f"      turn {turn.index} [{turn.action}] {turn.status}")
        for problem in turn.problems:
            typer.echo(f"        - {problem}")
        for warning in turn.warnings:
            typer.echo(f"        - warning: {_excerpt(warning, 220)}")
        if verbose:
            for check in turn.checks:
                if check.passed:
                    typer.echo(f"        - ok {check.kind}: {check.message}")
        if turn.status == "failed":
            for message in turn.bot_messages:
                typer.echo(f"        bot said: {_excerpt(message.text)}")
            for attempt in turn.rejected:
                typer.echo(f"        bot tried to send: {_excerpt(attempt_text(attempt.payload))}")


def _print_summary(run: RunResult) -> None:
    typer.echo("")
    line = f"{run.passed} passed, {run.failed} failed, {run.total} total in {run.duration_s:.1f}s"
    if run.warning_count:
        line += f"; {run.warning_count} warning(s), which never fail a run"
    typer.echo(line)


def _print_comparison(comparison: Comparison, run: RunResult, baseline_file: Path) -> None:
    saved = comparison.baseline_saved_at.strftime("%Y-%m-%d %H:%M UTC")
    typer.echo("")
    typer.echo(f"Compared with the baseline saved {saved} ({baseline_file}):")
    shown = ("newly_broken", "newly_fixed", "new_failing", "new_passing")
    for item in comparison.with_status(*shown):
        typer.echo(f"  {item.label.upper():<14} {item.name}")
        for problem in item.problems[:3]:
            typer.echo(f"                 {_excerpt(problem, 220)}")
    still_failing = comparison.with_status("still_failing")
    if still_failing:
        typer.echo(f"  STILL FAILING  {', '.join(i.name for i in still_failing)}")
    for name in comparison.removed:
        typer.echo(f"  REMOVED        {name}")
    typer.echo("")
    typer.echo(comparison.summary)
    if comparison.has_regression:
        typer.echo("Result: REGRESSION (something is newly broken)")


async def _run(
    config: ProjectConfig,
    scenarios: list[Scenario],
    config_dir: Path,
    concurrency: int,
    verbose: bool,
    judge: Judge | None = None,
) -> RunResult:
    store = CaptureStore()
    mock_app = create_app(store=store, access_token=config.mock.access_token)
    server = MockGraphServer(mock_app, host=config.mock.host, port=config.mock.port)
    try:
        await server.start()
    except OSError as exc:
        raise _fail(
            f"can't start the mock Graph API on {config.mock.host}:{config.mock.port}: {exc}", 3
        ) from exc
    try:
        typer.echo(
            f"Mock Graph API at {server.base_url} (the bot's GRAPH_API_BASE_URL must be this)"
        )
        async with WebhookSimulator(
            config.bot.webhook_url,
            app_secret=config.bot.app_secret,
            business=config.business_account(),
            timeout_s=config.bot.timeout_s,
        ) as sim:
            if config.bot.verify_token:
                check = await sim.verify(config.bot.verify_token)
                if check.error:
                    raise _fail(
                        f"can't reach the bot at {config.bot.webhook_url}: {check.error}", 3
                    )
                if not check.ok:
                    typer.echo(
                        f"warning: webhook verification failed (HTTP {check.status_code}); "
                        "is bot.verify_token right?",
                        err=True,
                    )
            runner = ScenarioRunner(
                simulator=sim,
                store=store,
                truth=build_truth_sources(config, config_dir),
                judge=judge,
                concurrency=concurrency,
                scenario_timeout_s=config.run.scenario_timeout_s,
            )
            result = await runner.run(
                scenarios, seed=config.run.seed, on_done=lambda r: _print_result(r, verbose)
            )
            if isinstance(judge, CachedJudge):
                typer.echo(
                    f"Judge {judge.provider}/{judge.model}: {judge.misses} new verdict(s), "
                    f"{judge.hits} from cache"
                )
            return result
    finally:
        await server.stop()
        if judge is not None:
            await judge.aclose()


@app.command()
def run(
    path: Path = typer.Argument(..., help="A scenario file or a folder of them."),
    config: Path | None = typer.Option(None, "--config", "-c", help="Project config file."),
    tag: list[str] = typer.Option([], "--tag", "-t", help="Only scenarios with this tag."),
    name: str | None = typer.Option(None, "--name", "-n", help="Only names containing this."),
    concurrency: int | None = typer.Option(None, "--concurrency", help="Parallel scenarios."),
    json_out: Path | None = typer.Option(None, "--json", help="Write full results as JSON."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show passing turns and checks."),
    no_judge_cache: bool = typer.Option(
        False, "--no-judge-cache", help="Ask the judge again instead of reusing saved verdicts."
    ),
    save_baseline_flag: bool = typer.Option(
        False,
        "--save-baseline",
        help="Save this run as the known-good baseline (later runs are compared with it).",
    ),
    baseline_path: Path | None = typer.Option(
        None, "--baseline", help="Baseline file (default: run.baseline in the config)."
    ),
    report: Path | None = typer.Option(
        None, "--report", help="Write a self-contained HTML report here."
    ),
) -> None:
    """Run scenarios against the bot, compare with the baseline, and report.

    With a saved baseline, each scenario is labelled still passing / still failing / newly broken
    / newly fixed, and the exit code is 1 only if something is newly broken (or is new and
    failing). Without one, the exit code is 1 if any scenario failed.
    """
    _safe_output()
    try:
        config_path = find_config(config, path)
        project = load_config(config_path)
        scenarios = load_scenarios(path)
        build_truth_sources(project, config_path.parent)  # fail early on a bad truth source
    except (ConfigError, ScenarioLoadError) as exc:
        raise _fail(str(exc), 2) from exc
    scenarios = _filter(scenarios, tag, name)
    if not scenarios:
        raise _fail("no scenarios matched", 2)
    baseline_file = baseline_path or (config_path.parent / project.run.baseline)
    previous: Baseline | None = None
    if not save_baseline_flag:
        try:
            previous = load_baseline(baseline_file)  # fail early, before a long run
        except BaselineError as exc:
            raise _fail(str(exc), 2) from exc
    judge: Judge | None = None
    if _uses_judge(scenarios):
        try:
            judge = build_judge(project, config_path.parent, use_cache=not no_judge_cache)
        except ConfigError as exc:
            raise _fail(str(exc), 2) from exc
    typer.echo(f"Running {len(scenarios)} scenario(s) with config {config_path}")
    try:
        result = asyncio.run(
            _run(
                project,
                scenarios,
                config_path.parent,
                concurrency or project.run.concurrency,
                verbose,
                judge,
            )
        )
    except httpx.HTTPError as exc:  # pragma: no cover - defensive
        raise _fail(f"harness error: {exc}", 3) from exc
    _print_summary(result)

    comparison: Comparison | None = None
    exit_code = result.exit_code
    if save_baseline_flag:
        saved = save_baseline(baseline_file, result)
        failing = [name for name, entry in saved.scenarios.items() if not entry.passed]
        typer.echo(
            f"Baseline saved to {baseline_file} "
            f"({len(saved.scenarios) - len(failing)} passing, {len(failing)} failing)"
        )
        if failing:
            typer.echo(
                "warning: these scenarios were failing, so they are now recorded as known "
                f"failures: {', '.join(failing)}",
                err=True,
            )
        exit_code = 0  # the baseline is the new reference point
    elif previous is not None:
        comparison = compare(result, previous)
        _print_comparison(comparison, result, baseline_file)
        exit_code = 1 if comparison.has_regression else 0
    else:
        typer.echo(f"No baseline at {baseline_file}; save one with --save-baseline.")

    if report is not None:
        written = write_report(report, result, comparison, baseline_path=str(baseline_file))
        typer.echo(f"Report written to {written.resolve()}")
    if json_out:
        payload = result.model_dump(mode="json")
        if comparison is not None:
            payload["comparison"] = comparison.model_dump(mode="json")
        json_out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        typer.echo(f"Results written to {json_out}")
    raise typer.Exit(exit_code)


@app.command()
def validate(
    path: Path = typer.Argument(..., help="A scenario file or a folder of them."),
) -> None:
    """Check scenario files for mistakes without running anything."""
    _safe_output()
    try:
        scenarios = load_scenarios(path)
    except ScenarioLoadError as exc:
        raise _fail(str(exc), 2) from exc
    files = {s.source_file for s in scenarios}
    typer.echo(f"OK: {len(scenarios)} scenario(s) from {len(files)} file(s)")


@app.command("judge-eval")
def judge_eval(
    path: Path = typer.Argument(..., help="A calibration file of replies with known verdicts."),
    config: Path | None = typer.Option(None, "--config", "-c", help="Project config file."),
    json_out: Path | None = typer.Option(None, "--json", help="Write the results as JSON."),
    no_cache: bool = typer.Option(False, "--no-cache", help="Ask the judge again for every case."),
) -> None:
    """Measure how often the configured judge is wrong, on cases with known answers."""
    _safe_output()
    try:
        config_path = find_config(config, path)
        project = load_config(config_path)
        truth = build_truth_sources(project, config_path.parent)
        judge = build_judge(project, config_path.parent, use_cache=not no_cache)
        cases = load_cases(path)
    except (ConfigError, ValueError, OSError) as exc:
        raise _fail(str(exc), 2) from exc

    async def go() -> list[CaseResult]:
        try:
            return await evaluate_cases(cases, judge, truth)
        finally:
            await judge.aclose()

    typer.echo(f"Judging {len(cases)} case(s) with {judge.provider}/{judge.model}")
    results = asyncio.run(go())
    for r in results:
        said = "pass" if r.judge_passed else "fail"
        typer.echo(
            f"{r.kind.upper():<10} {r.case.id:<34} expected {r.case.expect}, judge said {said}"
        )
        if not r.correct:
            typer.echo(f"           {r.reason}")
    by_kind: dict[str, int] = {}
    for r in results:
        by_kind[r.kind] = by_kind.get(r.kind, 0) + 1
    correct = by_kind.get("ok", 0)
    typer.echo("")
    typer.echo(
        f"{correct}/{len(results)} correct ({100 * correct / len(results):.0f}%); "
        f"false passes (missed a bad reply): {by_kind.get('false pass', 0)}, "
        f"false fails (blamed a good reply): {by_kind.get('false fail', 0)}, "
        f"errors: {by_kind.get('error', 0)}"
    )
    if json_out:
        payload = [
            {
                "id": r.case.id,
                "rubric": r.case.rubric,
                "expected": r.case.expect,
                "judge_passed": r.judge_passed,
                "result": r.kind,
                "reason": r.reason,
            }
            for r in results
        ]
        json_out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        typer.echo(f"Results written to {json_out}")
