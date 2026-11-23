"""Run the bot: ``python -m demo_bot`` (PORT and HOST env vars; default 127.0.0.1:8000)."""

import logging
import os

import uvicorn

from demo_bot.app import create_app

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    uvicorn.run(
        create_app(),
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
    )
