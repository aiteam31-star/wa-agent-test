"""The IPO fixture: typed models and a small lookup store."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict


class PriceBand(BaseModel):
    low: int
    high: int


class Dates(BaseModel):
    open: date
    close: date
    allotment: date
    listing: date


class Subscription(BaseModel):
    """Times subscribed, by investor category."""

    as_of: date
    qib: float
    nii: float
    retail: float
    employee: float | None = None
    total: float


class IPO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str
    name: str
    short_name: str
    sector: str
    exchange: str
    issue_size_cr: float
    price_band: PriceBand
    lot_size: int
    registrar: str
    status: Literal["upcoming", "open", "closed", "listed"]
    dates: Dates
    subscription: Subscription | None = None

    @property
    def min_investment(self) -> int:
        """Smallest application at the upper price band (one lot), in rupees."""
        return self.price_band.high * self.lot_size


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", text.lower()).strip()


class IPOStore:
    """Read-only access to the IPOs, with forgiving name matching."""

    def __init__(self, ipos: list[IPO]) -> None:
        self._ipos = ipos

    @classmethod
    def load(cls, path: Path) -> IPOStore:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls([IPO.model_validate(item) for item in raw["ipos"]])

    def all(self) -> list[IPO]:
        return list(self._ipos)

    def open_ipos(self) -> list[IPO]:
        return [i for i in self._ipos if i.status == "open"]

    def by_slug(self, slug: str) -> IPO | None:
        return next((i for i in self._ipos if i.slug == slug), None)

    def find(self, name: str) -> IPO | None:
        """Find one IPO by slug, name or a unique fragment; None if missing or ambiguous."""
        query = _norm(name)
        if not query:
            return None
        for ipo in self._ipos:
            if query in {_norm(ipo.slug), _norm(ipo.name), _norm(ipo.short_name)}:
                return ipo
        matches = [i for i in self._ipos if query in _norm(i.name) or _norm(i.short_name) in query]
        return matches[0] if len(matches) == 1 else None

    def find_in_text(self, text: str) -> IPO | None:
        """The first IPO mentioned in free text (full name, short name, or first word)."""
        haystack = f" {_norm(text)} "
        for ipo in self._ipos:
            first_word = _norm(ipo.short_name).split()[0]
            for token in (_norm(ipo.name), _norm(ipo.short_name), first_word):
                if len(token) >= 4 and f" {token} " in haystack:
                    return ipo
        return None
