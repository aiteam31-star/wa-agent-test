"""A judge that needs no model, for tests and CI. It records every request it receives."""

from __future__ import annotations

from collections.abc import Callable

from wa_agent_test.judges.base import JudgeRequest, Verdict


class FakeJudge:
    """Passes everything by default; give ``decide`` to script the verdicts."""

    provider = "fake"
    model = "fake"

    def __init__(self, decide: Callable[[JudgeRequest], Verdict] | None = None) -> None:
        self._decide = decide
        self.requests: list[JudgeRequest] = []

    async def judge(self, request: JudgeRequest) -> Verdict:
        self.requests.append(request)
        if self._decide is not None:
            return self._decide(request)
        return Verdict(passed=True, reason="the fake judge passes everything", model=self.model)

    async def aclose(self) -> None:
        return None
