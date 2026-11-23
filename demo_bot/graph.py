"""Outbound client for the WhatsApp Cloud API (``POST /{version}/{phone_number_id}/messages``)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from demo_bot.agent import Button, Reply, Row

logger = logging.getLogger("demo_bot.graph")

TEXT_MAX = 4096


@dataclass(frozen=True)
class SendResult:
    ok: bool
    status_code: int | None
    detail: str = ""


class GraphClient:
    """Sends messages to ``base_url`` (Meta's Graph API, or the harness's mock)."""

    def __init__(
        self, *, base_url: str, version: str, access_token: str, client: httpx.AsyncClient
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._version = version
        self._token = access_token
        self._client = client

    async def send_reply(self, phone_number_id: str, to: str, reply: Reply) -> SendResult:
        if reply.kind == "buttons":
            return await self.send_buttons(phone_number_id, to, reply.text, reply.buttons)
        if reply.kind == "list":
            return await self.send_list(phone_number_id, to, reply.text, reply.rows)
        return await self.send_text(phone_number_id, to, reply.text)

    async def send_text(self, phone_number_id: str, to: str, text: str) -> SendResult:
        return await self._post(
            phone_number_id,
            {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "text",
                "text": {"body": text[:TEXT_MAX]},
            },
        )

    async def send_buttons(
        self, phone_number_id: str, to: str, body: str, buttons: list[Button]
    ) -> SendResult:
        return await self._post(
            phone_number_id,
            {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "interactive",
                "interactive": {
                    "type": "button",
                    "body": {"text": body},
                    "action": {
                        "buttons": [
                            {"type": "reply", "reply": {"id": b.id, "title": b.title}}
                            for b in buttons
                        ]
                    },
                },
            },
        )

    async def send_list(
        self, phone_number_id: str, to: str, body: str, rows: list[Row]
    ) -> SendResult:
        return await self._post(
            phone_number_id,
            {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "interactive",
                "interactive": {
                    "type": "list",
                    "body": {"text": body},
                    "action": {
                        "button": "View IPOs",
                        "sections": [
                            {
                                "title": "Open IPOs",
                                "rows": [
                                    {"id": r.id, "title": r.title, "description": r.description}
                                    for r in rows
                                ],
                            }
                        ],
                    },
                },
            },
        )

    async def _post(self, phone_number_id: str, body: dict[str, Any]) -> SendResult:
        url = f"{self._base_url}/{self._version}/{phone_number_id}/messages"
        try:
            response = await self._client.post(
                url, json=body, headers={"Authorization": f"Bearer {self._token}"}
            )
        except httpx.HTTPError as exc:
            logger.error("send to %s failed: %s", body.get("to"), exc)
            return SendResult(False, None, f"{type(exc).__name__}: {exc}")
        if response.status_code >= 400:
            logger.error(
                "send to %s rejected (%s): %s", body.get("to"), response.status_code, response.text
            )
            return SendResult(False, response.status_code, response.text)
        return SendResult(True, response.status_code)
