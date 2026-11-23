"""Payload shape tests: inbound webhooks must match the WhatsApp Cloud API format."""

import json
import random
from typing import Any

import pytest

from wa_agent_test.payloads import (
    BusinessAccount,
    SimulatedUser,
    build_button_reply,
    build_image,
    build_list_reply,
    build_status,
    build_text,
    make_users,
    new_media_id,
    new_wamid,
)

BIZ = BusinessAccount(waba_id="WABA1", phone_number_id="PNID1", display_phone_number="15550001111")
USER = SimulatedUser(
    wa_id="919876543210", phone_number="+919876543210", profile_name="Aarav Sharma"
)
TS = 1700000000
METADATA = {"display_phone_number": "15550001111", "phone_number_id": "PNID1"}


def _value(payload: dict) -> dict:
    assert payload["object"] == "whatsapp_business_account"
    assert len(payload["entry"]) == 1
    entry = payload["entry"][0]
    assert entry["id"] == "WABA1"
    assert len(entry["changes"]) == 1
    change = entry["changes"][0]
    assert change["field"] == "messages"
    value = change["value"]
    assert value["messaging_product"] == "whatsapp"
    assert value["metadata"] == METADATA
    return value


def _message(payload: dict) -> dict:
    value = _value(payload)
    assert "statuses" not in value
    assert value["contacts"] == [{"profile": {"name": "Aarav Sharma"}, "wa_id": "919876543210"}]
    assert len(value["messages"]) == 1
    message = value["messages"][0]
    assert message["from"] == "919876543210"
    assert message["id"].startswith("wamid.")
    assert isinstance(message["timestamp"], str)
    return message


