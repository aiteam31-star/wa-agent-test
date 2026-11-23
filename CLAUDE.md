# CLAUDE.md

Guidance for Claude Code (and humans) working in this repo.

## What this is

`wa-agent-test` is an open-source testing harness for AI agents that run on the **WhatsApp Cloud API**. It replaces manual phone testing by playing both sides of Meta's API:

```
 scenario (YAML)
      │
      ▼
 Scenario runner ──► Webhook simulator ──POST inbound webhook──►  Bot under test
      ▲                                                               │
      │                                                  POST /{ver}/{phone_number_id}/messages
      │                                                               ▼
      └──────── captured outbound messages ◄────────────────  Mock Graph API
      │
      ▼
 Assertions (deterministic / facts / LLM judge) ─► results ─► baseline diff ─► HTML report / CLI exit code
```

The bot is a black box reachable over HTTP. Its Graph API base URL must be configurable so it can point at the mock.

## Components and where they live

Package: `src/wa_agent_test/` (src layout, import name `wa_agent_test`, CLI `wa-agent-test`).

| Module | Responsibility |
|---|---|
| `payloads/` | Pure builders for Meta inbound webhook payloads (text, image/audio/document, interactive button/list replies, location, reactions, `statuses`) and `X-Hub-Signature-256` signing. No I/O. |
| `simulator/` | httpx client that delivers payloads to the bot's webhook URL; also handles the GET `hub.challenge` verification handshake. |
| `mock_graph/` | FastAPI app mimicking `POST /{version}/{phone_number_id}/messages` (plus media/mark-as-read endpoints as needed). Validates the body shape, returns Meta-like responses (`messaging_product`, `contacts`, `messages[].id`), stores captured messages in a per-run, per-conversation store. Supports fault injection (HTTP errors, latency). |
| `scenarios/` | Pydantic models for scenarios, YAML loader (`for_each`, `file:line` errors), the asyncio `ScenarioRunner`, and plain-data run results. Reference: `docs/scenarios.md`. |
| `assertions/` | `Assertion` protocol and implementations: deterministic (contains, regex, equals, count, order, message type, buttons, latency), fact (`truth/`), and judge (`judges/`). |
| `truth/` | `TruthSource` protocol; built-ins: YAML/JSON file and generic HTTP endpoint. |
| `judges/` | `Judge` protocol; adapters for Anthropic and OpenAI (optional extras, lazy imports). |
| `baseline/` | Save/load a run's normalized results; diff a new run against it (new failures, fixed, changed replies, score drift). |
| `report/` | Jinja2 HTML report (self-contained single file) and JSON/JUnit output. |
| `cli.py` | Typer app. Built: `run`, `validate`. Planned: `serve-mock`, `send`, `baseline save|diff`, `report`. Thin; no business logic. |
| `config.py`, `yamlio.py` | Project config (`wa-agent-test.yaml`, `${ENV}` interpolation); YAML loading where only `true`/`false` are booleans (so `tap_button: Yes` stays text). |

Outside the package:

