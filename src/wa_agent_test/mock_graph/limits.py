"""Loader for the WhatsApp message limits in ``limits.yaml`` (the single source of truth)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict

DEFAULT_LIMITS_PATH = Path(__file__).with_name("limits.yaml")


class LimitSpec(BaseModel):
    """One limit, with how well it is backed by Meta's docs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    value: int
    status: Literal["confirmed", "conflicting", "unconfirmed"]
    source: str | None = None
    note: str | None = None


class Limits(BaseModel):
    """All limits enforced by the mock. Access numbers as ``limits.text_body_max.value``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    text_body_max: LimitSpec
    reply_buttons_max: LimitSpec
    reply_button_title_max: LimitSpec
    reply_button_id_max: LimitSpec
    reply_buttons_body_max: LimitSpec
    interactive_header_text_max: LimitSpec
    interactive_footer_max: LimitSpec
    list_body_max: LimitSpec
    list_button_label_max: LimitSpec
    list_sections_max: LimitSpec
    list_rows_max: LimitSpec
    list_section_title_max: LimitSpec
    list_row_title_max: LimitSpec
    list_row_description_max: LimitSpec
    list_row_id_max: LimitSpec

    def not_confirmed(self) -> dict[str, LimitSpec]:
        """Limits that are not marked ``confirmed``."""
        return {k: v for k, v in self if isinstance(v, LimitSpec) and v.status != "confirmed"}


def load_limits(path: Path | str | None = None) -> Limits:
    """Load limits from ``path`` (default: the packaged ``limits.yaml``).

    YAML keys starting with ``_`` (e.g. anchors) are ignored.
    """
    raw = yaml.safe_load(Path(path or DEFAULT_LIMITS_PATH).read_text(encoding="utf-8"))
    return Limits.model_validate({k: v for k, v in raw.items() if not k.startswith("_")})
