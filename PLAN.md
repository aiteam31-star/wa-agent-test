# PLAN.md

Staged roadmap for `wa-agent-test`. Each stage ends with working, tested software and explicit exit criteria. Stages 0-6 are done (4-6 as one piece of work; see their notes).

## Stage 0 — Scaffold ✅
Repo layout, `pyproject.toml`, `CLAUDE.md`, `PLAN.md`, CI skeleton, license, empty packages, import smoke test.

**Exit:** `pip install -e ".[dev]"` works; `pytest`, `ruff` and `mypy` all pass.

## Stage 1 — Payloads and webhook simulator ✅
- `payloads/`: builders for text, image, audio, document, location, interactive (button/list reply), reaction, and status (`sent/delivered/read/failed`) webhooks; configurable `phone_number_id`, `waba_id`, `wa_id`, profile name, timestamps, message IDs.
- HMAC `X-Hub-Signature-256` signing with an app secret.
- `simulator/`: async httpx sender, verification handshake (`hub.mode/verify_token/challenge`), configurable timeouts, structured result (status, latency, body).
- Golden-fixture tests against Meta's documented payload shapes.

**Exit:** can POST a realistic signed webhook to an arbitrary URL; payloads validated against fixtures.

**Delivered:** text, `button_reply`, `list_reply`, image and `sent/delivered/read` status builders; signing; `WebhookSimulator` (many concurrent users, verification handshake); status webhooks in the current per-message-pricing (PMP) format with the legacy CBP format behind `pricing_format="cbp"`; Meta format findings in `docs/meta-format-notes.yaml`.
**Carried over (not built):** audio, document, location and reaction builders; `failed`/`played` statuses; golden fixtures copied from Meta's docs (tests currently assert shapes inline). Add when a scenario needs them.

## Stage 2 — Mock Graph API ✅
- FastAPI app: `POST /{version}/{phone_number_id}/messages` for text, template, image/audio/document, interactive, reaction; mark-as-read; Meta-style success and error responses.
- Capture store: per-run, keyed by recipient `wa_id`, with arrival timestamps, `asyncio` wait primitives (`wait_for_count`, `wait_for_quiescence`).
- Bearer-token check (configurable), request-body validation with Meta-style error shape.
- Enforce Meta's interactive-message limits: reply buttons max 3 (titles max 20 chars), list messages max 10 rows. Violations return a Meta-style 400 **and are recorded** in the capture store as rejected requests, so assertions can see what the bot attempted to send.
- Fault injection: forced status codes, delay, rate-limit (429), per-recipient rules.
- In-process start on ephemeral port plus standalone `serve-mock`.

**Exit:** a minimal echo bot (`examples/echo_bot/`) pointed at the mock has its replies captured end-to-end in an integration test.

**Delivered:** `POST /{version}/{phone_number_id}/messages` for text, interactive (button/list) and template; limits in one file (`mock_graph/limits.yaml`, each marked confirmed/conflicting/unconfirmed); rejected requests logged and recorded; capture store with `wait_for_count`; bearer-token check; `MockGraphServer` (real ephemeral port), tested over real HTTP.
**Carried over (not built):** image/audio/document/reaction message bodies and mark-as-read; `wait_for_quiescence`; fault injection; `serve-mock` CLI command (Stage 9); the `examples/echo_bot/` end-to-end test (the Stage 3 demo bot supersedes it).

## Stage 3 — Demo bot (`demo_bot/`) ✅
A realistic WhatsApp Cloud API bot to test the harness against, answering questions about **5 fictional Indian IPOs**.

