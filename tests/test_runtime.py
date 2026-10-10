import asyncio
import threading
from collections.abc import Iterator

import pytest

from jarvis.core.runtime import CoreRuntime


@pytest.fixture
def runtime() -> Iterator[CoreRuntime]:
    core = CoreRuntime()
    core.start()
    yield core
    core.stop()


def test_submit_runs_the_coroutine_on_the_core_thread(runtime: CoreRuntime) -> None:
    async def thread_name() -> str:
        return threading.current_thread().name

    assert runtime.submit(thread_name()).result(timeout=2) == "jarvis-core"


def test_call_soon_runs_the_callback_on_the_core_thread(runtime: CoreRuntime) -> None:
    seen: list[str] = []
    done = threading.Event()

    def callback() -> None:
        seen.append(threading.current_thread().name)
        done.set()

    runtime.call_soon(callback)

    assert done.wait(2)
    assert seen == ["jarvis-core"]


def test_stop_cancels_pending_tasks() -> None:
    runtime = CoreRuntime()
    runtime.start()
    started = threading.Event()
    cancelled = threading.Event()

    async def forever() -> None:
        started.set()
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    runtime.submit(forever())
    assert started.wait(2)
    runtime.stop()

    assert cancelled.is_set()


def test_using_the_runtime_before_start_is_an_error() -> None:
    with pytest.raises(RuntimeError, match="start"):
        CoreRuntime().call_soon(lambda: None)
