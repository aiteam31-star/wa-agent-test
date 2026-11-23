"""The scenario runner: plays each scenario as a simulated user and checks the bot's replies."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from wa_agent_test.assertions import BotMessage, Button, CheckResult, Row, TurnContext
from wa_agent_test.judges import Judge
from wa_agent_test.mock_graph import CapturedMessage, CaptureStore
from wa_agent_test.payloads import SimulatedUser, make_users
from wa_agent_test.scenarios.models import Scenario, Turn
from wa_agent_test.scenarios.results import (
    RejectedMessage,
    RunResult,
    ScenarioResult,
    TurnResult,
)
from wa_agent_test.simulator import DeliveryResult, WebhookSimulator
from wa_agent_test.truth import TruthSource


class TurnError(Exception):
    """The turn can't be performed (for example, there is no such button to tap)."""


def to_bot_message(captured: CapturedMessage, sent_at: float) -> BotMessage:
    """Flatten a captured outbound message into text / buttons / rows for checks and reports."""
    payload: dict[str, Any] = captured.payload or {}
    kind = captured.type or "unknown"
    text = ""
    buttons: list[Button] = []
    rows: list[Row] = []
    if kind == "text":
        text = str(payload.get("text", {}).get("body", ""))
    elif kind == "interactive":
        interactive = payload.get("interactive", {})
        text = str(interactive.get("body", {}).get("text", ""))
        action = interactive.get("action", {})
        if interactive.get("type") == "button":
            buttons = [
                Button(id=str(b["reply"]["id"]), title=str(b["reply"]["title"]))
                for b in action.get("buttons", [])
            ]
        elif interactive.get("type") == "list":
            rows = [
                Row(id=str(r["id"]), title=str(r["title"]), description=r.get("description"))
                for section in action.get("sections", [])
                for r in section.get("rows", [])
            ]
    elif kind == "template":
        text = f"[template {payload.get('template', {}).get('name', '')}]"
    return BotMessage(
        message_id=captured.message_id or "",
        type=kind,
        text=text,
        buttons=buttons,
        rows=rows,
        latency_ms=(captured.received_monotonic - sent_at) * 1000,
        raw=payload,
    )


def _find_button(previous: list[BotMessage], key: str) -> tuple[Button, BotMessage]:
    seen: list[str] = []
    for message in reversed(previous):
        for button in message.buttons:
            seen.append(button.title)
            if button.title.lower() == key.lower() or button.id == key:
                return button, message
    if seen:
        raise TurnError(f"no button '{key}' on the bot's previous reply (buttons it sent: {seen})")
    raise TurnError(f"can't tap '{key}': the bot's previous reply had no reply buttons")


def _find_row(previous: list[BotMessage], key: str) -> tuple[Row, BotMessage]:
    seen: list[str] = []
    for message in reversed(previous):
        for row in message.rows:
            seen.append(row.title)
            if row.title.lower() == key.lower() or row.id == key:
                return row, message
    if seen:
        raise TurnError(f"no list row '{key}' on the bot's previous reply (rows it sent: {seen})")
    raise TurnError(f"can't pick '{key}': the bot's previous reply had no list")


