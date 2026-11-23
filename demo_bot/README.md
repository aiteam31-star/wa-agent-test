# demo_bot

A small WhatsApp Cloud API bot that answers questions about **5 fictional Indian IPOs**. It exists so `wa-agent-test` has a real bot to test; the data and companies are made up (`data/ipos.json`).

## What it does

- `GET /webhook`: Meta's verification handshake (`hub.verify_token`).
- `POST /webhook`: verifies `X-Hub-Signature-256` (401 if wrong), reads text messages and button/list replies, replies through the Graph API at `GRAPH_API_BASE_URL`. Status webhooks are ignored; duplicate deliveries are answered once.
- An LLM with three tools, backed by the JSON fixture: `list_open_ipos()`, `get_ipo_details(name)`, `get_subscription_status(name)`.
- Replies: a **list** of open IPOs for "which are open?", **text + 3 reply buttons** (Dates, Price band, Subscription) for a specific IPO, plain text otherwise.
- Per-user conversation history, in memory (lost on restart), so follow-ups like "and its subscription?" work.

## Run it

```powershell
pip install -e ".[dev]"
$env:GRAPH_API_BASE_URL = "http://127.0.0.1:9000"   # e.g. the wa-agent-test mock Graph API
$env:LLM_PROVIDER = "fake"                          # anthropic | ollama | fake
python -m demo_bot                                  # http://127.0.0.1:8000/webhook
```

## Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `APP_SECRET` | `dev-app-secret` | Signs/verifies `X-Hub-Signature-256` |
| `VERIFY_TOKEN` | `dev-verify-token` | GET handshake token |
| `WHATSAPP_ACCESS_TOKEN` | `dev-access-token` | Bearer token for sends |
| `GRAPH_API_BASE_URL` | `https://graph.facebook.com` | Where replies are POSTed; point at the mock |
| `GRAPH_API_VERSION` | `v21.0` | Version path segment |
| `LLM_PROVIDER` | `fake` | `anthropic`, `ollama` or `fake` |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` | -, `claude-haiku-5-5` | Anthropic Messages API (plain HTTP, no SDK) |
| `OLLAMA_BASE_URL`, `OLLAMA_MODEL` | `http://localhost:11434`, `llama3.1` | Local Ollama (needs a tool-calling model) |
| `BUGGY_MODE` | off | `1` turns on bug injection |
| `BUGGY_RATE` | `0.3` | Chance each bug fires per opportunity |
| `BUGGY_SEED` | random | Seed, to make "sometimes" reproducible |
| `BUGGY_FORCE` | empty | Comma list (`listing_date,buttons,advice`): only these fire, every time |

`fake` is a deterministic, rule-based stand-in for an LLM (it still calls the tools). It is the default so the bot and its tests run with no keys or network. Use `anthropic` or `ollama` for a real model.

## BUGGY_MODE

With `BUGGY_MODE=1` the bot has three realistic defects, for the harness to catch:

| Bug | What happens | How the harness catches it |
|---|---|---|
| `listing_date` | The tool returns a listing date 1-2 days late, so the bot quotes a wrong date | Fact check against `data/ipos.json` (Stage 6) |
| `buttons` | IPO replies carry 4 reply buttons; Meta allows 3, so the mock rejects the message with a 400 and records it | Rejected-request / button-count assertion (Stage 5) |
| `advice` | The reply ends "You should apply for this IPO..." | `not_contains: "you should apply"` (Stage 5) |

Examples: `BUGGY_MODE=1 BUGGY_FORCE=buttons` (always 4 buttons, nothing else), or `BUGGY_MODE=1 BUGGY_RATE=0.5 BUGGY_SEED=7` (each bug about half the time, reproducibly).
