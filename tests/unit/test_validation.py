"""Limit validation of outbound messages. Limits come from limits.yaml, never hard-coded."""

import copy
from typing import Any

import pytest

from wa_agent_test.mock_graph import Limits, validate_message


def text_msg(body: str = "hello") -> dict[str, Any]:
    return {
        "messaging_product": "whatsapp",
        "to": "919876543210",
        "type": "text",
        "text": {"body": body},
    }


def buttons_msg(n: int = 3, title: str = "Dates", body: str = "Pick one") -> dict[str, Any]:
    return {
        "messaging_product": "whatsapp",
        "to": "919876543210",
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body},
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {"id": f"b{i}", "title": f"{title}{i}"[: len(title) + 1]},
                    }
                    for i in range(n)
                ]
            },
        },
    }


def list_msg(sections: int = 1, rows_per_section: int = 3) -> dict[str, Any]:
    return {
        "messaging_product": "whatsapp",
        "to": "919876543210",
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": "Choose"},
            "action": {
                "button": "View",
                "sections": [
                    {
                        "title": f"Section {s}",
                        "rows": [
                            {"id": f"r{s}-{r}", "title": f"Row {s}-{r}", "description": "desc"}
                            for r in range(rows_per_section)
                        ],
                    }
                    for s in range(sections)
                ],
            },
        },
    }


def template_msg() -> dict[str, Any]:
    return {
        "messaging_product": "whatsapp",
        "to": "919876543210",
        "type": "template",
        "template": {"name": "hello_world", "language": {"code": "en_US"}},
    }


def paths(body: Any, limits: Limits) -> list[str]:
    return [v.path for v in validate_message(body, limits)]


def limit_keys(body: Any, limits: Limits) -> list[str | None]:
    return [v.limit for v in validate_message(body, limits)]


@pytest.mark.parametrize(
    "body",
    [text_msg(), buttons_msg(3), buttons_msg(1), list_msg(), list_msg(2, 5), template_msg()],
)
def test_valid_messages_pass(body: dict[str, Any], limits: Limits) -> None:
    assert validate_message(body, limits) == []


def test_text_body_at_limit_ok_and_over_limit_rejected(limits: Limits) -> None:
    maximum = limits.text_body_max.value
    assert validate_message(text_msg("x" * maximum), limits) == []
    (v,) = validate_message(text_msg("x" * (maximum + 1)), limits)
    assert v.kind == "limit" and v.limit == "text_body_max" and v.path == "text.body"
    assert str(maximum) in v.message and str(maximum + 1) in v.message


def test_text_body_over_4096_literal(limits: Limits) -> None:
    assert limit_keys(text_msg("x" * 4097), limits) == ["text_body_max"]


def test_more_than_three_reply_buttons_rejected(limits: Limits) -> None:
    (v,) = validate_message(buttons_msg(4), limits)
    assert v.kind == "limit" and v.limit == "reply_buttons_max"
    assert v.path == "interactive.action.buttons"
    assert "4" in v.message and "3" in v.message


def test_button_title_over_20_rejected(limits: Limits) -> None:
    body = buttons_msg(1)
    body["interactive"]["action"]["buttons"][0]["reply"]["title"] = "x" * 21
    assert limit_keys(body, limits) == ["reply_button_title_max"]
    body["interactive"]["action"]["buttons"][0]["reply"]["title"] = "x" * 20
    assert validate_message(body, limits) == []


def test_duplicate_button_titles_rejected(limits: Limits) -> None:
    body = buttons_msg(2)
    body["interactive"]["action"]["buttons"][1]["reply"]["title"] = "Dates0"
    (v,) = validate_message(body, limits)
    assert v.kind == "invalid" and "duplicate" in v.message


def test_button_id_and_body_limits(limits: Limits) -> None:
    body = buttons_msg(1)
    body["interactive"]["action"]["buttons"][0]["reply"]["id"] = "i" * (
        limits.reply_button_id_max.value + 1
    )
    assert limit_keys(body, limits) == ["reply_button_id_max"]
    long_body = buttons_msg(1, body="b" * (limits.reply_buttons_body_max.value + 1))
    assert limit_keys(long_body, limits) == ["reply_buttons_body_max"]


