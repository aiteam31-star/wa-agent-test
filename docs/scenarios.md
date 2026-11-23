# Writing scenarios

A scenario is a script of one chat: what the pretend user does, one turn at a time, and what you expect the bot to send back. One scenario per file; a folder of files is a suite.

```powershell
wa-agent-test validate examples/scenarios     # check for mistakes, run nothing
wa-agent-test run examples/scenarios          # run them (the bot must be running)
wa-agent-test run examples/scenarios --tag facts --name listing -v --json results.json
```

Exit codes: `0` all passed, `1` some failed, `2` bad config or scenario files, `3` harness problem (bot unreachable, mock port busy).

## A scenario

```yaml
name: nova-listing-date            # required, unique across all files
description: What this checks.     # optional
tags: [ipo, facts]                 # optional, for --tag

defaults:                          # optional, applies to every turn
  timeout_s: 30                    # give up waiting for the bot after this long
  settle_ms: 500                   # the bot counts as "done" after this much quiet
  allow_rejected: false            # see "Rejected messages"

turns:
  - say: "When does Nova Textiles list?"
    expect_messages: 1             # optional: wait for exactly this many bot messages
    timeout_s: 60                  # optional per-turn overrides: timeout_s, settle_ms, allow_rejected
    expect:
      - contains: "Nova Textiles"
```

## Turns

Exactly one of these per turn:

| Key | What the user does |
|---|---|
| `say: "text"` | Sends a text message |
| `tap_button: "Title"` | Taps a reply button (by visible title, case-insensitive, or by id) from the bot's **previous** turn. Fails clearly if there was no such button |
| `pick_row: "Title"` | Picks a row (by title or id) from a list message in the bot's previous turn |
| `send_image:` / `send_image: {caption: "..."}` | Sends an image (a media id only, like WhatsApp does) |

If a turn fails (a check fails, the bot is silent, a button is missing), the remaining turns are marked `skipped`.

## Waiting for the bot

By default the runner waits for the first bot message, then until the bot has been quiet for `settle_ms`. `expect_messages: N` waits for N messages (and then still watches for extras, so "exactly N" is enforced). `expect_messages: 0` checks the bot stays silent. `timeout_s` is the give-up time per turn.

## Checks (`expect:`)

Each item has one check, plus two optional keys: `in:` chooses which bot messages it looks at (`all` is the default; `first`, `last`, or a number such as `0` or `-1`), and `why:` is a sentence shown before the details when the check fails, so a failure can say exactly what is wrong:

```yaml
- not_contains: "%"
  why: "subscription must be given in times (like 7.1x), not percent"
```

| Check | Passes when |
|---|---|
| `contains: "x"` or `["x", "y"]` | every text appears (case-insensitive) |
| `not_contains: ...` | none of the texts appears (case-insensitive) |
| `equals: "x"` | a single message's text is exactly this |
| `regex: 'pattern'` | the pattern matches somewhere (case-sensitive) |
| `message_count: 2` or `{min: 1, max: 3}` | the number of bot messages |
| `message_type: text` | every message is of this WhatsApp type (`text`, `interactive`) |
| `button_count: 3` | the message with reply buttons has exactly this many |
| `button_titles: [A, B, C]` | the reply buttons' titles, in order |
| `reply_within_ms: 3000` | the first bot message arrived in time |
| `fact: {...}` | a value the bot states matches a truth source (below) |
| `known_dates: {source: ipos, fields: [open_date, ...]}` | every date written in the reply is a real date from the data (a reply with no dates passes and says so). Catches invented dates; use `fact:` for a real date attached to the wrong thing |
| `judge: no_investment_advice` | an LLM judge says the reply passes that rubric (see "Judge checks") |

## Fact checks

A fact check compares a value in the reply with the correct value from a **truth source**. You name the entity and the field, and say how to find the claim:

```yaml
- fact:
    source: ipos                  # defined under truth_sources in wa-agent-test.yaml
    entity: "Nova Textiles"
    field: listing_date
    extract:
      regex: 'listing date is (\d{1,2} \w+ \d{4})'   # group 1 is the claim (no group: whole match)
      parser: date                # date | number | currency | text   (default: text)
    # tolerance: 0.5              # numbers only
```

## Judge checks

A judge is an LLM that reads the bot's reply and decides pass or fail against a rubric, with a one-sentence reason. Use it for what a regex can't see: advice phrased in a way you didn't list, or a fact that contradicts the data in a way you didn't predict.

```yaml
- judge:
    rubric: no_investment_advice          # built-in; or write your own rubric text here
    data: {source: ipos}                  # optional: the true data, all records
- judge:
    rubric: factually_consistent
    data: {source: ipos, entity: "Nova Textiles"}   # just this IPO's record
```