- **Data:** `demo_bot/data/ipos.json` fixture with 5 fictional IPOs (name, issue dates, price band, lot size, listing date, exchange, registrar, status). This file is also the truth source for fact checks in Stage 6.
- **Bot:** FastAPI app with GET verification handshake, POST webhook (signature verified), replies sent via the Graph API at a configurable base URL (so it can point at the mock). Handles text questions and button/list replies; offers up to 3 reply buttons (e.g. "Dates", "Price band", "Another IPO").
- **LLM behind a pluggable provider, with tool calls:** `LLMProvider` protocol with Anthropic and local Ollama implementations (plain HTTP, no SDKs; OpenAI dropped), selected by `LLM_PROVIDER`. The model calls `list_open_ipos()`, `get_ipo_details(name)` and `get_subscription_status(name)`, which read the fixture. A `fake` provider (deterministic, still calls the tools) is the default and is used in tests and CI so no keys or network are needed.
- **`BUGGY_MODE` flag** injects three deliberate defects, each triggerable independently and deterministically for tests (`BUGGY_FORCE=listing_date,buttons,advice`) or probabilistically ("sometimes") with a seeded `BUGGY_RATE`:
  1. **Wrong listing date**: states a listing date that differs from the fixture.
  2. **Four buttons**: sends 4 reply buttons (Meta allows 3).
  3. **Investment advice**: says "you should apply".
- Own README with run instructions; dependencies kept as an optional extra so the core harness stays light.

**Exit:** with `BUGGY_MODE` off, the bot answers correctly for all 5 IPOs under the fake provider; with each forced defect on, the bot demonstrably produces it (unit-tested). Catching all three with the harness is the exit criterion of Stage 6 (see below).

**Delivered:** the bot as specified, per-user in-memory history, reply messages as a list (open IPOs) / text + 3 buttons (one IPO) / plain text, duplicate-delivery and status-webhook handling, and tests including simulator -> bot -> mock Graph API runs where each defect is visible (wrong date in the text, 4 buttons rejected and recorded by the mock, "you should apply" in the text). Smoke-tested over real sockets.
**Not yet verified:** the Anthropic and Ollama providers are tested against mocked HTTP only, never a real model.

## Stage 4 — Scenario model and runner ✅
- **Finalise the scenario YAML schema at the start of this stage** (not before). Whatever it looks like, it must support:
  - multi-turn conversations;
  - button and list replies (user taps a button/row from a previous bot message);
  - multiple bot messages per turn (expected count and/or settle-based collection);
  - per-turn timeouts (plus a default and a per-scenario overall timeout).
- Pydantic scenario schema + YAML loader with line-accurate errors; `wa-agent-test validate`.
- Turn types: text, media, interactive reply, wait, status event; per-turn `expect`.
- Runner: unique simulated user per scenario, bounded parallelism, quiescence-based reply waiting, full transcript capture.
- Run result models (plain data, JSON-serializable).
- Variables/templating in scenarios (e.g. `{{ user.wa_id }}`), data-driven scenario expansion (parametrize).

**Exit:** `wa-agent-test run examples/scenarios/` runs scenarios in parallel against the demo bot (clean mode) and prints a transcript summary.

**Delivered:** the final schema (see `docs/scenarios.md`): `say` / `tap_button` / `pick_row` / `send_image` turns, `expect_messages`, per-turn and default `timeout_s` / `settle_ms`, `allow_rejected` (rejected sends fail the turn by default), one scenario per file, `for_each` expansion, `file:line` errors, YAML where only `true`/`false` are booleans; `ScenarioRunner` (parallel, bounded, one simulated user per scenario, quiescence-based waiting, overall timeout); plain-data `RunResult`; `wa-agent-test run` (filters, `--json`, exit codes 0/1/2/3) and `validate`; `wa-agent-test.yaml` project config with `${ENV}` interpolation; 15 demo-bot scenario files (25 scenarios after `for_each`).
**Carried over:** `--fail-fast`, `--junit`, `serve-mock`, `send` and `report` commands; templating of runtime values such as `{{ user.wa_id }}`; running a scenario several times.

## Stage 5 — Deterministic assertions ✅
- `Assertion` protocol, registry, entry-point discovery.
- Built-ins: `contains`, `not_contains`, `equals`, `regex`, `message_count`, `message_type`, `button_count`/`button_titles`, `reply_within_ms`, `order`, `language` (optional), JSONPath on raw payloads; plus an assertion on rejected requests recorded by the mock (Stage 2).
- Clear failure messages with expected/actual excerpts.

**Exit:** scenarios can pass/fail on deterministic checks; unit tests cover each assertion. Demo-bot defects 2 (four buttons) and 3 ("you should apply") are caught here.

