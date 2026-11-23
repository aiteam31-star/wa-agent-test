"""Truth source backed by a JSON or YAML file."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from wa_agent_test import yamlio
from wa_agent_test.truth.base import TruthError


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", text.lower()).strip()


def _dig(data: Any, dotted: str) -> Any:
    current = data
    for part in dotted.split("."):
        if current is None:
            return None  # e.g. `subscription: null`, so `subscription.total` has no value
        if isinstance(current, Mapping) and part in current:
            current = current[part]
        else:
            raise KeyError(dotted)
    return current


class FileTruthSource:
    """Records in a JSON/YAML file.

    ``records`` is the dotted path to the list of records inside the file (omit if the file is
    the list). ``entity_match`` lists record keys whose values name the entity. ``fields`` maps a
    field name used in scenarios to a dotted path inside a record (a field not listed is used
    as a dotted path itself).
    """

    def __init__(
        self,
        path: Path,
        *,
        records: str | None = None,
        entity_match: Sequence[str] = ("name",),
        fields: Mapping[str, str] | None = None,
    ) -> None:
        text = path.read_text(encoding="utf-8")
        data = yamlio.load(text) if path.suffix in {".yaml", ".yml"} else json.loads(text)
        try:
            items = _dig(data, records) if records else data
        except KeyError as exc:
            raise TruthError(f"{path}: no '{records}' in the file") from exc
        if not isinstance(items, list):
            raise TruthError(f"{path}: expected a list of records")
        self._records: list[dict[str, Any]] = items
        self._entity_match = list(entity_match)
        self._fields = dict(fields or {})
        self._path = path

    def _names(self, record: Mapping[str, Any]) -> list[str]:
        return [_norm(str(record[k])) for k in self._entity_match if record.get(k) is not None]

    def _find(self, entity: str) -> dict[str, Any]:
        query = _norm(entity)
        if not query:
            raise TruthError("empty entity name")
        for record in self._records:
            if query in self._names(record):
                return record
        partial = [r for r in self._records if any(query in n for n in self._names(r))]
        if len(partial) == 1:
            return partial[0]
        known = ", ".join(str(r.get(self._entity_match[0])) for r in self._records)
        why = "is ambiguous" if partial else "was not found"
        raise TruthError(f"entity {entity!r} {why} (known: {known})")

    def lookup(self, entity: str, field: str) -> Any:
        record = self._find(entity)
        path = self._fields.get(field, field)
        try:
            return _dig(record, path)
        except KeyError as exc:
            raise TruthError(
                f"entity {entity!r} has no field {field!r} (looked for '{path}')"
            ) from exc
