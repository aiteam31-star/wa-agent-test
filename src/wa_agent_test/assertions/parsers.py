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

_MONTH = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?"
    r"|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
)
_DATE_IN_TEXT = [
    re.compile(rf"\b\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTH}\.?,?\s+\d{{4}}\b", re.IGNORECASE),
    re.compile(rf"\b{_MONTH}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}\b", re.IGNORECASE),
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{4}\b"),
]


def find_dates(text: str) -> list[tuple[str, date]]:
    """Every date written in ``text``, as ``(the text as written, the date)``, in order.

    Understands the same spellings as :func:`parse_date`. Things that look like a date but
    aren't one (``31 February 2026``) are skipped.
    """
    spans: list[tuple[int, int, str, date]] = []
    for pattern in _DATE_IN_TEXT:
        for match in pattern.finditer(text):
            try:
                parsed = parse_date(re.sub(r"[.,]", "", match.group(0)))
            except ValueError:
                continue
            spans.append((match.start(), match.end(), match.group(0), parsed))
    spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
    found: list[tuple[str, date]] = []
    last_end = -1
    for start, end, raw, parsed in spans:
        if start >= last_end:  # skip a shorter match inside one we already took
            found.append((raw, parsed))
            last_end = end
    return found


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
