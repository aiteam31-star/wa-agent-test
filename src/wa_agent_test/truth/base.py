"""The truth-source protocol used by fact checks."""

from __future__ import annotations

from typing import Any, Protocol


class TruthError(Exception):
    """A truth source can't answer (unknown entity or field). Fact checks report it as a failure."""


class TruthSource(Protocol):
    """Looks up the correct value of ``field`` for ``entity``."""

    def lookup(self, entity: str, field: str) -> Any: ...