def test_more_than_ten_list_rows_rejected_across_sections(limits: Limits) -> None:
    assert validate_message(list_msg(2, 5), limits) == []
    (v,) = validate_message(list_msg(2, 6), limits)
    assert v.limit == "list_rows_max" and "12" in v.message


def test_more_than_ten_list_sections_rejected(limits: Limits) -> None:
    assert "list_sections_max" in limit_keys(list_msg(11, 1), limits)


def test_list_field_limits(limits: Limits) -> None:
    body = list_msg()
    action = body["interactive"]["action"]
    action["button"] = "b" * 21
    row = action["sections"][0]["rows"][0]
    row["title"] = "t" * 25
    row["description"] = "d" * 73
    row["id"] = "i" * 201
    action["sections"][0]["title"] = "s" * 25
    assert sorted(k for k in limit_keys(body, limits) if k) == sorted(
        [
            "list_button_label_max",
            "list_row_title_max",
            "list_row_description_max",
            "list_row_id_max",
            "list_section_title_max",
        ]
    )


def test_section_title_required_only_with_multiple_sections(limits: Limits) -> None:
    single = list_msg(1)
    del single["interactive"]["action"]["sections"][0]["title"]
    assert validate_message(single, limits) == []
    multi = list_msg(2)
    del multi["interactive"]["action"]["sections"][1]["title"]
    assert paths(multi, limits) == ["interactive.action.sections[1].title"]


def test_all_violations_are_reported_not_just_first(limits: Limits) -> None:
    body = buttons_msg(4)
    body["interactive"]["action"]["buttons"][0]["reply"]["title"] = "x" * 30
    kinds = {v.limit for v in validate_message(body, limits)}
    assert kinds == {"reply_buttons_max", "reply_button_title_max"}


def test_limits_come_from_config_not_code(limits: Limits) -> None:
    tight = limits.model_copy(
        update={"text_body_max": limits.text_body_max.model_copy(update={"value": 5})}
    )
    assert validate_message(text_msg("123456"), tight)[0].limit == "text_body_max"
    assert validate_message(text_msg("12345"), tight) == []


@pytest.mark.parametrize(
    ("mutate", "expected_path"),
    [
        (lambda b: b.pop("to"), "to"),
        (lambda b: b.update(to="not-a-number"), "to"),
        (lambda b: b.update(messaging_product="sms"), "messaging_product"),
        (lambda b: b.pop("text"), "text"),
        (lambda b: b["text"].update(body=""), "text.body"),
        (lambda b: b["text"].update(body=123), "text.body"),
    ],
)
def test_structural_errors(mutate: Any, expected_path: str, limits: Limits) -> None:
    body = copy.deepcopy(text_msg())
    mutate(body)
    assert expected_path in paths(body, limits)


def test_plus_and_spaces_in_recipient_are_accepted(limits: Limits) -> None:
    body = text_msg()
    body["to"] = "+91 98765-43210"
    assert validate_message(body, limits) == []


def test_template_requires_name_and_language(limits: Limits) -> None:
    body = template_msg()
    del body["template"]["name"]
    del body["template"]["language"]
    assert paths(body, limits) == ["template.name", "template.language"]


def test_unsupported_types_are_flagged_not_silently_accepted(limits: Limits) -> None:
    body = {"messaging_product": "whatsapp", "to": "919876543210", "type": "audio", "audio": {}}
    (v,) = validate_message(body, limits)
    assert v.kind == "unsupported"
    cta = buttons_msg(1)
    cta["interactive"]["type"] = "cta_url"
    assert [v.kind for v in validate_message(cta, limits)] == ["unsupported"]


def test_non_object_body(limits: Limits) -> None:
    assert [v.path for v in validate_message([], limits)] == ["$"]
