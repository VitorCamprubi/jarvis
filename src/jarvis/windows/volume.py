"""Master volume of the default output device, through Windows Core Audio (pycaw, ADR-022).

COM must be initialised in every thread that uses it, so all calls go through one dedicated
worker thread that initialises COM once.
"""

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class VolumeState:
    level: int  # 0-100
    muted: bool


class Volume(Protocol):
    async def get(self) -> VolumeState: ...

    async def set_level(self, level: int) -> None: ...

    async def set_muted(self, muted: bool) -> None: ...


def _init_com() -> None:
    import comtypes

    comtypes.CoInitialize()


class MasterVolume:
    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(1, "jarvis-com", initializer=_init_com)

    async def get(self) -> VolumeState:
        def read(endpoint: Any) -> VolumeState:
            level = round(endpoint.GetMasterVolumeLevelScalar() * 100)
            return VolumeState(level, bool(endpoint.GetMute()))

        return await self._call(read)

    async def set_level(self, level: int) -> None:
        scalar = max(0, min(100, level)) / 100
        await self._call(lambda endpoint: endpoint.SetMasterVolumeLevelScalar(scalar, None))

    async def set_muted(self, muted: bool) -> None:
        await self._call(lambda endpoint: endpoint.SetMute(int(muted), None))

    async def _call[T](self, action: Callable[[Any], T]) -> T:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, _with_endpoint, action)


def _with_endpoint[T](action: Callable[[Any], T]) -> T:
    # COM objects are created and released inside this call, on the COM thread.
    from pycaw.pycaw import AudioUtilities

    return action(AudioUtilities.GetSpeakers().EndpointVolume)
