"""Small parsers that turn text found in a reply (or a truth value) into comparable values."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, datetime
from typing import Any

_DATE_FORMATS = (
    "%d %B %Y",
    "%d %b %Y",
    "%B %d, %Y",
    "%b %d, %Y",
    "%B %d %Y",
    "%b %d %Y",
    "%Y-%m-%d",
    "%d/%m/%Y",  # day first, as in India
    "%d-%m-%Y",
)
_ORDINAL = re.compile(r"(?<=\d)(st|nd|rd|th)\b", re.IGNORECASE)
_CURRENCY_NOISE = re.compile(r"(₹|rs\.?|inr)", re.IGNORECASE)


def parse_date(raw: Any) -> date:
    """Parse ``30 November 2026``, ``30 Nov 2026``, ``Nov 30, 2026`` or ``2026-11-30``.

    Slash and dash dates (``30/11/2026``) are day-first, as in India.
    """
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    text = _ORDINAL.sub("", str(raw).strip()).replace("Sept", "Sep")
    text = re.sub(r"\s+", " ", text)
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"not a recognised date: {raw!r}")


def parse_number(raw: Any) -> float:
    """Parse ``1,234.5``, ``₹14,807``, ``Rs. 210``, ``7.1x`` into a float."""
    if isinstance(raw, bool):
        raise ValueError(f"not a number: {raw!r}")
    if isinstance(raw, int | float):
        return float(raw)
    text = _CURRENCY_NOISE.sub("", str(raw)).replace(",", "").strip().rstrip("xX").strip()
    try:
        return float(text)
    except ValueError as exc:
        raise ValueError(f"not a recognised number: {raw!r}") from exc


def parse_text(raw: Any) -> str:
    """Case-insensitive, whitespace-normalised text."""
    return re.sub(r"\s+", " ", str(raw)).strip().lower()


PARSERS: dict[str, Callable[[Any], Any]] = {
    "date": parse_date,
    "number": parse_number,
    "currency": parse_number,
    "text": parse_text,
}


def show(value: Any) -> str:
    """Human-readable form of a parsed value for failure messages."""
    if isinstance(value, date):
        return f"{value.day} {value:%B %Y}"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)
