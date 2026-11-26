"""Background asyncio loop so browser automation and the engine never block the GUI."""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
from typing import Any, Awaitable, Callable

log = logging.getLogger(__name__)


class AsyncRunner:
    def __init__(self) -> None:
        # On Windows this is a ProactorEventLoop, which Playwright needs for its driver subprocess.
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._main, name="engine-loop", daemon=True)
        self._ready = threading.Event()

    def start(self) -> None:
        self._thread.start()
        self._ready.wait(10)

    def _main(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.call_soon(self._ready.set)
        try:
            self.loop.run_forever()
        finally:
            pending = [t for t in asyncio.all_tasks(self.loop) if not t.done()]
            for t in pending:
                t.cancel()
            if pending:
                self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            self.loop.close()

    @property
    def in_loop_thread(self) -> bool:
        return threading.current_thread() is self._thread

    def submit(self, coro: Awaitable[Any]) -> concurrent.futures.Future:
        return asyncio.run_coroutine_threadsafe(coro, self.loop)  # type: ignore[arg-type]

    def call_soon(self, fn: Callable[..., Any], *args: Any) -> None:
        self.loop.call_soon_threadsafe(fn, *args)

    def run_sync(self, coro: Awaitable[Any], timeout: float | None = 30) -> Any:
        return self.submit(coro).result(timeout)

    def stop(self, timeout: float = 10) -> None:
        if self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)
        self._thread.join(timeout)
