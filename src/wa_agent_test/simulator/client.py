"""Webhook simulator: delivers signed inbound payloads to a bot's webhook URL."""

from __future__ import annotations

import time
from dataclasses import dataclass
from types import TracebackType
from typing import Any

import httpx

from wa_agent_test.payloads import (
    SIGNATURE_HEADER,
    BusinessAccount,
    SimulatedUser,
    build_button_reply,
    build_image,
    build_list_reply,
    build_status,
    build_text,
    serialize_payload,
    sign_body,
)
from wa_agent_test.payloads.builders import PricingFormat, StatusName


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    """Outcome of one webhook delivery."""

    payload: dict[str, Any]
    body: bytes  # the exact bytes sent (and signed)
    signature: str
    message_id: str | None  # id of the inbound message (None for status updates)
    status_code: int | None  # None if the request failed before a response
    response_text: str
    latency_ms: float
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.status_code is not None and 200 <= self.status_code < 300


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """Outcome of the GET ``hub.challenge`` verification handshake."""

    ok: bool
    status_code: int | None
    response_text: str
    challenge: str
    error: str | None = None


class WebhookSimulator:
    """Plays Meta: sends signed webhooks to ``webhook_url`` on behalf of simulated users.

    Safe to use concurrently from many tasks (e.g. one per simulated user).
    """

    def __init__(
        self,
        webhook_url: str,
        *,
        app_secret: str,
        business: BusinessAccount | None = None,
        timeout_s: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.webhook_url = webhook_url
        self.app_secret = app_secret
        self.business = business or BusinessAccount()
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout_s)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> WebhookSimulator:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    # --- delivery ------------------------------------------------------------------------

    async def send_payload(
        self, payload: dict[str, Any], *, message_id: str | None = None
    ) -> DeliveryResult:
        """Serialize, sign and POST an arbitrary payload."""
        body = serialize_payload(payload)
        signature = sign_body(body, self.app_secret)
        headers = {"Content-Type": "application/json", SIGNATURE_HEADER: signature}
        start = time.perf_counter()
        try:
            response = await self._client.post(self.webhook_url, content=body, headers=headers)
        except httpx.HTTPError as exc:
            return DeliveryResult(
                payload=payload,
                body=body,
                signature=signature,
                message_id=message_id,
                status_code=None,
                response_text="",
                latency_ms=(time.perf_counter() - start) * 1000,
                error=f"{type(exc).__name__}: {exc}",
            )
        return DeliveryResult(
            payload=payload,
            body=body,
            signature=signature,
            message_id=message_id,
            status_code=response.status_code,
            response_text=response.text,
            latency_ms=(time.perf_counter() - start) * 1000,
        )

    async def verify(self, verify_token: str, challenge: str = "1158201444") -> VerificationResult:
        """Do Meta's GET verification handshake; ok if the bot echoes ``challenge`` with 200."""
        params = {
            "hub.mode": "subscribe",
            "hub.verify_token": verify_token,
            "hub.challenge": challenge,
        }
        try:
            response = await self._client.get(self.webhook_url, params=params)
        except httpx.HTTPError as exc:
            return VerificationResult(False, None, "", challenge, f"{type(exc).__name__}: {exc}")
        ok = response.status_code == 200 and response.text.strip() == challenge
        return VerificationResult(ok, response.status_code, response.text, challenge)

    # --- convenience senders -------------------------------------------------------------

    async def send_text(
        self,
        user: SimulatedUser,
        body: str,
        *,
        context_message_id: str | None = None,
    ) -> DeliveryResult:
        payload = build_text(self.business, user, body, context_message_id=context_message_id)
        return await self.send_payload(payload, message_id=_message_id(payload))

    async def send_button_reply(
        self,
        user: SimulatedUser,
        button_id: str,
        title: str,
        *,
        context_message_id: str | None = None,
    ) -> DeliveryResult:
        payload = build_button_reply(
            self.business, user, button_id, title, context_message_id=context_message_id
        )
        return await self.send_payload(payload, message_id=_message_id(payload))

    async def send_list_reply(
        self,
        user: SimulatedUser,
        row_id: str,
        title: str,
        description: str | None = None,
        *,
        context_message_id: str | None = None,
    ) -> DeliveryResult:
        payload = build_list_reply(
            self.business,
            user,
            row_id,
            title,
            description,
            context_message_id=context_message_id,
        )
        return await self.send_payload(payload, message_id=_message_id(payload))

    async def send_image(
        self,
        user: SimulatedUser,
        *,
        media_id: str | None = None,
        caption: str | None = None,
    ) -> DeliveryResult:
        payload = build_image(self.business, user, media_id=media_id, caption=caption)
        return await self.send_payload(payload, message_id=_message_id(payload))

    async def send_status(
        self,
        user: SimulatedUser,
        message_id: str,
        status: StatusName,
        *,
        pricing_format: PricingFormat = "pmp",
    ) -> DeliveryResult:
        payload = build_status(
            self.business, user, message_id, status, pricing_format=pricing_format
        )
        return await self.send_payload(payload)


def _message_id(payload: dict[str, Any]) -> str:
    message_id: str = payload["entry"][0]["changes"][0]["value"]["messages"][0]["id"]
    return message_id
