"""Scenario models: the pydantic schema for one scenario file."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from wa_agent_test.assertions import Assertion, parse_check


class Defaults(BaseModel):
    """Settings applied to every turn unless the turn overrides them."""

    model_config = ConfigDict(extra="forbid")

    timeout_s: float = Field(30.0, gt=0, description="give up waiting for the bot after this long")
    settle_ms: int = Field(500, ge=0, description="the bot counts as 'done' after this much quiet")
    allow_rejected: bool = Field(
        False, description="don't fail turns where the mock rejected a send"
    )


class ImageSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    caption: str | None = None


class Turn(BaseModel):
    """One thing the simulated user does, plus what to expect back.

    Exactly one of ``say``, ``tap_button``, ``pick_row``, ``send_image``.
    """

    model_config = ConfigDict(extra="forbid")

    say: str | None = None
    tap_button: str | None = None
    pick_row: str | None = None
    send_image: ImageSpec | None = None

    expect_messages: int | None = Field(None, ge=0)
    timeout_s: float | None = Field(None, gt=0)
    settle_ms: int | None = Field(None, ge=0)
    allow_rejected: bool | None = None
    expect: list[Assertion] = []

    @model_validator(mode="before")
    @classmethod
    def _bare_send_image(cls, data: Any) -> Any:
        # `send_image:` with no value means "an image with no caption"
        if isinstance(data, dict) and "send_image" in data and data["send_image"] is None:
            return {**data, "send_image": {}}
        return data

    @field_validator("expect", mode="before")
    @classmethod
    def _parse_checks(cls, value: Any) -> Any:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("expect must be a list of checks")
        parsed: list[Assertion] = []
        for i, item in enumerate(value):
            try:
                parsed.append(parse_check(item))
            except ValueError as exc:
                raise ValueError(f"expect[{i}]: {exc}") from exc
        return parsed

    @model_validator(mode="after")
    def _exactly_one_action(self) -> Turn:
        actions = [
            name
            for name in ("say", "tap_button", "pick_row", "send_image")
            if getattr(self, name) is not None
        ]
        if len(actions) != 1:
            found = ", ".join(actions) if actions else "none"
            raise ValueError(
                "each turn needs exactly one of say / tap_button / pick_row / send_image "
                f"(found: {found})"
            )
        return self

    @property
    def action_kind(self) -> str:
        return next(
            n
            for n in ("say", "tap_button", "pick_row", "send_image")
            if getattr(self, n) is not None
        )

    @property
    def label(self) -> str:
        kind = self.action_kind
        if kind == "send_image":
            caption = self.send_image.caption if self.send_image else None
            return f"send_image: {caption!r}" if caption else "send_image"
        return f"{kind}: {getattr(self, kind)!r}"


class Scenario(BaseModel):
    """A whole conversation: turns run in order, as one simulated user."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    description: str | None = None
    tags: list[str] = []
    defaults: Defaults = Defaults()
    turns: list[Turn] = Field(min_length=1)
    source_file: str | None = Field(default=None, exclude=True)  # set by the loader

    def timeout_for(self, turn: Turn) -> float:
        return turn.timeout_s if turn.timeout_s is not None else self.defaults.timeout_s

    def settle_ms_for(self, turn: Turn) -> int:
        return turn.settle_ms if turn.settle_ms is not None else self.defaults.settle_ms

    def allow_rejected_for(self, turn: Turn) -> bool:
        if turn.allow_rejected is not None:
            return turn.allow_rejected
        return self.defaults.allow_rejected
