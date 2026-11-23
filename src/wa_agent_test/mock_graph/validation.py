"""Validation of outbound message bodies (what a bot POSTs to /{phone_number_id}/messages).

Returns *all* violations found, so the reasons can be logged and recorded, not just the first.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from wa_agent_test.mock_graph.limits import Limits

ViolationKind = Literal["missing", "invalid", "limit", "unsupported"]


@dataclass(frozen=True, slots=True)
class Violation:
    """One reason a message was rejected."""

    kind: ViolationKind
    path: str
    message: str
    limit: str | None = None  # key in limits.yaml, for kind == "limit"

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


def normalize_wa_id(raw: Any) -> str | None:
    """Normalize a recipient (``+91 98765-43210`` -> ``919876543210``); None if not a phone."""
    if not isinstance(raw, str):
        return None
    cleaned = re.sub(r"[\s\-()]", "", raw)
    cleaned = cleaned.removeprefix("+")
    return cleaned if cleaned.isdigit() else None


class _Checker:
    def __init__(self, limits: Limits) -> None:
        self.limits = limits
        self.out: list[Violation] = []

    def add(self, kind: ViolationKind, path: str, message: str, limit: str | None = None) -> None:
        self.out.append(Violation(kind, path, message, limit))

    def obj(self, parent: dict[str, Any], key: str, path: str, *, required: bool = True) -> Any:
        value = parent.get(key)
        full = f"{path}.{key}" if path else key
        if value is None:
            if required:
                self.add("missing", full, "is required")
            return None
        if not isinstance(value, dict):
            self.add("invalid", full, "must be an object")
            return None
        return value

    def text(
        self,
        parent: dict[str, Any],
        key: str,
        path: str,
        *,
        limit_key: str | None = None,
        required: bool = True,
    ) -> str | None:
        full = f"{path}.{key}" if path else key
        value = parent.get(key)
        if value is None:
            if required:
                self.add("missing", full, "is required")
            return None
        if not isinstance(value, str):
            self.add("invalid", full, "must be a string")
            return None
        if not value.strip():
            self.add("invalid", full, "must not be empty")
        if limit_key is not None:
            maximum = getattr(self.limits, limit_key).value
            if len(value) > maximum:
                self.add(
                    "limit",
                    full,
                    f"is {len(value)} characters; must be at most {maximum} characters",
                    limit_key,
                )
        return value

    def count(self, n: int, path: str, limit_key: str, what: str) -> None:
        maximum = getattr(self.limits, limit_key).value
        if n > maximum:
            self.add("limit", path, f"has {n} {what}; at most {maximum} allowed", limit_key)

    # --- message types -------------------------------------------------------------------

    def message(self, body: dict[str, Any]) -> None:
        if body.get("messaging_product") != "whatsapp":
            self.add("invalid", "messaging_product", 'must be "whatsapp"')
        to = body.get("to")
        if to is None:
            self.add("missing", "to", "is required")
        elif normalize_wa_id(to) is None:
            self.add("invalid", "to", "must be a phone number (digits, optional leading +)")

        message_type = body.get("type", "text")
        if message_type == "text":
            self.text_message(body)
        elif message_type == "interactive":
            self.interactive(body)
        elif message_type == "template":
            self.template(body)
        else:
            self.add(
                "unsupported",
                "type",
                f"message type {message_type!r} is not supported by the mock yet "
                "(supported: text, interactive, template)",
            )

    def text_message(self, body: dict[str, Any]) -> None:
        text = self.obj(body, "text", "")
        if text is not None:
            self.text(text, "body", "text", limit_key="text_body_max")

    def template(self, body: dict[str, Any]) -> None:
        template = self.obj(body, "template", "")
        if template is None:
            return
        self.text(template, "name", "template")
        language = self.obj(template, "language", "template")
        if language is not None:
            self.text(language, "code", "template.language")
        components = template.get("components")
        if components is not None and not isinstance(components, list):
            self.add("invalid", "template.components", "must be an array")

    def interactive(self, body: dict[str, Any]) -> None:
        interactive = self.obj(body, "interactive", "")
        if interactive is None:
            return
        itype = interactive.get("type")
        if itype == "button":
            self.reply_buttons(interactive)
        elif itype == "list":
            self.list_message(interactive)
        else:
            self.add(
                "unsupported",
                "interactive.type",
                f"interactive type {itype!r} is not supported by the mock yet "
                "(supported: button, list)",
            )

    def _common(self, interactive: dict[str, Any], body_limit_key: str) -> None:
        body = self.obj(interactive, "body", "interactive")
        if body is not None:
            self.text(body, "text", "interactive.body", limit_key=body_limit_key)
        header = self.obj(interactive, "header", "interactive", required=False)
        if header is not None and header.get("type") == "text":
            self.text(header, "text", "interactive.header", limit_key="interactive_header_text_max")
        footer = self.obj(interactive, "footer", "interactive", required=False)
        if footer is not None:
            self.text(footer, "text", "interactive.footer", limit_key="interactive_footer_max")

    def reply_buttons(self, interactive: dict[str, Any]) -> None:
        self._common(interactive, "reply_buttons_body_max")
        action = self.obj(interactive, "action", "interactive")
        if action is None:
            return
        buttons = action.get("buttons")
        path = "interactive.action.buttons"
        if not isinstance(buttons, list) or not buttons:
            self.add("missing", path, "must be a non-empty array of reply buttons")
            return
        self.count(len(buttons), path, "reply_buttons_max", "buttons")
        titles: set[str] = set()
        for i, button in enumerate(buttons):
            bpath = f"{path}[{i}]"
            if not isinstance(button, dict):
                self.add("invalid", bpath, "must be an object")
                continue
            if button.get("type") != "reply":
                self.add("invalid", f"{bpath}.type", 'must be "reply"')
            reply = self.obj(button, "reply", bpath)
            if reply is None:
                continue
            self.text(reply, "id", f"{bpath}.reply", limit_key="reply_button_id_max")
            title = self.text(reply, "title", f"{bpath}.reply", limit_key="reply_button_title_max")
            if title is not None:
                if title in titles:
                    self.add("invalid", f"{bpath}.reply.title", f"duplicate title {title!r}")
                titles.add(title)

    def list_message(self, interactive: dict[str, Any]) -> None:
        self._common(interactive, "list_body_max")
        action = self.obj(interactive, "action", "interactive")
        if action is None:
            return
        self.text(action, "button", "interactive.action", limit_key="list_button_label_max")
        sections = action.get("sections")
        path = "interactive.action.sections"
        if not isinstance(sections, list) or not sections:
            self.add("missing", path, "must be a non-empty array of sections")
            return
        self.count(len(sections), path, "list_sections_max", "sections")
        total_rows = 0
        for i, section in enumerate(sections):
            spath = f"{path}[{i}]"
            if not isinstance(section, dict):
                self.add("invalid", spath, "must be an object")
                continue
            self.text(
                section,
                "title",
                spath,
                limit_key="list_section_title_max",
                required=len(sections) > 1,
            )
            rows = section.get("rows")
            if not isinstance(rows, list) or not rows:
                self.add("missing", f"{spath}.rows", "must be a non-empty array of rows")
                continue
            total_rows += len(rows)
            for j, row in enumerate(rows):
                rpath = f"{spath}.rows[{j}]"
                if not isinstance(row, dict):
                    self.add("invalid", rpath, "must be an object")
                    continue
                self.text(row, "id", rpath, limit_key="list_row_id_max")
                self.text(row, "title", rpath, limit_key="list_row_title_max")
                self.text(
                    row, "description", rpath, limit_key="list_row_description_max", required=False
                )
        self.count(total_rows, path, "list_rows_max", "rows (across all sections)")


def validate_message(body: Any, limits: Limits) -> list[Violation]:
    """Validate an outbound message body; an empty list means it would be accepted."""
    if not isinstance(body, dict):
        return [Violation("invalid", "$", "request body must be a JSON object")]
    checker = _Checker(limits)
    checker.message(body)
    return checker.out
