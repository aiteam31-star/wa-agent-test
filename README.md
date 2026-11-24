# wa-agent-test

An open-source testing harness for AI agents that run on the **WhatsApp Cloud API**. It replaces manual phone testing: it plays both WhatsApp and the user, so you can test a bot's conversations automatically.

```
scenario (YAML) -> simulator --signed webhook--> your bot --reply--> mock Graph API
                                                                         |
          checks (text, facts, LLM judge) -> baseline comparison -> HTML report / exit code
```

## What it does

- **Simulates WhatsApp.** Sends realistic, signed inbound webhooks (text, button and list taps, images, statuses) and runs a mock `POST /{version}/{phone_number_id}/messages` that captures the bot's replies and rejects what WhatsApp would reject (for example more than 3 reply buttons).
- **Scenarios in YAML.** Multi-turn chats, run in parallel, one simulated user each. See [docs/scenarios.md](docs/scenarios.md).
- **Checks.** Text and button checks, `fact:` checks against your real data, `known_dates:` (no invented dates), and an optional LLM judge (Ollama or Anthropic). Every check can be `severity: warn` (yellow, never fails).
- **Baselines.** Save a run as "known good"; later runs are labelled still passing / still failing / **newly broken** / newly fixed, and the exit code is non-zero only if something is newly broken.
- **Reports.** One self-contained HTML file that shows each scenario as a WhatsApp-style chat, with failed checks highlighted.
- **CI.** A GitHub Actions workflow runs it on every push and pull request. See [docs/github-setup.md](docs/github-setup.md) (written for people new to GitHub).

A small demo bot, [demo_bot/](demo_bot/), answers questions about five fictional Indian IPOs, with a `BUGGY_MODE` that injects realistic bugs for the harness to catch.

## Try it

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
python scripts/ci_run.py
```

That starts the demo bot and the mock, runs all 30 example scenarios, and compares them with the committed baseline; the HTML report is written to `reports/ci/report.html`. To watch it catch a bug:

```powershell
python scripts/ci_run.py --force listing_date
```

More demos (a real local model through Ollama, the judge comparison, the baseline demo) are in [scripts/README.md](scripts/README.md).

## Use it on your own bot

1. Write a `wa-agent-test.yaml` (see [examples/wa-agent-test.yaml](examples/wa-agent-test.yaml)): your bot's webhook URL, app secret, and any truth sources.
2. Point your bot's Graph API base URL at the mock (`mock.port`).
3. Write scenarios (see [docs/scenarios.md](docs/scenarios.md)) and run `wa-agent-test run <folder>`.

## Project docs

- [docs/scenarios.md](docs/scenarios.md): the scenario format, checks, judge, baselines and reports
- [docs/github-setup.md](docs/github-setup.md): put the project on GitHub and watch the checks run
- [PLAN.md](PLAN.md): the staged roadmap and what is done; [CLAUDE.md](CLAUDE.md): architecture and conventions

Licence: MIT.
