"""Pluggable truth sources used by fact-check assertions."""

from wa_agent_test.truth.base import TruthError, TruthSource
from wa_agent_test.truth.file import FileTruthSource

__all__ = ["FileTruthSource", "TruthError", "TruthSource"]
