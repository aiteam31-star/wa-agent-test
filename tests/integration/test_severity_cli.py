"""severity: warn through the real CLI: printed, counted, in the report, but never a failure."""

import asyncio
from pathlib import Path

import pytest
from test_baseline_cli import free_port, write_config
from typer.testing import CliRunner

from demo_bot.app import create_app as create_bot_app
from demo_bot.config import Settings
from wa_agent_test.cli import app as cli_app
from wa_agent_test.mock_graph import MockGraphServer

pytestmark = pytest.mark.integration

SCENARIO = """\
name: warns-only
turns:
  - say: "Which IPOs are open?"
    expect:
      - contains: "Nova Textiles"
      - contains: "this text is not in the reply"
        severity: warn
        why: "nice to have"
"""


async def run_cli(tmp_path: Path, scenario: str, *args: str) -> tuple[int, str]:
    scenarios = tmp_path / "scenarios"
    scenarios.mkdir(exist_ok=True)
    (scenarios / "s.yaml").write_text(scenario, encoding="utf-8")
    mock_port = free_port()
    settings = Settings(graph_base_url=f"http://127.0.0.1:{mock_port}")
    async with MockGraphServer(create_bot_app(settings)) as server:
        config = write_config(tmp_path, server.base_url, mock_port)
        result = await asyncio.to_thread(
            CliRunner().invoke, cli_app, ["run", str(scenarios), "--config", str(config), *args]
        )
    return result.exit_code, result.output


async def test_a_warning_is_printed_and_counted_but_the_run_passes(tmp_path: Path) -> None:
    report = tmp_path / "report.html"
    code, output = await run_cli(tmp_path, SCENARIO, "--report", str(report))
    assert code == 0, output
    assert "PASS  warns-only" in output
    assert (
        "warning (turn 1): nice to have (reply is missing ['this text is not in the reply']"
        in output
    )
    assert (
        "1 passed, 0 failed, 1 total" in output and "1 warning(s), which never fail a run" in output
    )
    html = report.read_text(encoding="utf-8")
    assert (
        'class="check warn"' in html and "nice to have" in html and "All scenarios passed" in html
    )


async def test_the_same_check_without_severity_warn_fails_the_run(tmp_path: Path) -> None:
    code, output = await run_cli(tmp_path, SCENARIO.replace("        severity: warn\n", ""))
    assert (
        code == 1
        and "FAIL  warns-only" in output
        and "warning" not in output.lower().split("fail")[0]
    )


async def test_warnings_do_not_count_against_a_baseline(tmp_path: Path) -> None:
    code, output = await run_cli(tmp_path, SCENARIO, "--save-baseline")
    assert code == 0 and "(1 passing, 0 failing)" in output
    code, output = await run_cli(tmp_path, SCENARIO)
    assert code == 0, output
    assert "0 newly broken, 0 fixed, 1 unchanged" in output
