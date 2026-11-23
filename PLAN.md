# PLAN.md

Staged roadmap for `wa-agent-test`. Each stage ends with working, tested software and explicit exit criteria. Stage 0 (this scaffold) is done.

## Stage 0 — Scaffold ✅
Repo layout, `pyproject.toml`, `CLAUDE.md`, `PLAN.md`, CI skeleton, license, empty packages.

**Exit:** `pip install -e ".[dev]"` works; `ruff`, `mypy`, `pytest` run (with no tests yet).

## Stage 1 — Payloads and webhook simulator
- `payloads/`: builders for text, image, audio, document, location, interactive (button/list reply), reaction, and status (`sent/delivered/read/failed`) webhooks; configurable `phone_number_id`, `waba_id`, `wa_id`, profile name, timestamps, message IDs.
- HMAC `X-Hub-Signature-256` signing with an app secret.
- `simulator/`: async httpx sender, verification handshake (`hub.mode/verify_token/challenge`), configurable timeouts, structured result (status, latency, body).
- Golden-fixture tests against Meta's documented payload shapes.

**Exit:** can POST a realistic signed webhook to an arbitrary URL; payloads validated against fixtures.

## Stage 2 — Mock Graph API
- FastAPI app: `POST /{version}/{phone_number_id}/messages` for text, template, image/audio/document, interactive, reaction; mark-as-read; Meta-style success and error responses.
- Capture store: per-run, keyed by recipient `wa_id`, with arrival timestamps, `asyncio` wait primitives (`wait_for_count`, `wait_for_quiescence`).
- Bearer-token check (configurable), request-body validation with Meta-style error shape.
- Fault injection: forced status codes, delay, rate-limit (429), per-recipient rules.
- In-process start on ephemeral port plus standalone `serve-mock`.

**Exit:** a sample bot (in `examples/echo_bot/`) pointed at the mock has its replies captured end-to-end in an integration test.

## Stage 3 — Scenario model and runner
- Pydantic scenario schema + YAML loader with line-accurate errors; `wa-agent-test validate`.
- Turn types: text, media, interactive reply, wait, status event; per-turn `expect`.
- Runner: unique simulated user per scenario, bounded parallelism, quiescence-based reply waiting, per-scenario timeout, full transcript capture.
- Run result models (plain data, JSON-serializable).
- Variables/templating in scenarios (e.g. `{{ user.wa_id }}`), data-driven scenario expansion (parametrize).

**Exit:** `wa-agent-test run examples/scenarios/` runs scenarios in parallel against the echo bot and prints a transcript summary.

## Stage 4 — Deterministic assertions
- `Assertion` protocol, registry, entry-point discovery.
- Built-ins: `contains`, `not_contains`, `equals`, `regex`, `message_count`, `message_type`, `has_buttons`/`button_titles`, `reply_within_ms`, `order`, `language` (optional), JSONPath on raw payloads.
- Clear failure messages with expected/actual excerpts.

**Exit:** scenarios can pass/fail on deterministic checks; unit tests cover each assertion.

## Stage 5 — Fact checks and truth sources
- `TruthSource` protocol; YAML/JSON file source and HTTP endpoint source (auth headers, caching, timeouts).
- `fact` assertion: declared facts (key → expected value) checked against reply text with normalization (numbers, currency, dates); optional claim extraction deferred to the judge.
- Truth lookups recorded in results.

**Exit:** a scenario can assert reply values against a truth source; both built-in sources tested.

## Stage 6 — LLM judge
- `Judge` protocol (rubric + transcript → verdict, score, rationale) with strict structured output.
- Anthropic and OpenAI adapters as optional extras with lazy imports; temperature 0; retries/backoff.
- On-disk response cache keyed by (model, rubric, transcript) to make CI cheap and reruns stable.
- Fake judge for tests; `llm`-marked live tests skipped by default.

**Exit:** `judge` assertions work with either provider and with the fake judge in CI.

## Stage 7 — Baselines, regression diffing, reports
- Normalize and save run results as a baseline (`baseline save`); store in `baselines/`.
- Diff: newly failing, newly passing, changed replies (text similarity threshold), judge score drift, latency regression, added/removed scenarios.
- HTML report: summary, per-scenario transcript, assertion results, baseline diff view; self-contained single file. Also JSON and JUnit XML.

**Exit:** `wa-agent-test run --baseline baselines/main.json --report reports/index.html` produces a diff-aware report and the right exit code.

## Stage 8 — CLI polish and GitHub Actions
- Typer CLI complete: `run`, `serve-mock`, `send`, `validate`, `baseline save|diff`, `report`; config file (`wa-agent-test.yaml`) with env-var interpolation; filtering by tag/name; `--fail-fast`, `--concurrency`, `--junit`.
- Exit codes per `CLAUDE.md`.
- Reusable composite GitHub Action (`action.yml`) and example workflow: start the bot, run scenarios, upload report artifact, comment diff summary on PRs, step summary.

**Exit:** example repo workflow runs green in CI and surfaces a regression on a deliberately broken bot.

## Stage 9 — Docs, examples, release
- Docs: quickstart, scenario reference (generated from models), writing custom judges/truth sources/assertions, CI guide.
- Examples: echo bot, a FastAPI LLM-style bot, sample scenarios for each assertion type.
- PyPI release workflow, changelog, contribution guide, issue templates.

**Exit:** tagged `v0.1.0` published; a new user can go from `pip install` to a passing CI run in under 15 minutes.

## Later ideas (unscheduled)
- WhatsApp Flows and template-message testing.
- Emulating Meta's webhook retry/backoff and out-of-order delivery.
- Media upload/download endpoints in the mock.
- Record/replay of real conversations into scenarios.
- pytest plugin exposing scenarios as test items.
- Web UI for live conversation inspection.

## Open questions
- Exact scenario YAML schema (finalize in Stage 3 after the echo-bot prototype).
- Whether fact checks should support automatic claim extraction via the judge or stay declarative.
- Report diff similarity metric (token-based vs embedding-based).
