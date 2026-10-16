import asyncio

import numpy as np
import pytest
from audio_fakes import frames, microphone_for

from jarvis.audio import wake
from jarvis.audio.clip import Samples
from jarvis.audio.wake import CHUNK_SAMPLES, WakeWatcher, to_int16
from jarvis.config import WakeConfig

CONFIG = WakeConfig(
    enabled=True,
    model="hey_jarvis",
    threshold=0.5,
    confirm_threshold=0.1,
    confirm_s=2.0,
    backlog_s=3.0,
    cooldown_s=2.0,
)


class ScriptedModel:
    """Scores 80 ms chunks from a script; then 0."""

    def __init__(self, scores: list[float]) -> None:
        self.scores = scores
        self.chunks: list[np.ndarray] = []
        self.resets = 0

    def score(self, chunk: np.ndarray) -> float:
        self.chunks.append(chunk)
        return self.scores[len(self.chunks) - 1] if len(self.chunks) <= len(self.scores) else 0.0

    def reset(self) -> None:
        self.resets += 1


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


class Setup:
    def __init__(
        self, confirms: bool = True, armed: bool = True, audio: list[Samples] | None = None
    ) -> None:
        self.model = ScriptedModel([])
        self.microphone, self.streams = microphone_for(audio or [])
        self.woken = 0
        self.checked: list[int] = []
        self.armed = armed
        self.clock = Clock()

        async def confirm(audio: Samples) -> bool:
            self.checked.append(len(audio))
            return confirms

        def wake() -> None:
            self.woken += 1

        self.watcher = WakeWatcher(
            self.microphone,
            lambda: self.model,
            CONFIG,
            confirm,
            wake,
            lambda: self.armed,
            clock=self.clock,
        )


def test_a_confident_score_wakes_at_once() -> None:
    async def scenario() -> int:
        setup = Setup()
        setup.watcher.consider(0.97)
        return setup.woken

    assert asyncio.run(scenario()) == 1


@pytest.fixture(autouse=True)
def quick_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wake, "LISTEN_ON_S", 0.0)


def test_an_uncertain_score_is_confirmed_by_whisper() -> None:
    async def scenario() -> tuple[int, int]:
        setup = Setup(confirms=True)
        setup.watcher.consider(0.22)  # a Brazilian "Ei Jarvis"
        setup.watcher.consider(0.25)  # the next chunk: one check is enough
        await asyncio.sleep(0.01)
        return setup.woken, len(setup.checked)

    assert asyncio.run(scenario()) == (1, 1)


def test_whisper_can_say_no() -> None:
    async def scenario() -> tuple[int, int]:
        setup = Setup(confirms=False)
        setup.watcher.consider(0.15)
        await asyncio.sleep(0.01)
        setup.watcher.consider(0.15)  # the same phrase still fading: not checked again
        await asyncio.sleep(0.01)
        return setup.woken, len(setup.checked)

    assert asyncio.run(scenario()) == (0, 1)


def test_low_scores_are_ignored_and_waking_has_a_cooldown() -> None:
    async def scenario() -> list[int]:
        setup = Setup()
        setup.watcher.consider(0.05)
        counts = [setup.woken]
        setup.watcher.consider(0.9)
        setup.watcher.consider(0.9)  # the same phrase, a chunk later
        counts.append(setup.woken)
        setup.clock.now += CONFIG.cooldown_s + 0.1
        setup.watcher.consider(0.9)
        counts.append(setup.woken)
        return counts

    assert asyncio.run(scenario()) == [0, 1, 2]


def test_the_microphone_is_scored_in_80_ms_chunks_while_armed() -> None:
    async def scenario() -> tuple[int, int]:
        setup = Setup(audio=frames(10))  # 10 x 512 samples
        watching = asyncio.create_task(setup.watcher.run())
        while not setup.streams:
            await asyncio.sleep(0.01)  # the model loads on a worker thread first
        await asyncio.to_thread(setup.streams[0].finished.wait)
        await asyncio.sleep(0.05)
        watching.cancel()
        return len(setup.model.chunks), setup.model.resets

    chunks, resets = asyncio.run(scenario())

    assert chunks == 10 * 512 // CHUNK_SAMPLES  # 4 chunks; the rest waits for more audio
    assert resets == 1  # once, when it became armed


def test_nothing_is_scored_while_busy() -> None:
    async def scenario() -> int:
        setup = Setup(armed=False, audio=frames(10))
        watching = asyncio.create_task(setup.watcher.run())
        while not setup.streams:
            await asyncio.sleep(0.01)
        await asyncio.to_thread(setup.streams[0].finished.wait)
        await asyncio.sleep(0.05)
        watching.cancel()
        return len(setup.model.chunks)

    assert asyncio.run(scenario()) == 0


def test_audio_becomes_16_bit() -> None:
    converted = to_int16(np.array([0.0, 0.5, -1.0, 1.5], dtype=np.float32))

    assert converted.dtype == np.int16
    assert converted.tolist() == [0, 16383, -32767, 32767]
