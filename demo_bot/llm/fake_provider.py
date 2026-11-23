"""Deterministic stand-in for an LLM, so tests and CI need no keys or network.

It behaves like a tool-calling model: it decides which tool to call from the user's words, then
writes an answer from the tool results. It is intentionally simple, not smart.
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from typing import Any

from demo_bot.data import IPOStore
from demo_bot.llm.base import LLMResponse, Message, ToolCall

_LIST_WORDS = ("open", "list", "available", "which ipo", "ipos")
_SUBSCRIPTION_WORDS = ("subscri", "oversubscri", "times", "demand")

HELP_TEXT = (
    "I can help with IPOs: which ones are open, price bands, lot sizes, key dates and "
    "subscription status. Try asking 'Which IPOs are open?'"
)


def _fmt_date(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day} {d:%B %Y}"


def _call(tool: str, /, **arguments: Any) -> LLMResponse:
    return LLMResponse(tool_calls=[ToolCall(f"call_{uuid.uuid4().hex[:12]}", tool, arguments)])


class FakeProvider:
    def __init__(self, store: IPOStore) -> None:
        self._store = store

    async def complete(
        self, system: str, messages: list[Message], tools: list[dict[str, Any]]
    ) -> LLMResponse:
        if messages and messages[-1]["role"] == "tool":
            return LLMResponse(text=self._answer(messages))
        return self._decide(messages)

    # --- deciding which tool to call --------------------------------------------------------

    def _decide(self, messages: list[Message]) -> LLMResponse:
        text = str(messages[-1]["content"]).lower()
        ipo = self._store.find_in_text(text) or self._last_ipo(messages)
        asks_subscription = any(w in text for w in _SUBSCRIPTION_WORDS)
        mentions_ipo = self._store.find_in_text(text) is not None
        if not mentions_ipo and any(w in text for w in _LIST_WORDS) and not asks_subscription:
            return _call("list_open_ipos")
        if ipo is not None:
            if asks_subscription:
                return _call("get_subscription_status", name=ipo.short_name)
            return _call("get_ipo_details", name=ipo.short_name)
        return LLMResponse(text=HELP_TEXT)

    def _last_ipo(self, messages: list[Message]) -> Any:
        for message in reversed(messages[:-1]):
            for call in message.get("tool_calls", []):
                found = self._store.find(str(call["arguments"].get("name", "")))
                if found:
                    return found
        return None

    # --- writing the answer from tool results -------------------------------------------------

    def _answer(self, messages: list[Message]) -> str:
        results: list[dict[str, Any]] = []
        for message in reversed(messages):
            if message["role"] != "tool":
                break
            results.insert(0, json.loads(message["content"]))
        return "\n\n".join(self._render(r) for r in results)

    def _render(self, r: dict[str, Any]) -> str:
        if "open_ipos" in r:
            if not r["open_ipos"]:
                return "No IPOs are open for bidding right now."
            lines = [
                f"- {i['name']}: price band ₹{i['price_band']['low']}-{i['price_band']['high']}, "
                f"closes {_fmt_date(i['closes'])}"
                for i in r["open_ipos"]
            ]
            return "IPOs open for bidding right now:\n" + "\n".join(lines)
        if r.get("found") is False:
            return f"{r['error']} I know about: {', '.join(r['available'])}."
        if "ipo" in r:
            i, d = r["ipo"], r["ipo"]["dates"]
            return (
                f"{i['name']} ({i['sector']}, {i['exchange']}): price band "
                f"₹{i['price_band']['low']}-{i['price_band']['high']}, lot size {i['lot_size']} "
                f"shares (minimum investment about ₹{i['min_investment']:,}). Bidding opens "
                f"{_fmt_date(d['open'])} and closes {_fmt_date(d['close'])}; allotment on "
                f"{_fmt_date(d['allotment'])}; listing date is {_fmt_date(d['listing'])}. "
                f"Status: {i['status']}."
            )
        if "subscription" in r:
            s = r["subscription"]
            if s is None:
                return f"{r['name']} opens on {_fmt_date(r['opens'])}. {r['note']}"
            return (
                f"{r['name']} subscription as of {_fmt_date(s['as_of'])}: QIB {s['qib']}x, "
                f"NII {s['nii']}x, retail {s['retail']}x, overall {s['total']}x."
            )
        return HELP_TEXT
