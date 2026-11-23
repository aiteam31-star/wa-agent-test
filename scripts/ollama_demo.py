"""Ask the demo bot, backed by a local Ollama model, one question through our simulator.

    python scripts/ollama_demo.py                                   # "Which IPOs are open?"
    python scripts/ollama_demo.py "When does Nova Textiles list?" llama3.2:3b

Needs Ollama running with the model pulled (``ollama pull llama3.2:3b``). It starts the mock
Graph API and the bot on local ports, sends the question as a pretend WhatsApp user, and prints
the bot's reply and which tools the model called.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from demo_bot.app import create_app as create_bot_app  # noqa: E402
from demo_bot.config import Settings  # noqa: E402
from wa_agent_test.mock_graph import CaptureStore, MockGraphServer  # noqa: E402
from wa_agent_test.mock_graph import create_app as create_mock_app  # noqa: E402
from wa_agent_test.payloads import make_users  # noqa: E402
from wa_agent_test.simulator import WebhookSimulator  # noqa: E402

QUESTION = sys.argv[1] if len(sys.argv) > 1 else "Which IPOs are open?"
MODEL = sys.argv[2] if len(sys.argv) > 2 else "llama3.2:3b"


async def main() -> None:
    store = CaptureStore()
    async with MockGraphServer(create_mock_app(store=store)) as mock:
        settings = Settings(
            graph_base_url=mock.base_url,
            llm_provider="ollama",
            ollama_model=MODEL,
            request_timeout_s=600,
        )
        async with httpx.AsyncClient(timeout=settings.request_timeout_s) as http:
            bot_app = create_bot_app(settings, http_client=http)
            async with MockGraphServer(bot_app) as bot:
                (user,) = make_users(1, seed=1)
                async with WebhookSimulator(
                    bot.base_url + "/webhook", app_secret=settings.app_secret, timeout_s=30
                ) as sim:
                    print(f"model: {MODEL}\nuser asks: {QUESTION!r}\n(waiting for the model...)")
                    start = time.monotonic()
                    delivery = await sim.send_text(user, QUESTION)
                    print(f"webhook delivered: HTTP {delivery.status_code}", flush=True)
                    try:
                        found = await store.wait_for_count(
                            user.wa_id, 1, timeout=600, include_rejected=True
                        )
                    except TimeoutError:
                        print("no reply within 10 minutes")
                        return
                    took = time.monotonic() - start

    reply = found[0]
    payload = reply.payload or {}
    print(f"\nreply after {took:.1f}s  (type={reply.type}, accepted={reply.accepted})")
    if reply.type == "text":
        print("TEXT:", payload["text"]["body"])
    else:
        interactive = payload["interactive"]
        print("BODY:", interactive["body"]["text"])
        action = interactive["action"]
        if interactive["type"] == "button":
            print("BUTTONS:", [b["reply"]["title"] for b in action["buttons"]])
        else:
            print("LIST ROWS:", [r["title"] for s in action["sections"] for r in s["rows"]])
    if not reply.accepted:
        print("REJECTED:", [str(v) for v in reply.violations])

    print("\nwhat the model did (tool calls):")
    for message in bot_app.state.agent.history(user.wa_id):
        for call in message.get("tool_calls", []):
            print("  called", call["name"], json.dumps(call["arguments"]))
        if message["role"] == "tool":
            print("  tool result:", message["content"][:200])


if __name__ == "__main__":
    asyncio.run(main())
