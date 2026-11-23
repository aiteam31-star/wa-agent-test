"""The HTML report: one self-contained file (no scripts, fonts or images from the internet).

A summary at the top, then every scenario as a WhatsApp-style chat, with failed checks
highlighted and explained. With a baseline, scenarios are grouped by what changed.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from jinja2 import Environment

from wa_agent_test.baseline import LABELS, Comparison
from wa_agent_test.scenarios import RunResult, ScenarioResult, TurnResult

# What is shown first: what changed for the worse, then for the better, then the rest.
GROUP_ORDER = [
    "newly_broken",
    "newly_fixed",
    "new_failing",
    "new_passing",
    "still_failing",
    "still_passing",
]
BAD = {"newly_broken", "new_failing", "still_failing", "failed"}
OPEN_BY_DEFAULT = {"newly_broken", "newly_fixed", "new_failing", "failed"}

TEMPLATE = """\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title }}</title>
<style>
:root {
  --page: #f6f5f2; --card: #ffffff; --text: #1d2327; --muted: #667781; --line: #e3e0d8;
  --wall: #efeae2; --user: #d9fdd3; --bot: #ffffff; --link: #027eb5;
  --ok: #1a7f37; --ok-bg: #e8f6ec; --fail: #c62828; --fail-bg: #fdecea;
  --warn: #8a5a00; --warn-bg: #fff4d6; --tag: #e9edef; --judge: #5b3fb4; --judge-bg: #efeaff;
}
@media (prefers-color-scheme: dark) {
  :root {
    --page: #111b21; --card: #1b2830; --text: #e9edef; --muted: #8696a0; --line: #2a3942;
    --wall: #0b141a; --user: #005c4b; --bot: #202c33; --link: #53bdeb;
    --ok: #5fd07a; --ok-bg: #12301d; --fail: #ff8a80; --fail-bg: #3a1a1a;
    --warn: #ffcc66; --warn-bg: #3a2e12; --tag: #2a3942; --judge: #c4b2ff; --judge-bg: #2b2250;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--page); color: var(--text);
  font: 15px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
}
.wrap { max-width: 920px; margin: 0 auto; padding: 0 16px; }
.top { background: var(--card); border-bottom: 1px solid var(--line); padding: 24px 0 18px; }
.eyebrow { margin: 0; color: var(--muted); font-size: 13px; letter-spacing: .04em; text-transform: uppercase; }
h1 { margin: 4px 0 8px; font-size: 28px; line-height: 1.25; }
.verdict { display: inline-block; margin: 0 0 10px; padding: 4px 12px; border-radius: 999px; font-weight: 600; }
.verdict.bad { color: var(--fail); background: var(--fail-bg); }
.verdict.good { color: var(--ok); background: var(--ok-bg); }
.meta { margin: 0 0 12px; color: var(--muted); font-size: 13px; }
.chips { display: flex; flex-wrap: wrap; gap: 8px; }
.chip { text-decoration: none; color: var(--text); background: var(--tag); border-radius: 8px; padding: 5px 11px; font-size: 14px; }
.chip.bad { background: var(--fail-bg); color: var(--fail); }
.chip.good { background: var(--ok-bg); color: var(--ok); }
h2 { margin: 28px 0 10px; font-size: 18px; }
h2 .count { color: var(--muted); font-weight: 400; margin-left: 6px; }
h2.bad { color: var(--fail); } h2.good { color: var(--ok); }
details.scenario { background: var(--card); border: 1px solid var(--line); border-radius: 10px; margin: 0 0 10px; overflow: hidden; }
details.scenario > summary { cursor: pointer; padding: 11px 14px; display: flex; flex-wrap: wrap; align-items: center; gap: 8px; list-style: none; }
details.scenario > summary::-webkit-details-marker { display: none; }
details.scenario > summary::before { content: "\\25B8"; color: var(--muted); }
details.scenario[open] > summary::before { content: "\\25BE"; }
.name { font-weight: 600; }
.badge { font-size: 12px; font-weight: 700; padding: 2px 9px; border-radius: 999px; background: var(--tag); }
.badge.bad { color: var(--fail); background: var(--fail-bg); }
.badge.good { color: var(--ok); background: var(--ok-bg); }
.spacer { flex: 1; }
.dim { color: var(--muted); font-size: 13px; }
.body { padding: 4px 14px 14px; border-top: 1px solid var(--line); }
.note { margin: 10px 0 0; padding: 8px 12px; border-radius: 8px; background: var(--warn-bg); color: var(--warn); font-size: 14px; }
.turn { margin-top: 14px; }
.turnhead { display: flex; gap: 8px; align-items: center; color: var(--muted); font-size: 13px; margin-bottom: 4px; }
.chat { background: var(--wall); border-radius: 10px; padding: 10px 12px; }
.row { display: flex; margin: 4px 0; }
.row.user { justify-content: flex-end; }
.bubble { max-width: 78%; padding: 6px 9px 5px; border-radius: 8px; box-shadow: 0 1px .5px rgba(0,0,0,.13); white-space: pre-wrap; overflow-wrap: anywhere; }
.bubble.user { background: var(--user); border-top-right-radius: 2px; }
.bubble.bot { background: var(--bot); border-top-left-radius: 2px; }
.bubble.rejected { border: 2px dashed var(--fail); background: var(--fail-bg); }
.small { display: block; margin-top: 2px; font-size: 11px; color: var(--muted); text-align: right; white-space: normal; }
.reject-tag { display: block; color: var(--fail); font-weight: 700; font-size: 12px; white-space: normal; margin-bottom: 3px; }
.btns { margin-top: 6px; border-top: 1px solid var(--line); white-space: normal; }
.btn { text-align: center; padding: 6px 4px; color: var(--link); font-weight: 600; border-bottom: 1px solid var(--line); }
.btn:last-child { border-bottom: 0; }
.rows { margin-top: 6px; border-top: 1px solid var(--line); white-space: normal; }
.rowitem { padding: 5px 4px; border-bottom: 1px solid var(--line); }
.rowitem:last-child { border-bottom: 0; }
.rowitem b { display: block; font-weight: 600; }
.rowitem span { color: var(--muted); font-size: 13px; }
.nothing { color: var(--muted); font-style: italic; padding: 4px 2px; }
.problems { margin: 10px 0 0; padding: 9px 12px; background: var(--fail-bg); border: 1px solid var(--fail); border-radius: 8px; }
.problems .title { color: var(--fail); font-weight: 700; margin: 0 0 3px; font-size: 13px; text-transform: uppercase; letter-spacing: .04em; }
.problems ul { margin: 0; padding-left: 18px; }
.problems li { margin: 2px 0; overflow-wrap: anywhere; }
.warnings { margin: 10px 0 0; padding: 9px 12px; background: var(--warn-bg); border: 1px solid var(--warn); border-radius: 8px; color: var(--text); }
.warnings .title { color: var(--warn); font-weight: 700; margin: 0 0 3px; font-size: 13px; text-transform: uppercase; letter-spacing: .04em; }
.warnings ul { margin: 0; padding-left: 18px; }
.warnings li { margin: 2px 0; overflow-wrap: anywhere; }
.badge.warn { color: var(--warn); background: var(--warn-bg); }
.chip.warn { background: var(--warn-bg); color: var(--warn); }
.checks { list-style: none; margin: 8px 0 0; padding: 0; }
.check { display: flex; gap: 8px; align-items: baseline; padding: 4px 8px; border-radius: 6px; font-size: 13.5px; overflow-wrap: anywhere; }
.check.fail { background: var(--fail-bg); border-left: 4px solid var(--fail); }
.check.pass { color: var(--muted); }
.check.warn { background: var(--warn-bg); border-left: 4px solid var(--warn); }
.mark { font-weight: 800; width: 1.1em; flex: none; }
.check.fail .mark { color: var(--fail); } .check.pass .mark { color: var(--ok); } .check.warn .mark { color: var(--warn); }
.tag { flex: none; font-size: 11px; text-transform: uppercase; letter-spacing: .04em; padding: 1px 6px; border-radius: 4px; background: var(--tag); color: var(--text); }
.tag.judge { background: var(--judge-bg); color: var(--judge); font-weight: 700; }
.err { margin: 8px 0 0; color: var(--fail); font-weight: 600; }
footer { margin: 34px 0 40px; color: var(--muted); font-size: 12px; text-align: center; }
@media (max-width: 560px) { h1 { font-size: 22px; } .bubble { max-width: 90%; } }
</style>
</head>
<body>
<header class="top"><div class="wrap">
  <p class="eyebrow">{{ title }}</p>
  <h1>{{ headline }}</h1>
  <p class="verdict {{ verdict_class }}">{{ verdict }}</p>
  <p class="meta">{{ meta }}</p>
  <div class="chips">
  {% for g in groups %}
    <a class="chip {{ g.tone }}" href="#group-{{ g.key }}"><b>{{ g.scenarios|length }}</b> {{ g.label|lower }}</a>
  {% endfor %}
  {% if warning_count %}<span class="chip warn"><b>{{ warning_count }}</b> warning{{ '' if warning_count == 1 else 's' }}</span>{% endif %}
  </div>
</div></header>
<main class="wrap">
{% for g in groups %}
<section id="group-{{ g.key }}">
  <h2 class="{{ g.tone }}">{{ g.label }}<span class="count">{{ g.scenarios|length }}</span></h2>
  {% for s in g.scenarios %}
  <details class="scenario" id="{{ s.id }}"{% if s.open %} open{% endif %}>
    <summary>
      <span class="badge {{ g.tone }}">{{ g.label }}</span>
      <span class="name">{{ s.name }}</span>
      {% if s.warnings %}<span class="badge warn">{{ s.warnings }} warning{{ '' if s.warnings == 1 else 's' }}</span>{% endif %}
      <span class="spacer"></span>
      <span class="dim">{{ s.duration }}{% if s.tags %} &middot; {{ s.tags|join(", ") }}{% endif %}</span>
    </summary>
    <div class="body">
      {% if s.was %}<p class="note">{{ s.was }}</p>{% endif %}
      {% if s.error %}<p class="err">{{ s.error }}</p>{% endif %}
      {% for t in s.turns %}
      <div class="turn">
        <div class="turnhead">
          <span class="badge {{ 'good' if t.status == 'passed' else ('bad' if t.status == 'failed' else '') }}">Turn {{ t.index }}: {{ t.status }}</span>
          <span>{{ t.duration }}</span>
        </div>
        <div class="chat">
          <div class="row user"><div class="bubble user">{{ t.user_text or t.action }}</div></div>
          {% if t.status == 'skipped' %}
          <div class="nothing">skipped: an earlier turn failed</div>
          {% endif %}
          {% for m in t.bot %}
          <div class="row"><div class="bubble bot">{{ m.text }}
            {% if m.buttons %}<div class="btns">{% for b in m.buttons %}<div class="btn">{{ b }}</div>{% endfor %}</div>{% endif %}
            {% if m.rows %}<div class="rows">{% for r in m.rows %}<div class="rowitem"><b>{{ r.title }}</b>{% if r.description %}<span>{{ r.description }}</span>{% endif %}</div>{% endfor %}</div>{% endif %}
            <span class="small">{{ m.latency }}</span></div></div>
          {% endfor %}
          {% for r in t.rejected %}
          <div class="row"><div class="bubble bot rejected">
            <span class="reject-tag">NOT DELIVERED: WhatsApp would reject this message</span>{{ r.text }}
            {% if r.buttons %}<div class="btns">{% for b in r.buttons %}<div class="btn">{{ b }}</div>{% endfor %}</div>{% endif %}
          </div></div>
          {% endfor %}
          {% if t.status != 'skipped' and not t.bot and not t.rejected %}
          <div class="nothing">the bot sent nothing</div>
          {% endif %}
        </div>
        {% if t.problems %}
        <div class="problems">
          <p class="title">What went wrong</p>
          <ul>{% for p in t.problems %}<li>{{ p }}</li>{% endfor %}</ul>
        </div>
        {% endif %}
        {% if t.warnings %}
        <div class="warnings">
          <p class="title">Warnings (these never fail the run)</p>
          <ul>{% for w in t.warnings %}<li>{{ w }}</li>{% endfor %}</ul>
        </div>
        {% endif %}
        {% if t.checks %}
        <ul class="checks">
          {% for c in t.checks %}
          <li class="check {{ c.state }}">
            <span class="mark">{{ '✓' if c.state == 'pass' else ('⚠' if c.state == 'warn' else '✗') }}</span>
            <span class="tag{{ ' judge' if c.kind == 'judge' else '' }}">{{ c.kind }}</span>
            {% if c.state == 'warn' %}<span class="tag">warning</span>{% endif %}
            <span>{{ c.message }}</span>
          </li>
          {% endfor %}
        </ul>
        {% endif %}
      </div>
      {% endfor %}
    </div>
  </details>
  {% endfor %}
</section>
{% endfor %}
{% if removed %}
<section id="group-removed">
  <h2>In the baseline but not in this run<span class="count">{{ removed|length }}</span></h2>
  <ul>{% for name in removed %}<li>{{ name }}</li>{% endfor %}</ul>
</section>
{% endif %}
</main>
<footer>{{ footer }}</footer>
</body>
</html>
"""


def _slug(text: str, index: int) -> str:
    return f"s{index}-" + (re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "scenario")


def attempt_text(payload: dict[str, Any] | None) -> str:
    """The text of a message the mock rejected (plain text, or an interactive body)."""
    if not payload:
        return ""
    text = payload.get("text")
    if isinstance(text, dict):
        return str(text.get("body", ""))
    interactive = payload.get("interactive")
    if isinstance(interactive, dict):
        body = interactive.get("body")
        if isinstance(body, dict):
            return str(body.get("text", ""))
    return ""


def _attempt_buttons(payload: dict[str, Any] | None) -> list[str]:
    interactive = (payload or {}).get("interactive")
    if not isinstance(interactive, dict) or interactive.get("type") != "button":
        return []
    buttons = interactive.get("action", {}).get("buttons", [])
    return [str(b.get("reply", {}).get("title", "")) for b in buttons]


def _turn_view(turn: TurnResult) -> dict[str, Any]:
    return {
        "index": turn.index,
        "status": turn.status,
        "user_text": turn.user_text,
        "action": turn.action,
        "duration": f"{turn.duration_ms / 1000:.1f}s" if turn.status != "skipped" else "",
        "problems": turn.problems,
        "warnings": turn.warnings,
        "checks": [
            {
                "kind": c.kind,
                "passed": c.passed,
                "state": "pass" if c.passed else ("warn" if c.warned else "fail"),
                "message": c.message,
            }
            for c in turn.checks
        ],
        "bot": [
            {
                "text": m.text,
                "buttons": [b.title for b in m.buttons],
                "rows": [{"title": r.title, "description": r.description} for r in m.rows],
                "latency": f"{m.latency_ms / 1000:.1f}s after the question",
            }
            for m in turn.bot_messages
        ],
        "rejected": [
            {
                "text": attempt_text(r.payload),
                "buttons": _attempt_buttons(r.payload),
            }
            for r in turn.rejected
        ],
    }


def _scenario_view(
    scenario: ScenarioResult, index: int, status: str, was: str | None
) -> dict[str, Any]:
    return {
        "id": _slug(scenario.name, index),
        "name": scenario.name,
        "status": status,
        "duration": f"{scenario.duration_s:.1f}s",
        "tags": scenario.tags,
        "was": was,
        "error": scenario.error,
        "turns": [_turn_view(t) for t in scenario.turns],
        "warnings": scenario.warning_count,
        "open": status in OPEN_BY_DEFAULT or scenario.warning_count > 0,
    }


def _was_text(status: str, before_passed: bool | None, problems: list[str]) -> str | None:
    if status == "newly_broken":
        return "Passed in the baseline, fails now."
    if status == "newly_fixed":
        why = f" It failed because: {problems[0]}" if problems else ""
        return "Failed in the baseline, passes now." + why
    if status == "new_failing":
        return "Not in the baseline, and it fails."
    if status == "still_failing":
        return "Already failing in the baseline (a known problem)."
    return None


def render_report(
    run: RunResult,
    comparison: Comparison | None = None,
    *,
    title: str = "wa-agent-test report",
    baseline_path: str | None = None,
) -> str:
    """The report as one HTML string."""
    by_status: dict[str, list[dict[str, Any]]] = {}
    if comparison is not None:
        info = {item.name: item for item in comparison.items}
        for i, scenario in enumerate(run.scenarios, start=1):
            item = info[scenario.name]
            was = _was_text(item.status, item.was_passed, item.was_problems)
            by_status.setdefault(item.status, []).append(
                _scenario_view(scenario, i, item.status, was)
            )
    else:
        for i, scenario in enumerate(run.scenarios, start=1):
            status = "failed" if not scenario.passed else "passed"
            by_status.setdefault(status, []).append(_scenario_view(scenario, i, status, None))

    groups: list[dict[str, Any]] = []
    keys = GROUP_ORDER if comparison is not None else ["failed", "passed"]
    labels = {**LABELS, "failed": "Failed", "passed": "Passed"}
    for key in keys:
        if key in by_status:
            groups.append(
                {
                    "key": key,
                    "label": labels[key],
                    "tone": "bad" if key in BAD else "good",
                    "scenarios": by_status[key],
                }
            )

    if comparison is not None:
        headline = comparison.summary
        if comparison.has_regression:
            broken = len(comparison.with_status("newly_broken", "new_failing"))
            verdict, verdict_class = f"Regression: {broken} scenario(s) broke", "bad"
        else:
            verdict, verdict_class = "No new breakage", "good"
        saved = comparison.baseline_saved_at.strftime("%Y-%m-%d %H:%M UTC")
        baseline_note = f"Compared with the baseline saved {saved}"
        if baseline_path:
            baseline_note += f" ({baseline_path})"
    else:
        headline = f"{run.passed} passed, {run.failed} failed"
        verdict, verdict_class = (
            ("Some scenarios failed", "bad") if run.failed else ("All scenarios passed", "good")
        )
        baseline_note = "No baseline to compare with (save one with --save-baseline)"
    started = run.started_at.strftime("%Y-%m-%d %H:%M UTC")
    warned = f" {run.warning_count} warning(s) (never failures)." if run.warning_count else ""
    meta = f"{run.total} scenario(s), run {started}, took {run.duration_s:.0f}s.{warned} {baseline_note}."

    env = Environment(autoescape=True, trim_blocks=True, lstrip_blocks=True)
    return env.from_string(TEMPLATE).render(
        title=title,
        headline=headline,
        verdict=verdict,
        verdict_class=verdict_class,
        meta=meta,
        groups=groups,
        warning_count=run.warning_count,
        removed=comparison.removed if comparison else [],
        footer="Generated by wa-agent-test. This file is self-contained: no scripts or "
        "network access are needed to read it.",
    )


def write_report(
    path: Path,
    run: RunResult,
    comparison: Comparison | None = None,
    **kwargs: Any,
) -> Path:
    """Write the report to ``path`` (folders are created) and return the path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(run, comparison, **kwargs), encoding="utf-8")
    return path
