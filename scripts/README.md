# scripts

Demo and comparison scripts, kept so a result can be reproduced later. They run the demo bot and the mock Graph API on local ports in one process, so you only need the project installed (`pip install -e ".[dev]"`). Run them from the repo root with the virtual environment active.

| Script | What it shows | Needs |
|---|---|---|
| `run_matrix.py` | Every example scenario against the demo bot, as a pass/fail table. Modes: `fake` (all green), `fake-buggy` (the three bugs; `--force listing_date` for one), `ollama` (a real local model) | Ollama only for `ollama` mode and for the judge (`--fake-judge` skips it) |
| `ollama_demo.py` | One question through the simulator to the bot backed by Ollama, with the reply and the tool calls | Ollama with `llama3.2:3b` pulled |
| `demo_baseline.py` | The baseline and report demo: save a baseline with the clean bot, re-run with a bug, label every scenario against the baseline, write the HTML report and print where it is | Ollama for the judge, or `--fake-judge` |
| `judge_side_by_side.py` | What the simple checks catch versus what the LLM judge catches on the advice traps (real run, hand-written replies, harder cases) | Ollama (bot and judge) |

```powershell
python scripts/run_matrix.py fake
python scripts/run_matrix.py fake-buggy --force listing_date --fake-judge
python scripts/ollama_demo.py "Which IPOs are open?"
python scripts/judge_side_by_side.py
python scripts/demo_baseline.py --fake-judge        # then open reports/demo/report.html
```

Judge verdicts are cached in `examples/.wa-agent-test/judge-cache`, so repeating a script is fast. Output files go to `reports/`, which git ignores.
