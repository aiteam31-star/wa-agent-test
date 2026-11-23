"""Run results: plain, JSON-serializable data (what baselines and reports will consume)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from wa_agent_test.assertions import BotMessage, CheckResult


class RejectedMessage(BaseModel):
    """A send the mock Graph API refused (it would also fail on real WhatsApp)."""

    reasons: list[str]
    payload: dict[str, object] | None = None


class TurnResult(BaseModel):
    index: int  # 1-based
    action: str
    status: Literal["passed", "failed", "skipped"]
    duration_ms: float = 0.0
    error: str | None = None  # the turn couldn't run or the bot never answered
    checks: list[CheckResult] = []
    bot_messages: list[BotMessage] = []
    rejected: list[RejectedMessage] = []


class ScenarioResult(BaseModel):
    name: str
    source_file: str | None = None
    tags: list[str] = []
    user_wa_id: str
    passed: bool
    duration_s: float
    error: str | None = None  # scenario-level problem (e.g. overall timeout)
    turns: list[TurnResult] = []


class RunResult(BaseModel):
    started_at: datetime
    duration_s: float
    scenarios: list[ScenarioResult]

    @property
    def total(self) -> int:
        return len(self.scenarios)

    @property
    def passed(self) -> int:
        return sum(1 for s in self.scenarios if s.passed)

    @property
    def failed(self) -> int:
        return self.total - self.passed

    @property
    def exit_code(self) -> int:
        """0 if everything passed, 1 otherwise (see CLAUDE.md for 2 and 3)."""
        return 0 if self.failed == 0 else 1
