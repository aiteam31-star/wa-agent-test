"""Demo of baselines and the HTML report.

    python scripts/demo_baseline.py                          # judge from the example config (Ollama)
    python scripts/demo_baseline.py --fake-judge             # no model needed
    python scripts/demo_baseline.py --force buttons,advice,listing_date --out-dir reports/demo-all

It does what you would do by hand:

  1. start the demo bot with its clean fake brain and run
         wa-agent-test run examples/scenarios --save-baseline
  2. start the bot again with BUGGY_FORCE=<bugs> (default: listing_date) and run
         wa-agent-test run examples/scenarios --report report.html
     which labels every scenario against the baseline, and exits 1 if anything is newly broken.

Files go to --out-dir (default reports/demo, which git ignores): baseline.json, report.html
(the run with the bug, compared with the baseline), report-baseline.html (the clean run) and
results.json. The path of report.html is printed at the end; open it in a browser.
"""

from __future__ import annotations

import argparse
import asyncio
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from typer.testing import CliRunner  # noqa: E402

from demo_bot.app import create_app as create_bot_app  # noqa: E402
from demo_bot.config import Settings  # noqa: E402
from wa_agent_test.cli import app as cli_app  # noqa: E402
from wa_agent_test.mock_graph import MockGraphServer  # noqa: E402

EXAMPLES = ROOT / "examples"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def write_config(out_dir: Path, bot_url: str, mock_port: int, fake_judge: bool) -> Path:
    """The example config, pointed at this demo's bot and mock ports."""
    text = (EXAMPLES / "wa-agent-test.yaml").read_text(encoding="utf-8")
    text = (
        text.replace("http://127.0.0.1:8000/webhook", f"{bot_url}/webhook")
        .replace("port: 9000", f"port: {mock_port}")
        .replace("../demo_bot", (ROOT / "demo_bot").as_posix())
        # share the examples' judge cache so judge verdicts are only ever computed once
        .replace(
            "cache_dir: .wa-agent-test/judge-cache",
            f"cache_dir: {(EXAMPLES / '.wa-agent-test' / 'judge-cache').as_posix()}",
        )
    )
    if fake_judge:
        text = text.replace("provider: ollama", "provider: fake")
    config = out_dir / "config.yaml"
    config.write_text(text, encoding="utf-8")
    return config


async def run_cli(out_dir: Path, bot: Settings, fake_judge: bool, *args: str) -> int:
    """Start the bot on a free port, run ``wa-agent-test run`` once, print what it said."""
    mock_port = free_port()
    settings = Settings(
        **{**bot.__dict__, "graph_base_url": f"http://127.0.0.1:{mock_port}"},
    )
    async with MockGraphServer(create_bot_app(settings)) as server:
        config = write_config(out_dir, server.base_url, mock_port, fake_judge)
        result = await asyncio.to_thread(
            CliRunner().invoke,
            cli_app,
            ["run", str(EXAMPLES / "scenarios"), "--config", str(config), *args],
        )
    print(result.output)
    return result.exit_code


async def main(args: argparse.Namespace) -> None:
    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    baseline = out_dir / "baseline.json"
    baseline.unlink(missing_ok=True)

    banner = "=" * 90
    print(f"{banner}\nSTEP 1: clean bot, save the baseline\n{banner}")
    code = await run_cli(
        out_dir,
        Settings(),
        args.fake_judge,
        "--save-baseline",
        "--baseline",
        str(baseline),
        "--report",
        str(out_dir / "report-baseline.html"),
    )
    print(f"(exit code {code})\n")

    print(
        f"{banner}\nSTEP 2: the bot with BUGGY_FORCE={args.force}, compare with the baseline\n{banner}"
    )
    buggy = Settings(buggy_mode=True, buggy_force=frozenset(args.force.split(",")), buggy_seed=1)
    report = out_dir / "report.html"
    code = await run_cli(
        out_dir,
        buggy,
        args.fake_judge,
        "--baseline",
        str(baseline),
        "--report",
        str(report),
        "--json",
        str(out_dir / "results.json"),
    )
    print(f"(exit code {code}: {'a regression was found' if code else 'no new breakage'})\n")
    print(f"{banner}\nOpen the report in your browser:\n  {report}\n  {report.as_uri()}\n{banner}")


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="replace")  # type: ignore[union-attr]
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--force", default="listing_date", help="bugs for step 2 (comma list)")
    parser.add_argument("--out-dir", default="reports/demo", help="where to write the files")
    parser.add_argument("--fake-judge", action="store_true", help="don't call a judge model")
    asyncio.run(main(parser.parse_args()))
