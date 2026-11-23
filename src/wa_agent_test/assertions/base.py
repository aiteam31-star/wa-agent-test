"""Shared types for assertions: bot messages, results, scopes and the Assertion base class."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict

from wa_agent_test.judges import Judge
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
    """What a check sees: the turn's bot messages, the truth sources, and (for judges) the rest."""

    messages: list[BotMessage]
    truth: Mapping[str, TruthSource]
    user_message: str = ""  # what the simulated user said this turn
    judge: Judge | None = None  # set when the run has a judge configured


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
    why: str | None = None  # optional explanation shown when the check fails

    def check(self, selected: list[BotMessage], ctx: TurnContext) -> tuple[bool, str]:
        raise NotImplementedError

    async def acheck(self, selected: list[BotMessage], ctx: TurnContext) -> tuple[bool, str]:
        """Async form of :meth:`check`. Checks that call a judge override this one."""
        return self.check(selected, ctx)

    def _result(self, passed: bool, message: str) -> CheckResult:
        if not passed and self.why:
            message = f"{self.why} ({message})"
        return CheckResult(kind=self.kind, passed=passed, message=message)

    def evaluate(self, ctx: TurnContext) -> CheckResult:
        try:
            selected = select(ctx.messages, self.scope)
        except ScopeError as exc:
            return CheckResult(kind=self.kind, passed=False, message=str(exc))
        return self._result(*self.check(selected, ctx))

    async def aevaluate(self, ctx: TurnContext) -> CheckResult:
        """Like :meth:`evaluate`, but allowed to wait (the runner uses this one)."""
        try:
            selected = select(ctx.messages, self.scope)
        except ScopeError as exc:
            return CheckResult(kind=self.kind, passed=False, message=str(exc))
        return self._result(*await self.acheck(selected, ctx))
