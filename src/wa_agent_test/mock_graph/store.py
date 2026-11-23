"""Capture store: every outbound message the bot attempts, keyed by recipient wa_id."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from wa_agent_test.mock_graph.validation import Violation


@dataclass(frozen=True, slots=True)
class CapturedMessage:
    """One outbound message request received by the mock Graph API."""

    to: str  # normalized recipient wa_id ("" if the request had no usable `to`)
    phone_number_id: str
    api_version: str
    type: str | None
    payload: dict[str, Any] | None  # raw request body (None if it was not valid JSON)
    received_at: datetime  # UTC wall clock
    received_monotonic: float  # time.monotonic(), for latency maths
    message_id: str | None  # the fake wamid returned; None if rejected
    violations: tuple[Violation, ...] = ()

    @property
    def accepted(self) -> bool:
        return not self.violations


class CaptureStore:
    """In-memory, append-only record of outbound messages, accepted and rejected."""

    def __init__(self) -> None:
        self._messages: list[CapturedMessage] = []
        self._changed = asyncio.Event()

    def record(
        self,
        *,
        to: str,
        phone_number_id: str,
        api_version: str,
        payload: dict[str, Any] | None,
        message_id: str | None,
        violations: tuple[Violation, ...] = (),
    ) -> CapturedMessage:
        message_type = payload.get("type", "text") if isinstance(payload, dict) else None
        captured = CapturedMessage(
            to=to,
            phone_number_id=phone_number_id,
            api_version=api_version,
            type=message_type if isinstance(message_type, str) else None,
            payload=payload,
            received_at=datetime.now(UTC),
            received_monotonic=time.monotonic(),
            message_id=message_id,
            violations=violations,
        )
        self._messages.append(captured)
        previous, self._changed = self._changed, asyncio.Event()
        previous.set()
        return captured

    def all(self) -> list[CapturedMessage]:
        return list(self._messages)

    def messages_for(self, wa_id: str, *, include_rejected: bool = False) -> list[CapturedMessage]:
        """Messages sent to ``wa_id`` in arrival order (accepted only, unless asked)."""
        return [m for m in self._messages if m.to == wa_id and (include_rejected or m.accepted)]

    def rejected(self, wa_id: str | None = None) -> list[CapturedMessage]:
        return [m for m in self._messages if not m.accepted and (wa_id is None or m.to == wa_id)]

    def clear(self) -> None:
        self._messages.clear()

    async def wait_for_count(
        self,
        wa_id: str,
        count: int,
        *,
        timeout: float,  # noqa: ASYNC109 - deadline is enforced manually across wake-ups
        include_rejected: bool = False,
    ) -> list[CapturedMessage]:
        """Wait until at least ``count`` messages for ``wa_id`` exist; raise TimeoutError."""
        deadline = time.monotonic() + timeout
        while True:
            found = self.messages_for(wa_id, include_rejected=include_rejected)
            if len(found) >= count:
                return found
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"expected {count} message(s) for {wa_id}, got {len(found)}")
            try:
                await asyncio.wait_for(self._changed.wait(), remaining)
            except TimeoutError:
                continue  # loop re-checks and raises with an accurate count
