"""What the core tells its observers (the HUD): plain, immutable events.

They are published on the core thread; an observer that lives elsewhere (the Qt HUD, on the
main thread) must hand them over to its own thread itself (ADR-004).
"""

from collections.abc import Callable
from dataclasses import dataclass

from jarvis.core.state import State
from jarvis.i18n import Language
from jarvis.tools.base import Link


@dataclass(frozen=True)
class StateChanged:
    state: State


@dataclass(frozen=True)
class UserSpoke:
    text: str
    language: Language  # the language JARVIS will answer in


@dataclass(frozen=True)
class JarvisSpoke:
    text: str
    language: Language


@dataclass(frozen=True)
class Shown:
    """Everything a reply has beyond its spoken words: details and clickable links."""

    details: str | None
    links: tuple[Link, ...]


@dataclass(frozen=True)
class SpendingChanged:
    spent_usd: float


@dataclass(frozen=True)
class LoadSampled:
    cpu_percent: float
    ram_percent: float
    gpu_percent: float | None  # None without an NVIDIA GPU
    vram_percent: float | None


Event = StateChanged | UserSpoke | JarvisSpoke | Shown | SpendingChanged | LoadSampled
EventSink = Callable[[Event], None]
