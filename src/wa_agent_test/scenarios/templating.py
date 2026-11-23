"""``for_each`` expansion and ``{{ variable }}`` substitution.

Deliberately tiny (not Jinja): only ``{{ name }}`` and ``{{ name.key }}`` for the variable
declared by ``for_each``. Quote any YAML string that contains ``{{ }}``.
"""

from __future__ import annotations

import copy
import re
from typing import Any

_VAR = re.compile(r"\{\{\s*([A-Za-z_]\w*(?:\.\w+)*)\s*\}\}")


class TemplateError(ValueError):
    pass


def has_variable(text: str) -> bool:
    return _VAR.search(text) is not None


def substitute(obj: Any, variables: dict[str, Any]) -> Any:
    """Replace ``{{ var }}`` in every string value (not keys), recursively."""
    if isinstance(obj, str):
        return _VAR.sub(lambda m: _lookup(m.group(1), variables), obj)
    if isinstance(obj, list):
        return [substitute(v, variables) for v in obj]
    if isinstance(obj, dict):
        return {k: substitute(v, variables) for k, v in obj.items()}
    return obj


def _lookup(path: str, variables: dict[str, Any]) -> str:
    head, *rest = path.split(".")
    if head not in variables:
        known = ", ".join(sorted(variables)) or "none"
        raise TemplateError(f"unknown variable '{{{{ {path} }}}}' (for_each defines: {known})")
    value: Any = variables[head]
    for key in rest:
        if not isinstance(value, dict) or key not in value:
            raise TemplateError(f"'{{{{ {path} }}}}': no key '{key}'")
        value = value[key]
    if isinstance(value, dict | list):
        raise TemplateError(f"'{{{{ {path} }}}}' is not a single value; use {{{{ {path}.key }}}}")
    return str(value)


def expand_for_each(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """One raw scenario dict -> one dict per ``for_each`` value (or itself if none)."""
    if "for_each" not in raw:
        return [raw]
    spec = raw["for_each"]
    if not isinstance(spec, dict) or len(spec) != 1:
        raise TemplateError("for_each must have exactly one variable, e.g. for_each: {ipo: [a, b]}")
    ((var, values),) = spec.items()
    if not isinstance(values, list) or not values:
        raise TemplateError(f"for_each.{var} must be a non-empty list")
    body = {k: v for k, v in raw.items() if k != "for_each"}
    name = body.get("name")
    if not isinstance(name, str) or not has_variable(name):
        raise TemplateError(
            f"with for_each, 'name' must include {{{{ {var} }}}} so each copy has its own name"
        )
    return [substitute(copy.deepcopy(body), {str(var): value}) for value in values]
