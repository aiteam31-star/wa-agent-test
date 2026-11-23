"""FastAPI app mimicking the WhatsApp Cloud API ``POST /{version}/{phone_number_id}/messages``."""

from __future__ import annotations

import json
import logging
import re
import secrets
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from wa_agent_test.mock_graph.limits import Limits, load_limits
from wa_agent_test.mock_graph.store import CaptureStore
from wa_agent_test.mock_graph.validation import Violation, normalize_wa_id, validate_message
from wa_agent_test.payloads.ids import new_wamid

logger = logging.getLogger("wa_agent_test.mock_graph")

_VERSION_RE = re.compile(r"^v\d+(\.\d+)?$")


def _fbtrace_id() -> str:
    return secrets.token_urlsafe(12).replace("-", "A").replace("_", "B")


def _error(status: int, message: str, code: int, details: str, error_type: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "message": message,
                "type": error_type,
                "code": code,
                "error_data": {"messaging_product": "whatsapp", "details": details},
                "fbtrace_id": _fbtrace_id(),
            }
        },
    )


def create_app(
    *,
    store: CaptureStore | None = None,
    limits: Limits | None = None,
    access_token: str | None = None,
) -> FastAPI:
    """Create the mock Graph API.

    ``store`` receives every message request (accepted and rejected); ``limits`` defaults to
    the packaged ``limits.yaml``. If ``access_token`` is set, requests must carry
    ``Authorization: Bearer <token>``.

    Error bodies follow Meta's ``{"error": {...}}`` shape. The exact error codes/messages are an
    approximation (code 100 for invalid parameters); they are not copied from Meta's docs.
    """
    app = FastAPI(title="wa-agent-test mock Graph API", docs_url=None, redoc_url=None)
    app.state.store = store if store is not None else CaptureStore()
    app.state.limits = limits if limits is not None else load_limits()
    app.state.access_token = access_token

    @app.post("/{version}/{phone_number_id}/messages")
    async def send_message(version: str, phone_number_id: str, request: Request) -> JSONResponse:
        capture: CaptureStore = app.state.store

        if not _VERSION_RE.match(version):
            return _error(
                400,
                "Unknown path components",
                2500,
                f"unsupported API version {version!r}",
                "GraphMethodException",
            )

        if app.state.access_token is not None:
            expected = f"Bearer {app.state.access_token}"
            if request.headers.get("authorization") != expected:
                logger.warning(
                    "rejected request to %s: bad or missing access token", phone_number_id
                )
                return _error(
                    401,
                    "Invalid OAuth access token - Cannot parse access token",
                    190,
                    "Invalid or missing Authorization bearer token",
                    "OAuthException",
                )

        raw = await request.body()
        payload: dict[str, Any] | None
        violations: list[Violation]
        try:
            parsed = json.loads(raw)
        except ValueError:
            payload, violations = (
                None,
                [Violation("invalid", "$", "request body is not valid JSON")],
            )
        else:
            payload = parsed if isinstance(parsed, dict) else None
            violations = validate_message(parsed, app.state.limits)

        to = normalize_wa_id(payload.get("to")) if payload is not None else None
        recipient = to or ""

        if violations:
            capture.record(
                to=recipient,
                phone_number_id=phone_number_id,
                api_version=version,
                payload=payload,
                message_id=None,
                violations=tuple(violations),
            )
            reasons = "; ".join(str(v) for v in violations)
            logger.warning("rejected message to %r: %s", recipient or "<unknown>", reasons)
            first = violations[0]
            return _error(
                400,
                f"(#100) Param {first.path} {first.message}",
                100,
                reasons,
                "OAuthException",
            )

        message_id = new_wamid()
        capture.record(
            to=recipient,
            phone_number_id=phone_number_id,
            api_version=version,
            payload=payload,
            message_id=message_id,
        )
        assert payload is not None
        return JSONResponse(
            {
                "messaging_product": "whatsapp",
                "contacts": [{"input": payload["to"], "wa_id": recipient}],
                "messages": [{"id": message_id}],
            }
        )

    return app
