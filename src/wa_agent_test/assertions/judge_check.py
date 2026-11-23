"""The ``judge:`` check: ask an LLM judge whether the reply passes a rubric.

Use it for things a regex can't see: advice phrased in a way you didn't list, or a fact that
contradicts the data in a way you didn't predict. It works alongside the simple checks; it
doesn't replace them. A judge that can't answer makes the check FAIL (never pass silently).
"""

from __future__ import annotations

import json
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, field_validator

from wa_agent_test.assertions.base import Assertion, BotMessage, TurnContext
from wa_agent_test.judges import JudgeRequest, resolve_rubric
from wa_agent_test.truth import TruthError


class DataRef(BaseModel):
    """Which truth data to show the judge: one entity's record, or every record."""

    model_config = ConfigDict(extra="forbid")

    source: str
    entity: str | None = None


class JudgeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rubric: str  # "no_investment_advice", "factually_consistent", or your own rubric text
    data: DataRef | None = None


class JudgeCheck(Assertion):
    kind: ClassVar[str] = "judge"
    value: JudgeSpec

    @field_validator("value", mode="before")
    @classmethod
    def _shorthand(cls, v: Any) -> Any:
        # `judge: no_investment_advice` means `judge: {rubric: no_investment_advice}`
        return {"rubric": v} if isinstance(v, str) else v

    def check(self, selected: list[BotMessage], ctx: TurnContext) -> tuple[bool, str]:
        raise NotImplementedError("judge checks must be run with aevaluate()")

    async def acheck(self, selected: list[BotMessage], ctx: TurnContext) -> tuple[bool, str]:
        rubric_id, rubric = resolve_rubric(self.value.rubric)
        if ctx.judge is None:
            return False, "no judge is configured (add a `judge:` section to wa-agent-test.yaml)"
        reply = "\n".join(m.text for m in selected).strip()
        if not reply:
            return False, "the bot sent no text for the judge to look at"

        data_text: str | None = None
        ref = self.value.data
        if ref is not None:
            source = ctx.truth.get(ref.source)
            if source is None:
                known = ", ".join(sorted(ctx.truth)) or "none"
                return False, f"truth source {ref.source!r} isn't defined (defined: {known})"
            dump = getattr(source, "dump", None)
            if dump is None:
                return False, f"truth source {ref.source!r} can't provide data for a judge"
            try:
                data_text = json.dumps(dump(ref.entity), ensure_ascii=False)
            except TruthError as exc:
                return False, f"truth source {ref.source!r}: {exc}"

        request = JudgeRequest(
            rubric_id=rubric_id,
            rubric=rubric,
            reply=reply,
            question=ctx.user_message,
            data=data_text,
        )
        try:
            verdict = await ctx.judge.judge(request)
        except Exception as exc:  # any failure to judge is a failed check, never a pass
            return False, f"judge error ({rubric_id}): {exc}"
        tag = f"judge {rubric_id}" + (" [cached]" if verdict.cached else "")
        return verdict.passed, f"{tag}: {verdict.reason}"
