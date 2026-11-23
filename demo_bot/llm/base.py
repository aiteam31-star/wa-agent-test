"""Provider-neutral LLM types.

Conversation messages are plain dicts:

* ``{"role": "user", "content": str}``
* ``{"role": "assistant", "content": str, "tool_calls": [{"id", "name", "arguments"}]}``
* ``{"role": "tool", "tool_call_id": str, "name": str, "content": str}`` (JSON string result)

Each provider converts these to its own wire format.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

Message = dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class LLMResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


class LLMProvider(Protocol):
    """Anything that can continue a conversation, optionally asking for tool calls."""

    async def complete(
        self, system: str, messages: list[Message], tools: list[dict[str, Any]]
    ) -> LLMResponse: ...
