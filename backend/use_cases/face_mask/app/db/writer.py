"""Serial database writer for worker threads.

Camera workers run in threads and must never block on the database. They hand a coroutine job to this writer;
a single consumer task on the application's event loop runs the jobs strictly in order (so an event row is
always inserted before the jobs that update it).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.db import init_db

logger = logging.getLogger(__name__)

Job = Callable[[AsyncSession], Awaitable[None]]


class DbWriter:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue[Job] | None = None
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue()
        self._task = asyncio.create_task(self._run(), name="face-mask-db-writer")

    def submit(self, job: Job) -> None:
        """Thread-safe. Never blocks and never raises into the caller."""
        if self._loop is None or self._queue is None:
            logger.warning("DB writer not started; job dropped")
            return
        self._loop.call_soon_threadsafe(self._queue.put_nowait, job)

    async def _run(self) -> None:
        assert self._queue is not None
        while True:
            job = await self._queue.get()
            try:
                async with init_db.session_scope() as session:
                    await job(session)
            except Exception:
                logger.exception("Database write job failed")
            finally:
                self._queue.task_done()

    async def drain(self, timeout: float = 10.0) -> None:
        if self._queue is not None:
            try:
                await asyncio.wait_for(self._queue.join(), timeout)
            except asyncio.TimeoutError:
                logger.warning("DB writer did not drain within %.0fs", timeout)

    async def stop(self) -> None:
        await self.drain()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
