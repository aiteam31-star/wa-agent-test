"""Shared pytest fixtures."""

import pytest

from wa_agent_test.mock_graph import Limits, load_limits


@pytest.fixture(scope="session")
def limits() -> Limits:
    return load_limits()
