"""Extension point: obey only the owner's voice (planned for v2, see docs/V2_IDEAS.md)."""

from typing import Protocol

from jarvis.audio.clip import Samples


class SpeakerVerifier(Protocol):
    async def is_owner(self, audio: Samples) -> bool: ...


class AcceptEveryone:
    """v1 behaviour: every voice is accepted."""

    async def is_owner(self, audio: Samples) -> bool:
        return True
