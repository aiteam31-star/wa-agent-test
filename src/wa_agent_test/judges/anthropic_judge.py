"""A judge backed by the Anthropic Messages API (plain HTTP, no SDK needed)."""

from __future__ import annotations

import httpx

from wa_agent_test.judges.base import (
    SYSTEM_PROMPT,
    JudgeError,
    JudgeRequest,
    Verdict,
    build_user_prompt,
    parse_verdict,
)

ANTHROPIC_VERSION = "2023-06-01"


class AnthropicJudge:
    provider = "anthropic"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        client: httpx.AsyncClient,
        base_url: str = "https://api.anthropic.com",
    ) -> None:
        self.model = model
        self._api_key = api_key
        self._client = client
        self._base_url = base_url.rstrip("/")

    async def judge(self, request: JudgeRequest) -> Verdict:
        try:
            response = await self._client.post(
                f"{self._base_url}/v1/messages",
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": ANTHROPIC_VERSION,
                    "content-type": "application/json",
                },
                json={
                    "model": self.model,
                    "max_tokens": 300,
                    "temperature": 0,
                    "system": SYSTEM_PROMPT,
                    "messages": [{"role": "user", "content": build_user_prompt(request)}],
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise JudgeError(f"couldn't reach Anthropic ({type(exc).__name__}: {exc})") from exc
        blocks = response.json().get("content", [])
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        return parse_verdict(text, self.model)

    async def aclose(self) -> None:
        await self._client.aclose()
