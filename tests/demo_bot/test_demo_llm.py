"""Anthropic and Ollama providers (HTTP mocked with respx) and the provider factory."""

import json
from typing import Any

import httpx
import pytest
import respx

from demo_bot.agent import Agent
from demo_bot.config import DEFAULT_DATA_PATH, Settings
from demo_bot.data import IPOStore
from demo_bot.llm import (
    AnthropicProvider,
    FakeProvider,
    OllamaProvider,
    create_provider,
)
from demo_bot.llm.anthropic_provider import to_anthropic_messages
from demo_bot.llm.ollama_provider import to_ollama_messages, to_ollama_tools
from demo_bot.tools import TOOL_SPECS

TOOL_CALL_MSG: dict[str, Any] = {
    "role": "assistant",
    "content": "",
    "tool_calls": [
        {"id": "t1", "name": "list_open_ipos", "arguments": {}},
        {"id": "t2", "name": "get_ipo_details", "arguments": {"name": "nova"}},
    ],
}
CONVERSATION: list[dict[str, Any]] = [
    {"role": "user", "content": "open ipos?"},
    TOOL_CALL_MSG,
    {"role": "tool", "tool_call_id": "t1", "name": "list_open_ipos", "content": "{}"},
    {"role": "tool", "tool_call_id": "t2", "name": "get_ipo_details", "content": "{}"},
]


def test_anthropic_conversion_merges_parallel_tool_results() -> None:
    out = to_anthropic_messages(CONVERSATION)
    assert out[0] == {"role": "user", "content": "open ipos?"}
    assert [b["type"] for b in out[1]["content"]] == ["tool_use", "tool_use"]
    assert out[1]["content"][1] == {
        "type": "tool_use",
        "id": "t2",
        "name": "get_ipo_details",
        "input": {"name": "nova"},
    }
    assert len(out) == 3 and out[2]["role"] == "user"
    assert [b["tool_use_id"] for b in out[2]["content"]] == ["t1", "t2"]


def test_ollama_conversion() -> None:
    out = to_ollama_messages("be nice", CONVERSATION)
    assert out[0] == {"role": "system", "content": "be nice"}
    assert out[2]["tool_calls"][1] == {
        "function": {"name": "get_ipo_details", "arguments": {"name": "nova"}}
    }
    assert out[3] == {"role": "tool", "tool_name": "list_open_ipos", "content": "{}"}
    tools = to_ollama_tools(TOOL_SPECS)
    assert tools[1]["type"] == "function"
    assert tools[1]["function"]["parameters"]["required"] == ["name"]


@respx.mock
async def test_anthropic_request_and_response_parsing() -> None:
    route = respx.post("https://api.anthropic.com/v1/messages").respond(
        json={
            "content": [
                {"type": "text", "text": "Checking."},
                {
                    "type": "tool_use",
                    "id": "tu1",
                    "name": "get_ipo_details",
                    "input": {"name": "x"},
                },
            ]
        }
    )
    async with httpx.AsyncClient() as client:
        provider = AnthropicProvider(api_key="sk-test", model="m1", client=client)
        response = await provider.complete("sys", [{"role": "user", "content": "hi"}], TOOL_SPECS)
    assert response.text == "Checking."
    assert [(c.id, c.name, c.arguments) for c in response.tool_calls] == [
        ("tu1", "get_ipo_details", {"name": "x"})
    ]
    request = route.calls.last.request
    assert request.headers["x-api-key"] == "sk-test"
    assert request.headers["anthropic-version"] == "2023-06-01"
    body = json.loads(request.content)
    assert body["model"] == "m1" and body["system"] == "sys" and body["temperature"] == 0
    assert [t["name"] for t in body["tools"]] == [t["name"] for t in TOOL_SPECS]
    assert body["messages"] == [{"role": "user", "content": "hi"}]


@respx.mock
async def test_anthropic_http_error_raises() -> None:
    respx.post("https://api.anthropic.com/v1/messages").respond(500)
    async with httpx.AsyncClient() as client:
        provider = AnthropicProvider(api_key="k", model="m", client=client)
        with pytest.raises(httpx.HTTPStatusError):
            await provider.complete("s", [{"role": "user", "content": "hi"}], [])


@respx.mock
async def test_ollama_request_and_response_parsing() -> None:
    route = respx.post("http://localhost:11434/api/chat").respond(
        json={
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"function": {"name": "list_open_ipos", "arguments": {}}},
                    {"function": {"name": "get_ipo_details", "arguments": '{"name": "nova"}'}},
                ],
            }
        }
    )
    async with httpx.AsyncClient() as client:
        provider = OllamaProvider(model="llama3.1", client=client)
        response = await provider.complete("sys", [{"role": "user", "content": "hi"}], TOOL_SPECS)
    assert [c.name for c in response.tool_calls] == ["list_open_ipos", "get_ipo_details"]
    assert response.tool_calls[1].arguments == {"name": "nova"}  # JSON-string args are decoded
    assert len({c.id for c in response.tool_calls}) == 2
    body = json.loads(route.calls.last.request.content)
    assert body["model"] == "llama3.1" and body["stream"] is False
    assert body["messages"][0] == {"role": "system", "content": "sys"}


@respx.mock
async def test_agent_runs_full_tool_loop_over_anthropic() -> None:
    route = respx.post("https://api.anthropic.com/v1/messages").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "tu1",
                            "name": "get_ipo_details",
                            "input": {"name": "Nova Textiles"},
                        }
                    ]
                },
            ),
            httpx.Response(200, json={"content": [{"type": "text", "text": "Lists on 30 Nov."}]}),
        ]
    )
    store = IPOStore.load(DEFAULT_DATA_PATH)
    async with httpx.AsyncClient() as client:
        provider = AnthropicProvider(api_key="k", model="m", client=client)
        reply = await Agent(provider=provider, store=store).handle("u1", "Nova listing?")
    assert reply.text == "Lists on 30 Nov." and reply.kind == "buttons"
    assert route.call_count == 2
    second = json.loads(route.calls[1].request.content)["messages"]
    assert [m["role"] for m in second] == ["user", "assistant", "user"]
    result_block = second[2]["content"][0]
    assert result_block["type"] == "tool_result" and result_block["tool_use_id"] == "tu1"
    assert json.loads(result_block["content"])["ipo"]["dates"]["listing"] == "2026-11-30"


async def test_provider_factory() -> None:
    store = IPOStore.load(DEFAULT_DATA_PATH)
    async with httpx.AsyncClient() as client:
        assert isinstance(create_provider(Settings(), store, client), FakeProvider)
        anthropic = Settings(llm_provider="anthropic", anthropic_api_key="k")
        assert isinstance(create_provider(anthropic, store, client), AnthropicProvider)
        assert isinstance(
            create_provider(Settings(llm_provider="ollama"), store, client), OllamaProvider
        )
        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
            create_provider(Settings(llm_provider="anthropic"), store, client)
        with pytest.raises(ValueError, match="unknown LLM_PROVIDER"):
            create_provider(Settings(llm_provider="gpt"), store, client)
