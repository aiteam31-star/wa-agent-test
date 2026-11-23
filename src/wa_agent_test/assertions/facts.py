"""Declarative fact checks: compare a value claimed in the reply with a truth source.

The scenario names the entity and the field, and says how to find the claim (a regex and a
parser). If the claim can't be found the check FAILS; it never passes silently.
"""

from __future__ import annotations

import re
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, model_validator

from wa_agent_test.assertions.base import Assertion, BotMessage, TurnContext, excerpt
from wa_agent_test.assertions.parsers import PARSERS, find_dates, parse_date, show
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


class KnownDatesSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    fields: list[str]  # truth fields whose values (across all records) are the allowed dates


class KnownDates(Assertion):
    """Every date written in the reply must be a real date from the data.

    This catches *invented* dates (a bot that makes up "opened on 29 Sep 2022") without needing
    to know which IPO each date belongs to, and without failing a reply that gives no dates.
    A reply with no dates passes, and the result says so. It does not catch a real date attached
    to the wrong thing (a closing date given as an opening date); use ``fact:`` for that.
    """

    kind: ClassVar[str] = "known_dates"
    value: KnownDatesSpec

    def check(self, selected: list[BotMessage], ctx: TurnContext) -> tuple[bool, str]:
        spec = self.value
        source = ctx.truth.get(spec.source)
        if source is None:
            known = ", ".join(sorted(ctx.truth)) or "none"
            return False, f"truth source {spec.source!r} isn't defined (defined: {known})"
        values = getattr(source, "values", None)
        if values is None:
            return False, f"truth source {spec.source!r} can't list all values of a field"
        allowed: set[Any] = set()
        for field in spec.fields:
            for raw in values(field):
                try:
                    allowed.add(parse_date(raw))
                except ValueError:
                    return False, f"truth source {spec.source!r}: {raw!r} ({field}) isn't a date"
        if not allowed:
            return False, f"truth source {spec.source!r} has no dates for {', '.join(spec.fields)}"

        text = "\n".join(m.text for m in selected)
        found = find_dates(text)
        if not found:
            return True, "the reply states no dates, so none are invented"
        invented = [raw for raw, parsed in found if parsed not in allowed]
        if invented:
            shown = ", ".join(dict.fromkeys(invented))
            return False, (
                f"reply contains date(s) that aren't in the data ({spec.source}): {shown}; "
                f"{len(found) - len(invented)} of {len(found)} date(s) were real"
            )
        return True, f"all {len(found)} date(s) in the reply appear in the data ({spec.source})"
