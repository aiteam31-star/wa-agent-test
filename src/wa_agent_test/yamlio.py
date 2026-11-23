"""YAML loading with one deliberate difference: only ``true``/``false`` are booleans.

Plain PyYAML (YAML 1.1) reads ``yes``, ``no``, ``on`` and ``off`` as booleans, which would turn a
scenario line like ``tap_button: Yes`` into ``True``. Here they stay strings.
"""

from __future__ import annotations

import re
from typing import Any

import yaml

_BOOL_TAG = "tag:yaml.org,2002:bool"


class _Loader(yaml.SafeLoader):
    pass


_Loader.yaml_implicit_resolvers = {
    first: [(tag, regexp) for tag, regexp in resolvers if tag != _BOOL_TAG]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_Loader.add_implicit_resolver(
    _BOOL_TAG, re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"), list("tTfF")
)


def load(text: str) -> Any:
    return yaml.load(text, Loader=_Loader)


def compose(text: str) -> yaml.Node | None:
    return yaml.compose(text, Loader=_Loader)
