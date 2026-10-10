"""The core thread: one asyncio event loop that runs the whole pipeline (ADR-004).

Other threads (hotkey listener, later the Qt HUD) never touch pipeline objects directly;
they hand work to this loop with ``call_soon`` or ``submit``, which are thread-safe.
"""

import asyncio
import concurrent.futures
import logging
import threading
from collections.abc import Callable, Coroutine
from typing import Any, cast

log = logging.getLogger(__name__)

START_TIMEOUT_S = 5.0
EXECUTOR_SHUTDOWN_TIMEOUT_S = 3.0


class CoreRuntime:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._started = threading.Event()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="jarvis-core", daemon=True)
        self._thread.start()
        if not self._started.wait(START_TIMEOUT_S):
            raise RuntimeError("The core event loop did not start")

    def submit[T](self, coroutine: Coroutine[Any, Any, T]) -> concurrent.futures.Future[T]:
        """Schedule a coroutine on the core loop from any thread."""
        return asyncio.run_coroutine_threadsafe(coroutine, self._require_loop())

    def call_soon(self, callback: Callable[[], object]) -> None:
        """Run a plain function on the core loop from any thread."""
        self._require_loop().call_soon_threadsafe(callback)

    def stop(self) -> None:
        """Cancel everything still running on the loop and wait for the thread to finish."""
        if self._loop is not None and self._thread is not None and self._thread.is_alive():
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join()

    def _run(self) -> None:
        # The concrete loop class; only it declares shutdown_default_executor(timeout).
        loop = cast(asyncio.BaseEventLoop, asyncio.new_event_loop())
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._started.set()
        try:
            loop.run_forever()
        finally:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.run_until_complete(loop.shutdown_default_executor(EXECUTOR_SHUTDOWN_TIMEOUT_S))
            loop.close()
            log.debug("Core loop closed")

    def _require_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None:
            raise RuntimeError("CoreRuntime.start() has not been called")
        return self._loop