**Delivered:** `contains`, `not_contains`, `equals`, `regex`, `message_count`, `message_type`, `button_count`, `button_titles`, `reply_within_ms`, with `in:` message selection; rejected requests fail turns by default. **Carried over:** `order`, `language`, JSONPath on raw payloads, entry-point discovery of third-party assertions.

## Stage 6 — Fact checks and truth sources ✅
- `TruthSource` protocol; YAML/JSON file source and HTTP endpoint source (auth headers, caching, timeouts).
- **Declarative fact assertions (v1).** Each `fact` assertion names the **entity** and the **field**, looks the expected value up in the truth source, and extracts the *claimed* value from the reply using a **regex or simple parser defined in the assertion itself** (e.g. a date, number, or currency parser). Values are normalized before comparison (dates, numbers, currency). No LLM is involved: deterministic, free, and easy to debug.
- Truth lookups and extracted claims are recorded in results (expected, extracted, match).
- A fact assertion fails clearly when the claim cannot be extracted (distinct from a wrong value).

**Delivered:** `TruthSource` protocol, `FileTruthSource` (JSON/YAML), declarative `fact` checks (date/number/currency/text parsers, tolerance). A claim the regex can't find is a failure, never a silent pass. **Carried over:** the HTTP truth source (auth headers, caching, timeouts).

**Exit:** a scenario can assert reply values against a truth source; both built-in sources tested. **All three demo-bot defects are caught** end to end: clean mode passes the demo scenario suite; each forced defect makes the suite fail on exactly the expected assertion (wrong listing date via fact check, four buttons, "you should apply").

## Stage 7 — LLM judge
- `Judge` protocol (rubric + transcript → verdict, score, rationale) with strict structured output.
- Anthropic and OpenAI adapters as optional extras with lazy imports; temperature 0; retries/backoff.
- On-disk response cache keyed by (model, rubric, transcript) to make CI cheap and reruns stable.
- Fake judge for tests; `llm`-marked live tests skipped by default.

**Exit:** `judge` assertions work with either provider and with the fake judge in CI.

## Stage 8 — Baselines, regression diffing, reports
- Normalize and save run results as a baseline (`baseline save`); store in `baselines/`.
- Diff: newly failing, newly passing, changed replies (text similarity threshold), judge score drift, latency regression, added/removed scenarios.
- HTML report: summary, per-scenario transcript, assertion results, baseline diff view; self-contained single file. Also JSON and JUnit XML.

**Exit:** `wa-agent-test run --baseline baselines/main.json --report reports/index.html` produces a diff-aware report and the right exit code.

## Stage 9 — CLI polish and GitHub Actions
- Typer CLI complete: `run`, `serve-mock`, `send`, `validate`, `baseline save|diff`, `report`; config file (`wa-agent-test.yaml`) with env-var interpolation; filtering by tag/name; `--fail-fast`, `--concurrency`, `--junit`.
- Exit codes per `CLAUDE.md`.
- Reusable composite GitHub Action (`action.yml`) and example workflow: start the bot, run scenarios, upload report artifact, comment diff summary on PRs, step summary.

**Exit:** example workflow runs green in CI against the clean demo bot and surfaces a regression when the demo bot runs with `BUGGY_MODE` on.

## Stage 10 — Docs, examples, release
- Docs: quickstart, scenario reference (generated from models), writing custom judges/truth sources/assertions, CI guide.
- Examples: echo bot, the demo bot walkthrough, sample scenarios for each assertion type.
- PyPI release workflow, changelog, contribution guide, issue templates.

**Exit:** tagged `v0.1.0` published; a new user can go from `pip install` to a passing CI run in under 15 minutes.

## Later ideas (unscheduled)
- **Judge-based automatic claim extraction** for fact checks (v1 keeps extraction declarative: regex/parser per assertion).
- WhatsApp Flows and template-message testing.
- Emulating Meta's webhook retry/backoff and out-of-order delivery.
- Media upload/download endpoints in the mock.
- Record/replay of real conversations into scenarios.
- pytest plugin exposing scenarios as test items.
- Web UI for live conversation inspection.

## Open questions
- Exact scenario YAML schema: deliberately open until the start of Stage 4 (constraints listed there).
- Report diff similarity metric (token-based vs embedding-based).
