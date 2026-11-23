"""The 15 example scenarios against the real demo bot: clean passes, each bug is caught.

Two ways in: the runner directly (in-process, exact failure sets) and the CLI over real sockets.
"""

import asyncio
import json
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from demo_bot.app import create_app as create_bot_app
from demo_bot.config import Settings
from wa_agent_test.cli import app as cli_app
from wa_agent_test.config import build_truth_sources, load_config
from wa_agent_test.mock_graph import CaptureStore, MockGraphServer
from wa_agent_test.mock_graph import create_app as create_mock_app
from wa_agent_test.scenarios import RunResult, ScenarioRunner, load_scenarios
from wa_agent_test.simulator import WebhookSimulator

pytestmark = pytest.mark.integration

ROOT = Path(__file__).parents[2]
EXAMPLES = ROOT / "examples"
CONFIG = EXAMPLES / "wa-agent-test.yaml"


@asynccontextmanager
async def run_examples(**bot_settings: Any) -> AsyncIterator[RunResult]:
    """Run every example scenario against an in-process demo bot and mock Graph API."""
    settings = Settings(graph_base_url="http://mock", **bot_settings)
    store = CaptureStore()
    graph = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_mock_app(store=store)), base_url="http://mock"
    )
    bot = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_bot_app(settings, http_client=graph)),
        base_url="http://bot",
    )
    config = load_config(CONFIG)
    try:
        sim = WebhookSimulator("http://bot/webhook", app_secret=settings.app_secret, client=bot)
        runner = ScenarioRunner(
            simulator=sim,
            store=store,
            truth=build_truth_sources(config, CONFIG.parent),
            concurrency=8,
        )
        yield await runner.run(load_scenarios(EXAMPLES / "scenarios"), seed=1)
    finally:
        await graph.aclose()
        await bot.aclose()


def failed_names(run: RunResult) -> set[str]:
    return {s.name for s in run.scenarios if not s.passed}


# The scenarios a bug is expected to break (everything else must keep passing).
LISTING_DATE_VICTIMS = {
    f"listing-date-fact: {n}"
    for n in (
        "Nova Textiles",
        "Bharat GreenGrid",
        "Kaveri Agro",
        "Sahyadri Fintech",
        "Marwar Cement",
    )
} | {"tap-dates-button"}
UNAFFECTED_BY_BUTTON_BUG = {
    "open-ipos-list",
    "off-topic-help",
    "unknown-ipo-not-invented",
    "fast-reply",
    "unsupported-image",
}


async def test_clean_bot_passes_all_25_scenarios() -> None:
    async with run_examples() as run:
        assert run.total == 25
        assert failed_names(run) == set(), [
            (s.name, [c.message for t in s.turns for c in t.checks if not c.passed])
            for s in run.scenarios
            if not s.passed
        ]


async def test_wrong_listing_date_is_caught_by_the_fact_checks() -> None:
    async with run_examples(
        buggy_mode=True, buggy_force=frozenset({"listing_date"}), buggy_seed=1
    ) as run:
        assert failed_names(run) == LISTING_DATE_VICTIMS
        victim = next(s for s in run.scenarios if s.name == "listing-date-fact: Nova Textiles")
        failed = next(c for t in victim.turns for c in t.checks if not c.passed)
        assert failed.kind == "fact"
        assert "but ipos says 30 November 2026" in failed.message


async def test_four_buttons_is_caught_without_any_button_assertion() -> None:
    async with run_examples(buggy_mode=True, buggy_force=frozenset({"buttons"})) as run:
        everything = {s.name for s in run.scenarios}
        names_unaffected = {s.name for s in run.scenarios if s.name in UNAFFECTED_BY_BUTTON_BUG}
        assert names_unaffected == UNAFFECTED_BY_BUTTON_BUG
        assert failed_names(run) == everything - UNAFFECTED_BY_BUTTON_BUG
        some = next(s for s in run.scenarios if s.name == "lot-size-fact")
        assert any("4 buttons" in c.message for t in some.turns for c in t.checks)


async def test_you_should_apply_is_caught() -> None:
    async with run_examples(buggy_mode=True, buggy_force=frozenset({"advice"})) as run:
        assert failed_names(run) == {"no-investment-advice"}
        check = next(
            c
            for s in run.scenarios
            if s.name == "no-investment-advice"
            for t in s.turns
            for c in t.checks
            if not c.passed
        )
        assert check.kind == "not_contains" and "you should apply" in check.message.lower()


async def test_random_bugs_fail_some_but_not_all_scenarios() -> None:
    # "sometimes" buggy: the exact victims depend on the order of random draws (scenarios run
    # in parallel), so only assert the shape: at least one failure, and at least one pass.
    async with run_examples(buggy_mode=True, buggy_rate=0.5, buggy_seed=3) as run:
        assert 0 < len(failed_names(run)) < run.total


# --- the CLI over real sockets ----------------------------------------------------------


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


async def cli_run(tmp_path: Path, **bot_settings: Any) -> tuple[int, str, dict[str, Any]]:
    mock_port = free_port()
    settings = Settings(graph_base_url=f"http://127.0.0.1:{mock_port}", **bot_settings)
    out = tmp_path / "results.json"
    async with MockGraphServer(create_bot_app(settings)) as bot:
        config = tmp_path / "wa-agent-test.yaml"
        config.write_text(
            CONFIG.read_text(encoding="utf-8")
            .replace("http://127.0.0.1:8000/webhook", f"{bot.base_url}/webhook")
            .replace("port: 9000", f"port: {mock_port}")
            .replace("../demo_bot", (ROOT / "demo_bot").as_posix()),
            encoding="utf-8",
        )
        result = await asyncio.to_thread(
            CliRunner().invoke,
            cli_app,
            ["run", str(EXAMPLES / "scenarios"), "--config", str(config), "--json", str(out)],
        )
    return result.exit_code, result.output, json.loads(out.read_text(encoding="utf-8"))


async def test_cli_run_against_a_clean_bot(tmp_path: Path) -> None:
    code, output, results = await cli_run(tmp_path)
    assert code == 0, output
    assert "25 passed, 0 failed, 25 total" in output
    assert all(s["passed"] for s in results["scenarios"])


async def test_cli_run_against_a_buggy_bot_exits_1_and_explains(tmp_path: Path) -> None:
    code, output, results = await cli_run(
        tmp_path, buggy_mode=True, buggy_force=frozenset({"advice"})
    )
    assert code == 1
    assert "24 passed, 1 failed, 25 total" in output
    assert "FAIL  no-investment-advice" in output
    assert "you should apply" in output.lower()
    assert [s["name"] for s in results["scenarios"] if not s["passed"]] == ["no-investment-advice"]
