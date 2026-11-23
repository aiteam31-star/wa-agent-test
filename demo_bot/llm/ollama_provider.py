"""Local Ollama provider (``/api/chat`` with tool calling)."""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx

from demo_bot.llm.base import LLMResponse, Message, ToolCall


def to_ollama_messages(system: str, messages: list[Message]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for m in messages:
        role = m["role"]
        if role == "user":
            out.append({"role": "user", "content": m["content"]})
        elif role == "assistant":
            msg: dict[str, Any] = {"role": "assistant", "content": m.get("content", "")}
            if m.get("tool_calls"):
                msg["tool_calls"] = [
                    {"function": {"name": c["name"], "arguments": c["arguments"]}}
                    for c in m["tool_calls"]
                ]
            out.append(msg)
        elif role == "tool":
            out.append({"role": "tool", "tool_name": m["name"], "content": m["content"]})
    return out


def to_ollama_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in tools
    ]


class OllamaProvider:
    def __init__(
        self,
        *,
        model: str,
        client: httpx.AsyncClient,
        base_url: str = "http://localhost:11434",
    ) -> None:
        self._model = model
        self._client = client
        self._base_url = base_url.rstrip("/")

    async def complete(
        self, system: str, messages: list[Message], tools: list[dict[str, Any]]
    ) -> LLMResponse:
        response = await self._client.post(
            f"{self._base_url}/api/chat",
            json={
                "model": self._model,
                "messages": to_ollama_messages(system, messages),
                "tools": to_ollama_tools(tools),
                "stream": False,
                "options": {"temperature": 0},
            },
        )
        response.raise_for_status()
        message = response.json().get("message", {})
        calls: list[ToolCall] = []
        for raw in message.get("tool_calls") or []:
            function = raw["function"]
            arguments = function.get("arguments") or {}
            if isinstance(arguments, str):  # some models return JSON text
                arguments = json.loads(arguments)
            calls.append(ToolCall(f"call_{uuid.uuid4().hex[:12]}", function["name"], arguments))
        return LLMResponse(text=(message.get("content") or "").strip(), tool_calls=calls)
