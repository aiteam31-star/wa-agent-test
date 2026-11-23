"""Run the mock Graph API on a real local port, in-process (for bots that make HTTP calls)."""

from __future__ import annotations

import asyncio
import time
from types import TracebackType

import uvicorn
from fastapi import FastAPI


class MockGraphServer:
    """Async context manager that serves ``app`` on an ephemeral port (``port=0``)."""

    def __init__(self, app: FastAPI, *, host: str = "127.0.0.1", port: int = 0) -> None:
        self._app = app
        self._host = host
        self._port = port
        self._server: uvicorn.Server | None = None
        self._task: asyncio.Task[None] | None = None

    @property
    def base_url(self) -> str:
        """URL to give the bot as its Graph API base (no version / phone number id)."""
        return f"http://{self._host}:{self._port}"

    async def start(self) -> None:
        config = uvicorn.Config(
            self._app,
            host=self._host,
            port=self._port,
            log_level="warning",
            access_log=False,
            lifespan="off",
        )
        server = uvicorn.Server(config)
        self._server = server
        self._task = asyncio.create_task(server.serve())
        deadline = time.monotonic() + 10
        while not server.started:
            if self._task.done():
                self._task.result()
                raise RuntimeError("mock Graph server exited during startup")
            if time.monotonic() > deadline:
                raise TimeoutError("mock Graph server did not start within 10s")
            await asyncio.sleep(0.01)
        self._port = server.servers[0].sockets[0].getsockname()[1]

    async def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._task is not None:
            await self._task
        self._server = self._task = None

    async def __aenter__(self) -> MockGraphServer:
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.stop()
