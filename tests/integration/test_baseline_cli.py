"""`wa-agent-test run` with baselines and reports, against the real demo bot on real sockets."""

import asyncio
import json
import socket
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from demo_bot.app import create_app as create_bot_app
from demo_bot.config import Settings
from wa_agent_test.cli import app as cli_app
from wa_agent_test.mock_graph import MockGraphServer

pytestmark = pytest.mark.integration

ROOT = Path(__file__).parents[2]
EXAMPLES = ROOT / "examples"
LISTING_BUG = {"buggy_mode": True, "buggy_force": frozenset({"listing_date"}), "buggy_seed": 1}
LISTING_VICTIMS = 6  # five listing-date-fact scenarios + tap-dates-button


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def write_config(tmp_path: Path, bot_url: str, mock_port: int) -> Path:
    config = tmp_path / "wa-agent-test.yaml"
    config.write_text(
        (EXAMPLES / "wa-agent-test.yaml")
        .read_text(encoding="utf-8")
        .replace("http://127.0.0.1:8000/webhook", f"{bot_url}/webhook")
        .replace("port: 9000", f"port: {mock_port}")
        .replace("../demo_bot", (ROOT / "demo_bot").as_posix())
        .replace("provider: ollama", "provider: fake"),
        encoding="utf-8",
    )
    return config


async def run_cli(tmp_path: Path, bot: dict[str, Any] | None = None, *args: str) -> tuple[int, str]:
    """Start the demo bot (clean, or with ``bot`` settings), run the CLI once, return the result."""
    mock_port = free_port()
    settings = Settings(graph_base_url=f"http://127.0.0.1:{mock_port}", **(bot or {}))
    async with MockGraphServer(create_bot_app(settings)) as server:
        config = write_config(tmp_path, server.base_url, mock_port)
        result = await asyncio.to_thread(
            CliRunner().invoke,
            cli_app,
            ["run", str(EXAMPLES / "scenarios"), "--config", str(config), *args],
        )
    return result.exit_code, result.output


# --- without and with a baseline ------------------------------------------


async def test_without_a_baseline_the_run_says_so_and_exits_by_pass_or_fail(tmp_path: Path) -> None:
    code, output = await run_cli(tmp_path)
    assert code == 0 and "No baseline at" in output and "--save-baseline" in output
    code, output = await run_cli(tmp_path, LISTING_BUG)
    assert code == 1  # the old rule still holds with no baseline: any failure fails the run
    assert "No baseline at" in output


async def test_save_baseline_then_an_unchanged_run_has_nothing_to_report(tmp_path: Path) -> None:
    code, output = await run_cli(tmp_path, None, "--save-baseline")
    assert code == 0, output
    assert "Baseline saved to" in output and "(30 passing, 0 failing)" in output
    saved = json.loads((tmp_path / "baselines" / "baseline.json").read_text(encoding="utf-8"))
    assert len(saved["scenarios"]) == 30 and all(s["passed"] for s in saved["scenarios"].values())

    code, output = await run_cli(tmp_path)
    assert code == 0, output
    assert "0 newly broken, 0 fixed, 30 unchanged" in output and "REGRESSION" not in output


async def test_a_newly_broken_scenario_fails_the_run_and_is_named(tmp_path: Path) -> None:
    await run_cli(tmp_path, None, "--save-baseline")
    report = tmp_path / "out" / "report.html"
    results = tmp_path / "results.json"
    code, output = await run_cli(
        tmp_path, LISTING_BUG, "--report", str(report), "--json", str(results)
    )
    assert code == 1, output
    assert f"{LISTING_VICTIMS} newly broken, 0 fixed, {30 - LISTING_VICTIMS} unchanged" in output
    assert "Result: REGRESSION" in output
    assert "NEWLY BROKEN   listing-date-fact: Nova Textiles" in output
    assert "NEWLY BROKEN   tap-dates-button" in output
    assert "but ipos says 30 November 2026" in output  # the reason is printed under the name

    html = report.read_text(encoding="utf-8")
    assert f"<h1>{LISTING_VICTIMS} newly broken, 0 fixed, 24 unchanged</h1>" in html
    assert "Regression" in html and "listing-date-fact: Nova Textiles" in html
    assert 'class="bubble user">When does Nova Textiles list?' in html
    assert "but ipos says 30 November 2026" in html and "<script" not in html
    assert str(report.resolve()) in output

    data = json.loads(results.read_text(encoding="utf-8"))
    assert data["comparison"]["has_regression"] is True
    statuses = [i["status"] for i in data["comparison"]["items"]]
    assert statuses.count("newly_broken") == LISTING_VICTIMS


async def test_a_fixed_scenario_is_labelled_and_does_not_fail_the_run(tmp_path: Path) -> None:
    code, output = await run_cli(tmp_path, LISTING_BUG, "--save-baseline")
    assert code == 0  # saving always succeeds; the known failures are recorded
    assert f"({30 - LISTING_VICTIMS} passing, {LISTING_VICTIMS} failing)" in output
    assert "now recorded as known failures" in output

    code, output = await run_cli(tmp_path)  # the bot is fixed now
    assert code == 0, output
    assert f"0 newly broken, {LISTING_VICTIMS} fixed, {30 - LISTING_VICTIMS} unchanged" in output
    assert output.count("NEWLY FIXED") == LISTING_VICTIMS


async def test_a_known_failure_that_keeps_failing_does_not_fail_the_run(tmp_path: Path) -> None:
    await run_cli(tmp_path, LISTING_BUG, "--save-baseline")
    code, output = await run_cli(tmp_path, LISTING_BUG)
    assert code == 0, output
    assert "0 newly broken, 0 fixed, 30 unchanged" in output
    assert "STILL FAILING" in output and "REGRESSION" not in output


async def test_new_failing_scenarios_fail_the_run_and_removed_ones_are_listed(
    tmp_path: Path,
) -> None:
    await run_cli(tmp_path, None, "--save-baseline", "--name", "lot-size")  # a baseline of just 1
    code, output = await run_cli(tmp_path, LISTING_BUG)
    assert code == 1, output  # 6 scenarios are new and already failing
    assert f"0 newly broken, 0 fixed, 1 unchanged, 29 new ({LISTING_VICTIMS} failing)" in output
    assert "NEW, FAILING" in output

    await run_cli(tmp_path, None, "--save-baseline")
    code, output = await run_cli(tmp_path, None, "--name", "lot-size")
    assert code == 0, output
    assert "1 unchanged, 29 removed" in output and output.count("REMOVED") == 29


async def test_a_custom_baseline_path_and_a_damaged_baseline(tmp_path: Path) -> None:
    custom = tmp_path / "elsewhere" / "known-good.json"
    code, _ = await run_cli(tmp_path, None, "--save-baseline", "--baseline", str(custom))
    assert code == 0 and custom.is_file()
    assert not (tmp_path / "baselines").exists()

    custom.write_text("{broken", encoding="utf-8")
    code, output = await run_cli(tmp_path, None, "--baseline", str(custom))
    assert code == 2 and "can't read the baseline" in output  # fails fast, before the long run
    assert "Running" not in output
