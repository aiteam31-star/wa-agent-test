"""Declarative fact checks: compare a value claimed in the reply with a truth source.

The scenario names the entity and the field, and says how to find the claim (a regex and a
parser). If the claim can't be found the check FAILS; it never passes silently.
"""

from __future__ import annotations

import re
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, model_validator

from wa_agent_test.assertions.base import Assertion, BotMessage, TurnContext, excerpt
from wa_agent_test.assertions.parsers import PARSERS, show
from wa_agent_test.truth import TruthError


class Extract(BaseModel):
    """How to find the claimed value in the reply."""

    model_config = ConfigDict(extra="forbid")

    regex: str
    parser: Literal["date", "number", "currency", "text"] = "text"
    group: int = 1

    @model_validator(mode="after")
    def _regex_is_usable(self) -> Extract:
        try:
            compiled = re.compile(self.regex)
        except re.error as exc:
            raise ValueError(f"invalid regular expression {self.regex!r}: {exc}") from exc
        if compiled.groups == 0 and self.group == 1:
            self.group = 0  # no capture group: use the whole match
        if self.group > compiled.groups:
            raise ValueError(
                f"group {self.group} doesn't exist in {self.regex!r} (it has {compiled.groups})"
            )
        return self


class FactSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    entity: str
    field: str
    extract: Extract
    tolerance: float = 0.0  # numbers only


class Fact(Assertion):
    kind: ClassVar[str] = "fact"
    value: FactSpec

    def check(self, selected: list[BotMessage], ctx: TurnContext) -> tuple[bool, str]:
        spec = self.value
        human = spec.field.replace("_", " ")

        source = ctx.truth.get(spec.source)
        if source is None:
            known = ", ".join(sorted(ctx.truth)) or "none"
            return (
                False,
                f"truth source {spec.source!r} isn't defined in the config (defined: {known})",
            )
        try:
            truth_raw = source.lookup(spec.entity, spec.field)
        except TruthError as exc:
            return False, f"truth source {spec.source!r}: {exc}"
        if truth_raw is None:
            return False, f"truth source {spec.source!r} has no {human} for {spec.entity!r}"

        text = "\n".join(m.text for m in selected)
        matches = list(re.finditer(spec.extract.regex, text))
        if not matches:
            return False, (
                f"couldn't find a {human} in the reply "
                f"(pattern {spec.extract.regex!r} didn't match: {excerpt(text)!r})"
            )

        parse = PARSERS[spec.extract.parser]
        try:
            expected = parse(truth_raw)
        except ValueError as exc:
            return False, f"truth source {spec.source!r} value for {human} is unusable: {exc}"

        claims: list[Any] = []
        for match in matches:
            raw = match.group(spec.extract.group)
            if raw is None:
                return False, f"pattern matched but its group {spec.extract.group} was empty"
            try:
                claims.append(parse(raw))
            except ValueError:
                return (
                    False,
                    f"found {raw!r} for {human} but couldn't read it as a {spec.extract.parser}",
                )

        wrong = [c for c in claims if not _same(c, expected, spec.tolerance)]
        if wrong:
            shown = ", ".join(dict.fromkeys(show(c) for c in wrong))
            return False, (
                f"reply says {human} {shown} but {spec.source} says {show(expected)} "
                f"for {spec.entity}"
            )
        return True, f"{human} {show(claims[0])} matches {spec.source} for {spec.entity}"


def _same(claimed: Any, expected: Any, tolerance: float) -> bool:
    if isinstance(claimed, float) and isinstance(expected, float):
        return abs(claimed - expected) <= tolerance
    return bool(claimed == expected)
