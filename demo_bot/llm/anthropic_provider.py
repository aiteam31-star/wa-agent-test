"""Anthropic Messages API provider (plain httpx, no SDK needed)."""

from __future__ import annotations

from typing import Any

import httpx

from demo_bot.llm.base import LLMResponse, Message, ToolCall

ANTHROPIC_VERSION = "2023-06-01"


def to_anthropic_messages(messages: list[Message]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages:
        role = m["role"]
        if role == "user":
            out.append({"role": "user", "content": m["content"]})
        elif role == "assistant":
            blocks: list[dict[str, Any]] = []
            if m.get("content"):
                blocks.append({"type": "text", "text": m["content"]})
            for call in m.get("tool_calls", []):
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": call["id"],
                        "name": call["name"],
                        "input": call["arguments"],
                    }
                )
            out.append({"role": "assistant", "content": blocks})
        elif role == "tool":
            block = {
                "type": "tool_result",
                "tool_use_id": m["tool_call_id"],
                "content": m["content"],
            }
            previous = out[-1] if out else None
            if previous and previous["role"] == "user" and isinstance(previous["content"], list):
                previous["content"].append(block)  # parallel tool results share one user turn
            else:
                out.append({"role": "user", "content": [block]})
    return out


class AnthropicProvider:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        client: httpx.AsyncClient,
        base_url: str = "https://api.anthropic.com",
        max_tokens: int = 1024,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._max_tokens = max_tokens

    async def complete(
        self, system: str, messages: list[Message], tools: list[dict[str, Any]]
    ) -> LLMResponse:
        response = await self._client.post(
            f"{self._base_url}/v1/messages",
            headers={
                "x-api-key": self._api_key,
                "anthropic-version": ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
            json={
                "model": self._model,
                "max_tokens": self._max_tokens,
                "temperature": 0,
                "system": system,
                "messages": to_anthropic_messages(messages),
                "tools": tools,
            },
        )
        response.raise_for_status()
        text_parts: list[str] = []
        calls: list[ToolCall] = []
        for block in response.json().get("content", []):
            if block.get("type") == "text":
                text_parts.append(block["text"])
            elif block.get("type") == "tool_use":
                calls.append(ToolCall(block["id"], block["name"], block.get("input") or {}))
        return LLMResponse(text="".join(text_parts).strip(), tool_calls=calls)
