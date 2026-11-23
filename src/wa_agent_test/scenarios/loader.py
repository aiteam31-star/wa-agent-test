"""Load scenario YAML files, with errors that point at file and line."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from wa_agent_test import yamlio
from wa_agent_test.scenarios.models import Scenario
from wa_agent_test.scenarios.templating import TemplateError, expand_for_each

SUFFIXES = {".yaml", ".yml"}


@dataclass(frozen=True)
class Problem:
    file: str
    line: int
    path: str
    message: str

    def __str__(self) -> str:
        where = f"{self.file}:{self.line}"
        return f"{where}: {self.path + ': ' if self.path else ''}{self.message}"


class ScenarioLoadError(Exception):
    """One or more scenario files are invalid. ``problems`` lists every issue found."""

    def __init__(self, problems: list[Problem]) -> None:
        self.problems = problems
        super().__init__("\n".join(str(p) for p in problems))


def _find_line(root: yaml.Node, loc: Iterable[Any]) -> int:
    node = root
    line = node.start_mark.line + 1
    for part in loc:
        if isinstance(node, yaml.MappingNode) and isinstance(part, str):
            for key_node, value_node in node.value:
                if key_node.value == part:
                    line = key_node.start_mark.line + 1
                    node = value_node
                    break
            else:
                break
        elif (
            isinstance(node, yaml.SequenceNode) and isinstance(part, int) and part < len(node.value)
        ):
            node = node.value[part]
            line = node.start_mark.line + 1
        else:
            break
    return line


def _format_loc(loc: Iterable[Any]) -> str:
    out = ""
    for part in loc:
        out += f"[{part}]" if isinstance(part, int) else (f".{part}" if out else str(part))
    return out


def _clean(msg: str) -> str:
    return msg.removeprefix("Value error, ")


def load_scenario_file(path: Path) -> list[Scenario]:
    """Load one file. Returns several scenarios if it uses ``for_each``."""
    shown = str(path)
    text = path.read_text(encoding="utf-8")
    try:
        root = yamlio.compose(text)
        raw = yamlio.load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        line = mark.line + 1 if mark else 1
        raise ScenarioLoadError([Problem(shown, line, "", f"not valid YAML: {exc}")]) from exc
    if root is None or not isinstance(raw, dict):
        raise ScenarioLoadError(
            [Problem(shown, 1, "", "a scenario file must be a YAML mapping (name:, turns:, ...)")]
        )

    try:
        expanded = expand_for_each(raw)
    except TemplateError as exc:
        raise ScenarioLoadError(
            [Problem(shown, _find_line(root, ["for_each"]), "for_each", str(exc))]
        ) from exc

    scenarios: list[Scenario] = []
    for data in expanded:
        try:
            scenario = Scenario.model_validate(data)
        except ValidationError as exc:
            raise ScenarioLoadError(
                [
                    Problem(
                        shown, _find_line(root, e["loc"]), _format_loc(e["loc"]), _clean(e["msg"])
                    )
                    for e in exc.errors()
                ]
            ) from exc
        scenario.source_file = shown
        scenarios.append(scenario)
    return scenarios


def find_scenario_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    if not path.is_dir():
        raise ScenarioLoadError([Problem(str(path), 1, "", "no such file or folder")])
    return sorted(p for p in path.rglob("*") if p.suffix in SUFFIXES and p.is_file())


def load_scenarios(path: Path) -> list[Scenario]:
    """Load a file or a folder (recursively). Reports all invalid files together."""
    problems: list[Problem] = []
    scenarios: list[Scenario] = []
    for file in find_scenario_files(path):
        try:
            scenarios.extend(load_scenario_file(file))
        except ScenarioLoadError as exc:
            problems.extend(exc.problems)
    seen: dict[str, str] = {}
    for s in scenarios:
        if s.name in seen:
            problems.append(
                Problem(
                    s.source_file or "",
                    1,
                    "name",
                    f"duplicate scenario name {s.name!r} (also in {seen[s.name]})",
                )
            )
        seen[s.name] = s.source_file or ""
    if problems:
        raise ScenarioLoadError(problems)
    return scenarios
