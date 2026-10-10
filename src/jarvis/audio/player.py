"""Audio playback that can be awaited and cancelled."""

import asyncio
from typing import Protocol

import sounddevice as sd

from jarvis.audio.clip import AudioClip


class Player(Protocol):
    async def play(self, clip: AudioClip) -> None:
        """Play the clip and return when it has finished; cancelling stops the sound."""
        ...


class SoundDevicePlayer:
    def __init__(self, device: int | None = None) -> None:
        self._device = device

    async def play(self, clip: AudioClip) -> None:
        sd.play(clip.samples, clip.sample_rate, device=self._device)
        try:
            # sd.wait blocks, so it runs on a worker thread and the event loop stays free.
            await asyncio.to_thread(sd.wait)
        except asyncio.CancelledError:
            sd.stop()  # also releases the worker thread blocked in sd.wait
            raise
