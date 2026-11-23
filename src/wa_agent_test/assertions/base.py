"""Shared types for assertions: bot messages, results, scopes and the Assertion base class."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict

from wa_agent_test.truth import TruthSource

Scope = Literal["all", "first", "last"] | int


class Button(BaseModel):
    id: str
    title: str


class Row(BaseModel):
    id: str
    title: str
    description: str | None = None


class BotMessage(BaseModel):
    """One message the bot sent to the simulated user, flattened for checking and reports."""

    message_id: str
    type: str
    text: str
    buttons: list[Button] = []
    rows: list[Row] = []
    latency_ms: float
    raw: dict[str, Any]


class CheckResult(BaseModel):
    kind: str
    passed: bool
    message: str


@dataclass(frozen=True)
class TurnContext:
    """What a check sees: the bot's (accepted) messages for one turn, and the truth sources."""

    messages: list[BotMessage]
    truth: Mapping[str, TruthSource]


class ScopeError(Exception):
    """The requested message (``in:``) doesn't exist."""


def select(messages: list[BotMessage], scope: Scope) -> list[BotMessage]:
    if scope == "all":
        return messages
    if not messages:
        raise ScopeError("the bot sent no message")
    if scope == "first":
        return [messages[0]]
    if scope == "last":
        return [messages[-1]]
    index = int(scope)
    if not -len(messages) <= index < len(messages):
        raise ScopeError(f"the bot sent {len(messages)} message(s); there is no message at {index}")
    return [messages[index]]


def excerpt(text: str, limit: int = 160) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


class Assertion(BaseModel):
    """Base class for checks. ``scope`` is the YAML ``in:`` key (which bot messages to look at)."""

    model_config = ConfigDict(extra="forbid")

    kind: ClassVar[str]
    scope: Scope = "all"

    def check(self, selected: list[BotMessage], ctx: TurnContext) -> tuple[bool, str]:
        raise NotImplementedError

    def evaluate(self, ctx: TurnContext) -> CheckResult:
        try:
            selected = select(ctx.messages, self.scope)
        except ScopeError as exc:
            return CheckResult(kind=self.kind, passed=False, message=str(exc))
        passed, message = self.check(selected, ctx)
        return CheckResult(kind=self.kind, passed=passed, message=message)
