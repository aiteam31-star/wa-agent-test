"""Builders for inbound webhook payloads in the WhatsApp Cloud API format.

Every builder returns a plain JSON-serializable dict::

    {"object": "whatsapp_business_account",
     "entry": [{"id": <waba_id>,
                "changes": [{"field": "messages", "value": {...}}]}]}

Message webhooks put ``messaging_product``, ``metadata``, ``contacts`` and ``messages`` in
``value``; status webhooks put ``metadata`` and ``statuses`` there (no contacts/messages).

Note: the ``conversation`` / ``pricing`` objects on status webhooks changed with Meta's 2025
per-message pricing; ``build_status`` supports the current and the legacy shape. What is and
isn't confirmed is recorded in ``docs/meta-format-notes.yaml``.
"""

from __future__ import annotations

import base64
import hashlib
import time
from typing import Any, Literal

from wa_agent_test.payloads.entities import BusinessAccount, SimulatedUser
from wa_agent_test.payloads.ids import new_conversation_id, new_media_id, new_wamid

StatusName = Literal["sent", "delivered", "read"]
PricingFormat = Literal["pmp", "cbp"]
Payload = dict[str, Any]

_SECONDS_IN_DAY = 24 * 60 * 60


def _now() -> int:
    return int(time.time())


def _envelope(business: BusinessAccount, value: dict[str, Any]) -> Payload:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": business.waba_id,
                "changes": [{"value": value, "field": "messages"}],
            }
        ],
    }


def _base_value(business: BusinessAccount) -> dict[str, Any]:
    return {
        "messaging_product": "whatsapp",
        "metadata": {
            "display_phone_number": business.display_phone_number,
            "phone_number_id": business.phone_number_id,
        },
    }


def _message_payload(
    business: BusinessAccount,
    user: SimulatedUser,
    message_type: str,
    content: dict[str, Any],
    *,
    message_id: str | None,
    timestamp: int | None,
    context_message_id: str | None,
) -> Payload:
    message: dict[str, Any] = {}
    if context_message_id is not None:
        message["context"] = {"from": business.display_phone_number, "id": context_message_id}
    message["from"] = user.wa_id
    message["id"] = message_id or new_wamid()
    message["timestamp"] = str(timestamp if timestamp is not None else _now())
    message["type"] = message_type
    message.update(content)

    value = _base_value(business)
    value["contacts"] = [{"profile": {"name": user.profile_name}, "wa_id": user.wa_id}]
    value["messages"] = [message]
    return _envelope(business, value)


def build_text(
    business: BusinessAccount,
    user: SimulatedUser,
    body: str,
    *,
    message_id: str | None = None,
    timestamp: int | None = None,
    context_message_id: str | None = None,
) -> Payload:
    """Inbound text message."""
    return _message_payload(
        business,
        user,
        "text",
        {"text": {"body": body}},
        message_id=message_id,
        timestamp=timestamp,
        context_message_id=context_message_id,
    )


def build_button_reply(
    business: BusinessAccount,
    user: SimulatedUser,
    button_id: str,
    title: str,
    *,
    context_message_id: str | None = None,
    message_id: str | None = None,
    timestamp: int | None = None,
) -> Payload:
    """The user tapped a reply button. ``context_message_id`` is the bot message it was on."""
    return _message_payload(
        business,
        user,
        "interactive",
        {
            "interactive": {
                "type": "button_reply",
                "button_reply": {"id": button_id, "title": title},
            }
        },
        message_id=message_id,
        timestamp=timestamp,
        context_message_id=context_message_id,
    )


def build_list_reply(
    business: BusinessAccount,
    user: SimulatedUser,
    row_id: str,
    title: str,
    description: str | None = None,
    *,
    context_message_id: str | None = None,
    message_id: str | None = None,
    timestamp: int | None = None,
) -> Payload:
    """The user picked a row from a list message."""
    reply: dict[str, Any] = {"id": row_id, "title": title}
    if description is not None:
        reply["description"] = description
    return _message_payload(
        business,
        user,
        "interactive",
        {"interactive": {"type": "list_reply", "list_reply": reply}},
        message_id=message_id,
        timestamp=timestamp,
        context_message_id=context_message_id,
    )


def build_image(
    business: BusinessAccount,
    user: SimulatedUser,
    *,
    media_id: str | None = None,
    caption: str | None = None,
    mime_type: str = "image/jpeg",
    sha256: str | None = None,
    message_id: str | None = None,
    timestamp: int | None = None,
    context_message_id: str | None = None,
) -> Payload:
    """Inbound image. The bytes are not included: like Meta, only a media id is sent."""
    media_id = media_id or new_media_id()
    image: dict[str, Any] = {}
    if caption is not None:
        image["caption"] = caption
    image["mime_type"] = mime_type
    image["sha256"] = (
        sha256 or base64.b64encode(hashlib.sha256(media_id.encode()).digest()).decode()
    )
    image["id"] = media_id
    return _message_payload(
        business,
        user,
        "image",
        {"image": image},
        message_id=message_id,
        timestamp=timestamp,
        context_message_id=context_message_id,
    )


def build_status(
    business: BusinessAccount,
    user: SimulatedUser,
    message_id: str,
    status: StatusName,
    *,
    timestamp: int | None = None,
    conversation_id: str | None = None,
    include_billing: bool = True,
    pricing_format: PricingFormat = "pmp",
    pricing_type: str = "regular",
) -> Payload:
    """Delivery status update for an outbound message ``message_id`` (sent/delivered/read).

    ``pricing_format`` selects the billing fields (see ``docs/meta-format-notes.yaml``):

    * ``"pmp"`` (default, current): per-message pricing, Graph API v24.0+. No ``conversation``
      object; ``pricing`` (``pricing_model: "PMP"``, ``type``, ``category``, ``billable``) only
      on ``delivered``. ``pricing_type`` is e.g. ``regular`` or ``free_customer_service``
      (free types set ``billable`` to false).
    * ``"cbp"`` (legacy): conversation-based pricing as sent before 2025-07-01 / by API <= v23
      examples: ``conversation`` plus ``pricing`` (``pricing_model: "CBP"``) on sent/delivered.

    ``include_billing=False`` omits ``conversation`` and ``pricing`` in either format.
    """
    ts = timestamp if timestamp is not None else _now()
    entry: dict[str, Any] = {
        "id": message_id,
        "status": status,
        "timestamp": str(ts),
        "recipient_id": user.wa_id,
    }
    if include_billing and pricing_format == "cbp" and status != "read":
        conversation: dict[str, Any] = {
            "id": conversation_id or new_conversation_id(),
            "origin": {"type": "service"},
        }
        if status == "sent":
            conversation["expiration_timestamp"] = str(ts + _SECONDS_IN_DAY)
        entry["conversation"] = conversation
        entry["pricing"] = {"billable": True, "pricing_model": "CBP", "category": "service"}
    elif include_billing and pricing_format == "pmp" and status == "delivered":
        entry["pricing"] = {
            "billable": not pricing_type.startswith("free"),
            "pricing_model": "PMP",
            "type": pricing_type,
            "category": "service",
        }

    value = _base_value(business)
    value["statuses"] = [entry]
    return _envelope(business, value)
