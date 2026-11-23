"""Builders for realistic Meta WhatsApp Cloud API inbound webhook payloads.

Covers text, interactive replies, image and status payloads, plus X-Hub-Signature-256 signing.
"""

from wa_agent_test.payloads.builders import (
    build_button_reply,
    build_image,
    build_list_reply,
    build_status,
    build_text,
)
from wa_agent_test.payloads.entities import BusinessAccount, SimulatedUser, make_users
from wa_agent_test.payloads.ids import new_conversation_id, new_media_id, new_wamid
from wa_agent_test.payloads.signing import (
    SIGNATURE_HEADER,
    serialize_payload,
    sign_body,
    verify_signature,
)

__all__ = [
    "SIGNATURE_HEADER",
    "BusinessAccount",
    "SimulatedUser",
    "build_button_reply",
    "build_image",
    "build_list_reply",
    "build_status",
    "build_text",
    "make_users",
    "new_conversation_id",
    "new_media_id",
    "new_wamid",
    "serialize_payload",
    "sign_body",
    "verify_signature",
]