class ScenarioRunner:
    def __init__(
        self,
        *,
        simulator: WebhookSimulator,
        store: CaptureStore,
        truth: Mapping[str, TruthSource] | None = None,
        judge: Judge | None = None,
        concurrency: int = 4,
        scenario_timeout_s: float = 300.0,
    ) -> None:
        self.sim = simulator
        self.store = store
        self.truth: Mapping[str, TruthSource] = truth or {}
        self.judge = judge
        self.concurrency = max(1, concurrency)
        self.scenario_timeout_s = scenario_timeout_s

    # --- whole runs -------------------------------------------------------------------------

    async def run(
        self,
        scenarios: Sequence[Scenario],
        *,
        seed: int | None = 1,
        on_done: Callable[[ScenarioResult], None] | None = None,
    ) -> RunResult:
        """Run scenarios in parallel (bounded by ``concurrency``), one simulated user each."""
        started_at = datetime.now(UTC)
        start = time.monotonic()
        users = make_users(len(scenarios), seed=seed)
        gate = asyncio.Semaphore(self.concurrency)

        async def one(scenario: Scenario, user: SimulatedUser) -> ScenarioResult:
            async with gate:
                result = await self.run_scenario(scenario, user)
            if on_done is not None:
                on_done(result)
            return result

        results = await asyncio.gather(*(one(s, u) for s, u in zip(scenarios, users, strict=True)))
        return RunResult(
            started_at=started_at, duration_s=time.monotonic() - start, scenarios=list(results)
        )

    async def run_scenario(self, scenario: Scenario, user: SimulatedUser) -> ScenarioResult:
        start = time.monotonic()
        turns: list[TurnResult] = []
        error: str | None = None
        try:
            async with asyncio.timeout(self.scenario_timeout_s):
                await self._play(scenario, user, turns)
        except TimeoutError:
            error = f"the scenario took longer than {self.scenario_timeout_s:g}s overall"
        except Exception as exc:
            error = f"internal error: {type(exc).__name__}: {exc}"
        return ScenarioResult(
            name=scenario.name,
            source_file=scenario.source_file,
            tags=scenario.tags,
            user_wa_id=user.wa_id,
            passed=error is None and all(t.status == "passed" for t in turns),
            duration_s=time.monotonic() - start,
            error=error,
            turns=turns,
        )

    async def _play(self, scenario: Scenario, user: SimulatedUser, out: list[TurnResult]) -> None:
        previous: list[BotMessage] = []
        failed = False
        for index, turn in enumerate(scenario.turns, start=1):
            if failed:
                out.append(TurnResult(index=index, action=turn.label, status="skipped"))
                continue
            result, previous = await self._run_turn(scenario, turn, index, user, previous)
            out.append(result)
            failed = result.status == "failed"  # later turns would talk to a derailed bot

    # --- one turn ---------------------------------------------------------------------------

    async def _send(
        self, turn: Turn, user: SimulatedUser, previous: list[BotMessage]
    ) -> DeliveryResult:
        if turn.say is not None:
            return await self.sim.send_text(user, turn.say)
        if turn.tap_button is not None:
            button, message = _find_button(previous, turn.tap_button)
            return await self.sim.send_button_reply(
                user, button.id, button.title, context_message_id=message.message_id
            )
        if turn.pick_row is not None:
            row, message = _find_row(previous, turn.pick_row)
            return await self.sim.send_list_reply(
                user, row.id, row.title, row.description, context_message_id=message.message_id
            )
        assert turn.send_image is not None
        return await self.sim.send_image(user, caption=turn.send_image.caption)

    async def _collect(
        self, wa_id: str, baseline: int, *, expect: int | None, timeout_s: float, settle_s: float
    ) -> list[CapturedMessage]:
        """Wait for the bot's reply messages (accepted and rejected) to this turn."""

        def attempts() -> list[CapturedMessage]:
            return self.store.messages_for(wa_id, include_rejected=True)[baseline:]

        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s
        if expect == 0:
            await asyncio.sleep(settle_s)
            return attempts()
        try:
            await self.store.wait_for_count(
                wa_id, baseline + (expect or 1), timeout=timeout_s, include_rejected=True
            )
        except TimeoutError:
            return attempts()
        while True:  # keep going while the bot is still sending
            have = len(attempts())
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            try:
                await self.store.wait_for_count(
                    wa_id,
                    baseline + have + 1,
                    timeout=min(settle_s, remaining),
                    include_rejected=True,
                )
            except TimeoutError:
                break
        return attempts()

    async def _run_turn(
        self,
        scenario: Scenario,
        turn: Turn,
        index: int,
        user: SimulatedUser,
        previous: list[BotMessage],
    ) -> tuple[TurnResult, list[BotMessage]]:
        started = time.monotonic()
        label = turn.label

        def finish(status: str, **kwargs: Any) -> TurnResult:
            return TurnResult(
                index=index,
                action=label,
                status=status,
                duration_ms=(time.monotonic() - started) * 1000,
                **kwargs,
            )

        baseline = len(self.store.messages_for(user.wa_id, include_rejected=True))
        sent_at = time.monotonic()
        try:
            delivery = await self._send(turn, user, previous)
        except TurnError as exc:
            return finish("failed", error=str(exc)), []
        if not delivery.ok:
            reason = (
                f"couldn't reach the bot: {delivery.error}"
                if delivery.error
                else f"the bot answered the webhook with HTTP {delivery.status_code}"
            )
            return finish("failed", error=reason), []

        timeout_s = scenario.timeout_for(turn)
        captured = await self._collect(
            user.wa_id,
            baseline,
            expect=turn.expect_messages,
            timeout_s=timeout_s,
            settle_s=scenario.settle_ms_for(turn) / 1000,
        )
        accepted = [c for c in captured if c.accepted]
        rejected = [c for c in captured if not c.accepted]
        bot_messages = [to_bot_message(c, sent_at) for c in accepted]
        rejected_out = [
            RejectedMessage(reasons=[str(v) for v in c.violations], payload=c.payload)
            for c in rejected
        ]

        checks: list[CheckResult] = []
        error: str | None = None
        if turn.expect_messages is None and not captured:
            error = f"the bot didn't reply within {timeout_s:g}s"
        if turn.expect_messages is not None:
            got = len(captured)
            checks.append(
                CheckResult(
                    kind="expect_messages",
                    passed=got == turn.expect_messages,
                    message=f"expected exactly {turn.expect_messages} bot message(s), got {got}"
                    + (f" within {timeout_s:g}s" if got < turn.expect_messages else ""),
                )
            )
        if rejected and not scenario.allow_rejected_for(turn):
            reasons = "; ".join(r for item in rejected_out for r in item.reasons)
            checks.append(
                CheckResult(
                    kind="rejected_messages",
                    passed=False,
                    message=f"the bot sent a message WhatsApp would reject: {reasons}",
                )
            )
        judged: list[BotMessage] | None = None
        if error is None:
            if rejected and not scenario.allow_rejected_for(turn):
                # The turn fails anyway, but check the text of everything the bot *tried* to
                # send too, so one run reports every problem (a wrong date AND a rejected send).
                judged = [to_bot_message(c, sent_at) for c in captured]
            elif bot_messages or not rejected:
                judged = bot_messages
        if judged is not None:
            ctx = TurnContext(
                messages=judged,
                truth=self.truth,
                user_message=turn.user_text,
                judge=self.judge,
            )
            for check in turn.expect:
                checks.append(await check.aevaluate(ctx))

        ok = error is None and all(c.passed for c in checks)
        result = finish(
            "passed" if ok else "failed",
            error=error,
            checks=checks,
            bot_messages=bot_messages,
            rejected=rejected_out,
        )
        return result, bot_messages
