"""Request serialization and X-Hub-Signature-256 signing, as Meta does for webhooks."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

SIGNATURE_HEADER = "X-Hub-Signature-256"
_PREFIX = "sha256="


def serialize_payload(payload: dict[str, Any]) -> bytes:
    """Serialize a payload to the exact bytes that are sent and signed.

    Compact separators, and non-ASCII escaped as ``\\uXXXX`` (Meta signs the escaped form).
    """
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def sign_body(body: bytes, app_secret: str) -> str:
    """Return the ``X-Hub-Signature-256`` header value: ``sha256=`` + HMAC-SHA256 hex digest."""
    digest = hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return _PREFIX + digest


def verify_signature(body: bytes, header_value: str | None, app_secret: str) -> bool:
    """Constant-time check of a signature header against the raw body."""
    if not header_value or not header_value.startswith(_PREFIX):
        return False
    return hmac.compare_digest(sign_body(body, app_secret), header_value)