def test_text_payload_exact_shape() -> None:
    payload = build_text(BIZ, USER, "hello", message_id="wamid.X", timestamp=TS)
    assert payload == {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WABA1",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": METADATA,
                            "contacts": [
                                {"profile": {"name": "Aarav Sharma"}, "wa_id": "919876543210"}
                            ],
                            "messages": [
                                {
                                    "from": "919876543210",
                                    "id": "wamid.X",
                                    "timestamp": "1700000000",
                                    "type": "text",
                                    "text": {"body": "hello"},
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }


def test_text_with_context() -> None:
    message = _message(build_text(BIZ, USER, "hi", context_message_id="wamid.PREV"))
    assert message["context"] == {"from": "15550001111", "id": "wamid.PREV"}


def test_button_reply_shape() -> None:
    payload = build_button_reply(BIZ, USER, "btn_dates", "Dates", context_message_id="wamid.PREV")
    message = _message(payload)
    assert message["type"] == "interactive"
    assert message["interactive"] == {
        "type": "button_reply",
        "button_reply": {"id": "btn_dates", "title": "Dates"},
    }
    assert message["context"]["id"] == "wamid.PREV"


def test_list_reply_shape() -> None:
    message = _message(build_list_reply(BIZ, USER, "row_1", "Nova Textiles", "Mainboard IPO"))
    assert message["type"] == "interactive"
    assert message["interactive"] == {
        "type": "list_reply",
        "list_reply": {"id": "row_1", "title": "Nova Textiles", "description": "Mainboard IPO"},
    }


def test_list_reply_without_description_omits_key() -> None:
    message = _message(build_list_reply(BIZ, USER, "row_1", "Nova Textiles"))
    assert "description" not in message["interactive"]["list_reply"]


def test_image_shape_has_media_id_not_bytes() -> None:
    message = _message(build_image(BIZ, USER, media_id="1234567890123456", caption="my id card"))
    assert message["type"] == "image"
    image = message["image"]
    assert image["id"] == "1234567890123456"
    assert image["caption"] == "my id card"
    assert image["mime_type"] == "image/jpeg"
    assert isinstance(image["sha256"], str)
    assert set(image) == {"id", "caption", "mime_type", "sha256"}


def test_image_generates_media_id_and_omits_missing_caption() -> None:
    image = _message(build_image(BIZ, USER))["image"]
    assert image["id"].isdigit()
    assert "caption" not in image


def _status_entry(status: str, **kwargs: Any) -> dict[str, Any]:
    payload = build_status(BIZ, USER, "wamid.OUT", status, timestamp=TS, **kwargs)  # type: ignore[arg-type]
    value = _value(payload)
    assert "messages" not in value
    assert "contacts" not in value
    (entry,) = value["statuses"]
    assert entry["id"] == "wamid.OUT"
    assert entry["status"] == status
    assert entry["timestamp"] == "1700000000"
    assert entry["recipient_id"] == "919876543210"
    entry_typed: dict[str, Any] = entry
    return entry_typed


@pytest.mark.parametrize("status", ["sent", "delivered", "read"])
def test_status_default_is_current_per_message_pricing(status: str) -> None:
    entry = _status_entry(status)
    assert "conversation" not in entry  # removed for Graph API v24.0+
    if status == "delivered":
        assert entry["pricing"] == {
            "billable": True,
            "pricing_model": "PMP",
            "type": "regular",
            "category": "service",
        }
    else:
        assert "pricing" not in entry


def test_status_pmp_free_service_message_is_not_billable() -> None:
    pricing = _status_entry("delivered", pricing_type="free_customer_service")["pricing"]
    assert pricing["type"] == "free_customer_service"
    assert pricing["billable"] is False


@pytest.mark.parametrize("status", ["sent", "delivered", "read"])
def test_status_legacy_cbp_format(status: str) -> None:
    entry = _status_entry(status, pricing_format="cbp")
    if status == "read":
        assert "conversation" not in entry and "pricing" not in entry
        return
    assert entry["conversation"]["origin"] == {"type": "service"}
    assert entry["pricing"] == {"billable": True, "pricing_model": "CBP", "category": "service"}
    assert ("expiration_timestamp" in entry["conversation"]) == (status == "sent")


@pytest.mark.parametrize("pricing_format", ["pmp", "cbp"])
@pytest.mark.parametrize("status", ["sent", "delivered", "read"])
def test_status_without_billing(status: str, pricing_format: str) -> None:
    entry = _status_entry(status, include_billing=False, pricing_format=pricing_format)
    assert set(entry) == {"id", "status", "timestamp", "recipient_id"}


def test_payloads_are_json_serializable() -> None:
    for payload in (
        build_text(BIZ, USER, "héllo ✓"),
        build_button_reply(BIZ, USER, "a", "b"),
        build_list_reply(BIZ, USER, "a", "b"),
        build_image(BIZ, USER),
        build_status(BIZ, USER, "wamid.X", "delivered"),
    ):
        assert json.loads(json.dumps(payload)) == payload


def test_generated_message_ids_are_unique() -> None:
    ids = {_message(build_text(BIZ, USER, "x"))["id"] for _ in range(200)}
    assert len(ids) == 200


def test_seeded_ids_are_reproducible() -> None:
    assert new_wamid(random.Random(1)) == new_wamid(random.Random(1))
    assert new_media_id(random.Random(1)) == new_media_id(random.Random(1))
    assert len(new_media_id()) == 16


def test_make_users_unique_and_wellformed() -> None:
    users = make_users(500, seed=7)
    assert len({u.wa_id for u in users}) == 500
    assert len({u.phone_number for u in users}) == 500
    for u in users:
        assert u.wa_id.isdigit() and u.wa_id.startswith("91") and len(u.wa_id) == 12
        assert u.phone_number == "+" + u.wa_id
        assert u.profile_name


def test_make_users_seed_is_deterministic() -> None:
    assert make_users(5, seed=3) == make_users(5, seed=3)
    assert make_users(5, seed=3) != make_users(5, seed=4)


def test_user_from_phone_number() -> None:
    user = SimulatedUser.from_phone_number("+91 98765-43210", "Test")
    assert user.wa_id == "919876543210" and user.phone_number == "+919876543210"
    with pytest.raises(ValueError):
        SimulatedUser.from_phone_number("abc")
