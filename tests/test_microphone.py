import asyncio
from typing import Any

import numpy as np
import pytest
from audio_fakes import FakeInputStream, frames, microphone_for

from jarvis.audio import microphone as microphone_module
from jarvis.audio.microphone import Microphone, MicrophoneError
from jarvis.audio.vad import FRAME_SAMPLES, SAMPLE_RATE

FRAME_S = FRAME_SAMPLES / SAMPLE_RATE


async def received(queue: asyncio.Queue[Any], count: int) -> list[Any]:
    return [await asyncio.wait_for(queue.get(), 2) for _ in range(count)]


def test_the_stream_is_open_while_someone_listens() -> None:
    async def scenario() -> tuple[bool, bool, bool]:
        microphone, streams = microphone_for(frames(5))
        first = microphone.subscribe()
        second = microphone.subscribe()
        await received(first, 5)
        await received(second, 5)  # both get every frame
        microphone.unsubscribe(first)
        still_open = microphone.is_open
        microphone.unsubscribe(second)
        return still_open, microphone.is_open, streams[0].closed

    assert asyncio.run(scenario()) == (True, False, True)


def test_the_last_seconds_are_kept() -> None:
    async def scenario() -> tuple[int, int]:
        numbered = [np.full(FRAME_SAMPLES, n / 100, dtype=np.float32) for n in range(10)]
        microphone, _ = microphone_for(numbered)
        frames_queue = microphone.subscribe()
        await received(frames_queue, 10)
        recent = microphone.recent(3 * FRAME_S)
        backlog = microphone.subscribe(backlog_s=2 * FRAME_S)
        first_of_backlog = backlog.get_nowait()
        microphone.close()
        return len(recent) // FRAME_SAMPLES, round(float(first_of_backlog[0]) * 100)

    assert asyncio.run(scenario()) == (3, 8)  # frames 7-9, and a backlog from frame 8


def test_a_silent_microphone_is_reopened(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(microphone_module, "CHECK_EVERY_S", 0.01)
    monkeypatch.setattr(microphone_module, "STALL_S", 0.05)
    deliveries = [[], frames(3)]  # the first stream never sends a frame: unplugged headset
    streams: list[FakeInputStream] = []
    rescans: list[bool] = []

    def factory(**settings: Any) -> FakeInputStream:
        stream = FakeInputStream(deliveries[len(streams)], **settings)
        streams.append(stream)
        return stream

    async def scenario() -> int:
        microphone = Microphone(
            lambda: 1, 1, stream_factory=factory, rescan=lambda: rescans.append(True)
        )
        queue = microphone.subscribe()
        watchdog = asyncio.create_task(microphone.keep_alive())
        got = await received(queue, 3)
        watchdog.cancel()
        microphone.close()
        return len(got)

    assert asyncio.run(scenario()) == 3
    assert len(streams) == 2 and rescans == [True]


def test_a_missing_microphone_is_retried_later(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(microphone_module, "CHECK_EVERY_S", 0.01)
    monkeypatch.setattr(microphone_module, "STALL_S", 0.05)
    monkeypatch.setattr(microphone_module, "RETRY_S", 0.05)
    attempts: list[int] = []

    def factory(**settings: Any) -> FakeInputStream:
        attempts.append(1)
        if len(attempts) in (2, 3):
            raise OSError("no such device")
        return FakeInputStream(frames(2) if len(attempts) == 4 else [], **settings)

    async def scenario() -> int:
        microphone = Microphone(lambda: 1, 1, stream_factory=factory, rescan=lambda: None)
        queue = microphone.subscribe()
        watchdog = asyncio.create_task(microphone.keep_alive())
        got = await received(queue, 2)
        watchdog.cancel()
        microphone.close()
        return len(got)

    assert asyncio.run(scenario()) == 2
    assert len(attempts) == 4


def test_an_unavailable_microphone_is_reported() -> None:
    def broken(**settings: Any) -> Any:
        raise OSError("device unavailable")

    async def scenario() -> None:
        Microphone(lambda: None, 1, stream_factory=broken).subscribe()

    with pytest.raises(MicrophoneError, match="device unavailable"):
        asyncio.run(scenario())
