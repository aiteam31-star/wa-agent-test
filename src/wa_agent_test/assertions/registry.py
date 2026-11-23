"""Maps the keys used in a scenario's ``expect:`` list to assertion classes."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from wa_agent_test.assertions.base import Assertion
from wa_agent_test.assertions.deterministic import (
    ButtonCount,
    ButtonTitles,
    Contains,
    Equals,
    MessageCount,
    MessageType,
    NotContains,
    Regex,
    ReplyWithinMs,
)
from wa_agent_test.assertions.facts import Fact

REGISTRY: dict[str, type[Assertion]] = {
    cls.kind: cls
    for cls in (
        Contains,
        NotContains,
        Equals,
        Regex,
        MessageCount,
        MessageType,
        ButtonCount,
        ButtonTitles,
        ReplyWithinMs,
        Fact,
    )
}


def parse_check(item: Any) -> Assertion:
    """Turn one ``expect:`` item (``{contains: "x"}``, optionally with ``in:``) into a check."""
    if isinstance(item, Assertion):
        return item
    if not isinstance(item, dict):
        raise ValueError("must be a mapping such as {contains: 'text'}")
    data = dict(item)
    scope = data.pop("in", "all")
    why = data.pop("why", None)
    if "judge" in data:
        raise ValueError("'judge' checks are not available yet (planned for a later stage)")
    if len(data) != 1:
        found = sorted(data) or "nothing"
        raise ValueError(f"needs exactly one check (plus optional 'in' and 'why'), found {found}")
    ((kind, value),) = data.items()
    cls = REGISTRY.get(str(kind))
    if cls is None:
        raise ValueError(f"unknown check {kind!r}; known checks: {', '.join(sorted(REGISTRY))}")
    try:
        return cls(value=value, scope=scope, why=why)  # type: ignore[call-arg]
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'] if p != 'value')}: {e['msg']}".lstrip(": ")
            for e in exc.errors()
        )
        raise ValueError(f"{kind}: {details}") from exc
