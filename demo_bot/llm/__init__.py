"""Pluggable LLM providers, chosen by the LLM_PROVIDER environment variable."""

from __future__ import annotations

import httpx

from demo_bot.config import Settings
from demo_bot.data import IPOStore
from demo_bot.llm.anthropic_provider import AnthropicProvider
from demo_bot.llm.base import LLMProvider, LLMResponse, Message, ToolCall
from demo_bot.llm.fake_provider import FakeProvider
from demo_bot.llm.ollama_provider import OllamaProvider


def create_provider(settings: Settings, store: IPOStore, client: httpx.AsyncClient) -> LLMProvider:
    """Build the provider named by ``settings.llm_provider`` (anthropic, ollama or fake)."""
    name = settings.llm_provider
    if name == "anthropic":
        if not settings.anthropic_api_key:
            raise ValueError("LLM_PROVIDER=anthropic requires ANTHROPIC_API_KEY")
        return AnthropicProvider(
            api_key=settings.anthropic_api_key,
            model=settings.anthropic_model,
            client=client,
            base_url=settings.anthropic_base_url,
        )
    if name == "ollama":
        return OllamaProvider(
            model=settings.ollama_model, client=client, base_url=settings.ollama_base_url
        )
    if name == "fake":
        return FakeProvider(store)
    raise ValueError(f"unknown LLM_PROVIDER {name!r}; use anthropic, ollama or fake")


__all__ = [
    "AnthropicProvider",
    "FakeProvider",
    "LLMProvider",
    "LLMResponse",
    "Message",
    "OllamaProvider",
    "ToolCall",
    "create_provider",
]
