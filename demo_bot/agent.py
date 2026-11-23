"""The conversation agent: per-user memory, the LLM tool loop, and reply building."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Literal

from demo_bot.buggy import ADVICE_SENTENCE, EXTRA_BUTTON_TITLE, BuggyMode
from demo_bot.data import IPOStore
from demo_bot.llm import LLMProvider, Message
from demo_bot.tools import TOOL_SPECS, ToolRunner

logger = logging.getLogger("demo_bot.agent")

SYSTEM_PROMPT = (
    "You are an assistant on WhatsApp that answers questions about Indian IPOs. "
    "Use the tools to look up facts and never invent dates, prices or subscription numbers. "
    "Quote dates exactly as the tools give them. Keep answers short and plain text. "
    "You are not a financial adviser: never tell the user whether to apply or invest."
)
FALLBACK_TEXT = "Sorry, I'm having trouble answering right now. Please try again in a moment."
MAX_TOOL_ROUNDS = 5

# Meta's limits for the messages we build (kept in sync with the harness's limits.yaml).
BUTTON_BODY_MAX = 1024
LIST_BODY_MAX = 4096
BUTTON_TITLES = (("dates", "Dates"), ("price", "Price band"), ("subscription", "Subscription"))

ReplyKind = Literal["text", "buttons", "list"]


@dataclass(frozen=True)
class Button:
    id: str
    title: str


@dataclass(frozen=True)
class Row:
    id: str
    title: str
    description: str


@dataclass
class Reply:
    """What to send back: plain text, text + reply buttons, or a list of open IPOs."""

    text: str
    kind: ReplyKind = "text"
    buttons: list[Button] = field(default_factory=list)
    rows: list[Row] = field(default_factory=list)
    ipo_slug: str | None = None


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


class Agent:
    def __init__(
        self,
        *,
        provider: LLMProvider,
        store: IPOStore,
        buggy: BuggyMode | None = None,
        history_max_messages: int = 40,
    ) -> None:
        self.provider = provider
        self.store = store
        self.buggy = buggy or BuggyMode()
        self.tools = ToolRunner(store, self.buggy)
        self.history_max_messages = history_max_messages
        self._history: dict[str, list[Message]] = {}

    def history(self, wa_id: str) -> list[Message]:
        """The in-memory conversation for one user (copy)."""
        return list(self._history.get(wa_id, []))

    # --- inbound interactive replies -> a natural-language question ----------------------

    def question_for_reply(self, reply_id: str, title: str) -> str:
        action, _, slug = reply_id.partition(":")
        ipo = self.store.by_slug(slug)
        name = ipo.name if ipo else title
        questions = {
            "dates": f"What are the key dates for {name}?",
            "price": f"What is the price band and lot size for {name}?",
            "subscription": f"What is the subscription status of {name}?",
            "ipo": f"Tell me about {name}.",
            "apply": f"Should I apply for {name}?",
        }
        return questions.get(action, title)

    # --- main entry point -----------------------------------------------------------------

    async def handle(self, wa_id: str, user_text: str) -> Reply:
        history = self._history.setdefault(wa_id, [])
        history.append({"role": "user", "content": user_text})
        slugs: list[str] = []
        listed_open = False
        answer = FALLBACK_TEXT
        try:
            for _ in range(MAX_TOOL_ROUNDS):
                response = await self.provider.complete(SYSTEM_PROMPT, history, TOOL_SPECS)
                if not response.tool_calls:
                    answer = response.text or FALLBACK_TEXT
                    history.append({"role": "assistant", "content": answer})
                    break
                history.append(
                    {
                        "role": "assistant",
                        "content": response.text,
                        "tool_calls": [
                            {"id": c.id, "name": c.name, "arguments": c.arguments}
                            for c in response.tool_calls
                        ],
                    }
                )
                for call in response.tool_calls:
                    result = self.tools.run(call.name, call.arguments)
                    if call.name == "list_open_ipos":
                        listed_open = True
                    if isinstance(result.get("slug"), str):
                        slugs.append(result["slug"])
                    history.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.id,
                            "name": call.name,
                            "content": json.dumps(result),
                        }
                    )
            else:
                history.append({"role": "assistant", "content": FALLBACK_TEXT})
        except Exception:
            logger.exception("LLM/tool failure for %s", wa_id)
            self._drop_incomplete_turn(history)
            answer = FALLBACK_TEXT
        self._trim(history)
        return self._build_reply(answer, slugs[-1] if slugs else None, listed_open)

    # --- helpers ------------------------------------------------------------------------

    def _build_reply(self, answer: str, slug: str | None, listed_open: bool) -> Reply:
        ipo = self.store.by_slug(slug) if slug else None
        if ipo is not None:
            text = answer
            if self.buggy.fire("advice"):
                room = BUTTON_BODY_MAX - len(ADVICE_SENTENCE) - 1
                text = f"{_truncate(answer, room)} {ADVICE_SENTENCE}"
            buttons = [Button(f"{key}:{ipo.slug}", title) for key, title in BUTTON_TITLES]
            if self.buggy.fire("buttons"):
                buttons.append(Button(f"apply:{ipo.slug}", EXTRA_BUTTON_TITLE))
            return Reply(
                _truncate(text, BUTTON_BODY_MAX), "buttons", buttons=buttons, ipo_slug=ipo.slug
            )
        if listed_open and self.store.open_ipos():
            rows = [
                Row(
                    f"ipo:{i.slug}",
                    i.short_name,
                    f"₹{i.price_band.low}-{i.price_band.high} · closes {i.dates.close:%d %b}",
                )
                for i in self.store.open_ipos()
            ]
            return Reply(_truncate(answer, LIST_BODY_MAX), "list", rows=rows)
        return Reply(answer)

    @staticmethod
    def _drop_incomplete_turn(history: list[Message]) -> None:
        """After a failure, remove the partial turn so the history stays valid for the LLM."""
        while history and history[-1]["role"] != "user":
            history.pop()
        if history:
            history.pop()

    def _trim(self, history: list[Message]) -> None:
        """Keep the newest messages, starting on a user message so tool pairs stay intact."""
        excess = len(history) - self.history_max_messages
        if excess <= 0:
            return
        cut = excess
        while cut < len(history) and history[cut]["role"] != "user":
            cut += 1
        del history[:cut]
