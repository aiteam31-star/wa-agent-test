"""A judge backed by a local Ollama model (free, private, the default)."""

from __future__ import annotations

import httpx

from wa_agent_test.judges.base import (
    SYSTEM_PROMPT,
    VERDICT_SCHEMA,
    JudgeError,
    JudgeRequest,
    Verdict,
    build_user_prompt,
    parse_verdict,
)


class OllamaJudge:
    provider = "ollama"

    def __init__(
        self,
        *,
        model: str,
        client: httpx.AsyncClient,
        base_url: str = "http://localhost:11434",
    ) -> None:
        self.model = model
        self._client = client
        self._base_url = base_url.rstrip("/")

    async def judge(self, request: JudgeRequest) -> Verdict:
        try:
            response = await self._client.post(
                f"{self._base_url}/api/chat",
                json={
                    "model": self.model,
                    "stream": False,
                    "format": VERDICT_SCHEMA,  # makes Ollama answer with valid JSON of this shape
                    "options": {"temperature": 0},
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": build_user_prompt(request)},
                    ],
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise JudgeError(f"couldn't reach Ollama ({type(exc).__name__}: {exc})") from exc
        content = str(response.json().get("message", {}).get("content", ""))
        return parse_verdict(content, self.model)

    async def aclose(self) -> None:
        await self._client.aclose()
