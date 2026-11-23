"""Smoke test: the package and its subpackages import cleanly."""

import importlib

import pytest

import wa_agent_test

SUBPACKAGES = [
    "payloads",
    "simulator",
    "mock_graph",
    "scenarios",
    "assertions",
    "truth",
    "judges",
    "baseline",
    "report",
    "cli",
]


def test_version() -> None:
    assert wa_agent_test.__version__ == "0.1.0"


@pytest.mark.parametrize("name", SUBPACKAGES)
def test_subpackage_imports(name: str) -> None:
    importlib.import_module(f"wa_agent_test.{name}")
