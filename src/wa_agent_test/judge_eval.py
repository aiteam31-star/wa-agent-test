"""Test the judge itself: run it on replies whose correct verdict is known, and count mistakes.

A judge is a model, so it can be wrong. Run this before trusting one, and again after changing
the model or a rubric. Cases live in a YAML file (see examples/judge-calibration.yaml).
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from wa_agent_test import yamlio
from wa_agent_test.assertions import BotMessage, DataRef, JudgeCheck, JudgeSpec, TurnContext
from wa_agent_test.judges import Judge
from wa_agent_test.truth import TruthSource


class CalibrationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    rubric: str
    question: str = ""
    reply: str
    data: DataRef | None = None
    expect: Literal["pass", "fail"]  # the verdict a correct judge gives
    note: str = ""


class CaseResult(BaseModel):
    case: CalibrationCase
    judge_passed: bool
    reason: str
    errored: bool = False  # the judge couldn't answer

    @property
    def correct(self) -> bool:
        return not self.errored and self.judge_passed == (self.case.expect == "pass")

    @property
    def kind(self) -> str:
        """``ok``, ``false pass`` (judge missed a bad reply), ``false fail`` or ``error``."""
        if self.errored:
            return "error"
        if self.correct:
            return "ok"
        return "false pass" if self.judge_passed else "false fail"


class Calibration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cases: list[CalibrationCase] = Field(min_length=1)


def load_cases(path: Path) -> list[CalibrationCase]:
    raw = yamlio.load(path.read_text(encoding="utf-8"))
    return Calibration.model_validate(raw).cases


async def evaluate_cases(
    cases: list[CalibrationCase], judge: Judge, truth: Mapping[str, TruthSource]
) -> list[CaseResult]:
    """Run every case through the same code path a scenario's ``judge:`` check uses."""
    results: list[CaseResult] = []
    for case in cases:
        check = JudgeCheck(value=JudgeSpec(rubric=case.rubric, data=case.data))
        message = BotMessage(message_id="", type="text", text=case.reply, latency_ms=0.0, raw={})
        ctx = TurnContext([message], truth, user_message=case.question, judge=judge)
        outcome = await check.aevaluate(ctx)
        results.append(
            CaseResult(
                case=case,
                judge_passed=outcome.passed,
                reason=outcome.message,
                errored=outcome.message.startswith(("judge error", "no judge", "truth source")),
            )
        )
    return results
