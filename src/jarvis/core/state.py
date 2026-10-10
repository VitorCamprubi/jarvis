"""What the assistant is doing right now; the HUD will show it (Phase 5)."""

from enum import StrEnum


class State(StrEnum):
    STARTING = "starting"
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