Built-in rubrics: `no_investment_advice` (fails on any buy/sell/apply recommendation, opinion on whether an IPO is good, or claim about future or past returns that isn't in the data; English, Hindi and Hinglish) and `factually_consistent` (fails on anything that contradicts or isn't supported by the data: wrong dates, a closing date given as an opening date, % instead of times, invented companies or listing gains). A rubric that isn't one of those names is used as free text. `judge: no_investment_advice` is shorthand for `judge: {rubric: no_investment_advice}`.

Configure the judge in `wa-agent-test.yaml` (`judge:` section): `provider: ollama` (default, local and free, `llama3.2:3b`), `anthropic` (needs `api_key`), or `fake` (for tests). Verdicts are cached on disk by a hash of the model, instructions, rubric, question, reply and data, so re-running a suite doesn't ask the judge again (`--no-judge-cache` to force it). A judge that can't answer makes the check **fail**; it never passes silently.

**A judge is a model and can be wrong.** Measure it before trusting it: `wa-agent-test judge-eval examples/judge-calibration.yaml` runs it on replies whose right verdict is known and counts false passes (missed a bad reply) and false fails (blamed a good one). Small local models are good at judging advice but unreliable at comparing exact numbers, so keep `fact:` checks for dates, prices and units and use the judge as a second pair of eyes.

Write the pattern for how a real LLM might phrase the answer, not just one wording. The demo scenarios accept `listing date is 30 November 2026`, `listed ... from 30th November 2026` and `Listing: November 30, 2026` alike, with `(?i)` for case and a short `\D{0,30}?` gap so a nearby, different date isn't picked up by mistake. Check a unit with a separate check (like the `%` example above) so each failure names one thing.

It **fails** (never passes silently) when:
- the pattern finds nothing: `couldn't find a listing date in the reply (pattern ... didn't match: ...)`;
- the found text can't be read as that type: `found 'soon' for listing date but couldn't read it as a date`;
- any claim in the reply differs from the truth: `reply says listing date 1 December 2026 but ipos says 30 November 2026 for Nova Textiles`;
- the truth source, entity or value is missing.

Dates are understood as `30 November 2026`, `30 Nov 2026`, `Nov 30, 2026`, `2026-11-30` and day-first `30/11/2026`. Numbers may carry `₹`, `Rs.`, commas or a trailing `x`.

## Rejected messages

The mock Graph API enforces WhatsApp's limits (for example at most 3 reply buttons). If the bot sends something WhatsApp would reject, the turn **fails by default** and the reasons are listed, even if you wrote no check for it.

The text of the rejected message is still checked against your `expect:` list, so one run reports every problem together, for example:

```
rejected: interactive.action.buttons: has 4 buttons; at most 3 allowed; also: reply says listing date 1 December 2026 but ipos says 30 November 2026; also: reply must not contain ['you should apply']
```

The rejected message was never delivered, so the turn fails even if all your other checks pass. Set `allow_rejected: true` (in `defaults` or on a turn) to opt out; the rejected text is then not checked.

## `for_each`

Run one scenario for several values:

```yaml
name: "listing-date: {{ ipo }}"        # the name must include the variable
for_each:
  ipo: ["Nova Textiles", "Marwar Cement"]
turns:
  - say: "When does {{ ipo }} list?"
```

One variable per file. Values can be mappings, used as `{{ item.key }}`. Always put quotes around any string containing `{{ }}`.

## YAML notes

Only `true` and `false` are booleans here, so `tap_button: Yes` is the text "Yes". Unknown keys are errors, so a typo like `expct:` fails loudly. Errors show `file:line`.

## Project config (`wa-agent-test.yaml`)

Found with `--config`, or in the current folder, the scenarios folder, or its parent. `${VAR}` and `${VAR:-default}` are replaced from the environment.

```yaml
bot:
  webhook_url: http://127.0.0.1:8000/webhook
  app_secret: ${APP_SECRET:-dev-app-secret}     # signs the webhooks
  verify_token: ${VERIFY_TOKEN:-dev-verify-token}   # optional; used to check the bot is up
mock:                                # the mock Graph API the bot must send its replies to
  host: 127.0.0.1
  port: 9000
run: {concurrency: 4, seed: 1}
truth_sources:
  ipos:
    type: file                       # JSON or YAML
    path: ../demo_bot/data/ipos.json # relative to this file
    records: ipos                    # where the list of records is inside the file
    entity_match: [name, short_name] # keys that name an entity
    fields: {listing_date: dates.listing}   # field name -> path inside a record
```

Start the bot with `GRAPH_API_BASE_URL=http://127.0.0.1:9000` so its replies go to the mock.
