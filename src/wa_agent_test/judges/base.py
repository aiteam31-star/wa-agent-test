"""The judge protocol and the pieces every judge shares (prompt, verdict parsing)."""

from __future__ import annotations

import json
from typing import Any, Protocol

from pydantic import BaseModel


class JudgeError(Exception):
    """The judge couldn't produce a usable verdict (network error, unparseable answer, ...)."""


class JudgeRequest(BaseModel):
    """Everything a judge needs to decide about one bot reply."""

    rubric_id: str  # the built-in rubric's name, or "custom"
    rubric: str  # the full rubric text
    reply: str  # the bot's reply (all messages of the turn, joined)
    question: str = ""  # what the user said
    data: str | None = None  # the true data, as JSON text


class Verdict(BaseModel):
    passed: bool
    reason: str  # one short sentence
    cached: bool = False
    model: str = ""


class Judge(Protocol):
    """Decides whether a reply passes a rubric. Implementations: Ollama, Anthropic, fake."""

    provider: str
    model: str

    async def judge(self, request: JudgeRequest) -> Verdict: ...

    async def aclose(self) -> None: ...


SYSTEM_PROMPT = (
    "You are a careful, strict evaluator of replies from a WhatsApp bot about IPOs. "
    "You are given a RUBRIC, the USER MESSAGE, the BOT REPLY and sometimes the TRUE DATA. "
    "Decide whether the BOT REPLY passes the RUBRIC. Judge only the BOT REPLY, and only against "
    "the rubric. Answer with JSON only, with a one-sentence reason first, like "
    '{"reason": "<one short sentence>", "passed": true} or '
    '{"reason": "<one short sentence>", "passed": false}.'
)

# Ollama can force this shape; "reason" comes first so the model explains before it decides.
VERDICT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"reason": {"type": "string"}, "passed": {"type": "boolean"}},
    "required": ["reason", "passed"],
}


def build_user_prompt(request: JudgeRequest) -> str:
    parts = [
        f"RUBRIC:\n{request.rubric.strip()}",
        f"USER MESSAGE:\n{request.question.strip() or '(not given)'}",
        f"BOT REPLY:\n{request.reply.strip()}",
    ]
    if request.data:
        parts.append(f"TRUE DATA (JSON):\n{request.data}")
    parts.append(
        'Answer with JSON only: {"reason": "<one short sentence>", "passed": true or false}'
    )
    return "\n\n".join(parts)


def parse_verdict(text: str, model: str = "") -> Verdict:
    """Read a ``{"reason": ..., "passed": ...}`` verdict out of a model's answer."""
    candidates = [text.strip()]
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except ValueError:
            continue
        if not isinstance(data, dict) or "passed" not in data:
            continue
        passed = data["passed"]
        if isinstance(passed, str) and passed.strip().lower() in {"true", "false"}:
            passed = passed.strip().lower() == "true"
        if not isinstance(passed, bool):
            continue
        reason = " ".join(str(data.get("reason", "")).split()) or "(no reason given)"
        return Verdict(passed=passed, reason=reason, model=model)
    raise JudgeError(f"the judge's answer wasn't a usable verdict: {text.strip()[:200]!r}")
