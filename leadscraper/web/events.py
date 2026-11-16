"""Thread-safe publish/subscribe bridge from worker threads to SSE clients.

Workers publish from plain threads; subscribers are asyncio queues on the
server's event loop. The bus keeps every event of the current run so a
browser that connects (or reloads) mid-run replays the run and then follows
it live.
"""

import asyncio
import logging
import threading
import time
from collections import deque
from collections.abc import AsyncIterator
from typing import Any

_REPLAY_LIMIT = 20_000


class EventBus:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subs: list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = []
        self._buffer: deque[dict[str, Any]] = deque(maxlen=_REPLAY_LIMIT)
        self._seq = 0

    def publish(self, type_: str, **data: Any) -> None:
        with self._lock:
            self._seq += 1
            event = {"seq": self._seq, "type": type_, "ts": time.time(), **data}
            self._buffer.append(event)
            subs = list(self._subs)
        for loop, queue in subs:
            try:
                loop.call_soon_threadsafe(queue.put_nowait, event)
            except RuntimeError:  # subscriber's loop already closed
                pass

    def clear(self) -> None:
        """Start a fresh replay buffer (called when a new run starts)."""
        with self._lock:
            self._buffer.clear()

    async def subscribe(self) -> AsyncIterator[dict[str, Any]]:
        queue: asyncio.Queue = asyncio.Queue()
        entry = (asyncio.get_running_loop(), queue)
        # Snapshot and register under one lock: every event is then either in
        # the snapshot or delivered to the queue, never both, never neither.
        with self._lock:
            snapshot = list(self._buffer)
            self._subs.append(entry)
        try:
            for event in snapshot:
                yield event
            while True:
                yield await queue.get()
        finally:
            with self._lock:
                self._subs.remove(entry)


class BusLogHandler(logging.Handler):
    """Forward leadscraper log records to the dashboard's activity feed."""

    def __init__(self, bus: EventBus, level: int = logging.INFO):
        super().__init__(level)
        self.bus = bus

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.bus.publish(
                "log",
                level=record.levelname.lower(),
                logger=record.name.removeprefix("leadscraper."),
                message=record.getMessage()[:400],
                thread=record.threadName,
            )
        except Exception:
            self.handleError(record)