| Path | Responsibility |
|---|---|
| `demo_bot/` | Demo WhatsApp Cloud API bot answering questions about 5 fictional Indian IPOs from `demo_bot/data/ipos.json`, with a pluggable LLM provider (Anthropic, local Ollama, plus a deterministic `fake` for tests/CI; all via plain HTTP, with tool calls). `BUGGY_MODE` injects three known defects (wrong listing date, 4 buttons instead of Meta's max 3, "you should apply" advice) that the harness must catch. Not part of the installed package; its fixture doubles as a truth source. |
| `examples/echo_bot/` | Minimal echo bot used for the mock Graph API integration test. |

## Key design rules

1. **Isolation per scenario.** Every scenario gets its own simulated user (unique `wa_id`) and its own capture bucket, so scenarios run in parallel without cross-talk. The mock Graph API routes captured messages to a conversation by the `to` field of the outbound message.
2. **One mock server per run, shared by all scenarios.** Started in-process on an ephemeral port by default; `serve-mock` runs it standalone.
3. **Asyncio everywhere.** No blocking calls in the runner. Concurrency is bounded by a semaphore (`--concurrency`).
4. **Waiting for replies is quiescence-based.** After a user turn, wait until the expected message count arrives or no new outbound message for `settle_ms`, bounded by `timeout_s`. Never `sleep` a fixed duration.
5. **Realistic payloads.** Payload builders must match Meta's documented schema (`object: whatsapp_business_account`, `entry[].changes[].value` with `metadata`, `contacts`, `messages`). Keep golden fixtures in `tests/fixtures/` and test builders against them.
6. **Determinism first.** Deterministic assertions are the default; LLM judging is opt-in per assertion, cached, and run at temperature 0. Judge and truth-source results are recorded verbatim in the run result for reproducibility.
7. **Pluggability via Protocols + entry points** (`wa_agent_test.judges`, `wa_agent_test.truth_sources`, `wa_agent_test.assertions`). Core never imports provider SDKs at module import time.
8. **Run results are plain data** (pydantic models, JSON-serializable). Baseline diffing and reports consume only that data, never live objects.
9. **Exit codes:** `0` all pass and no regressions; `1` assertion failures or regressions; `2` usage/config errors; `3` harness/infrastructure error (bot unreachable, etc.).
10. **The mock enforces Meta's limits and records violations.** E.g. more than 3 reply buttons returns a Meta-style 400 and the rejected attempt is stored so assertions can fail on it. Don't silently accept payloads Meta would reject.
11. **Secrets** (API keys, app secret) come from environment variables or the config file's `${ENV_VAR}` references; never written to reports or baselines.

## Scenario YAML

The schema is final for v1 and documented in [docs/scenarios.md](docs/scenarios.md); the pydantic models in `scenarios/models.py` are the source of truth. Decisions to keep:

- One scenario per file; turns are `say` / `tap_button` / `pick_row` / `send_image`; a failed turn skips the rest.
- Rejected sends (the mock enforces Meta's limits) **fail the turn by default**; opt out with `allow_rejected: true`.
- Fact checks are declarative: the scenario names the entity and field and supplies the regex/parser. A claim that can't be found, can't be parsed, or differs from the truth is a **failure**; never make a fact check pass silently.
- `for_each` takes one variable; `{{ var }}` substitution is plain text replacement (not Jinja) done before validation.
- Write fact regexes for how a real LLM phrases things (several wordings, `(?i)`, bounded gaps), and check units with a separate check using `why:` so failures name one thing. `tests/unit/test_example_patterns.py` pins the example patterns to real model sentences.
- Unknown keys are errors (`extra="forbid"`); errors carry `file:line`.

## Conventions

- Python 3.11+, full type hints, `mypy --strict` clean on `src/` and `demo_bot/`.
- `ruff check` and `ruff format` (line length 100). Run before finishing any change.
- Pydantic v2 models; use `model_config = ConfigDict(extra="forbid")` for user-authored config so typos fail loudly.
- Public API is whatever is re-exported from `wa_agent_test/__init__.py` and subpackage `__init__.py`; everything else is private.
- Tests: pytest + pytest-asyncio (`asyncio_mode = auto`). Unit tests in `tests/unit/` mirror the package layout; tests that start servers go in `tests/integration/` and are marked `integration`. Tests needing real LLM keys are marked `llm` and skipped by default. Use `respx` for httpx mocking; never hit the network in unit tests.
- Every stage in [PLAN.md](PLAN.md) ships with tests; don't start a stage's features before the previous stage's exit criteria are met.
- Commits are small and conventional (`feat:`, `fix:`, `test:`, `docs:`, `chore:`).

## Commands

```powershell
pip install -e ".[dev]"      # install with dev tools
pytest                       # unit + integration (llm tests skipped)
pytest -m "not integration"  # fast loop
ruff check . ; ruff format .
mypy                         # src/ and demo_bot/ (see pyproject)
```

## Out of scope (for now)

Testing against the real Meta API, template-message approval flows, WhatsApp Flows, webhook delivery retries emulating Meta's backoff, and judge-based automatic claim extraction for fact checks (all tracked as later ideas in PLAN.md).
