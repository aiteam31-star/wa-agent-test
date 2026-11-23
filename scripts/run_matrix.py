"""Run every example scenario against the demo bot and print a pass/fail table.

    python scripts/run_matrix.py fake                          # fake brain, no bugs: all green
    python scripts/run_matrix.py fake-buggy                    # fake brain, all three bugs
    python scripts/run_matrix.py fake-buggy --force listing_date
    python scripts/run_matrix.py ollama                        # real local model (needs Ollama)
    python scripts/run_matrix.py ollama --filter advice-trap

The bot and the mock Graph API run in this process on real local ports. The judge (for
``judge:`` checks) is the one in examples/wa-agent-test.yaml; use --fake-judge to skip a model.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from demo_bot.app import create_app as create_bot_app  # noqa: E402
from demo_bot.config import Settings  # noqa: E402
from wa_agent_test.config import build_judge, build_truth_sources, load_config  # noqa: E402
from wa_agent_test.judges import FakeJudge, Judge  # noqa: E402
from wa_agent_test.mock_graph import CaptureStore, MockGraphServer  # noqa: E402
from wa_agent_test.mock_graph import create_app as create_mock_app  # noqa: E402
from wa_agent_test.scenarios import ScenarioResult, ScenarioRunner, load_scenarios  # noqa: E402
from wa_agent_test.simulator import WebhookSimulator  # noqa: E402

CONFIG = ROOT / "examples" / "wa-agent-test.yaml"
OLLAMA_MODEL = "llama3.2:3b"
ALL_BUGS = "buttons,advice,listing_date"


def bot_settings(args: argparse.Namespace, mock_url: str) -> tuple[Settings, int]:
    """The demo bot's settings for this mode, and how many scenarios to run at once."""
    if args.mode == "fake":
        return Settings(graph_base_url=mock_url), 8
    if args.mode == "fake-buggy":
        return (
            Settings(
                graph_base_url=mock_url,
                buggy_mode=True,
                buggy_force=frozenset(args.force.split(",")),
                buggy_seed=1,
            ),
            8,
        )
    # One at a time: Ollama on a CPU answers one request at a time, so parallel scenarios would
    # only queue up and fail on timing that says nothing about answer quality.
    return (
        Settings(
            graph_base_url=mock_url,
            llm_provider="ollama",
            ollama_model=OLLAMA_MODEL,
            request_timeout_s=300,
        ),
        1,
    )


def why(result: ScenarioResult) -> str:
    if result.error:
        return result.error
    for turn in result.turns:
        if turn.status == "failed":
            return f"turn {turn.index}: {turn.summary}"
    return ""


def bugs_caught(result: ScenarioResult) -> str:
    found: list[str] = []
    for turn in result.turns:
        for check in turn.checks:
            if check.passed:
                continue
            if check.kind == "rejected_messages" and "buttons" not in found:
                found.append("buttons")
            elif check.kind == "fact" and "listing date" in check.message:
                if "listing_date" not in found:
                    found.append("listing_date")
            elif check.kind == "not_contains" and "should apply" in check.message.lower():
                found.append("advice")
    return ",".join(found)


async def warm_up_ollama() -> None:
    """Load the model once, so the first scenario isn't charged for loading it."""
    async with httpx.AsyncClient(timeout=300) as client:
        await client.post(
            "http://localhost:11434/api/chat",
            json={
                "model": OLLAMA_MODEL,
                "messages": [{"role": "user", "content": "hi"}],
                "stream": False,
                "keep_alive": "30m",
            },
        )


async def main(args: argparse.Namespace) -> None:
    config = load_config(CONFIG)
    scenarios = load_scenarios(ROOT / "examples" / "scenarios")
    if args.filter:
        scenarios = [s for s in scenarios if args.filter in s.name]
    if args.mode == "ollama":
        print("warming up the model (not timed)...", flush=True)
        await warm_up_ollama()

    judge: Judge | None = None
    if any(c.kind == "judge" for s in scenarios for t in s.turns for c in t.expect):
        judge = FakeJudge() if args.fake_judge else build_judge(config, CONFIG.parent)

    store = CaptureStore()
    async with MockGraphServer(create_mock_app(store=store)) as mock:
        settings, concurrency = bot_settings(args, mock.base_url)
        async with httpx.AsyncClient(timeout=settings.request_timeout_s) as http:
            async with MockGraphServer(create_bot_app(settings, http_client=http)) as bot:
                async with WebhookSimulator(
                    bot.base_url + "/webhook", app_secret=settings.app_secret, timeout_s=30
                ) as sim:
                    runner = ScenarioRunner(
                        simulator=sim,
                        store=store,
                        truth=build_truth_sources(config, CONFIG.parent),
                        judge=judge,
                        concurrency=concurrency,
                    )
                    start = time.monotonic()
                    run = await runner.run(scenarios, seed=1)
                    took = time.monotonic() - start
    if judge is not None:
        await judge.aclose()

    if args.json:
        Path(args.json).write_text(run.model_dump_json(indent=2), encoding="utf-8")
    show_bugs = args.mode == "fake-buggy"
    label = f"{args.mode}" + (f" force={args.force}" if show_bugs else "")
    print(
        f"\n=== {label}: {run.passed} passed, {run.failed} failed of {run.total} ({took:.0f}s) ==="
    )
    header = f"{'scenario':<42} {'result':<6}" + (f" {'bug caught':<22}" if show_bugs else "")
    print(header + " reason")
    print("-" * (len(header) + 7))
    for result in run.scenarios:
        row = f"{result.name:<42} {'PASS' if result.passed else 'FAIL':<6}"
        if show_bugs:
            row += f" {bugs_caught(result):<22}"
        reason = " ".join(why(result).split())
        print(row + (" " + reason[:150] + ("..." if len(reason) > 150 else "") if reason else ""))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("mode", choices=["fake", "fake-buggy", "ollama"])
    parser.add_argument("--force", default=ALL_BUGS, help="bugs to force in fake-buggy mode")
    parser.add_argument("--filter", help="only scenarios whose name contains this")
    parser.add_argument("--json", help="write the full results here")
    parser.add_argument("--fake-judge", action="store_true", help="don't call a judge model")
    asyncio.run(main(parser.parse_args()))
