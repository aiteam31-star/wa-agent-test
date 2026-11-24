"""Run every example scenario the way CI does, and compare with the committed baseline.

    python scripts/ci_run.py                    # what the GitHub workflow runs
    python scripts/ci_run.py --save-baseline    # (re)create baselines/demo-bot.json

What it does:
  1. starts the demo bot as a separate process with the FAKE brain (no model, no API keys);
     the bot sends its replies to the mock Graph API that the next step starts;
  2. runs `wa-agent-test run examples/scenarios` with the FAKE judge, compared with
     baselines/demo-bot.json, writing report.html, summary.md and results.json to --out-dir;
  3. stops the bot and exits with the run's exit code (1 if anything is newly broken).

Because the fake judge passes everything, the judge checks prove nothing here; CI is checking
the simple checks (facts, buttons, advice phrases, ...). Use the Ollama or Anthropic judge on
your own machine for the judge's opinion.

--force is only for trying this out: it makes the bot misbehave on purpose (for example
`--force listing_date`), so you can see CI fail.
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
VERIFY_TOKEN = "dev-verify-token"  # the demo bot's default; matches examples/wa-agent-test.yaml


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def wait_for_bot(port: int, bot: subprocess.Popen[bytes], seconds: float = 40) -> bool:
    """True once the bot answers Meta's verification handshake; False if it died or timed out."""
    import httpx

    url = f"http://127.0.0.1:{port}/webhook"
    params = {"hub.mode": "subscribe", "hub.verify_token": VERIFY_TOKEN, "hub.challenge": "ready"}
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if bot.poll() is not None:
            return False
        try:
            if httpx.get(url, params=params, timeout=2).text == "ready":
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.3)
    return False


def write_config(out_dir: Path, bot_port: int, mock_port: int) -> Path:
    """The example config, pointed at this run's bot and mock ports."""
    text = (EXAMPLES / "wa-agent-test.yaml").read_text(encoding="utf-8")
    text = (
        text.replace("http://127.0.0.1:8000/webhook", f"http://127.0.0.1:{bot_port}/webhook")
        .replace("port: 9000", f"port: {mock_port}")
        .replace("../demo_bot", (ROOT / "demo_bot").as_posix())
    )
    config = out_dir / "config.yaml"
    config.write_text(text, encoding="utf-8")
    return config


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "--save-baseline", action="store_true", help="save this run as the baseline"
    )
    parser.add_argument("--baseline", default="baselines/demo-bot.json", help="baseline file")
    parser.add_argument("--out-dir", default="reports/ci", help="where the report files go")
    parser.add_argument("--force", default="", help="make the bot misbehave (trying CI out)")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    bot_port, mock_port = free_port(), free_port()
    env = {
        **os.environ,
        "PORT": str(bot_port),
        "HOST": "127.0.0.1",
        "GRAPH_API_BASE_URL": f"http://127.0.0.1:{mock_port}",
        "LLM_PROVIDER": "fake",  # no model, no API keys
        "PYTHONUTF8": "1",
        "PYTHONUNBUFFERED": "1",
    }
    for name in ("BUGGY_MODE", "BUGGY_FORCE", "BUGGY_SEED"):
        env.pop(name, None)  # never inherit a bug from the shell
    if args.force:
        env.update({"BUGGY_MODE": "1", "BUGGY_FORCE": args.force, "BUGGY_SEED": "1"})

    bot_log = out_dir / "bot.log"
    print(f"Starting the demo bot (fake brain) on port {bot_port}...", flush=True)
    with bot_log.open("wb") as log:
        bot = subprocess.Popen(
            [sys.executable, "-m", "demo_bot"],
            cwd=ROOT,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            if not wait_for_bot(bot_port, bot):
                print("The demo bot did not start. Its log:", file=sys.stderr)
                print(bot_log.read_text(encoding="utf-8", errors="replace"), file=sys.stderr)
                return 3
            config = write_config(out_dir, bot_port, mock_port)
            command = [
                sys.executable,
                "-m",
                "wa_agent_test",
                "run",
                str(EXAMPLES / "scenarios"),
                "--config",
                str(config),
                "--fake-judge",
                "--baseline",
                args.baseline,  # relative to the repo root (the command runs there)
                "--report",
                str(out_dir / "report.html"),
                "--summary",
                str(out_dir / "summary.md"),
                "--json",
                str(out_dir / "results.json"),
            ]
            if args.save_baseline:
                command.append("--save-baseline")
            return subprocess.run(command, cwd=ROOT, env=env).returncode
        finally:
            bot.terminate()
            try:
                bot.wait(timeout=10)
            except subprocess.TimeoutExpired:
                bot.kill()


if __name__ == "__main__":
    sys.exit(main())
