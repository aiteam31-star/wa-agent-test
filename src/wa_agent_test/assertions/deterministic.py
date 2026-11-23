"""Deterministic checks on the bot's replies."""

from __future__ import annotations

import re
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, field_validator

from wa_agent_test.assertions.base import Assertion, BotMessage, TurnContext, excerpt


def _joined(messages: list[BotMessage]) -> str:
    return "\n".join(m.text for m in messages)


def _as_list(value: str | list[str]) -> list[str]:
    return [value] if isinstance(value, str) else value


class Contains(Assertion):
    """Every given text appears in the reply (case-insensitive)."""

    kind: ClassVar[str] = "contains"
    value: str | list[str]

    def check(self, selected: list[BotMessage], ctx: TurnContext) -> tuple[bool, str]:
        text = _joined(selected)
        missing = [s for s in _as_list(self.value) if s.lower() not in text.lower()]
        if missing:
            return False, f"reply is missing {missing!r}; it said: {excerpt(text)!r}"
        return True, f"reply contains {_as_list(self.value)!r}"


class NotContains(Assertion):
    """None of the given texts appears in the reply (case-insensitive)."""

    kind: ClassVar[str] = "not_contains"
    value: str | list[str]

    def check(self, selected: list[BotMessage], ctx: TurnContext) -> tuple[bool, str]:
        text = _joined(selected)
        found = [s for s in _as_list(self.value) if s.lower() in text.lower()]
        if found:
            return False, f"reply must not contain {found!r} but it does: {excerpt(text)!r}"
        return True, f"reply avoids {_as_list(self.value)!r}"


class Equals(Assertion):
    """A single message's text equals the given text exactly (ignoring outer whitespace)."""

    kind: ClassVar[str] = "equals"
    value: str

    def check(self, selected: list[BotMessage], ctx: TurnContext) -> tuple[bool, str]:
        if len(selected) != 1:
            return (
                False,
                f"equals needs exactly one message, got {len(selected)} (use in: first/last)",
            )
        actual = selected[0].text.strip()
        if actual == self.value.strip():
            return True, "reply text is exactly as expected"
        return False, f"expected exactly {self.value!r} but got {excerpt(actual)!r}"


class Regex(Assertion):
    """The reply text matches the regular expression somewhere."""

    kind: ClassVar[str] = "regex"
    value: str

    @field_validator("value")
    @classmethod
    def _compiles(cls, v: str) -> str:
        try:
            re.compile(v)
        except re.error as exc:
            raise ValueError(f"invalid regular expression {v!r}: {exc}") from exc
        return v

    def check(self, selected: list[BotMessage], ctx: TurnContext) -> tuple[bool, str]:
        text = _joined(selected)
        if re.search(self.value, text):
            return True, f"reply matches /{self.value}/"
        return False, f"reply does not match /{self.value}/; it said: {excerpt(text)!r}"


class CountRange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min: int | None = None
    max: int | None = None


class MessageCount(Assertion):
    """The number of bot messages (an exact number, or ``{min:, max:}``)."""

    kind: ClassVar[str] = "message_count"
    value: int | CountRange

    def check(self, selected: list[BotMessage], ctx: TurnContext) -> tuple[bool, str]:
        n = len(selected)
        if isinstance(self.value, int):
            ok, want = n == self.value, f"exactly {self.value}"
        else:
            lo, hi = self.value.min, self.value.max
            ok = (lo is None or n >= lo) and (hi is None or n <= hi)
            want = f"between {lo if lo is not None else 0} and {hi if hi is not None else 'any'}"
        return ok, f"bot sent {n} message(s); expected {want}"


class MessageType(Assertion):
    """Every message is of this WhatsApp type (``text``, ``interactive``, ...)."""

    kind: ClassVar[str] = "message_type"
    value: str

    def check(self, selected: list[BotMessage], ctx: TurnContext) -> tuple[bool, str]:
        if not selected:
            return False, "the bot sent no message"
        wrong = sorted({m.type for m in selected if m.type != self.value})
        if wrong:
            return False, f"expected message type {self.value!r} but got {wrong}"
        return True, f"all messages are {self.value!r}"


class ButtonCount(Assertion):
    """The message with reply buttons has exactly this many."""

    kind: ClassVar[str] = "button_count"
    value: int

    def check(self, selected: list[BotMessage], ctx: TurnContext) -> tuple[bool, str]:
        with_buttons = [m for m in selected if m.buttons]
        if not with_buttons:
            return False, "no message with reply buttons was sent"
        counts = [len(m.buttons) for m in with_buttons]
        if all(c == self.value for c in counts):
            return True, f"{self.value} reply buttons"
        return False, f"expected {self.value} reply buttons but got {counts}"


class ButtonTitles(Assertion):
    """The reply buttons' titles, in order."""

    kind: ClassVar[str] = "button_titles"
    value: list[str]

    def check(self, selected: list[BotMessage], ctx: TurnContext) -> tuple[bool, str]:
        with_buttons = [m for m in selected if m.buttons]
        if not with_buttons:
            return False, "no message with reply buttons was sent"
        for m in with_buttons:
            titles = [b.title for b in m.buttons]
            if titles != self.value:
                return False, f"expected button titles {self.value} but got {titles}"
        return True, f"button titles are {self.value}"


class ReplyWithinMs(Assertion):
    """The first bot message arrived within this many milliseconds of the user's message."""

    kind: ClassVar[str] = "reply_within_ms"
    value: int

    def check(self, selected: list[BotMessage], ctx: TurnContext) -> tuple[bool, str]:
        if not ctx.messages:
            return False, "the bot sent no message"
        latency = ctx.messages[0].latency_ms
        return latency <= self.value, f"first reply took {latency:.0f} ms; limit {self.value} ms"
